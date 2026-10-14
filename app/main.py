import asyncio
import os
import secrets
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, Request, Response, Cookie
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import validate_telegram
from app.store import Store
from app.media import MAX_MEDIA_BYTES, detect_media
from app.packs import list_packs, find_pack, materialize_pack
from app.limits import MAX_SAFE_INTEGER

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
store = Store(os.getenv('DATABASE_PATH', str(ROOT / 'data/game.sqlite3')))
@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(simulate())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title='Крысиные бега', lifespan=lifespan)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
connections = {}


class Login(BaseModel):
    init_data: str = Field(default='', max_length=16384)
    name: str = Field(default='Игрок', min_length=1, max_length=64)


class Command(BaseModel):
    action: str = Field(max_length=20)
    question: str = Field(default='', max_length=64)
    text: str = Field(default='', max_length=500)
    player: str = Field(default='', max_length=100)
    choice: Optional[int] = Field(default=None, ge=0, le=1)


class CreateRoom(BaseModel):
    pack: str = Field(default='demo', max_length=80)


class Question(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=500)
    value: int = Field(default=100, ge=0, le=MAX_SAFE_INTEGER)
    seconds: int = Field(default=45, ge=1, le=MAX_SAFE_INTEGER)
    media_id: str = Field(default='', max_length=64)
    clip_start: float = Field(default=0, ge=0, allow_inf_nan=False)
    clip_end: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    stage: str = Field(default='', max_length=64)
    choices: Optional[list[str]] = None
    correct_choice: Optional[int] = Field(default=None, ge=0, le=1)
    category: str = Field(default='', max_length=100)


def set_session_cookie(response, request, token):
    response.set_cookie('ratrace_session', token, max_age=86400, httponly=True,
                        secure=request.url.scheme == 'https', samesite='lax')


def current_user(authorization):
    try:
        if not authorization or not authorization.startswith('Bearer '):
            raise ValueError('Нужен вход в приложение')
        user = store.user(authorization[7:])
        if not DEV_MODE and user['id'].startswith('dev-'):
            raise ValueError('Войдите через Telegram')
        return user
    except ValueError as e:
        raise HTTPException(401, str(e))


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html', headers={'Cache-Control': 'no-cache'})


@app.get('/api/health')
def health():
    with store.connect() as db:
        db.execute('SELECT 1').fetchone()
    return {'status': 'ok', 'build': os.getenv('BUILD_SHA', 'local')}


@app.get('/api/config')
def config():
    return {'dev_mode': DEV_MODE, 'bot_username': os.getenv('BOT_USERNAME', '').lstrip('@')}


@app.post('/api/login')
def login(body: Login, request: Request, response: Response):
    try:
        if body.init_data:
            user = validate_telegram(body.init_data, BOT_TOKEN)
        elif DEV_MODE:
            name = body.name.strip()
            if not name:
                raise ValueError('Введите имя')
            user = {'id': 'dev-' + secrets.token_hex(12), 'name': name}
        else:
            raise ValueError('Откройте приложение через Telegram')
        token = store.session(user)
        set_session_cookie(response, request, token)
        return {'token': token, 'user': user}
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(401, str(e))


@app.get('/api/me')
def me(request: Request, response: Response, authorization: str = Header(default='')):
    user = current_user(authorization)
    set_session_cookie(response, request, authorization[7:])
    return user


@app.post('/api/rooms')
def create(body: CreateRoom = CreateRoom(), authorization: str = Header(default='')):
    user = current_user(authorization)
    if body.pack == 'custom':
        return {'code': store.create(user, pack=body.pack)}
    try:
        pack = find_pack(pack_roots(), 'library-demo-quiz' if body.pack == 'demo' else body.pack)
        assets = materialize_pack(pack, Path(store.path).parent / 'media')
        return {'code': store.create(user, pack=body.pack, questions=pack['questions'], assets=assets, title=pack['title'], stages=pack['stages'])}
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))


def pack_roots():
    return [Path(os.getenv('GAME_PACKS_DIR', str(Path(store.path).parent / 'games'))), ROOT / 'games']


@app.get('/api/packs')
def packs(authorization: str = Header(default='')):
    current_user(authorization)
    return list_packs(pack_roots())


@app.post('/api/practice')
def practice(body: CreateRoom = CreateRoom(), authorization: str = Header(default='')):
    user = current_user(authorization)
    if body.pack == 'custom':
        raise HTTPException(400, 'Для тренировки выберите готовую игру')
    else:
        try:
            pack = find_pack(pack_roots(), 'library-demo-quiz' if body.pack == 'demo' else body.pack)
            assets = materialize_pack(pack, Path(store.path).parent / 'media')
            code = store.create(user, practice=True, pack=body.pack, questions=pack['questions'], assets=assets, title=pack['title'], stages=pack['stages'])
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
    return store.public(code, user['id'])


