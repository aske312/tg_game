"""Validated game.json folders containing questions and events."""
import hashlib
import json
import re
import secrets
from pathlib import Path

from app.media import MAX_MEDIA_BYTES, detect_media
from app.modes import stages_from_doc, binary_fields, grid_category
from app.events import normalize_effect
from app.limits import integer, finite_number
from app.pack_validation import publication_issues, PublicationError
from app.game_settings import question_defaults

MAX_PACK_BYTES = 1024 * 1024


def load_pack(directory):
    directory = Path(directory).resolve()
    manifest = directory / 'game.json'
    if not manifest.is_file():
        raise ValueError('В папке должен быть game.json')
    if not manifest.resolve().is_relative_to(directory) or manifest.stat().st_size > MAX_PACK_BYTES:
        raise ValueError('Недопустимый документ или размер больше 1 МБ')
    try:
        raw = manifest.read_text(encoding='utf-8-sig')
        doc = json.loads(raw)
    except (ValueError, UnicodeError) as e:
        raise ValueError('Не удалось прочитать JSON') from e
    if not isinstance(doc, dict) or doc.get('schema_version', 1) != 1:
        raise ValueError('Ожидается объект с schema_version: 1')
    issues = publication_issues(doc, directory)
    if issues:
        raise PublicationError(issues)
    defaults = question_defaults(doc)
    title = doc.get('title')
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError('Укажите title до 100 символов')
    items = doc.get('rounds')
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise ValueError('В rounds должно быть от 1 до 100 раундов')
    stages = stages_from_doc(doc)
    stage_map = {stage['id']: stage for stage in stages}
    questions, ids, paths = [], set(), set()
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValueError(f'Вопрос {i}: ожидается объект')
        qid = item.get('id', f'q{i}')
        if not isinstance(qid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', qid) or qid in ids:
            raise ValueError(f'Вопрос {i}: уникальный id из букв, цифр, _ или -')
        ids.add(qid)
        stage_id = item.get('stage', stages[0]['id'])
        if not isinstance(stage_id, str) or stage_id not in stage_map:
            raise ValueError(f'Вопрос {i}: неизвестный игровой раунд stage')
        mode = stage_map[stage_id]['type']
        location = f'Раунд {stages.index(stage_map[stage_id]) + 1} «{stage_map[stage_id]["title"]}» → {"Событие" if item.get("type") == "event" else "Вопрос"} {sum(q["stage"] == stage_id for q in questions) + 1}'
        if item.get('type') == 'event':
            if mode == 'grid':
                raise ValueError(f'{location}: события добавляйте в блиц или выбор из двух')
            effect = item.get('effect')
            try:
                effect = normalize_effect(effect)
            except ValueError as error:
                raise ValueError(f'{location}: {error}') from None
            event_title = item.get('title', 'Событие')
            text = item.get('text', '')
            if not isinstance(event_title, str) or not event_title.strip() or len(event_title) > 100:
                raise ValueError(f'{location}: заполните поле «Название события» (до 100 символов)')
            if not isinstance(text, str) or len(text) > 2000:
                raise ValueError(f'{location}: поле «Описание события» — до 2000 символов')
            category = item.get('category', '')
            if not isinstance(category, str) or len(category.strip()) > 100:
                raise ValueError(f'Раунд {i}: категория события до 100 символов')
            questions.append(dict(id=qid, stage=stage_id, type='event', title=event_title, text=text,
                                  category=category.strip(),
                                  effect=effect))
            continue
        if item.get('type') != 'question':
            raise ValueError(f'Раунд {i}: type должен быть question или event')
        try:
            binary = binary_fields(item, required=mode == 'binary')
        except ValueError as error:
            raise ValueError(f'Вопрос {i}: {error}') from None
        for field, limit in (('text', 2000),) + (() if binary else (('answer', 500),)):
            if not isinstance(item.get(field), str) or not item[field].strip() or len(item[field]) > limit:
                raise ValueError(f'Вопрос {i}: заполните {field} (до {limit} символов)')
        points, seconds = item.get('points', defaults['points']), item.get('time_limit', defaults['time_limit'])
        integer(points, f'Вопрос {i}, очки', minimum=0)
        integer(seconds, f'Вопрос {i}, время ответа')
        accepted = item.get('accepted_answers', [])
        if not isinstance(accepted, list) or len(accepted) > 20 or any(not isinstance(v, str) or not v.strip() or len(v) > 500 for v in accepted):
            raise ValueError(f'Вопрос {i}: accepted_answers должен быть списком ответов')
        category = str(item.get('category') or title)[:100]
        if mode == 'grid':
            try:
                category = grid_category(item.get('category'), stage_map[stage_id])
            except ValueError as error:
                raise ValueError(f'Вопрос {i}: {error}') from None
        q = dict(id=qid, stage=stage_id, type='question', category=category.strip(), text=item['text'].strip(), answer=binary.get('answer', item.get('answer', '')).strip(),
                 accepted_answers=accepted, value=points, seconds=seconds)
        q.update(binary)
        media = item.get('media')
        if media is not None:
            if not isinstance(media, dict) or media.get('type') not in ('image', 'audio', 'video') or not isinstance(media.get('file'), str):
                raise ValueError(f'Вопрос {i}: media требует type и file')
            relative = Path(media['file'])
            source = (directory / relative).resolve()
            if relative.is_absolute() or not source.is_relative_to(directory) or not source.is_file():
                raise ValueError(f'Вопрос {i}: файл должен существовать внутри папки пакета')
            if source.stat().st_size > MAX_MEDIA_BYTES:
                raise ValueError(f'Вопрос {i}: файл больше 25 МБ')
            paths.add(source)
            with source.open('rb') as f:
                detect_media(f.read(128), media['type'])
            start, end = media.get('start', 0), media.get('end')
            finite_number(start, f'Вопрос {i}, начало отрывка')
            if end is not None:
                finite_number(end, f'Вопрос {i}, конец отрывка')
            if end is not None and end <= start:
                raise ValueError(f'Вопрос {i}: недопустимые границы отрывка')
            audio_only = media.get('audio_only', False)
            if type(audio_only) is not bool or audio_only and media['type'] != 'video':
                raise ValueError(f'Вопрос {i}: режим «только звук» доступен для видео и должен быть true или false')
            q['media'] = dict(kind=media['type'], source=str(source), start=start, end=end)
            if audio_only:
                q['media']['audio_only'] = True
        questions.append(q)
    if sum(p.stat().st_size for p in paths) > 100 * 1024 * 1024:
        raise ValueError('Общий размер медиа пакета не должен превышать 100 МБ')
    if not any(q.get('type') == 'question' for q in questions):
        raise ValueError('В пакете нужен хотя бы один question')
    for stage in stages:
        if not any(q.get('stage') == stage['id'] and q.get('type') == 'question' for q in questions):
            raise ValueError(f'Раунд «{stage["title"]}»: добавьте хотя бы один вопрос')
    return dict(title=title.strip(), description=str(doc.get('description', ''))[:500], questions=questions, stages=stages)


def pack_deleted(roots, name):
    """Persistent tombstones also hide bundled packages after a code update."""
    for root in roots:
        root = Path(root).resolve()
        marker = (root / '.deleted' / (name + '.json')).resolve()
        if marker.is_relative_to(root) and marker.is_file():
            return True
    return False


def find_pack(roots, pack_id):
    if not pack_id.startswith('library-') or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', pack_id[8:]):
        raise ValueError('Недопустимый идентификатор пакета')
    name = pack_id[8:]
    if pack_deleted(roots, name):
        raise ValueError('Игра удалена из библиотеки')
    for root in roots:
        root = Path(root).resolve()
        folder = (root / name).resolve()
        if folder.is_relative_to(root) and folder.is_dir():
            return load_pack(folder)
    raise ValueError('Пакет игры не найден')


def list_packs(roots):
    packs, errors, seen = [], [], set()
    for root in roots:
        if not Path(root).exists():
            continue
        for folder in sorted(Path(root).iterdir()):
            if not folder.is_dir() or folder.name in seen or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', folder.name) or pack_deleted(roots, folder.name):
                continue
            seen.add(folder.name)
            try:
                pack = find_pack(roots, 'library-'+folder.name)
                packs.append(dict(id='library-'+folder.name, title=pack['title'], description=pack['description'], count=len(pack['questions']),
                                  questions=sum(q.get('type') == 'question' for q in pack['questions']), stages=pack['stages']))
            except (ValueError, OSError) as e:
                errors.append(dict(folder=folder.name, error=str(e)))
    return dict(packs=packs, errors=errors)


def materialize_pack(pack, media_directory):
    """Copy files into immutable content-addressed storage before creating a room."""
    directory = Path(media_directory)
    directory.mkdir(parents=True, exist_ok=True)
    assets, cache = [], {}
    for q in pack['questions']:
        if not q.get('media'):
            continue
        media = q['media']
        source = media.pop('source')
        key = (source, media['kind'])
        if key not in cache:
            data = Path(source).read_bytes()
            if len(data) > MAX_MEDIA_BYTES:
                raise ValueError('Материал изменился и превышает 25 МБ')
            mime, extension = detect_media(data[:128], media['kind'])
            filename = hashlib.sha256(data).hexdigest()+extension
            target = directory / filename
            if not target.exists():
                temporary = directory / (secrets.token_hex(20)+'.part')
                try:
                    temporary.write_bytes(data)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            asset = secrets.token_hex(20)
            cache[key] = asset
            assets.append(dict(id=asset, kind=media['kind'], mime=mime, filename=filename))
        media['url'] = '/api/media/'+cache[key]
    return assets
