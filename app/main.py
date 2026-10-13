import asyncio
import os
import secrets
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import validate_telegram
from app.store import Store

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
    question: str = Field(default='', max_length=20)
    text: str = Field(default='', max_length=500)


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
def login(body: Login):
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
        return {'token': store.session(user), 'user': user}
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(401, str(e))


@app.get('/api/me')
def me(authorization: str = Header(default='')):
    return current_user(authorization)


@app.post('/api/rooms')
def create(authorization: str = Header(default='')):
    return {'code': store.create(current_user(authorization))}


@app.post('/api/practice')
def practice(authorization: str = Header(default='')):
    user = current_user(authorization)
    code = store.create(user, practice=True)
    return store.public(code, user['id'])


async def publish(code):
    for ws, uid in list(connections.get(code, {}).items()):
        try:
            await asyncio.wait_for(ws.send_json(store.public(code, uid)), timeout=3)
        except (RuntimeError, WebSocketDisconnect, asyncio.TimeoutError, OSError):
            connections.get(code, {}).pop(ws, None)


async def simulate():
    while True:
        await asyncio.sleep(.5)
        try:
            for code in store.practice_rooms():
                if store.tick_practice(code):
                    await publish(code)
        except Exception:
            logging.getLogger(__name__).exception('Practice simulation failed')


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


@app.post('/api/rooms/{code}/action')
async def action(code: str, body: Command, authorization: str = Header(default='')):
    user = current_user(authorization)
    try:
        store.change(code.upper(), user, body.action, body.question, body.text)
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
        snapshot = store.public(code, user['id'])
        connections.setdefault(code, {})[ws] = user['id']
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
