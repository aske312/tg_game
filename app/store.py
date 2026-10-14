import copy
import json
import re
import secrets
import sqlite3
import time
from random import SystemRandom
from contextlib import contextmanager
from pathlib import Path

from app.questions import QUESTIONS
from app.events import apply_event, snapshot_modifiers, consume_modifiers, score_delta, normalize_effect, describe_effect
from app.limits import MAX_SAFE_INTEGER, finite_number
from app.modes import LEGACY_STAGE, binary_fields, grid_category


def normalize_answer(text):
    return re.sub(r'[^\w]+', ' ', text.lower().replace('ё', 'е')).strip()


def answer_matches(text, answer):
    variants = [answer] + answer.split('/')
    if answer in ('Юрий Гагарин', 'Александр Пушкин', 'Джоан Роулинг', 'Михаил Булгаков', 'Джордж Оруэлл'):
        variants.append(answer.split()[-1])
    return normalize_answer(text) in {normalize_answer(v) for v in variants}


def matches_question(text, q):
    return answer_matches(text, q['answer']) or any(answer_matches(text, v) for v in q.get('accepted_answers', []))


def message(s, name, text, kind='chat', uid=None):
    s['message_seq'] = s.get('message_seq', 0) + 1
    s.setdefault('messages', []).append(dict(id=s['message_seq'], name=name, text=text, kind=kind, user_id=uid, time=time.time()))
    s['messages'] = s['messages'][-100:]


def current_question(s):
    return next((q for q in s['pack'] if q['id'] == s['active']), None)


def migrate(s):
    s.setdefault('stages', [dict(LEGACY_STAGE)])
    s.setdefault('stage_index', 0)
    s.setdefault('chooser', s['host'])
    s.setdefault('advance_at', None)
    s.setdefault('ui_version', s['version'])
    s.setdefault('paused', False)
    s.setdefault('scores_visible', False)
    for stage in s['stages']:
        if stage['type'] == 'grid' and 'categories' not in stage:
            stage['categories'] = list(dict.fromkeys(q['category'] for q in s['pack'] if q.get('stage') == stage['id'] and q.get('type') != 'event'))
    if s.get('schema') == 2:
        return s
    s['pack'] = copy.deepcopy(QUESTIONS)
    s['schema'] = 2
    s['answers'] = {}
    submitted = s.pop('submitted', None)
    if submitted and s.get('active'):
        s['answers'][submitted['user_id']] = dict(text=submitted['text'], verdict=None, time=time.time())
    if s['phase'] in ('board', 'answer'):
        s['phase'] = 'question' if s.get('active') else 'ready'
        if s.get('active'):
            s['deadline'] = time.time()+30
    s.pop('buzzer', None)
    s.pop('attempted', None)
    s['bot_due'] = {}
    return s


def current_stage(s):
    return s['stages'][s['stage_index']]


def remaining_stage(s):
    return [q for q in s['pack'] if q.get('stage', 'legacy') == current_stage(s)['id'] and q['id'] not in s['used']]


def player_practice(s):
    return s['practice'] and not s.get('host_practice')


def can_pick(s, uid):
    return (current_stage(s)['type'] == 'grid' and s['phase'] in ('board', 'reveal')
            and not s.get('paused') and not s.get('scores_visible')
            and bool(remaining_stage(s))
            and (uid in (s['host'], s['chooser']) or (s['practice'] and uid == s['owner'])))


def finish_reveal(s):
    s['phase'] = 'reveal'
    correct = [(a['time'], uid) for uid, a in s['answers'].items() if a['verdict'] == 'correct']
    s['chooser'] = min(correct)[1] if correct and current_stage(s)['chooser'] == 'winner' else s['host']
    s['advance_at'] = time.time()+3 if current_stage(s)['type'] != 'grid' and current_stage(s)['auto_advance'] and (remaining_stage(s) or player_practice(s)) else None


def finish_game(s):
    s.update(phase='finished', deadline=None, advance_at=None, finished_at=time.time(), scores_visible=False, media_playback=None)


