import json
import secrets
import sqlite3
import time
import re
from contextlib import contextmanager
from pathlib import Path

from app.questions import QUESTIONS, BY_ID


def normalize_answer(text):
    return re.sub(r'[^\w]+', ' ', text.lower().replace('ё', 'е')).strip()


def answer_matches(text, answer):
    variants = [answer] + answer.split('/')
    # Demo pack: allow a surname instead of a full author name.
    if answer in ('Юрий Гагарин', 'Александр Пушкин', 'Джоан Роулинг', 'Михаил Булгаков', 'Джордж Оруэлл'):
        variants.append(answer.split()[-1])
    return normalize_answer(text) in {normalize_answer(v) for v in variants}


def message(s, name, text, kind='chat', uid=None):
    messages = s.setdefault('messages', [])
    s['message_seq'] = s.get('message_seq', 0) + 1
    messages.append(dict(id=s['message_seq'], name=name, text=text, kind=kind, user_id=uid, time=time.time()))
    s['messages'] = messages[-100:]


def grade(s, correct):
    player = next(p for p in s['players'] if p['id'] == s['buzzer'])
    value = BY_ID[s['active']]['value']
    player['score'] += value if correct else -value
    message(s, 'Ведущий', f"{player['name']}: {'верно' if correct else 'неверно'} ({'+' if correct else '−'}{value})", 'system')
    s['attempted'].append(s['buzzer'])
    s.update(buzzer=None, submitted=None, auto_at=None)
    if correct or len(s['attempted']) == len(s['players'])-1:
        s.update(phase='reveal', deadline=None)
        s['used'].append(s['active'])
    else:
        s.update(phase='question', deadline=time.time()+15, auto_at=time.time()+7)


