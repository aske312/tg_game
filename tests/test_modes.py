import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.modes import stages_from_doc
from app.packs import load_pack
from app.store import Store
from builder.store import Catalog


def stage(sid, mode, **settings):
    if mode == 'grid':
        settings.setdefault('categories', ['Тема'])
    return stages_from_doc({'stages':[dict(id=sid,type=mode,title=sid,**settings)]})[0]


def question(qid, sid, **fields):
    return dict(id=qid,stage=sid,type='question',category='Тема',text=qid,answer='Да',value=100,seconds=45,**fields)


def room(tmp_path, stages, questions):
    db=Store(tmp_path/'modes.sqlite3')
    host,a,b=[dict(id=name,name=name) for name in ('host','a','b')]
    code=db.create(host,stages=stages,questions=questions)
    for user in (a,b):db.change(code,user,'join')
    db.change(code,host,'start')
    if db.read(code)['phase']=='intro':
        db.change(code,host,'next')
    return db,code,host,a,b


def answer_and_grade(db,code,host,a,b):
    db.change(code,a,'answer',text='Да')
    db.change(code,b,'answer',text='Да')
    db.change(code,host,'correct',player='b')
    db.change(code,host,'correct',player='a')


def test_six_mixed_rounds_share_score_and_persist(tmp_path):
    stages=[stage(str(i),mode) for i,mode in enumerate(('blitz','grid','binary','binary','blitz','grid'))]
    questions=[question('q'+s['id'],s['id'],**(dict(choices=['Да','Нет'],correct_choice=0) if s['type']=='binary' else {})) for s in stages]
    db,code,host,a,b=room(tmp_path,stages,questions)
    for index,s in enumerate(stages):
        state=Store(db.path).public(code,'a')
        assert state['stage_number']==index+1 and state['stage_count']==6
        if s['type']=='grid':
            if state['phase']=='intro':
                db.change(code,host,'next')
                state=db.public(code,'a')
            assert state['phase']=='board' and not state['can_pick']
            assert all(set(cell)=={'id','category','value','used'} for cell in state['board'])
            db.change(code,host,'pick',question='q'+s['id'])
        if s['type']=='binary':
            db.change(code,a,'answer',choice=0)
            db.change(code,b,'answer',choice=1)
            assert db.read(code)['phase']=='reveal'
        else:
            answer_and_grade(db,code,host,a,b)
        db=Store(db.path)
        assert next(p for p in db.read(code)['players'] if p['id']=='a')['score']==100*(index+1)
        db.change(code,host,'next')
    assert db.read(code)['phase']=='finished' and len(db.read(code)['used'])==6
    assert next(p for p in db.read(code)['players'] if p['id']=='b')['score']==200


def test_grid_first_correct_answer_gets_choice_after_all_grades(tmp_path,monkeypatch):
    db,code,host,a,b=room(tmp_path,[stage('g','grid')],[question('q1','g'),question('q2','g'),question('q3','g')])
    db.change(code,host,'pick',question='q2')
    now=[1000]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    db.change(code,b,'answer',text='Да')
    now[0]+=1
    db.change(code,a,'answer',text='Да')
    db.change(code,host,'correct',player='a')
    assert not db.public(code,'a')['can_pick']
    db.change(code,host,'correct',player='b')
    assert db.public(code,'b')['can_pick'] and not db.public(code,'a')['can_pick']
    with pytest.raises(ValueError):db.change(code,a,'pick',question='q1')
    with pytest.raises(ValueError):db.change(code,b,'pick',question='q2')
    with pytest.raises(ValueError):db.change(code,b,'pick',question='')
    db.change(code,b,'pick',question='q1')
    assert db.read(code)['active']=='q1'


@pytest.mark.parametrize('chooser', ['host','winner'])
def test_grid_host_setting_or_no_correct_answers_return_to_host(tmp_path,chooser):
    db,code,host,a,b=room(tmp_path,[stage('g','grid',chooser=chooser)],[question('q1','g'),question('q2','g')])
    db.change(code,host,'pick',question='q1')
    db.change(code,a,'answer',text='Да')
    db.change(code,b,'answer',text='Нет')
    db.change(code,host,'wrong',player='b')
    db.change(code,host,'correct' if chooser=='host' else 'wrong',player='a')
    assert db.read(code)['chooser']=='host'
    assert not db.public(code,'a')['can_pick']
    db.change(code,host,'next')
    assert db.read(code)['phase']=='board'


