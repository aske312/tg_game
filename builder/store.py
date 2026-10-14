"""Private drafts and atomic publication into the existing game.json library."""
import copy
import hashlib
import io
import json
import re
import secrets
import shutil
import sqlite3
import threading
import time
import zipfile
from pathlib import Path

from app.media import MAX_MEDIA_BYTES, detect_media
from app.packs import MAX_PACK_BYTES, load_pack, pack_deleted


class Conflict(ValueError):
    pass


def encode(doc):
    return (json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def revision(doc):
    return hashlib.sha256(encode(doc)).hexdigest()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(8) + '.part')
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class Catalog:
    def __init__(self, data, games, bundled):
        self.data, self.games, self.bundled = [Path(p).resolve() for p in (data, games, bundled)]
        self.drafts = self.data / 'drafts'
        self.drafts.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.database = self.data / 'sessions.sqlite3'
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL NOT NULL)')

    def session(self):
        token = secrets.token_urlsafe(32)
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?, ?)', (hashlib.sha256(token.encode()).hexdigest(), time.time()+43200))
        return token

    def authenticated(self, token):
        with sqlite3.connect(self.database) as db:
            return db.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?',
                              (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone() is not None

    def logout(self, token):
        with sqlite3.connect(self.database) as db:
            db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def folder(self, root, game_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', game_id):
            raise ValueError('Недопустимый идентификатор игры')
        result = (root / game_id).resolve()
        if not result.is_relative_to(root):
            raise ValueError('Папка игры должна находиться внутри библиотеки')
        return result

    def published_folder(self, game_id):
        if pack_deleted([self.games], game_id):
            return None
        for root in (self.games, self.bundled):
            folder = self.folder(root, game_id)
            if (folder / 'game.json').is_file():
                return folder
        return None

    def read_doc(self, folder):
        path = (folder / 'game.json').resolve()
        if not path.is_relative_to(folder):
            raise ValueError('Недопустимый путь документа')
        if not path.is_file():
            raise ValueError('Игра не найдена')
        if path.stat().st_size > MAX_PACK_BYTES:
            raise ValueError('Документ больше 1 МБ')
        try:
            doc = json.loads(path.read_text(encoding='utf-8-sig'))
        except (UnicodeError, ValueError):
            raise ValueError('Не удалось прочитать game.json') from None
        if not isinstance(doc, dict):
            raise ValueError('В game.json должен быть объект')
        rounds = doc.get('rounds')
        if not isinstance(rounds, list) or any(not isinstance(q, dict) or q.get('type') not in ('question', 'event') for q in rounds):
            raise ValueError('В rounds должен быть список вопросов и событий')
        return doc

    def meta(self, folder):
        path = folder / '.meta.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}

    def asset(self, folder, name):
        relative = Path(name)
        path = (folder / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(folder) or path == folder:
            raise ValueError('Материал должен находиться внутри папки игры')
        return path

    def media_files(self, doc):
        rounds = doc.get('rounds')
        if not isinstance(rounds, list):
            raise ValueError('В rounds должен быть список раундов')
        return {q['media']['file'] for q in rounds if isinstance(q, dict)
                and isinstance(q.get('media'), dict) and isinstance(q['media'].get('file'), str)}

    def copy_media(self, doc, source, target):
        total = 0
        for name in self.media_files(doc):
            src, dst = self.asset(source, name), self.asset(target, name)
            if not src.is_file():
                continue  # A missing material can be repaired in the editor.
            size = src.stat().st_size
            total += size
            if size > MAX_MEDIA_BYTES or total > 100 * 1024 * 1024:
                raise ValueError('Материал больше 25 МБ или медиа игры больше 100 МБ')
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)

    def snapshot(self, game_id):
        self.ensure_active(game_id)
        folder = self.folder(self.drafts, game_id)
        doc = self.read_doc(folder)
        metadata = self.meta(folder)
        published = self.published_folder(game_id)
        return dict(id=game_id, document=doc, revision=revision(doc), delete_revision=self.deletion_revision(game_id),
                    published=bool(published), dirty=revision(doc) != metadata.get('published_revision'))

    def ensure_active(self, game_id):
        self.folder(self.games, game_id)
        if pack_deleted([self.games], game_id):
            raise ValueError('Игра удалена из библиотеки')

    def deletion_revision(self, game_id):
        draft = self.folder(self.drafts, game_id) / 'game.json'
        published = self.published_folder(game_id)
        if not draft.is_file() and not published:
            raise ValueError('Игра не найдена')
        def digest(path):
            path = self.asset(path.parent, path.name)
            return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return revision(dict(id=game_id, draft=digest(draft), published=digest(published/'game.json') if published else None))

    def delete(self, game_id, expected):
        with self.lock:
            self.ensure_active(game_id)
            if self.deletion_revision(game_id) != expected:
                raise Conflict('Игра изменена в другом окне или вне конструктора. Обнови библиотеку перед удалением.')
            draft = self.folder(self.drafts, game_id)
            live = self.folder(self.games, game_id)
            if draft != self.drafts/game_id or live != self.games/game_id:
                raise ValueError('Нельзя удалить игру через ссылку на другую папку')
            published = self.published_folder(game_id)
            backup = self.asset(self.data, f'backups/{game_id}/{time.time_ns()}-deleted.zip')
            backup.parent.mkdir(parents=True, exist_ok=True)
            temporary = backup.with_suffix('.part')
            try:
                # Keep a private recovery copy, including uploaded and orphaned media.
                with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
                    for label, folder in [('draft', draft), ('published', published)]:
                        if folder and folder.is_dir():
                            for path in sorted(folder.rglob('*')):
                                relative = path.relative_to(folder)
                                source = self.asset(folder, str(relative))
                                if source.is_file():
                                    archive.write(source, label+'/'+relative.as_posix())
                temporary.replace(backup)
            finally:
                temporary.unlink(missing_ok=True)
            # Hide first so deleting an override cannot expose its bundled version.
            marker = self.asset(self.games, f'.deleted/{game_id}.json')
            atomic_write(marker, encode(dict(deleted_at=time.time())))
            for folder in (draft, live):
                if folder.is_dir():
                    shutil.rmtree(folder)
            return dict(ok=True)

    def list(self):
        with self.lock:
            names = set()
            for root in (self.games, self.bundled, self.drafts):
                if root.is_dir():
                    names.update(p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', p.name))
            items = []
            for name in sorted(names):
                if pack_deleted([self.games], name):
                    continue
                draft = self.folder(self.drafts, name)
                published = self.published_folder(name)
                if not (draft / 'game.json').is_file() and not published:
                    continue
                try:
                    is_draft = (draft / 'game.json').is_file()
                    doc = self.read_doc(draft if is_draft else published)
                    rounds = doc.get('rounds', [])
                    if not isinstance(rounds, list):
                        rounds = []
                    dirty = is_draft and revision(doc) != self.meta(draft).get('published_revision')
                    items.append(dict(id=name, title=str(doc.get('title', name)), description=str(doc.get('description', '')),
                                      questions=sum(isinstance(q, dict) and q.get('type') == 'question' for q in rounds),
                                      rounds=len(rounds), stages_count=len(doc['stages']) if isinstance(doc.get('stages'), list) else 1,
                                      published=bool(published), dirty=dirty, delete_revision=self.deletion_revision(name), error=''))
                except ValueError as error:
                    items.append(dict(id=name, title=name, description='', questions=0, rounds=0,
                                      published=bool(published), dirty=False, delete_revision=self.deletion_revision(name), error=str(error)))
            return items

    def create(self, title):
        with self.lock:
            game_id = 'game-' + secrets.token_hex(6)
            folder = self.folder(self.drafts, game_id)
            doc = dict(schema_version=1, title=title.strip(), description='', rounds=[],
                       stages=[dict(id='legacy', type='blitz', title='Раунд 1', order='sequential', chooser='winner', auto_advance=False)])
            atomic_write(folder / 'game.json', encode(doc))
            atomic_write(folder / '.meta.json', encode({'base': None}))
            return self.snapshot(game_id)

    def open(self, game_id):
        with self.lock:
            self.ensure_active(game_id)
            draft = self.folder(self.drafts, game_id)
            if not (draft / 'game.json').is_file():
                source = self.published_folder(game_id)
                if not source:
                    raise ValueError('Игра не найдена')
                doc = self.read_doc(source)
                draft.mkdir(parents=True, exist_ok=True)
                self.copy_media(doc, source, draft)
                atomic_write(draft / 'game.json', encode(doc))
                atomic_write(draft / '.meta.json', encode(dict(base=revision(doc), published_revision=revision(doc))))
            return self.snapshot(game_id)

    def save(self, game_id, doc, expected):
        with self.lock:
            self.ensure_active(game_id)
            folder = self.folder(self.drafts, game_id)
            current = self.read_doc(folder)
            if revision(current) != expected:
                raise Conflict('Игра изменена в другом окне. Обнови страницу перед сохранением.')
            try:
                data = encode(doc)
            except (ValueError, TypeError):
                raise ValueError('Некорректный документ игры') from None
            if len(data) > MAX_PACK_BYTES:
                raise ValueError('Документ больше 1 МБ')
            if not isinstance(doc.get('rounds'), list) or len(doc['rounds']) > 100:
                raise ValueError('В игре может быть до 100 раундов')
            if any(not isinstance(q, dict) or q.get('type') not in ('question', 'event') for q in doc['rounds']):
                raise ValueError('Раунды должны быть вопросами или событиями')
            atomic_write(folder / 'game.json', data)
            return self.snapshot(game_id)

    def upload(self, game_id, temporary, kind):
        with self.lock:
            self.ensure_active(game_id)
            folder = self.folder(self.drafts, game_id)
            self.read_doc(folder)
            data = temporary.read_bytes()
            mime, extension = detect_media(data[:128], kind)
            name = 'media/' + hashlib.sha256(data).hexdigest() + extension
            path = self.asset(folder, name)
            existing = sum(p.stat().st_size for p in (folder / 'media').rglob('*') if p.is_file()) if (folder / 'media').exists() else 0
            if not path.exists() and existing + len(data) > 100 * 1024 * 1024:
                raise ValueError('Материалы черновика занимают больше 100 МБ')
            if not path.exists():
                atomic_write(path, data)
            return dict(file=name, type=kind, size=len(data), mime=mime)

    def validate(self, game_id, doc):
        from app.pack_validation import publication_issues
        with self.lock:
            self.ensure_active(game_id)
            return dict(issues=publication_issues(doc, self.folder(self.drafts, game_id)))

    def publish(self, game_id, expected):
        with self.lock:
            self.ensure_active(game_id)
            draft = self.folder(self.drafts, game_id)
            doc = self.read_doc(draft)
            if revision(doc) != expected:
                raise Conflict('Черновик изменён в другом окне. Обнови страницу.')
            load_pack(draft)
            metadata = self.meta(draft)
            source = self.published_folder(game_id)
            current_base = revision(self.read_doc(source)) if source else None
            if current_base != metadata.get('base'):
                raise Conflict('Опубликованная игра изменилась вне конструктора. Сначала загрузи её свежую версию.')
            target = self.folder(self.games, game_id)
            published_doc = copy.deepcopy(doc)
            # Immutable filenames keep an old manifest's media valid during publication.
            for q in published_doc['rounds']:
                if not q.get('media'):
                    continue
                media = q['media']
                data = self.asset(draft, media['file']).read_bytes()
                _, extension = detect_media(data[:128], media['type'])
                name = 'media/' + hashlib.sha256(data).hexdigest() + extension
                path = self.asset(target, name)
                if not path.exists():
                    atomic_write(path, data)
                media['file'] = name
            published_data = encode(published_doc)
            if len(published_data) > MAX_PACK_BYTES:
                raise ValueError('Документ после подготовки медиа больше 1 МБ')
            if source:
                backup = self.data / 'backups' / game_id / (str(time.time_ns()) + '.json')
                atomic_write(backup, encode(self.read_doc(source)))
            atomic_write(target / 'game.json', published_data)
            metadata.update(base=revision(published_doc), published_revision=revision(doc))
            atomic_write(draft / '.meta.json', encode(metadata))
            return self.snapshot(game_id)

    def reload(self, game_id):
        with self.lock:
            self.ensure_active(game_id)
            source = self.published_folder(game_id)
            if not source:
                raise ValueError('У игры ещё нет опубликованной версии')
            draft = self.folder(self.drafts, game_id)
            old = self.read_doc(draft)
            atomic_write(self.data / 'backups' / game_id / (str(time.time_ns()) + '-draft.json'), encode(old))
            doc = self.read_doc(source)
            self.copy_media(doc, source, draft)
            atomic_write(draft / 'game.json', encode(doc))
            atomic_write(draft / '.meta.json', encode(dict(base=revision(doc), published_revision=revision(doc))))
            return self.snapshot(game_id)

    def export(self, game_id):
        with self.lock:
            self.ensure_active(game_id)
            folder = self.folder(self.drafts, game_id)
            load_pack(folder)
            doc = self.read_doc(folder)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('game.json', encode(doc))
                for name in self.media_files(doc):
                    archive.write(self.asset(folder, name), name)
            return buffer.getvalue()
