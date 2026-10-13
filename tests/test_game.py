import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import pytest
from app.auth import validate_telegram
from app.store import Store

@pytest.fixture
def game(tmp_path):
    db=Store(tmp_path/'game.sqlite3')
    host={'id':'1','name':'Ведущий'}
    a={'id':'2','name':'Аня'}
    b={'id':'3','name':'Борис'}
    code=db.create(host)
    for p in (a,b): db.change(code,p,'join')
    db.change(code,host,'start')
    db.change(code,host,'select','0-0')
    return db,code,host,a,b

def test_scoring_and_answers(game):
    db,code,host,a,b=game
    assert 'answer' not in db.public(code,a['id'])['question']
    assert db.public(code,host['id'])['question']['answer']=='Меркурий'
    db.change(code,a,'buzz')
    db.change(code,a,'answer',text='Венера')
    db.change(code,host,'wrong')
    with pytest.raises(ValueError): db.change(code,a,'buzz')
    db.change(code,b,'buzz')
    db.change(code,b,'answer',text='Меркурий')
    db.change(code,host,'correct')
    s=db.public(code,a['id'])
    assert s['phase']=='reveal' and s['question']['answer']=='Меркурий'
    assert [p['score'] for p in s['players']]==[0,-100,100]
    with pytest.raises(ValueError): db.change(code,host,'correct')
    db.change(code,host,'next')
    with pytest.raises(ValueError): db.change(code,host,'select','0-0')

def test_simultaneous_buzz(game):
    db,code,host,a,b=game
    def buzz(p):
        try: db.change(code,p,'buzz'); return True
        except ValueError: return False
    with ThreadPoolExecutor(max_workers=2) as pool: assert sum(pool.map(buzz,[a,b]))==1
    assert db.read(code)['buzzer'] in ('2','3')

def test_permissions_persistence_timeout(game,monkeypatch):
    db,code,host,a,b=game
    with pytest.raises(ValueError): db.change(code,a,'skip')
    with pytest.raises(ValueError): db.public(code,'outsider')
    with pytest.raises(ValueError): db.change(code,{'id':'4','name':'Поздний'},'join')
    token=db.session(a)
    restored=Store(db.path)
    assert restored.user(token)==a and restored.read(code)['active']=='0-0'
    deadline=db.read(code)['deadline']
    monkeypatch.setattr('app.store.time.time',lambda:deadline+1)
    with pytest.raises(ValueError): db.change(code,a,'buzz')
    db.change(code,host,'skip'); db.change(code,host,'finish')
    assert db.read(code)['phase']=='finished'