async def publish(code):
    for ws, (uid, display) in list(connections.get(code, {}).items()):
        try:
            await asyncio.wait_for(ws.send_json(store.public(code, uid, display)), timeout=3)
        except (RuntimeError, WebSocketDisconnect, asyncio.TimeoutError, OSError):
            connections.get(code, {}).pop(ws, None)


async def simulate():
    while True:
        await asyncio.sleep(.5)
        try:
            for code in store.running_rooms():
                if store.tick(code):
                    await publish(code)
        except Exception:
            logging.getLogger(__name__).exception('Quiz timers or practice simulation failed')


@app.post('/api/rooms/{code}/questions')
async def add_question(code: str, body: Question, authorization: str = Header(default='')):
    user = current_user(authorization)
    q = body.model_dump()
    q['text'], q['answer'] = q['text'].strip(), q['answer'].strip()
    if not q['text'] or not q['answer'] or (q['clip_end'] is not None and q['clip_end'] <= q['clip_start']):
        raise HTTPException(400, 'Заполните вопрос и ответ; конец отрывка должен быть позже начала')
    try:
        store.add_question(code.upper(), user, q)
        await publish(code.upper())
        return store.public(code.upper(), user['id'])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/rooms/{code}/media')
async def upload_media(code: str, request: Request, kind: Literal['image', 'audio', 'video'], authorization: str = Header(default='')):
    user = current_user(authorization)
    try:
        store.media_permission(code.upper(), user)
    except ValueError as e:
        raise HTTPException(403, str(e))
    directory = Path(store.path).parent / 'media'
    directory.mkdir(parents=True, exist_ok=True)
    asset = secrets.token_hex(20)
    path = directory / (asset+'.part')
    kept = False
    try:
        total, prefix = 0, b''
        with path.open('wb') as f:
            async for chunk in request.stream():
                total += len(chunk)
                if total > MAX_MEDIA_BYTES:
                    raise HTTPException(413, 'Максимальный размер файла — 25 МБ')
                prefix = (prefix+chunk)[:128] if len(prefix) < 128 else prefix
                f.write(chunk)
        mime, extension = detect_media(prefix, kind)
        filename = asset+extension
        path = path.rename(directory / filename)
        store.save_media(code.upper(), user, asset, kind, mime, filename)
        kept = True
        return {'id': asset, 'kind': kind, 'url': '/api/media/'+asset}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        if not kept:
            path.unlink(missing_ok=True)


@app.get('/api/media/{asset}')
def media(asset: str, ratrace_session: str = Cookie(default='')):
    user = current_user('Bearer '+ratrace_session)
    try:
        info = store.media_info(asset)
        store.public(info['room'], user['id'], display=True)
    except ValueError as e:
        raise HTTPException(404, str(e))
    path = Path(store.path).parent / 'media' / info['filename']
    if not path.is_file():
        raise HTTPException(404, 'Файл не найден')
    return FileResponse(path, media_type=info['mime'], headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=3600'})


@app.post('/api/rooms/{code}/join')
async def join(code: str, authorization: str = Header(default='')):
    user = current_user(authorization)
    try:
        store.change(code.upper(), user, 'join')
        await publish(code.upper())
        return store.public(code.upper(), user['id'])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get('/api/rooms/{code}')
def state(code: str, authorization: str = Header(default='')):
    user = current_user(authorization)
    try:
        return store.public(code.upper(), user['id'])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/rooms/{code}/watch')
async def watch(code: str, authorization: str = Header(default='')):
    user = current_user(authorization)
    try:
        store.change(code.upper(), user, 'watch')
        await publish(code.upper())
        return store.public(code.upper(), user['id'], display=True)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post('/api/rooms/{code}/action')
async def action(code: str, body: Command, authorization: str = Header(default='')):
    user = current_user(authorization)
    try:
        changed = store.change(code.upper(), user, body.action, body.question, body.text, body.player, body.choice)
        if changed:
            await publish(code.upper())
        return store.public(code.upper(), user['id'])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.websocket('/ws/{code}')
async def socket(ws: WebSocket, code: str):
    code = code.upper()
    await ws.accept()
    try:
        # Authenticate in the first frame, so tokens never appear in access-log URLs.
        message = await asyncio.wait_for(ws.receive_json(), timeout=10)
        user = store.user(message.get('token', ''))
        if not DEV_MODE and user['id'].startswith('dev-'):
            raise ValueError('Войдите через Telegram')
        display = message.get('display') is True
        snapshot = store.public(code, user['id'], display)
        connections.setdefault(code, {})[ws] = (user['id'], display)
        await ws.send_json(snapshot)
        while True:
            await ws.receive_text()
    except (ValueError, TypeError, AttributeError, asyncio.TimeoutError):
        await ws.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        connections.get(code, {}).pop(ws, None)
        if not connections.get(code):
            connections.pop(code, None)