def test_binary_has_only_two_choices_and_no_early_solution(tmp_path):
    db,code,host,a,b=room(tmp_path,[stage('b','binary')],[question('q','b',choices=['Бан','Пропан'],correct_choice=1)])
    with pytest.raises(ValueError):db.change(code,a,'answer',text='Пропан')
    with pytest.raises(ValueError):db.change(code,a,'answer',choice=True)
    with pytest.raises(ValueError):db.change(code,a,'answer',choice=2)
    db.change(code,a,'answer',choice=1)
    state=db.public(code,'b')
    assert state['answers']=={} and state['question']['choices']==['Бан','Пропан']
    assert 'correct_choice' not in state['question'] and 'answer' not in state['question']
    db.change(code,b,'answer',choice=0)
    state=db.read(code)
    assert state['phase']=='reveal' and state['answers']['a']['text']=='Пропан'
    assert state['answers']['a']['points']==100 and state['answers']['b']['points']==-100
    with pytest.raises(ValueError):db.change(code,host,'correct',player='b')


def test_blitz_random_order_keeps_events_and_survives_restart(tmp_path,monkeypatch):
    monkeypatch.setattr('app.store.SystemRandom.shuffle',lambda self,items:items.reverse())
    event=dict(id='e',stage='b',type='event',title='Event',text='',effect=dict(type='random_buff',target='all_players',questions=1))
    db,code,host,a,b=room(tmp_path,[stage('b','blitz',order='random')],[question('q1','b'),event,question('q2','b'),question('q3','b')])
    assert [q['id'] for q in Store(db.path).read(code)['pack']]==['q3','e','q2','q1']
    assert db.read(code)['active']=='q3'


def test_auto_blitz_waits_for_grading_then_moves_once(tmp_path,monkeypatch):
    db,code,host,a,b=room(tmp_path,[stage('b','blitz',auto_advance=True)],[question('q1','b'),question('q2','b')])
    db.change(code,a,'answer',text='Да')
    db.change(code,b,'answer',text='Да')
    db.change(code,host,'correct',player='a')
    assert not db.tick(code) and db.read(code)['advance_at'] is None
    db.change(code,host,'correct',player='b')
    now=db.read(code)['advance_at']+.1
    monkeypatch.setattr('app.store.time.time',lambda:now)
    assert Store(db.path).tick(code)
    assert db.read(code)['active']=='q2' and db.read(code)['advance_at'] is None
    assert not db.tick(code)


def test_auto_event_then_timeout_waits_for_host_and_penalizes_skips(tmp_path,monkeypatch):
    event=dict(id='e',stage='b',type='event',title='Event',text='',effect=dict(type='double_reward',target='all_players',questions=1))
    db,code,host,a,b=room(tmp_path,[stage('b','blitz',auto_advance=True)],[event,question('q','b')])
    now=[db.read(code)['advance_at']+.1]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    assert db.tick(code) and db.read(code)['phase']=='question'
    now[0]=db.read(code)['deadline']+.1
    assert db.tick(code) and db.read(code)['phase']=='question'
    db.change(code,host,'close')
    assert db.read(code)['advance_at'] is None
    db.change(code,host,'next')
    assert db.read(code)['phase']=='finished'
    assert [p['score'] for p in db.read(code)['players']]==[0,-100,-100]


def test_practice_grid_and_binary_robots(tmp_path,monkeypatch):
    db=Store(tmp_path/'practice.sqlite3')
    player=dict(id='p',name='P')
    stages=[stage('g','grid'),stage('b','binary')]
    code=db.create(player,practice=True,stages=stages,questions=[question('qg','g'),question('qb','b',choices=['Да','Нет'],correct_choice=0)])
    assert db.public(code,'p')['can_pick']
    db.change(code,player,'pick',question='qg')
    db.change(code,player,'answer',text='Да')
    now=[max(db.read(code)['bot_due'].values())+.1]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    assert db.tick(code)
    now[0]+=2
    assert db.tick(code) and db.read(code)['phase']=='reveal'
    db.change(code,player,'next')
    db.change(code,player,'answer',choice=0)
    now[0]=max(db.read(code)['bot_due'].values())+.1
    assert db.tick(code) and db.read(code)['phase']=='reveal'
    assert all(a['choice'] in (0,1) for a in db.read(code)['answers'].values())