def signed(token,age=0):
    d={'auth_date':str(int(time.time())-age),'user':json.dumps({'id':123,'first_name':'Тест'})}
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    d['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(d.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(d)

def test_auth():
    assert validate_telegram(signed('secret'),'secret')['id']=='123'
    for raw,token in [(signed('secret'),'wrong'),(signed('secret',90000),'secret'),('user=fake','secret')]:
        with pytest.raises(ValueError): validate_telegram(raw,token)


def test_bot_room_invitation():
    from app.bot import invitation_url
    assert invitation_url('https://example.com', '/start ABC234')=='https://example.com?room=ABC234'
    assert invitation_url('https://example.com/?mode=test', '/start abc234')=='https://example.com/?mode=test&room=ABC234'
    assert invitation_url('https://example.com', '/start')=='https://example.com'
    assert invitation_url('https://example.com', '/start https://other.example')=='https://example.com'


def test_bot_profile_rate_limit_does_not_block_startup():
    import asyncio
    from app.bot import configure_bot
    calls=[]
    async def configured(method, **payload):
        calls.append(method)
        if method=='getChatMenuButton': return {'web_app':{'url':'https://example.com/'}}
        if method=='getMyName': return {'name':'Крысиные бега'}
        raise AssertionError('Already configured profile should not be changed')
    asyncio.run(configure_bot(configured,'https://example.com'))
    assert 'setMyName' not in calls and 'setChatMenuButton' not in calls
    async def limited(method, **payload):
        if method=='getChatMenuButton': return {'web_app':{'url':'https://example.com'}}
        if method=='getMyName': return {'name':'Old name'}
        if method=='setMyName': raise RuntimeError('Too Many Requests: retry after 85061')
        raise AssertionError(method)
    # This used to abort the bot before it could start receiving messages.
    asyncio.run(configure_bot(limited,'https://example.com'))

def test_http_websocket(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main,'store',Store(tmp_path/'api.sqlite3'))
    monkeypatch.setattr(main,'DEV_MODE',True)
    with TestClient(main.app) as client:
        host=client.post('/api/login',json={'name':'Host'}).json()
        player=client.post('/api/login',json={'name':'Player'}).json()
        headers={'Authorization':'Bearer '+host['token']}
        ph={'Authorization':'Bearer '+player['token']}
        assert client.post('/api/rooms').status_code==401
        code=client.post('/api/rooms',headers=headers).json()['code']
        assert client.post(f'/api/rooms/{code}/join',headers=ph).status_code==200
        with client.websocket_connect(f'/ws/{code}') as ws:
            ws.send_json({'token':player['token']})
            assert ws.receive_json()['phase']=='lobby'
            assert client.post(f'/api/rooms/{code}/action',headers=headers,json={'action':'start'}).status_code==200
            assert ws.receive_json()['phase']=='board'
            client.post(f'/api/rooms/{code}/action',headers=headers,json={'action':'select','question':'0-0'})
            assert 'answer' not in ws.receive_json()['question']
        monkeypatch.setattr(main,'DEV_MODE',False)
        assert client.post('/api/login',json={'name':'Fake'}).status_code==401
        assert client.get('/api/me',headers=headers).status_code==401

def test_complete_game_and_reconnect(game):
    from app.questions import QUESTIONS
    db,code,host,a,b=game
    for q in QUESTIONS:
        if q['id']!='0-0': db.change(code,host,'select',q['id'])
        db.change(code,a,'buzz')
        db.change(code,a,'answer',text=q['answer'])
        db.change(code,host,'correct')
        db.change(code,host,'next')
    s=db.read(code)
    assert s['phase']=='finished'
    assert len(s['used'])==20
    assert s['players'][1]['score']==6000
    db.change(code,a,'join')
    assert len(db.read(code)['players'])==3


def test_text_chat_and_answer_permissions(game, monkeypatch):
    db,code,host,a,b=game
    db.change(code,a,'message',text='<b>Привет</b>')
    assert db.public(code,b['id'])['messages'][-1]['text']=='<b>Привет</b>'
    assert db.read(code)['phase']=='question'
    with pytest.raises(ValueError): db.change(code,a,'answer',text='Меркурий')
    db.change(code,a,'buzz')
    with pytest.raises(ValueError): db.change(code,b,'answer',text='Меркурий')
    with pytest.raises(ValueError): db.change(code,host,'correct')
    with pytest.raises(ValueError): db.change(code,a,'answer',text='  ')
    deadline=db.read(code)['deadline']
    monkeypatch.setattr('app.store.time.time',lambda:deadline+1)
    with pytest.raises(ValueError): db.change(code,a,'answer',text='Меркурий')
    with pytest.raises(ValueError): db.change(code,host,'correct')
    db.change(code,host,'wrong')
    assert db.read(code)['players'][1]['score']==-100


def test_answer_can_only_be_submitted_once(game):
    db,code,host,a,b=game
    db.change(code,a,'buzz')
    db.change(code,a,'answer',text='Меркурий')
    with pytest.raises(ValueError): db.change(code,a,'answer',text='Венера')
    assert db.public(code,host['id'])['submitted']['text']=='Меркурий'
    db.change(code,host,'correct')
    restored=Store(db.path).public(code,a['id'])
    assert any(m['kind']=='answer' and m['text']=='Меркурий' for m in restored['messages'])


def test_practice_player_and_auto_host(tmp_path,monkeypatch):
    db=Store(tmp_path/'practice.sqlite3')
    user={'id':'real-player','name':'Игрок'}
    code=db.create(user,practice=True)
    s=db.public(code,user['id'])
    assert s['host']!=user['id'] and s['owner']==user['id']
    assert len([p for p in s['players'] if p.get('synthetic')])==3
    assert not db.tick_practice(code)
    with pytest.raises(ValueError): db.change(code,user,'correct')
    db.change(code,user,'select','0-0')
    assert 'answer' not in db.public(code,user['id'])['question']
    db.change(code,user,'buzz')
    db.change(code,user,'answer',text='  МЕРКУРИЙ!!! ')
    assert not db.tick_practice(code)
    now=[db.read(code)['auto_at']+.01]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    assert db.tick_practice(code)
    s=db.read(code)
    assert s['phase']=='reveal' and s['players'][1]['score']==100
    db.change(code,user,'next')
    db.change(code,user,'select','0-1')
    now[0]+=7.01
    assert db.tick_practice(code)
    assert db.read(code)['buzzer'].startswith('sim-')
    now[0]+=2.01
    assert db.tick_practice(code)
    assert db.read(code)['submitted']['text']=='Не знаю'
    now[0]+=1.51
    assert db.tick_practice(code)
    assert db.read(code)['phase']=='question'
    assert any(p['score']==-200 for p in db.read(code)['players'])
    db.change(code,user,'buzz')
    now[0]+=20.01
    assert db.tick_practice(code)
    assert db.read(code)['players'][1]['score']==-100
    # A restarted process picks up persisted simulation deadlines.
    restored=Store(db.path)
    now[0]+=7.01
    assert restored.tick_practice(code)
    db.change(code,user,'finish')
    assert not restored.tick_practice(code)
    assert code not in restored.practice_rooms()


def test_practice_api(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main,'store',Store(tmp_path/'practice-api.sqlite3'))
    monkeypatch.setattr(main,'DEV_MODE',True)
    with TestClient(main.app) as client:
        assert client.post('/api/practice').status_code==401
        auth=client.post('/api/login',json={'name':'Тест'}).json()
        headers={'Authorization':'Bearer '+auth['token']}
        s=client.post('/api/practice',headers=headers).json()
        assert s['practice'] and s['host']!=auth['user']['id']
        with client.websocket_connect('/ws/'+s['code']) as ws:
            ws.send_json({'token':auth['token']})
            assert ws.receive_json()['phase']=='board'
            path='/api/rooms/'+s['code']+'/action'
            assert client.post(path,headers=headers,json={'action':'select','question':'0-0'}).status_code==200
            assert ws.receive_json()['phase']=='question'
            client.post(path,headers=headers,json={'action':'buzz'})
            assert ws.receive_json()['phase']=='answer'
            client.post(path,headers=headers,json={'action':'answer','text':'Меркурий'})
            assert ws.receive_json()['submitted']['text']=='Меркурий'
            assert ws.receive_json()['phase']=='reveal'
