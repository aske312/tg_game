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
            res = await client.post('/api/practice', headers=headers)
            res.raise_for_status()
            state = res.json()
            code = state['code']
            assert state['owner'] == user['id'] and state['host'] != user['id']
            assert len([p for p in state['players'] if p.get('synthetic')]) == 3
            async with websockets.connect(url.replace('https://', 'wss://')+'/ws/'+code) as ws:
                await ws.send(json.dumps({'token': token}))
                assert json.loads(await asyncio.wait_for(ws.recv(), 5))['phase'] == 'board'
                async def action(action, **extra):
                    res = await client.post('/api/rooms/'+code+'/action', headers=headers, json={'action': action, **extra})
                    res.raise_for_status()
                    return json.loads(await asyncio.wait_for(ws.recv(), 5))
                state = await action('select', question='0-0')
                assert 'answer' not in state['question']
                await action('buzz')
                state = await action('answer', text=BY_ID['0-0']['answer'])
                assert state['submitted']['text'] == BY_ID['0-0']['answer']
                state = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert state['phase'] == 'reveal'
                assert next(p for p in state['players'] if p['id']==user['id'])['score'] == 100
                print('Public WebSocket, text answer and automatic scoring verified.')
                await action('next')
                await action('select', question='0-1')
                state = json.loads(await asyncio.wait_for(ws.recv(), 12))
                assert state['buzzer'].startswith('sim-')
                state = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert state['submitted'] and state['messages'][-1]['kind'] == 'answer'
                state = json.loads(await asyncio.wait_for(ws.recv(), 5))
                assert len(state['attempted']) == 1
                print('Artificial opponent answered and was scored.')
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
                db.execute('DELETE FROM rooms WHERE code=?', (code,))
            db.execute('DELETE FROM sessions WHERE token=?', (token,))
        print('Only the smoke-test room and session were cleaned up.')


if __name__ == '__main__':
    asyncio.run(main())
