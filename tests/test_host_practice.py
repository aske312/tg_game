import pytest
from fastapi.testclient import TestClient

from app.store import Store
from app.modes import stages_from_doc


def test_host_practice_starts_in_lobby_and_requires_manual_grading(tmp_path,monkeypatch):
    db=Store(tmp_path/'host.sqlite3')
    host=dict(id='h',name='Host')
    code=db.create(host,practice=True,host_practice=True,questions=[dict(id='q',type='question',text='2+2?',answer='4',value=100,seconds=45)])
    state=db.public(code,host['id'])
    assert state['host']==host['id'] and state['phase']=='lobby' and state['host_practice']
    assert len(state['players'])==4 and sum(bool(p.get('synthetic')) for p in state['players'])==3
    assert not any(p['id'].startswith('sim-host-') for p in state['players'])
    db.change(code,host,'start')
    assert db.read(code)['phase']=='intro'
    db.change(code,host,'next')
    with pytest.raises(ValueError):db.change(code,host,'answer',text='4')
    now=[max(db.read(code)['bot_due'].values())+.1]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    assert db.tick(code) and db.read(code)['phase']=='review'
    assert len(db.public(code,host['id'])['answers'])==3
    now[0]+=10
    assert not db.tick(code)
    assert all(a['verdict'] is None for a in db.read(code)['answers'].values())
    for uid in db.read(code)['answers']:db.change(code,host,'correct',player=uid)
    assert db.read(code)['phase']=='reveal'
    db.change(code,host,'show_scores')
    assert db.read(code)['scores_visible']
    db.change(code,host,'next')
    assert db.read(code)['phase']=='finished'


def test_host_rehearsal_keeps_grid_intro_pause_and_round_breaks(tmp_path,monkeypatch):
    db=Store(tmp_path/'grid.sqlite3')
    host=dict(id='h',name='Host')
    stages=stages_from_doc({'stages':[dict(id='g',type='grid',title='Grid',categories=['Topic'])]})
    code=db.create(host,practice=True,host_practice=True,stages=stages,questions=[dict(id='q',stage='g',category='Topic',type='question',text='?',answer='4',value=100,seconds=45)])
    db.change(code,host,'start')
    assert db.read(code)['phase']=='intro'
    db.change(code,host,'next')
    db.change(code,host,'pick',question='q')
    db.change(code,host,'pause')
    now=[max(db.read(code)['bot_due'].values())+100]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    assert not db.tick(code) and db.read(code)['answers']=={}
    db.change(code,host,'unpause')
    now[0]=max(db.read(code)['bot_due'].values())+.1
    assert db.tick(code) and db.read(code)['phase']=='review'


def test_api_allows_both_practice_perspectives_and_preserves_host_media_access(tmp_path,monkeypatch):
    from app import main
    db=Store(tmp_path/'api.sqlite3')
    monkeypatch.setattr(main,'store',db)
    monkeypatch.setattr(main,'DEV_MODE',True)
    with TestClient(main.app) as client:
        auth=client.post('/api/login',json={'name':'Host'}).json()
        headers={'Authorization':'Bearer '+auth['token']}
        host_state=client.post('/api/practice',headers=headers,json={'pack':'library-example-race','role':'host'}).json()
        assert host_state['host']==auth['user']['id'] and host_state['phase']=='lobby'
        assert host_state['question_list']
        assert client.get(host_state['question_list'][0]['media']['url']).status_code==200
        player_state=client.post('/api/practice',headers=headers,json={'pack':'library-example-race','role':'player'}).json()
        assert player_state['host']!=auth['user']['id'] and player_state['phase']=='question'
        assert client.post('/api/practice',headers=headers,json={'role':'invalid'}).status_code==422
        response=client.post('/api/practice',headers=headers,json={'role':'host','pack':'custom'})
        assert response.status_code==200 and response.json()['phase']=='lobby'
        path='/api/rooms/'+response.json()['code']
        assert client.post(path+'/action',headers=headers,json={'action':'start'}).status_code==400
        assert client.post(path+'/questions',headers=headers,json={'text':'2+2?','answer':'4'}).status_code==200
        assert client.post(path+'/action',headers=headers,json={'action':'start'}).json()['phase']=='intro'
        assert client.post(path+'/action',headers=headers,json={'action':'next'}).json()['phase']=='question'
        assert client.post('/api/practice',headers=headers,json={'role':'player','pack':'custom'}).status_code==400
