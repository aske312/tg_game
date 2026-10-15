import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.media import MAX_MEDIA_BYTES
from app.pack_validation import PublicationError
from builder.auth import check_password
from builder.store import Catalog, Conflict
from app.version import version_info, versioned_html

ROOT = Path(__file__).resolve().parent.parent
COOKIE = 'ratrace_builder'


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class NewGame(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class SaveGame(BaseModel):
    document: dict
    revision: str = Field(min_length=64, max_length=64)


class Version(BaseModel):
    revision: str = Field(min_length=64, max_length=64)


def create_app(catalog, password_hash):
    @asynccontextmanager
    async def lifespan(app):
        if not password_hash:
            raise RuntimeError('Настройте BUILDER_PASSWORD_HASH для конструктора игр')
        yield

    app = FastAPI(title='Крысиные бега — конструктор', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.catalog = catalog
    attempts = {}

    @app.middleware('http')
    async def protections(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('X-Builder-Request') != '1':
                return Response(status_code=403)
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
                return Response(status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        return response

    def author(request: Request):
        token = request.cookies.get(COOKIE, '')
        if not token or not catalog.authenticated(token):
            raise HTTPException(401, 'Войдите в конструктор')
        return token

    def invoke(method, *args):
        try:
            return method(*args)
        except Conflict as error:
            raise HTTPException(409, str(error)) from None
        except PublicationError as error:
            raise HTTPException(400, dict(message='Публикация остановлена. Исправьте отмеченные поля.', issues=error.issues)) from None
        except (ValueError, OSError) as error:
            raise HTTPException(400, str(error)) from None

    @app.get('/')
    def index():
        return HTMLResponse(versioned_html(ROOT / 'builder/static/index.html'))

    @app.get('/favicon.ico')
    def favicon():
        return FileResponse(ROOT / 'static/rat.svg', media_type='image/svg+xml')

    @app.get('/api/version')
    def app_version():
        return version_info()

    app.mount('/static', StaticFiles(directory=ROOT / 'builder/static'), name='static')

    @app.get('/api/health')
    def health():
        return dict(status='ok', service='builder', **version_info())

    @app.post('/api/login')
    async def login(body: Login, request: Request, response: Response):
        ip = request.client.host if request.client else 'unknown'
        now = time.time()
        for key, failures in list(attempts.items()):
            attempts[key] = [stamp for stamp in failures if now-stamp < 300]
            if not attempts[key]:
                del attempts[key]
        failures = attempts.get(ip, [])
        if len(failures) >= 10:
            raise HTTPException(429, 'Слишком много попыток. Попробуйте через 5 минут.')
        if not await asyncio.to_thread(check_password, body.password, password_hash):
            attempts.setdefault(ip, []).append(now)
            raise HTTPException(401, 'Неверный пароль')
        attempts.pop(ip, None)
        token = catalog.session()
        response.set_cookie(COOKIE, token, max_age=43200, httponly=True, secure=request.url.scheme == 'https', samesite='strict')
        return dict(ok=True)

    @app.get('/api/me', dependencies=[Depends(author)])
    def me():
        return dict(name='Автор игр')

    @app.post('/api/logout')
    def logout(response: Response, token=Depends(author)):
        catalog.logout(token)
        response.delete_cookie(COOKIE)
        return dict(ok=True)

    @app.get('/api/games', dependencies=[Depends(author)])
    def games():
        return invoke(catalog.list)

    @app.post('/api/games', dependencies=[Depends(author)])
    def create(body: NewGame):
        if not body.title.strip():
            raise HTTPException(400, 'Введите название игры')
        return invoke(catalog.create, body.title)

    @app.post('/api/games/{game_id}/open', dependencies=[Depends(author)])
    def open_game(game_id: str):
        return invoke(catalog.open, game_id)

    @app.put('/api/games/{game_id}', dependencies=[Depends(author)])
    def save(game_id: str, body: SaveGame):
        return invoke(catalog.save, game_id, body.document, body.revision)

    @app.delete('/api/games/{game_id}', dependencies=[Depends(author)])
    def delete(game_id: str, body: Version):
        return invoke(catalog.delete, game_id, body.revision)

    @app.post('/api/games/{game_id}/publish', dependencies=[Depends(author)])
    def publish(game_id: str, body: Version):
        return invoke(catalog.publish, game_id, body.revision)

    @app.post('/api/games/{game_id}/validate', dependencies=[Depends(author)])
    def validate(game_id: str, body: SaveGame):
        return invoke(catalog.validate, game_id, body.document)

    @app.post('/api/games/{game_id}/reload', dependencies=[Depends(author)])
    def reload(game_id: str):
        return invoke(catalog.reload, game_id)

    @app.post('/api/games/{game_id}/media', dependencies=[Depends(author)])
    async def upload(game_id: str, request: Request, kind: Literal['image', 'audio', 'video']):
        directory = catalog.data / 'uploads'
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / (secrets.token_hex(20) + '.part')
        try:
            total = 0
            with temporary.open('wb') as output:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > MAX_MEDIA_BYTES:
                        raise HTTPException(413, 'Максимальный размер файла — 25 МБ')
                    output.write(chunk)
            return invoke(catalog.upload, game_id, temporary, kind)
        finally:
            temporary.unlink(missing_ok=True)

    @app.get('/api/games/{game_id}/media', dependencies=[Depends(author)])
    def media(game_id: str, file: str):
        folder = invoke(catalog.folder, catalog.drafts, game_id)
        path = invoke(catalog.asset, folder, file)
        if not path.is_file() or path.suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.webp','.mp3','.wav','.ogg','.m4a','.mp4','.webm'):
            raise HTTPException(404, 'Материал не найден')
        return FileResponse(path)

    @app.get('/api/games/{game_id}/export', dependencies=[Depends(author)])
    def export(game_id: str):
        data = invoke(catalog.export, game_id)
        return Response(data, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="{game_id}.zip"'})

    return app


load_dotenv(ROOT / 'data/builder.env')
app = create_app(Catalog(os.getenv('BUILDER_DATA_DIR', ROOT / 'data/builder'),
                         os.getenv('GAME_PACKS_DIR', ROOT / 'data/games'), ROOT / 'games'),
                 os.getenv('BUILDER_PASSWORD_HASH', ''))
