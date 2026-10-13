"""Verify the deployed app with a short-lived, explicitly named test session."""
import asyncio
import json
import secrets
import sys
from pathlib import Path

import httpx
import websockets
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.store import Store
from app.questions import BY_ID


async def main():
    cfg = dotenv_values('/etc/rat-race/app.env')
    url = cfg['APP_URL'].rstrip('/')
    store = Store(cfg['DATABASE_PATH'])
    user = {'id': 'smoke-'+secrets.token_hex(8), 'name': 'Проверка развёртывания'}
    token = store.session(user)
    code = None
    try:
        async with httpx.AsyncClient(base_url=url, timeout=15) as client:
            health = await client.get('/api/health')
            health.raise_for_status()
            print('HTTPS/database health:', health.json())
            assert (await client.post('/api/login', json={'name': 'Anonymous'})).status_code == 401
            assert (await client.post('/api/practice')).status_code == 401
            print('Anonymous access is blocked.')
            headers = {'Authorization': 'Bearer '+token}
            await client.get('/api/me', headers=headers)
            library = await client.get('/api/packs', headers=headers)
            library.raise_for_status()
            assert any(p['id']=='library-example-race' for p in library.json()['packs'])
            res = await client.post('/api/practice', headers=headers, json={'pack':'library-example-race'})
            res.raise_for_status()
            state = res.json()
            code = state['code']
            assert state['owner'] == user['id'] and state['host'] != user['id']
            assert len([p for p in state['players'] if p.get('synthetic')]) == 3
            async with websockets.connect(url.replace('https://', 'wss://')+'/ws/'+code) as ws:
                await ws.send(json.dumps({'token': token}))
                assert json.loads(await asyncio.wait_for(ws.recv(), 5))['phase'] == 'question'
                async def action(action, **extra):
                    res = await client.post('/api/rooms/'+code+'/action', headers=headers, json={'action': action, **extra})
                    res.raise_for_status()
                    return res.json()
                assert 'answer' not in state['question']
                image = await client.get(state['question']['media']['url'], headers={'Range':'bytes=0-7'})
                assert image.status_code == 206 and image.content == b'\x89PNG\r\n\x1a\n'
                answer = store.read(code)['pack'][0]['answer']
                state = await action('answer', text=answer)
                assert state['answers'][user['id']]['text'] == answer
                while state['phase'] != 'reveal':
                    state = json.loads(await asyncio.wait_for(ws.recv(), 15))
                assert state['phase'] == 'reveal'
                assert next(p for p in state['players'] if p['id']==user['id'])['score'] == 100
                assert len(state['answers']) == 3
                print('Public WebSocket, parallel answers, robots and automatic scoring verified.')
                state = await action('next')
                assert state['phase'] == 'event' and len(state['event']['targets']) == 1
                state = await action('next')
                assert state['question']['media']['kind'] == 'audio'
                audio = await client.get(state['question']['media']['url'],headers={'Range':'bytes=0-15'})
                assert audio.status_code == 206
                await action('close')
                state = await action('next')
                assert state['phase'] == 'event' and len(state['event']['targets']) == 3
                state = await action('next')
                assert state['question']['media']['kind'] == 'video'
                video = await client.get(state['question']['media']['url'],headers={'Range':'bytes=0-31'})
                assert video.status_code == 206
                print('JSON library, persisted events, authenticated image/audio/video ranges verified.')
            base = 'https://api.telegram.org/bot'+cfg['BOT_TOKEN']
            try:
                menu = (await client.post(base+'/getChatMenuButton', json={})).json()
                assert menu.get('ok') and menu['result']['web_app']['url'].rstrip('/') == url
                print('Telegram menu points to the server HTTPS URL.')
            except httpx.HTTPError:
                raise RuntimeError('Telegram menu check failed') from None
    finally:
        with store.connect() as db:
            if code:
                db.execute('DELETE FROM media WHERE room=?', (code,))
                db.execute('DELETE FROM rooms WHERE code=?', (code,))
            db.execute('DELETE FROM sessions WHERE token=?', (token,))
        print('Only the smoke-test room and session were cleaned up.')


if __name__ == '__main__':
    asyncio.run(main())