def media_position(s, now):
    playback = s.get('media_playback')
    if not playback:
        return 0
    position = playback['position']
    if playback['playing'] and not s.get('paused'):
        position += max(0, now-playback['updated_at'])
    media = (current_question(s) or {}).get('media', {})
    if media.get('end') is not None:
        position = min(position, max(0, media['end']-media.get('start', 0)))
    if playback.get('duration') is not None:
        position = min(position, playback['duration'])
    return position


def start_question(s, selected=None):
    s['media_playback'] = None
    available = remaining_stage(s)
    while not available:
        if s['stage_index']+1 == len(s['stages']):
            finish_game(s)
            s['active'] = None
            return
        s['stage_index'] += 1
        s['chooser'] = s['host']
        available = remaining_stage(s)
    s['advance_at'] = None
    s['scores_visible'] = False
    if current_stage(s)['type'] == 'grid' and selected is None:
        if not player_practice(s) and current_stage(s)['id'] not in s.setdefault('introduced_stages', []):
            s['introduced_stages'].append(current_stage(s)['id'])
            categories = current_stage(s).get('categories', [])
            now = time.time()
            s.update(phase='intro', active=None, answers={}, deadline=None, event=None,
                     intro_started_at=now, intro_until=now+min(40, 12+len(categories)*2))
            return
        s.update(phase='board', active=None, answers={}, deadline=None, event=None)
        return
    q = next((q for q in available if q['id'] == selected), None) if selected else available[0]
    if not q:
        raise ValueError('Вопрос уже сыгран или принадлежит другому раунду')
    if q.get('type') == 'event':
        s.update(phase='event', active=q['id'], answers={}, deadline=None, event=apply_event(s, q))
        s['used'].append(q['id'])
        if current_stage(s)['auto_advance'] and (remaining_stage(s) or player_practice(s)):
            s['advance_at'] = time.time()+3
        message(s, 'Ведущий', s['event']['title']+' · '+s['event']['description']+' Участники: '+', '.join(s['event']['targets']), 'system')
        return
    now = time.time()
    s.update(phase='question', active=q['id'], answers={}, deadline=now+q.get('seconds', 45), auto_at=None, event=None)
    if q.get('media', {}).get('kind') in ('audio', 'video'):
        s['media_playback'] = dict(question=q['id'], playing=True, position=0, updated_at=now, revision=0)
    snapshot_modifiers(s)
    s['bot_due'] = {p['id']: now+5+i*3 for i, p in enumerate([p for p in s['players'] if p.get('synthetic') and p['id'] != s['host']])}
    message(s, 'Ведущий', f"Вопрос {len(s['used'])+1}: {q['text']}", 'system')


def close_question(s):
    s.update(phase='review' if s['answers'] else 'reveal', deadline=None, auto_at=time.time()+1.5)
    q = current_question(s)
    if q['id'] not in s['used']:
        s['used'].append(q['id'])
    consume_modifiers(s)
    for uid, answer in s['answers'].items():
        player = next(p for p in s['players'] if p['id'] == uid)
        message(s, player['name'], answer['text'], 'answer', uid)
    message(s, 'Ведущий', 'Приём ответов закрыт. Проверяем ответы.' if s['answers'] else 'Никто не ответил. Вопрос завершён.', 'system')
    if not s['answers']:
        finish_reveal(s)
    elif q.get('choices'):
        for uid, answer in s['answers'].items():
            grade(s, uid, answer.get('choice') == q['correct_choice'])