def reveal(s):
    s['used'].append(s['active'])
    s.update(phase='reveal', deadline=None, buzzer=None, submitted=None, auto_at=None)
    message(s, 'Ведущий', 'Вопрос закрыт. Ответ: '+BY_ID[s['active']]['answer'], 'system')


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS rooms(code TEXT PRIMARY KEY, state TEXT NOT NULL);
            ''')

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

    def create(self, user, practice=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            while True:
                code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
                if not db.execute('SELECT 1 FROM rooms WHERE code=?', (code,)).fetchone():
                    break
            state = dict(code=code, host=user['id'], players=[dict(**user, score=0)], phase='lobby',
                         active=None, used=[], attempted=[], buzzer=None, deadline=None, version=0,
                         practice=practice, owner=user['id'], messages=[], submitted=None, auto_at=None)
            if practice:
                host = dict(id='sim-host-'+code, name='Робоведущий', score=0, synthetic=True)
                bots = [dict(id=f'sim-{i}-{code}', name=name, score=0, synthetic=True)
                        for i, name in enumerate(('Сырник', 'Шустрик'))]
                state.update(host=host['id'], players=[host, dict(**user, score=0), *bots], phase='board')
                message(state, 'Робоведущий', 'Тренировка началась! Выбирай вопрос. Сырник и Шустрик — искусственные игроки.', 'system')
            db.execute('INSERT INTO rooms VALUES (?, ?)', (code, json.dumps(state)))
        return code

    def read(self, code):
        with self.connect() as db:
            row = db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()
        if not row:
            raise ValueError('Комната не найдена')
        return json.loads(row[0])

    def change(self, code, user, action, question=None, text=''):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()
            if not row:
                raise ValueError('Комната не найдена')
            s = json.loads(row[0])
            s.setdefault('submitted', None)
            uid = user['id']
            member = next((p for p in s['players'] if p['id'] == uid), None)
            if action == 'join':
                if not member:
                    if s['phase'] != 'lobby':
                        raise ValueError('Игра уже началась')
                    if len(s['players']) >= 9:
                        raise ValueError('Комната заполнена (8 игроков и ведущий)')
                    s['players'].append(dict(**user, score=0))
            else:
                if not member:
                    raise ValueError('Вы не участник комнаты')
                practice_owner = s.get('practice') and uid == s.get('owner')
                if action not in ('buzz', 'answer', 'message') and uid != s['host'] and not (practice_owner and action in ('select', 'next', 'finish')):
                    raise ValueError('Это действие доступно только ведущему')
                if action == 'start':
                    if s['phase'] != 'lobby' or len(s['players']) < 2:
                        raise ValueError('Для старта нужен хотя бы один игрок')
                    s['phase'] = 'board'
                elif action == 'select':
                    if s['phase'] != 'board' or question not in BY_ID or question in s['used']:
                        raise ValueError('Этот вопрос недоступен')
                    s.update(phase='question', active=question, buzzer=None, attempted=[], submitted=None,
                             deadline=time.time()+30, auto_at=time.time()+7)
                    message(s, 'Ведущий', f"{BY_ID[question]['category']} · {BY_ID[question]['value']}: {BY_ID[question]['text']}", 'system')
                elif action == 'buzz':
                    if uid == s['host'] or s['phase'] != 'question' or uid in s['attempted'] or time.time() >= s['deadline']:
                        raise ValueError('Сейчас нельзя ответить')
                    s.update(phase='answer', buzzer=uid, submitted=None, deadline=time.time()+20, auto_at=None)
                elif action in ('answer', 'message'):
                    text = text.strip()
                    if not text or len(text) > 500:
                        raise ValueError('Сообщение должно содержать от 1 до 500 символов')
                    if action == 'answer':
                        if s['phase'] != 'answer' or s['buzzer'] != uid or s['submitted']:
                            raise ValueError('Сейчас не ваша очередь отвечать')
                        if time.time() >= s['deadline']:
                            raise ValueError('Время ответа вышло')
                        s['submitted'] = dict(user_id=uid, text=text)
                        s['auto_at'] = time.time()+1.5
                    message(s, member['name'], text, 'answer' if action == 'answer' else 'chat', uid)
                elif action in ('correct', 'wrong'):
                    if s['phase'] != 'answer':
                        raise ValueError('Нет игрока для оценки')
                    if not s['submitted'] and (time.time() < s['deadline'] or action == 'correct'):
                        raise ValueError('Дождитесь текстового ответа или истечения времени')
                    grade(s, action == 'correct')
                elif action == 'skip':
                    if s['phase'] not in ('question', 'answer'):
                        raise ValueError('Нет открытого вопроса')
                    reveal(s)
                elif action == 'next':
                    if s['phase'] != 'reveal':
                        raise ValueError('Сначала завершите вопрос')
                    s.update(phase='finished' if len(s['used']) == len(QUESTIONS) else 'board', active=None)
                elif action == 'finish':
                    if s['phase'] in ('lobby', 'finished'):
                        raise ValueError('Игра ещё не началась или уже завершена')
                    s.update(phase='finished', active=None, deadline=None, buzzer=None)
                else:
                    raise ValueError('Неизвестное действие')
            s['version'] += 1
            db.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(s), code))

    def public(self, code, uid):
        s = self.read(code)
        if not any(p['id'] == uid for p in s['players']):
            raise ValueError('Вы не участник комнаты')
        s['board'] = [{k: q[k] for k in ('id', 'category', 'value')} for q in QUESTIONS]
        s['question'] = None
        if s['active']:
            q = BY_ID[s['active']]
            s['question'] = {k: q[k] for k in ('id', 'category', 'value', 'text')}
            if uid == s['host'] or s['phase'] == 'reveal':
                s['question']['answer'] = q['answer']
        s['server_time'] = time.time()
        return s

    def practice_rooms(self):
        with self.connect() as db:
            rows = db.execute('SELECT code, state FROM rooms').fetchall()
        return [code for code, raw in rows if (s := json.loads(raw)).get('practice') and s['phase'] != 'finished']

    def tick_practice(self, code):
        """Server-only simulation, persisted so it survives process restarts."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM rooms WHERE code=?', (code,)).fetchone()
            if not row:
                return False
            s = json.loads(row[0])
            if not s.get('practice') or s['phase'] not in ('question', 'answer'):
                return False
            now = time.time()
            if s['phase'] == 'question':
                if now >= s['deadline']:
                    reveal(s)
                elif not s.get('auto_at') or now < s['auto_at']:
                    return False
                else:
                    bots = [p for p in s['players'] if p.get('synthetic') and p['id'] != s['host'] and p['id'] not in s['attempted']]
                    if not bots:
                        return False
                    # Alternate the first bot and right/wrong answers, for reproducible testing.
                    bot = bots[len(s['used']) % len(bots)]
                    s.update(phase='answer', buzzer=bot['id'], submitted=None, deadline=now+20, auto_at=now+2)
            elif s.get('submitted'):
                if now < s['auto_at']:
                    return False
                grade(s, answer_matches(s['submitted']['text'], BY_ID[s['active']]['answer']))
            elif now >= s['deadline']:
                grade(s, False)
            elif s.get('auto_at') and now >= s['auto_at']:
                bot = next(p for p in s['players'] if p['id'] == s['buzzer'])
                correct = (len(s['used']) + len(s['attempted'])) % 2 == 0
                text = BY_ID[s['active']]['answer'] if correct else 'Не знаю'
                s.update(submitted=dict(user_id=bot['id'], text=text), auto_at=now+1.5)
                message(s, bot['name'], text, 'answer', bot['id'])
            else:
                return False
            s['version'] += 1
            db.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(s), code))
            return True
