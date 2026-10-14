import copy
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.store import Store
from app.packs import load_pack, materialize_pack


@pytest.fixture
def game(tmp_path):
    db = Store(tmp_path/'game.sqlite3')
    host, a, b = [dict(id=str(i), name=str(i)) for i in range(3)]
    code = db.create(host, questions=[dict(id='q', type='question', text='2+2?', answer='4', accepted_answers=['four'], value=100, seconds=45)])
    for p in (a, b):
        db.change(code, p, 'join')
    db.change(code, host, 'start')
    return db, code, host, a, b


def test_private_answers_and_grading(game):
    db, code, host, a, b = game
    db.change(code, a, 'answer', text='4')
    state = db.public(code, b['id'])
    assert state['answers'] == {} and 'answer' not in state['question']
    assert 'accepted_answers' not in state['question'] and 'pack' not in state
    for action in ('message', 'answer'):
        with pytest.raises(ValueError):
            db.change(code, a, action, text='again')
    with pytest.raises(ValueError):
        db.change(code, host, 'correct', player=a['id'])
    db.change(code, b, 'answer', text='5')
    assert db.read(code)['phase'] == 'review'
    db.change(code, host, 'correct', player=a['id'])
    with pytest.raises(ValueError):
        db.change(code, host, 'correct', player=a['id'])
    db.change(code, host, 'wrong', player=b['id'])
    state = Store(db.path).public(code, a['id'])
    assert [p['score'] for p in state['players']] == [0, 100, -100]
    assert state['phase'] == 'reveal'
    db.change(code, host, 'next')
    assert db.read(code)['phase'] == 'finished'


def test_concurrent_answers(game):
    db, code, host, a, b = game
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda p: db.change(code, p, 'answer', text='4'), (a, b)))
    assert len(db.read(code)['answers']) == 2
    assert db.read(code)['phase'] == 'review'


def test_timeout_and_skipped_answer(game, monkeypatch):
    db, code, host, a, b = game
    db.change(code, a, 'answer', text='4')
    now = db.read(code)['deadline']+1
    monkeypatch.setattr('app.store.time.time', lambda: now)
    with pytest.raises(ValueError):
        db.change(code, b, 'answer', text='4')
    assert db.tick(code)
    assert db.read(code)['phase'] == 'question'
    db.change(code, host, 'close')
    db.change(code, host, 'correct', player=a['id'])
    assert db.read(code)['players'][2]['score'] == -100
    with pytest.raises(ValueError):
        db.public(code, 'outsider')


@pytest.mark.parametrize('kind,correct,points', [('double_reward',True,200),('shield',False,0),('half_reward',True,50),('double_penalty',False,-200)])
def test_event_scoring_and_duration(tmp_path, monkeypatch, kind, correct, points):
    from app import events
    monkeypatch.setattr(events.secrets, 'choice', lambda options: kind if isinstance(options[0], str) else options[0])
    db = Store(tmp_path/'event.sqlite3')
    host, player = dict(id='h',name='H'), dict(id='p',name='P')
    event = dict(id='e',type='event',title='Event',text='',effect=dict(type='random_buff' if kind in ('double_reward','shield') else 'random_debuff',target='random_player',questions=1))
    question = dict(id='q',type='question',text='?',answer='4',value=100,seconds=45)
    # Patch only during event drawing: room codes also use secrets.choice.
    monkeypatch.undo()
    code = db.create(host, questions=[event, question, dict(question,id='q2')])
    db.change(code, player, 'join')
    monkeypatch.setattr(events.secrets, 'choice', lambda options: kind if isinstance(options[0], str) else options[0])
    db.change(code, host, 'start')
    assert Store(db.path).public(code,player['id'])['event']['targets'] == ['P']
    assert not db.tick(code)
    db.change(code, host, 'next')
    db.change(code, player, 'answer', text='4')
    assert db.read(code)['modifiers'] == {}
    db.change(code, host, 'correct' if correct else 'wrong', player='p')
    assert db.read(code)['answers']['p']['points'] == points
    db.change(code, host, 'next')
    db.change(code, player, 'answer', text='4')
    db.change(code, host, 'correct', player='p')
    assert db.read(code)['players'][1]['score'] == points+100


def test_practice_robots(tmp_path, monkeypatch):
    db = Store(tmp_path/'practice.sqlite3')
    player = dict(id='p',name='P')
    code = db.create(player, practice=True)
    initial = db.read(code)
    db.change(code, player, 'answer', text=initial['pack'][0]['answer'])
    now = [max(initial['bot_due'].values())+.1]
    monkeypatch.setattr('app.store.time.time', lambda: now[0])
    assert db.tick(code) and db.read(code)['phase'] == 'review'
    now[0] += 2
    assert Store(db.path).tick(code)
    s = db.read(code)
    assert s['phase'] == 'reveal' and s['players'][1]['score'] == 100
    assert sorted(p['score'] for p in s['players'][2:]) == [-100,100]


