import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.store import Store


def telegram_data(user_id=123):
    data={'auth_date':str(int(time.time())), 'user':json.dumps({'id':user_id,'first_name':'Telegram host'})}
    secret=hmac.new(b'WebAppData',b'test-bot-token',hashlib.sha256).digest()
    data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest.fixture
def production(tmp_path,monkeypatch):
    from app import main
    db=Store(tmp_path/'web.sqlite3')
    monkeypatch.setattr(main,'store',db)
    monkeypatch.setattr(main,'DEV_MODE',False)
    monkeypatch.setattr(main,'BOT_TOKEN','test-bot-token')
    monkeypatch.setattr(main,'connections',{})
    with TestClient(main.app,base_url='https://testserver') as client:
        yield client,db,main


def test_production_web_login_and_cookie_restore(production):
    client,db,_=production
    result=client.post('/api/login',json={'name':'  Web Player  '})
    assert result.status_code==200
    auth=result.json();assert auth['user']['name']=='Web Player'
    assert auth['user']['id'].startswith('web-') and auth['user']['auth_source']=='web'
    assert 'httponly' in result.headers['set-cookie'].lower() and 'secure' in result.headers['set-cookie'].lower()
    assert result.headers['cache-control']=='no-store'
    assert client.get('/api/config').json()['web_login'] is True
    assert client.get('/api/web-session').json()==auth
    assert client.post('/api/login',json={'name':'Web Player'}).json()==auth
    assert client.get('/api/me',headers={'Authorization':'Bearer '+auth['token']}).json()==auth['user']
    assert client.post('/api/rooms',json={'pack':'custom'},headers={'Authorization':'Bearer '+auth['token']}).status_code==200


def test_web_names_are_not_account_identifiers(production):
    client,db,main=production
    first=client.post('/api/login',json={'name':'Same name'}).json()
    with TestClient(main.app,base_url='https://testserver') as other:
        second=other.post('/api/login',json={'name':'Same name'}).json()
    assert first['user']['id']!=second['user']['id']
    changed=client.post('/api/login',json={'name':'Different name'}).json()
    assert changed['user']['id']!=first['user']['id']
    assert db.user(first['token'])['name']=='Same name'


@pytest.mark.parametrize('name',['','   ','x'*65])
def test_invalid_web_names_are_rejected(production,name):
    client,db,_=production
    assert client.post('/api/login',json={'name':name}).status_code in (401,422)
    with db.connect() as conn:assert conn.execute('SELECT count(*) FROM sessions').fetchone()[0]==0


def test_invalid_telegram_data_does_not_fall_back_to_web(production):
    client,db,_=production
    web=client.post('/api/login',json={'name':'Web'}).json()
    assert client.post('/api/login',json={'init_data':'user=forged','name':'Fallback'}).status_code==401
    assert client.get('/api/web-session').json()==web
    telegram=client.post('/api/login',json={'init_data':telegram_data()}).json()
    assert telegram['user']['id']=='123' and telegram['user'].get('auth_source')!='web'
    assert client.get('/api/web-session').json()==web
    client.cookies.set('ratrace_web_session',telegram['token'])
    assert client.get('/api/web-session').status_code==401


def test_guest_login_does_not_enable_dev_or_unauthenticated_access(production):
    client,db,_=production
    assert client.get('/api/web-session').status_code==401
    assert client.get('/api/me').status_code==401
    assert client.post('/api/practice').status_code==401
    auth=client.post('/api/login',json={'name':'Web'}).json()
    assert client.get('/api/config').json()['dev_mode'] is False
    dev=db.session({'id':'dev-forbidden','name':'Dev'})
    assert client.get('/api/me',headers={'Authorization':'Bearer '+dev}).status_code==401
    assert client.get('/api/me',headers={'Authorization':'Bearer '+auth['token']}).status_code==200


def test_telegram_host_and_web_player_share_a_game_and_reconnect(production):
    client,db,_=production
    host=client.post('/api/login',json={'init_data':telegram_data()}).json()
    player=client.post('/api/login',json={'name':'Web player'}).json()
    code=db.create(host['user'],questions=[dict(id='q',text='2+2?',answer='4',value=100,seconds=3600)])
    path='/api/rooms/'+code
    hh={'Authorization':'Bearer '+host['token']};ph={'Authorization':'Bearer '+player['token']}
    assert client.post(path+'/join',headers=ph).status_code==200
    assert client.post(path+'/action',headers=ph,json={'action':'start'}).status_code==400
    with client.websocket_connect('/ws/'+code) as ws:
        ws.send_json({'token':player['token']});assert ws.receive_json()['phase']=='lobby'
        client.post(path+'/action',headers=hh,json={'action':'start'}).raise_for_status();assert ws.receive_json()['phase']=='intro'
        client.post(path+'/action',headers=hh,json={'action':'next'}).raise_for_status();assert 'answer' not in ws.receive_json()['question']
        client.post(path+'/action',headers=ph,json={'action':'answer','question':'q','text':'4'}).raise_for_status()
        assert ws.receive_json()['phase']=='review'
        client.post(path+'/action',headers=hh,json={'action':'correct','question':'q','player':player['user']['id']}).raise_for_status()
        assert ws.receive_json()['phase']=='reveal'
    restored=client.get('/api/web-session').json();assert restored==player
    assert client.post(path+'/join',headers=ph).status_code==200
    assert len(db.read(code)['players'])==2
    with client.websocket_connect('/ws/'+code) as ws:
        ws.send_json({'token':restored['token']});state=ws.receive_json()
        assert state['answers'][player['user']['id']]['verdict']=='correct'
        assert state['players'][1]['score']==100


def test_browser_host_can_access_materials_in_production(production):
    client,_,_=production
    auth=client.post('/api/login',json={'name':'Browser host'}).json();headers={'Authorization':'Bearer '+auth['token']}
    response=client.post('/api/practice',headers=headers,json={'role':'host','pack':'library-example-race'})
    assert response.status_code==200
    url=response.json()['question_list'][0]['media']['url']
    assert client.get(url,headers={'Range':'bytes=0-7'}).status_code==206


def test_web_logout_revokes_only_its_session(production):
    client,db,_=production
    web=client.post('/api/login',json={'name':'Web'}).json()
    tg=client.post('/api/login',json={'init_data':telegram_data()}).json()
    assert client.post('/api/web-logout').status_code==401
    assert client.post('/api/web-logout',headers={'Authorization':'Bearer '+tg['token']}).status_code==403
    assert client.post('/api/web-logout',headers={'Authorization':'Bearer '+web['token']}).status_code==200
    assert client.get('/api/web-session').status_code==401
    assert client.get('/api/me',headers={'Authorization':'Bearer '+web['token']}).status_code==401
    assert client.get('/api/me',headers={'Authorization':'Bearer '+tg['token']}).status_code==200
    assert client.cookies.get('ratrace_session')==tg['token']
