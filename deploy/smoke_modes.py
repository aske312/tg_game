"""Exercise mixed rounds over the public API using temporary test participants."""
import asyncio
import json
import secrets
import sys
from pathlib import Path

import httpx
import websockets
from dotenv import dotenv_values

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.store import Store


async def main():
    cfg=dotenv_values('/etc/rat-race/app.env')
    url=cfg['APP_URL'].rstrip('/')
    db=Store(cfg['DATABASE_PATH'])
    users=[dict(id='smoke-modes-'+secrets.token_hex(8),name=name) for name in ['Проверка: ведущий','Проверка: первый игрок','Проверка: второй игрок']]
    tokens=[db.session(user) for user in users]
    headers=[{'Authorization':'Bearer '+token} for token in tokens]
    rooms=[]
    try:
        async with httpx.AsyncClient(base_url=url,timeout=15) as client:
            response=await client.post('/api/rooms',headers=headers[0],json={'pack':'library-mixed-rounds'})
            response.raise_for_status()
            code=response.json()['code'];rooms.append(code)
            path='/api/rooms/'+code
            for header in headers[1:]:
                (await client.post(path+'/join',headers=header,json={})).raise_for_status()
            ws_url=url.replace('https://','wss://',1).replace('http://','ws://',1)+'/ws/'+code
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({'token':tokens[2]}))
                assert json.loads(await ws.recv())['phase']=='lobby'
                async def action(actor,kind,expected=200,**body):
                    response=await client.post(path+'/action',headers=headers[actor],json=dict(action=kind,**body))
                    assert response.status_code==expected,(kind,response.status_code,response.text)
                    if expected!=200:return None
                    state=response.json()
                    while True:
                        shadow=json.loads(await asyncio.wait_for(ws.recv(),8))
                        if shadow['version']>=state['version']:break
                    if shadow['phase']=='question':
                        assert 'answer' not in shadow['question'] and 'correct_choice' not in shadow['question']
                        assert set(shadow['answers'])<={users[2]['id']}
                    return state
                state=await action(0,'start')
                seen=[]
                while state['phase']!='finished':
                    mode=state['stage']['type']
                    if not seen or seen[-1]!=mode:seen.append(mode)
                    if state['phase'] in ('board','reveal') and mode=='grid' and not state['stage_complete']:
                        cell=next(q for q in state['board'] if not q['used'])
                        await action(2,'pick',expected=400,question=cell['id'])
                        assert all(set(c)=={'id','category','value','used'} for c in state['board'])
                        actor=1 if state['chooser']==users[1]['id'] else 0
                        state=await action(actor,'pick',question=cell['id'])
                    if state['phase']=='question':
                        question=next(q for q in db.read(code)['pack'] if q['id']==state['active'])
                        if mode=='binary':
                            await action(1,'answer',choice=question['correct_choice'])
                            state=await action(2,'answer',choice=1-question['correct_choice'])
                            assert state['phase']=='reveal'
                        else:
                            await action(1,'answer',text=question['answer'])
                            state=await action(2,'answer',text=question['answer'])
                            assert state['phase']=='review'
                            await action(0,'correct',player=users[2]['id'])
                            state=await action(0,'correct',player=users[1]['id'])
                            if mode=='grid':assert state['chooser']==users[1]['id']
                    if state['phase']=='reveal' and (mode!='grid' or state['stage_complete']):
                        state=await action(0,'next')
                assert seen==['blitz','grid','binary']
                assert len(state['used'])==8 and state['stage_count']==3
                scores={p['id']:p['score'] for p in state['players']}
                assert scores[users[1]['id']]==1000 and scores[users[2]['id']]==600
                print('Public mixed-round API/WebSocket OK: round transitions, grid permissions and winner selection, hidden solutions, binary scoring and shared score.')
            response=await client.post('/api/practice',headers=headers[0],json={'pack':'demo'})
            response.raise_for_status();state=response.json();rooms.append(state['code'])
            assert state['question_count']==23
            media=await client.get(state['question']['media']['url'],headers=dict(headers[0],Range='bytes=0-7'))
            assert media.status_code==206
            print('Editable built-in demo and its authenticated media are available in practice.')
    finally:
        with db.connect() as conn:
            for code in rooms:
                conn.execute('DELETE FROM media WHERE room=?',(code,))
                conn.execute('DELETE FROM rooms WHERE code=?',(code,))
            for token in tokens:conn.execute('DELETE FROM sessions WHERE token=?',(token,))
        print('Only the temporary mode-test rooms and sessions were removed.')


if __name__=='__main__':
    asyncio.run(main())