def test_json_pack_snapshot(tmp_path):
    pack = load_pack('games/example-race')
    assert len(pack['questions']) == 6
    assets = materialize_pack(pack, tmp_path/'media')
    assert len(assets) == 3
    assert all('source' not in q.get('media', {}) for q in pack['questions'])
    db = Store(tmp_path/'db.sqlite3')
    host = dict(id='h',name='H')
    code = db.create(host, questions=pack['questions'], assets=assets)
    pack['questions'][0]['answer'] = 'changed'
    assert db.read(code)['pack'][0]['answer'] != 'changed'
    assert db.media_info(assets[0]['id'])['room'] == code


@pytest.mark.parametrize('mutation', ['unknown','duration','duplicate','escape','only_events'])
def test_invalid_pack(tmp_path, mutation):
    doc = dict(schema_version=1,title='Test',rounds=[dict(id='q',type='question',text='?',answer='4')])
    if mutation == 'unknown': doc['rounds'][0]['type']='other'
    if mutation == 'duplicate': doc['rounds']*=2
    if mutation == 'escape': doc['rounds'][0]['media']=dict(type='image',file='../outside.png')
    if mutation in ('duration','only_events'):
        doc['rounds']=[dict(id='e',type='event',effect=dict(type='random_buff',target='all_players',questions=6 if mutation=='duration' else 1))]
    (tmp_path/'game.json').write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError): load_pack(tmp_path)


def test_api_library_media_and_websocket(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main,'store',Store(tmp_path/'api.sqlite3'))
    monkeypatch.setattr(main,'DEV_MODE',True)
    with TestClient(main.app) as client:
        host=client.post('/api/login',json={'name':'H'}).json()
        hh={'Authorization':'Bearer '+host['token']}
        assert client.get('/api/packs',headers=hh).json()['packs']
        code=client.post('/api/rooms',headers=hh,json={'pack':'library-example-race'}).json()['code']
        s=client.get('/api/rooms/'+code,headers=hh).json()
        media=s['question_list'][0]['media']['url']
        assert client.get(media,headers={'Range':'bytes=0-7'}).status_code == 206
        player=client.post('/api/login',json={'name':'P'}).json()
        ph={'Authorization':'Bearer '+player['token']}
        assert client.get(media).status_code == 404
        assert client.post('/api/rooms/'+code+'/join',headers=ph).status_code == 200
        assert client.get(media).status_code == 200
        assert client.post('/api/rooms/'+code+'/media?kind=image',headers=ph,content=b'invalid').status_code == 403
        with client.websocket_connect('/ws/'+code) as ws:
            ws.send_json({'token':player['token']})
            assert ws.receive_json()['phase']=='lobby'
            assert client.post('/api/rooms/'+code+'/action',headers=hh,json={'action':'start'}).status_code==200
            s=ws.receive_json()
            assert s['phase']=='question' and 'answer' not in s['question']
            client.post('/api/rooms/'+code+'/action',headers=ph,json={'action':'answer','text':'red'})
            assert ws.receive_json()['phase']=='review'
        client.cookies.clear()
        assert client.get(media).status_code == 401


def test_custom_media_upload(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    monkeypatch.setattr(main,'store',Store(tmp_path/'api.sqlite3'))
    monkeypatch.setattr(main,'DEV_MODE',True)
    with TestClient(main.app) as client:
        auth=client.post('/api/login',json={'name':'H'}).json()
        headers={'Authorization':'Bearer '+auth['token']}
        code=client.post('/api/rooms',headers=headers,json={'pack':'custom'}).json()['code']
        path='/api/rooms/'+code
        assert client.post(path+'/media?kind=image',headers=headers,content=b'<svg/>').status_code==400
        asset=client.post(path+'/media?kind=audio',headers=headers,content=Path('static/demo/signals.wav').read_bytes()).json()
        s=client.post(path+'/questions',headers=headers,json=dict(text='?',answer='3',media_id=asset['id'],clip_start=0,clip_end=3)).json()
        assert s['question_list'][0]['media']['end']==3
        assert client.get(asset['url'],headers={'Range':'bytes=0-15'}).status_code==206


def test_complete_library_sequence(tmp_path):
    db=Store(tmp_path/'sequence.sqlite3')
    pack=load_pack('games/example-race')
    host,player=dict(id='h',name='H'),dict(id='p',name='P')
    code=db.create(host,questions=pack['questions'])
    db.change(code,player,'join')
    db.change(code,host,'start')
    phases=[]
    while db.read(code)['phase']!='finished':
        state=db.read(code)
        phases.append(state['phase'])
        if state['phase']=='question':
            db.change(code,player,'answer',text='answer')
            db.change(code,host,'correct',player='p')
        else:
            db.change(code,host,'next')
    assert phases.count('event')==2 and phases.count('question')==4
    assert len(db.read(code)['used'])==6


def test_legacy_room_migration(game):
    db,code,host,a,b=game
    state=db.read(code)
    state.pop('schema')
    state.update(phase='board',active=None,players=[dict(host,score=0),dict(a,score=350),dict(b,score=-50)])
    with db.connect() as conn:
        conn.execute('UPDATE rooms SET state=? WHERE code=?',(json.dumps(state),code))
    restored=Store(db.path)
    state=restored.public(code,a['id'])
    assert state['phase']=='ready' and state['schema']==2
    assert [p['score'] for p in state['players']]==[0,350,-50]
    restored.change(code,host,'next')
    assert restored.read(code)['phase']=='question'