def test_http_choice_and_full_length_grid_id(tmp_path,monkeypatch):
    from app import main
    db=Store(tmp_path/'api.sqlite3')
    monkeypatch.setattr(main,'store',db)
    monkeypatch.setattr(main,'DEV_MODE',True)
    with TestClient(main.app) as client:
        users=[client.post('/api/login',json={'name':name}).json() for name in ['H','P']]
        hh,ph=[{'Authorization':'Bearer '+u['token']} for u in users]
        code=db.create(users[0]['user'],stages=[stage('g','grid'),stage('b','binary')],questions=[question('q'*64,'g'),question('qb','b',choices=['Да','Нет'],correct_choice=0)])
        path='/api/rooms/'+code
        assert client.post(path+'/join',headers=ph,json={}).status_code==200
        client.post(path+'/action',headers=hh,json={'action':'start'})
        assert client.post(path+'/action',headers=hh,json={'action':'next'}).status_code==200
        assert client.post(path+'/action',headers=ph,json={'action':'pick','question':'q'*64}).status_code==400
        assert client.post(path+'/action',headers=hh,json={'action':'pick','question':'q'*64}).status_code==200
        client.post(path+'/action',headers=ph,json={'action':'answer','text':'Да'})
        client.post(path+'/action',headers=hh,json={'action':'correct','player':users[1]['user']['id']})
        client.post(path+'/action',headers=hh,json={'action':'next'})
        response=client.post(path+'/action',headers=ph,json={'action':'answer','choice':0})
        assert response.status_code==200 and response.json()['phase']=='reveal'
        assert response.json()['answers'][users[1]['user']['id']]['points']==100


def test_mixed_document_and_builtin_library_can_be_edited(tmp_path,monkeypatch):
    from app import main
    root=Path(__file__).resolve().parents[1]
    catalog=Catalog(tmp_path/'builder',tmp_path/'games',root/'games')
    monkeypatch.setattr(main,'store',Store(tmp_path/'api.sqlite3'))
    monkeypatch.setattr(main,'DEV_MODE',True)
    monkeypatch.setenv('GAME_PACKS_DIR',str(catalog.games))
    with TestClient(main.app) as client:
        auth=client.post('/api/login',json={'name':'Host'}).json()
        headers={'Authorization':'Bearer '+auth['token']}
        listed=client.get('/api/packs',headers=headers).json()['packs']
        assert {p['id'].removeprefix('library-') for p in listed} <= {p['id'] for p in catalog.list()}
        snapshot=catalog.open('demo-quiz')
        document=copy.deepcopy(snapshot['document'])
        document['title']='Edited demo'
        saved=catalog.save('demo-quiz',document,snapshot['revision'])
        catalog.publish('demo-quiz',saved['revision'])
        code=client.post('/api/rooms',headers=headers,json={'pack':'demo'}).json()['code']
        state=client.get('/api/rooms/'+code,headers=headers).json()
        assert state['pack_title']=='Edited demo' and state['question_count']==23
        assert client.get(state['question_list'][0]['media']['url']).status_code==200


@pytest.mark.parametrize('error', ['unknown_mode','duplicate_stage','unknown_stage','empty_stage','missing_choices','same_choices','event_grid'])
def test_invalid_round_config_is_not_published(tmp_path,error):
    doc=dict(schema_version=1,title='Mixed game',stages=[stage('b','binary')],rounds=[dict(id='q',stage='b',type='question',text='?',choices=['Да','Нет'],correct_choice=0)])
    if error=='unknown_mode':doc['stages'][0]['type']='other'
    if error=='duplicate_stage':doc['stages']*=2
    if error=='unknown_stage':doc['rounds'][0]['stage']='missing'
    if error=='empty_stage':doc['stages'].append(stage('empty','blitz'))
    if error=='missing_choices':doc['rounds'][0].pop('choices')
    if error=='same_choices':doc['rounds'][0]['choices']=['ДА','да']
    if error=='event_grid':
        doc['stages'][0]['type']='grid'
        doc['rounds'][0]=dict(id='e',stage='b',type='event',effect=dict(type='random_buff',target='all_players',questions=1))
    (tmp_path/'game.json').write_text(json.dumps(doc),encoding='utf-8')
    with pytest.raises(ValueError):load_pack(tmp_path)