def grade(s, uid, correct):
    answer = s['answers'].get(uid)
    if s['phase'] != 'review' or not answer or answer['verdict'] is not None:
        raise ValueError('Этот ответ уже оценён или недоступен')
    player = next(p for p in s['players'] if p['id'] == uid)
    value = current_question(s)['value']
    delta = score_delta(s, uid, value, correct)
    player['score'] += delta
    answer['points'] = delta
    answer['verdict'] = 'correct' if correct else 'wrong'
    message(s, 'Ведущий', f"{player['name']}: {'верно' if correct else 'неверно'} ({delta:+d})", 'system')
    if all(a['verdict'] is not None for a in s['answers'].values()):
        finish_reveal(s)


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS rooms(code TEXT PRIMARY KEY, state TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY, room TEXT NOT NULL, kind TEXT NOT NULL, mime TEXT NOT NULL, filename TEXT NOT NULL);
            ''')
            for code, raw in db.execute('SELECT code, state FROM rooms').fetchall():
                s = json.loads(raw)
                if s.get('schema') != 2:
                    s = migrate(s)
                    s['version'] += 1
                    db.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(s), code))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self, user):
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?, ?, ?)', (token, json.dumps(user), time.time()+86400))
        return token

    def user(self, token):
        with self.connect() as db:
            row = db.execute('SELECT user FROM sessions WHERE token=? AND expires>?', (token, time.time())).fetchone()
        if not row:
            raise ValueError('Сессия истекла. Перезагрузите приложение')
        return json.loads(row[0])

    def create(self, user, practice=False, pack='demo', questions=None, assets=None, title=None, stages=None, host_practice=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            while True:
                code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
                if not db.execute('SELECT 1 FROM rooms WHERE code=?', (code,)).fetchone():
                    break
            s = dict(schema=2, code=code, host=user['id'], owner=user['id'], players=[dict(**user, score=0)], phase='lobby',
                     pack=copy.deepcopy(questions if questions is not None else QUESTIONS if pack == 'demo' else []),
                     pack_id=pack, pack_title=title or ('Демоквиз' if pack == 'demo' else 'Ваш квиз'), active=None, used=[], answers={},
                     deadline=None, version=0, practice=practice, messages=[], auto_at=None, bot_due={}, event=None, modifiers={}, round_modifiers={},
                     stages=copy.deepcopy(stages or [LEGACY_STAGE]), stage_index=0, chooser=user['id'], advance_at=None,
                     host_practice=bool(practice and host_practice))
            for stage in s['stages']:
                if stage['type'] != 'grid' and stage.get('order') == 'random':
                    positions = [i for i, q in enumerate(s['pack']) if q.get('stage', 'legacy') == stage['id'] and q.get('type') != 'event']
                    shuffled = [s['pack'][i] for i in positions]
                    SystemRandom().shuffle(shuffled)
                    for i, q in zip(positions, shuffled):
                        s['pack'][i] = q
            if practice and host_practice:
                bots = [dict(id=f'sim-{i}-{code}', name=name, score=0, synthetic=True)
                        for i, name in enumerate(('Сырник', 'Шустрик', 'Кусик'))]
                s['players'].extend(bots)
            elif practice:
                host = dict(id='sim-host-'+code, name='Робоведущий', score=0, synthetic=True)
                bots = [dict(id=f'sim-{i}-{code}', name=name, score=0, synthetic=True) for i, name in enumerate(('Сырник', 'Шустрик'))]
                s.update(host=host['id'], chooser=host['id'], players=[host, dict(**user, score=0), *bots])
                message(s, 'Робоведущий', 'Все отвечают одновременно. Напиши свой ответ: соперники его не увидят до закрытия вопроса.', 'system')
                start_question(s)
            db.execute('INSERT INTO rooms VALUES (?, ?)', (code, json.dumps(s)))
            for asset in assets or []:
                db.execute('INSERT INTO media VALUES (?, ?, ?, ?, ?)', (asset['id'], code, asset['kind'], asset['mime'], asset['filename']))
        return code

    def read(self, code):
        with self.connect() as db:
            row = db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()
        if not row:
            raise ValueError('Комната не найдена')
        return migrate(json.loads(row[0]))

    def media_permission(self, code, user):
        s = self.read(code)
        if s['host'] != user['id'] or s['phase'] != 'lobby':
            raise ValueError('Материалы загружает ведущий до начала игры')

    def save_media(self, code, user, asset, kind, mime, filename):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            s = migrate(json.loads(db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()[0]))
            if s['host'] != user['id'] or s['phase'] != 'lobby':
                raise ValueError('Комната уже запущена')
            db.execute('INSERT INTO media VALUES (?, ?, ?, ?, ?)', (asset, code, kind, mime, filename))

    def media_info(self, asset):
        with self.connect() as db:
            row = db.execute('SELECT room, kind, mime, filename FROM media WHERE id=?', (asset,)).fetchone()
        if not row:
            raise ValueError('Материал не найден')
        return dict(zip(('room', 'kind', 'mime', 'filename'), row))

    def add_question(self, code, user, question):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()
            if not row:
                raise ValueError('Комната не найдена')
            s = migrate(json.loads(row[0]))
            if s['host'] != user['id'] or s['phase'] != 'lobby':
                raise ValueError('Вопросы добавляет ведущий до начала игры')
            if len(s['pack']) >= 100:
                raise ValueError('Максимум 100 вопросов в квизе')
            q = dict(question, id='custom-'+secrets.token_hex(8), category='Ваши вопросы')
            if q.get('choices') is None:
                q.pop('choices', None)
                q.pop('correct_choice', None)
            stage_id = q.pop('stage', '') or s['stages'][0]['id']
            stage = next((stage for stage in s['stages'] if stage['id'] == stage_id), None)
            if not stage:
                raise ValueError('Неизвестный игровой раунд')
            if stage['type'] == 'grid':
                q['category'] = grid_category(question.get('category'), stage)
            q.update(stage=stage_id, **binary_fields(q, required=stage['type'] == 'binary'))
            if q.get('media_id'):
                row = db.execute('SELECT kind FROM media WHERE id=? AND room=?', (q.pop('media_id'), code)).fetchone()
                if not row:
                    raise ValueError('Материал принадлежит другой комнате или не найден')
                asset = question['media_id']
                q['media'] = dict(kind=row[0], url='/api/media/'+asset, start=q.pop('clip_start', 0), end=q.pop('clip_end', None))
            else:
                for key in ('media_id', 'clip_start', 'clip_end'):
                    q.pop(key, None)
            s['pack'].append(q)
            s['version'] += 1
            s['ui_version'] += 1
            db.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(s), code))

    def change(self, code, user, action, question=None, text='', player='', choice=None, delta=None, effect=None, position=None, duration=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()
            if not row:
                raise ValueError('Комната не найдена')
            s = migrate(json.loads(row[0]))
            uid = user['id']
            member = next((p for p in s['players'] if p['id'] == uid), None)
            if action == 'watch':
                observers = s.setdefault('observers', [])
                if uid not in observers:
                    observers.append(uid)
            elif action == 'join':
                if not member:
                    if s['phase'] != 'lobby':
                        raise ValueError('Игра уже началась')
                    if len(s['players']) >= 9:
                        raise ValueError('Комната заполнена (8 игроков и ведущий)')
                    s['players'].append(dict(**user, score=0))
            else:
                screen_media = (action in ('media_play', 'media_pause', 'media_seek') and user.get('role') == 'display'
                                and user.get('room') == code and uid in s.get('observers', []))
                if not member and not screen_media:
                    raise ValueError('Вы не участник комнаты')
                practice_owner = s['practice'] and uid == s['owner']
                if action not in ('answer', 'message', 'pick', 'reaction') and uid != s['host'] and not screen_media and not (practice_owner and action in ('close', 'next', 'finish', 'pause', 'unpause', 'show_scores', 'hide_scores')):
                    raise ValueError('Это действие доступно только ведущему')
                if s['paused'] and action not in ('reaction', 'unpause', 'show_scores', 'hide_scores', 'adjust_score', 'set_effect', 'clear_effect', 'skip_stage'):
                    raise ValueError('Игра на паузе')
                if action in ('media_play', 'media_pause', 'media_seek'):
                    q = current_question(s)
                    if s['phase'] not in ('question', 'review', 'reveal') or not q or q['id'] != question or q.get('media', {}).get('kind') not in ('audio', 'video'):
                        raise ValueError('Медиаматериал этого вопроса уже недоступен')
                    now = time.time()
                    playback = s.get('media_playback') or dict(question=q['id'], playing=True, position=0, updated_at=now, revision=0)
                    if action == 'media_seek' and position is None:
                        raise ValueError('Укажите позицию в отрывке')
                    if position is not None:
                        finite_number(position, 'Позиция в отрывке')
                    position = media_position(s, now) if position is None else position
                    media = q['media']
                    if duration is not None:
                        finite_number(duration, 'Длительность отрывка', minimum=.001)
                    duration = duration or playback.get('duration')
                    if media.get('end') is not None:
                        configured = media['end']-media.get('start', 0)
                        duration = min(configured, duration) if duration is not None else configured
                    if duration is not None:
                        position = min(position, duration)
                        if action == 'media_play' and position >= duration-.05:
                            position = 0
                    s['media_playback'] = dict(question=q['id'], playing=action == 'media_play' if action != 'media_seek' else playback['playing'],
                                               position=position, updated_at=now, revision=playback['revision']+1, duration=duration)
                elif action in ('adjust_score', 'set_effect', 'clear_effect'):
                    target = next((p for p in s['players'] if p['id'] == player and p['id'] != s['host']), None)
                    if not target or s['phase'] == 'finished':
                        raise ValueError('Выберите игрока в незавершённой игре')
                    if action == 'adjust_score':
                        if type(delta) is not int or abs(delta) > MAX_SAFE_INTEGER or abs(target['score'] + delta) > MAX_SAFE_INTEGER:
                            raise ValueError('Укажите допустимое целое изменение счёта')
                        target['score'] += delta
                        message(s, 'Ведущий', f"Корректировка: {target['name']} {delta:+d} · счёт {target['score']}", 'system')
                    else:
                        # Closed questions retain their scoring snapshot; changes apply to future questions.
                        if action == 'clear_effect':
                            s['modifiers'].pop(player, None)
                            if s['phase'] == 'question':
                                s['round_modifiers'].pop(player, None)
                            description = 'эффект снят'
                        else:
                            normalized = normalize_effect(dict(effect or {}, target='all_players'))
                            details = describe_effect(normalized)
                            modifier = dict(kind=normalized['type'], remaining=normalized['questions'], title=details['title'],
                                            **{k: normalized[k] for k in ('factor', 'amount') if k in normalized})
                            s['modifiers'][player] = modifier
                            if s['phase'] == 'question':
                                s['round_modifiers'][player] = copy.deepcopy(modifier)
                            description = f"{details['title']} · на {normalized['questions']} вопр."
                        timing = ' со следующего вопроса' if s['phase'] in ('review', 'reveal') else ''
                        message(s, 'Ведущий', f"{target['name']}: {description}{timing}", 'system')
                elif action == 'skip_stage':
                    if s['phase'] in ('lobby', 'finished'):
                        raise ValueError('Пропуск раунда доступен во время игры')
                    skipped = [q['id'] for q in s['pack'] if q.get('stage', 'legacy') == current_stage(s)['id'] and q['id'] not in s['used']]
                    s.setdefault('skipped', []).extend(skipped)
                    s['used'].extend(skipped)
                    message(s, 'Ведущий', f"Раунд «{current_stage(s)['title']}» пропущен. Неоценённые ответы не начисляют очки.", 'system')
                    s.update(active=None, answers={}, deadline=None, advance_at=None, auto_at=None, bot_due={}, event=None,
                             round_modifiers={}, scores_visible=False, chooser=s['host'])
                    was_paused = s['paused']
                    start_question(s)
                    if was_paused:
                        s['paused_at'] = time.time()
                    if s['phase'] == 'finished':
                        s['paused'] = False
                        s.pop('paused_at', None)
                elif action == 'start':
                    if s['phase'] != 'lobby' or len(s['players']) < 2 or not s['pack']:
                        raise ValueError('Для старта нужны вопросы и хотя бы один игрок')
                    start_question(s)
                elif action == 'pick':
                    if not can_pick(s, uid):
                        raise ValueError('Сейчас вопрос выбирает другой участник')
                    if not question:
                        raise ValueError('Выберите вопрос в сетке')
                    start_question(s, selected=question)
                elif action == 'answer':
                    if uid == s['host'] or s['phase'] != 'question' or uid in s['answers']:
                        raise ValueError('Ответ уже отправлен или приём ответов закрыт')
                    if time.time() >= s['deadline']:
                        raise ValueError('Время ответа вышло')
                    q = current_question(s)
                    if q.get('choices'):
                        if type(choice) is not int or choice not in (0, 1):
                            raise ValueError('Выберите один из двух вариантов')
                        text = q['choices'][choice]
                    elif choice is not None:
                        raise ValueError('Этот вопрос требует текстового ответа')
                    text = text.strip()
                    if not text or len(text) > 500:
                        raise ValueError('Ответ должен содержать от 1 до 500 символов')
                    s['answers'][uid] = dict(text=text, time=time.time(), verdict=None)
                    if q.get('choices'):
                        s['answers'][uid]['choice'] = choice
                    if len(s['answers']) == len(s['players'])-1:
                        close_question(s)
                elif action == 'reaction':
                    if text not in ('🐀', '🔥', '👏', '😂', '❤️', '🤯'):
                        raise ValueError('Выберите реакцию из списка')
                    reactions = s.setdefault('reactions', [])
                    now = time.time()
                    if any(r['user_id'] == uid and now-r['time'] < 1 for r in reactions):
                        return False
                    s['reaction_seq'] = s.get('reaction_seq', 0)+1
                    reactions.append(dict(id=s['reaction_seq'], user_id=uid, emoji=text, time=now))
                    s['reactions'] = reactions[-30:]
                elif action == 'pause':
                    if s['phase'] in ('lobby', 'finished'):
                        raise ValueError('Пауза доступна во время игры')
                    now = time.time()
                    if s.get('media_playback'):
                        s['media_playback'].update(position=media_position(s, now), updated_at=now)
                    s.update(paused=True, paused_at=now)
                elif action == 'unpause':
                    if not s['paused']:
                        return False
                    elapsed = time.time()-s.pop('paused_at')
                    for key in ('deadline', 'advance_at', 'auto_at', 'intro_until', 'intro_started_at'):
                        if s.get(key) is not None:
                            s[key] += elapsed
                    s['bot_due'] = {uid: due+elapsed for uid, due in s['bot_due'].items()}
                    s['paused'] = False
                    if s.get('media_playback'):
                        s['media_playback']['updated_at'] = time.time()
                elif action in ('show_scores', 'hide_scores'):
                    if s['phase'] not in ('reveal', 'event') or remaining_stage(s):
                        raise ValueError('Счёт можно показать после завершения раунда')
                    s['scores_visible'] = action == 'show_scores'
                    s['advance_at'] = None
                    if action == 'show_scores' and s.get('media_playback'):
                        now = time.time()
                        playback = s['media_playback']
                        playback.update(position=media_position(s, now), playing=False, updated_at=now, revision=playback['revision']+1)
                elif action == 'message':
                    text = text.strip()
                    if s['phase'] == 'question':
                        raise ValueError('Чат откроется после закрытия вопроса. Отправьте ответ через поле ответа')
                    if not text or len(text) > 500:
                        raise ValueError('Сообщение должно содержать от 1 до 500 символов')
                    message(s, member['name'], text, uid=uid)
                elif action == 'close':
                    if s['phase'] != 'question':
                        raise ValueError('Приём ответов уже закрыт')
                    close_question(s)
                elif action in ('correct', 'wrong'):
                    grade(s, player, action == 'correct')
                elif action == 'next':
                    if s['phase'] not in ('reveal', 'ready', 'event', 'intro'):
                        raise ValueError('Сначала оцените все ответы')
                    start_question(s)
                elif action == 'finish':
                    if s['phase'] in ('lobby', 'finished'):
                        raise ValueError('Игра ещё не началась или уже завершена')
                    if s['phase'] == 'question' or (s['phase'] == 'review' and any(a['verdict'] is None for a in s['answers'].values())):
                        raise ValueError('Сначала закройте вопрос и оцените ответы')
                    finish_game(s)
                else:
                    raise ValueError('Неизвестное действие')
            s['version'] += 1
            if action not in ('reaction', 'watch'):
                s['ui_version'] += 1
            db.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(s), code))
            return True

    def public(self, code, uid, display=False):
        s = self.read(code)
        if not any(p['id'] == uid for p in s['players']) and not (display and uid in s.get('observers', [])):
            raise ValueError('Вы не участник комнаты')
        q = current_question(s)
        stage = current_stage(s)
        s['stage'] = stage
        s['stage_number'] = s['stage_index']+1
        s['stage_count'] = len(s['stages'])
        s['can_pick'] = not display and can_pick(s, uid)
        s['board'] = [dict(id=q['id'], category=q['category'], value=q['value'], used=q['id'] in s['used'])
                      for q in s['pack'] if q.get('stage', 'legacy') == stage['id'] and q.get('type') != 'event'] if stage['type'] == 'grid' else []
        s['stage_complete'] = not remaining_stage(s)
        s['question'] = None
        if q and q.get('type') != 'event':
            s['question'] = {k: v for k, v in q.items() if k not in ('answer', 'accepted_answers', 'correct_choice')}
            if (uid == s['host'] and not display) or s['phase'] in ('reveal', 'finished') or (s['phase'] == 'review' and not display):
                s['question']['answer'] = q['answer']
                if q.get('choices'):
                    s['question']['correct_choice'] = q['correct_choice']
        s['answered_ids'] = list(s['answers'])
        if s['phase'] == 'question' and (uid != s['host'] or display):
            s['answers'] = {k: v for k, v in s['answers'].items() if k == uid}
            s['messages'] = [m for m in s['messages'] if m['kind'] != 'answer']
        s['question_count'] = sum(q.get('type') != 'event' for q in s['pack'])
        s['round_count'] = len(s['pack'])
        s['round_number'] = min(len(s['used'])+(s['phase'] == 'question'), len(s['pack']))
        s['question_number'] = sum(q['id'] in s['used'] and q.get('type') != 'event' for q in s['pack'])+(s['phase'] == 'question')
        if uid == s['host'] and not display and s['phase'] == 'lobby':
            s['question_list'] = s['pack']
        if display:
            s['answers'] = {}
            s['messages'] = []
        s['display'] = display
        s.pop('observers', None)
        s.pop('pack')
        s.pop('bot_due', None)
        s.pop('auto_at', None)
        s['server_time'] = time.time()
        return s

    def running_rooms(self):
        with self.connect() as db:
            rows = db.execute('SELECT code, state FROM rooms').fetchall()
        return [code for code, raw in rows if json.loads(raw)['phase'] not in ('lobby', 'finished')]

    def tick(self, code):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()
            if not row:
                return False
            raw = json.loads(row[0])
            changed = raw.get('schema') != 2
            s = migrate(raw)
            if s['paused']:
                return False
            now = time.time()
            if s['phase'] == 'intro' and now >= s['intro_until']:
                start_question(s)
                changed = True
            elif s['phase'] == 'question':
                if now >= s['deadline']:
                    close_question(s)
                    changed = True
                elif s['practice']:
                    for i, p in enumerate(s['players']):
                        if p.get('synthetic') and p['id'] != s['host'] and p['id'] not in s['answers'] and now >= s['bot_due'].get(p['id'], float('inf')):
                            correct = (i+len(s['used'])) % 2 == 0
                            q = current_question(s)
                            if q.get('choices'):
                                choice = q['correct_choice'] if correct else 1-q['correct_choice']
                                s['answers'][p['id']] = dict(text=q['choices'][choice], choice=choice, time=now, verdict=None)
                            else:
                                s['answers'][p['id']] = dict(text=q['answer'] if correct else 'Не знаю', time=now, verdict=None)
                            changed = True
                    if len(s['answers']) == len(s['players'])-1:
                        close_question(s)
            elif s['phase'] == 'review' and player_practice(s) and now >= (s.get('auto_at') or 0):
                for uid, a in s['answers'].items():
                    if a['verdict'] is None:
                        grade(s, uid, matches_question(a['text'], current_question(s)))
                changed = True
            elif s['phase'] in ('reveal', 'event') and s.get('advance_at') is not None and now >= s['advance_at']:
                start_question(s)
                changed = True
            if changed:
                s['version'] += 1
                s['ui_version'] += 1
                db.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(s), code))
            return changed
