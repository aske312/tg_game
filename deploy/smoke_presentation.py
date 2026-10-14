"""Check live presentation controls without depending on the game library."""
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
from app.modes import stages_from_doc


async def main():
    cfg=dotenv_values('/etc/rat-race/app.env')
    url=cfg['APP_URL'].rstrip('/')
    db=Store(cfg['DATABASE_PATH'])
    users=[dict(id='smoke-presentation-'+secrets.token_hex(8),name=name)
           for name in ('Deploy check: host','Deploy check: player','Deploy check: display')]
    tokens=[db.session(user) for user in users]
    headers=[{'Authorization':'Bearer '+token} for token in tokens]
    code=None
    try:
        stages=stages_from_doc({'stages':[
            dict(id='grid',type='grid',title='Test grid',categories=['Space','Music']),
            dict(id='blitz',type='blitz',title='Test blitz',auto_advance=True),
        ]})
        questions=[dict(id=qid,stage=sid,type='question',category=category,text='2+2?',answer='4',value=100,seconds=45)
                   for qid,sid,category in [('g1','grid','Space'),('g2','grid','Music'),('b1','blitz','Test')]]
        code=db.create(users[0],stages=stages,questions=questions,title='Temporary deployment check')
        path='/api/rooms/'+code
        async with httpx.AsyncClient(base_url=url,timeout=15) as client:
            response=await client.get('/api/health');response.raise_for_status()
            print('Public HTTPS health:',response.json(),flush=True)
            page=await client.get('/');page.raise_for_status()
            assert 'id="grid-intro"' in page.text and 'id="pause-game"' in page.text and 'id="award-spotlight"' in page.text
            for asset in ('/static/experience.js?v=1','/static/experience.css?v=1','/static/app.js?v=13'):
                response=await client.get(asset);response.raise_for_status()
                assert len(response.content)>100
            (await client.post(path+'/join',headers=headers[1])).raise_for_status()
            response=await client.post(path+'/watch',headers=headers[2]);response.raise_for_status()
            assert response.json()['display'] and len(response.json()['players'])==2
            ws_url=url.replace('https://','wss://',1).replace('http://','ws://',1)+'/ws/'+code
            async with websockets.connect(ws_url) as display,websockets.connect(ws_url) as player:
                for ws,token,is_display in ((display,tokens[2],True),(player,tokens[1],False)):
                    await ws.send(json.dumps(dict(token=token,display=is_display)))
                    assert json.loads(await asyncio.wait_for(ws.recv(),8))['display']==is_display
                async def action(actor,kind,**body):
                    response=await client.post(path+'/action',headers=headers[actor],json=dict(action=kind,**body))
                    response.raise_for_status()
                    state=response.json()
                    shadows=[]
                    for ws in (display,player):
                        while True:
                            shadow=json.loads(await asyncio.wait_for(ws.recv(),8))
                            if shadow['version']>=state['version']:break
                        shadows.append(shadow)
                    assert shadows[0]['display'] and len(shadows[0]['players'])==2
                    return state,shadows
                async def denied(actor,kind,**body):
                    response=await client.post(path+'/action',headers=headers[actor],json=dict(action=kind,**body))
                    assert response.status_code==400,(kind,response.status_code)

                state,shadows=await action(0,'start')
                assert all(s['phase']=='intro' for s in shadows)
                assert state['stage']['categories']==['Space','Music']
                await denied(1,'next')
                await denied(0,'pick',question='g1')
                await action(0,'next')
                state,_=await action(0,'pick',question='g1')
                deadline=state['deadline']
                state,_=await action(0,'pause')
                assert state['paused']
                await denied(1,'answer',text='4')
                await denied(1,'unpause')
                ui_version=state['ui_version']
                state,shadows=await action(1,'reaction',text='🔥')
                assert all(s['reactions'][-1]['emoji']=='🔥' for s in shadows)
                assert state['ui_version']==ui_version
                response=await client.post(path+'/action',headers=headers[1],json=dict(action='reaction',text='👏'))
                assert response.status_code==200 and response.json()['version']==state['version']
                await asyncio.sleep(1.1)
                state,_=await action(1,'reaction',text='👏')
                assert len(state['reactions'])==2
                assert state['paused'] and state['phase']=='question' and state['deadline']==deadline
                state,_=await action(0,'unpause')
                assert state['deadline']>=deadline+1
                _,shadows=await action(1,'answer',text='4')
                assert shadows[0]['answers']=={} and 'answer' not in shadows[0]['question']
                state,_=await action(0,'correct',player=users[1]['id'])
                assert state['chooser']==users[1]['id'] and state['can_pick']
                await action(1,'pick',question='g2')
                await action(1,'answer',text='4')
                state,_=await action(0,'correct',player=users[1]['id'])
                assert state['stage_complete']
                await denied(1,'show_scores')
                state,shadows=await action(0,'show_scores')
                assert all(s['scores_visible'] for s in shadows)
                await action(0,'pause')
                await action(0,'unpause')
                state,_=await action(0,'next')
                assert state['active']=='b1' and not state['scores_visible']
                await action(1,'answer',text='4')
                state,_=await action(0,'correct',player=users[1]['id'])
                assert state['advance_at'] is None
                await action(0,'show_scores')
                state,shadows=await action(0,'next')
                assert all(s['phase']=='finished' and s['finished_at']==state['finished_at'] for s in shadows)
                assert next(p for p in state['players'] if p['id']==users[1]['id'])['score']==300
                print('Public WebSocket: intro, silent reaction limit, pause, preserved deadline, grid choice, round scores and synchronized finish verified.',flush=True)
    finally:
        with db.connect() as conn:
            if code:conn.execute('DELETE FROM rooms WHERE code=?',(code,))
            conn.executemany('DELETE FROM sessions WHERE token=?',[(token,) for token in tokens])
        print('Only this check\'s temporary room and sessions were cleaned up.',flush=True)


if __name__=='__main__':
    asyncio.run(main())
