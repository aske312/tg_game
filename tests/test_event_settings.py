import copy
import json
import io
import wave
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.events import apply_event, normalize_effect
from app.packs import load_pack
from app.store import Store
from builder.store import Catalog

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('kind,parameter,correct,wrong',[
    ('double_reward',{},200,-100),('shield',{},100,0),('half_reward',{},50,-100),('double_penalty',{},100,-200),
    ('reward_multiplier',{'factor':2.55},255,-100),('reward_reduction',{'factor':.25},25,-100),
    ('penalty_multiplier',{'factor':3},100,-300),('bonus_points',{'amount':250},350,-100),('penalty_points',{'amount':250},100,-350)
])
def test_configured_effect_scoring_expiration_and_binary_answers(tmp_path,kind,parameter,correct,wrong):
    db=Store(tmp_path/'game.sqlite3')
    host,a,b=[dict(id=name,name=name) for name in ('host','a','b')]
    effect=dict(type=kind,target='all_players',questions=2,**parameter)
    event=dict(id='event',type='event',title='Custom event',text='',effect=effect)
    question=dict(id='q1',type='question',text='?',answer='Yes',value=100,seconds=3600)
    binary=dict(question,id='q2',choices=['Yes','No'],correct_choice=0)
    code=db.create(host,questions=[event,question,binary,dict(question,id='q3')])
    for player in (a,b):db.change(code,player,'join')
    db.change(code,host,'start')
    assert db.read(code)['event']['kind']==kind
    db.change(code,host,'next')
    db.change(code,a,'answer',text='Yes');db.change(code,b,'answer',text='No')
    db.change(code,host,'correct',player='a');db.change(code,host,'wrong',player='b')
    assert db.read(code)['answers']['a']['points']==correct
    assert db.read(code)['answers']['b']['points']==wrong
    assert db.read(code)['modifiers']['a']['remaining']==1
    # The persisted second question uses exactly the same effect with automatic grading.
    db=Store(db.path);db.change(code,host,'next')
    db.change(code,a,'answer',choice=0);db.change(code,b,'answer',choice=1)
    assert db.read(code)['answers']['a']['points']==correct
    assert db.read(code)['answers']['b']['points']==wrong
    assert db.read(code)['modifiers']=={}
    db.change(code,host,'next');db.change(code,a,'answer',text='Yes');db.change(code,b,'answer',text='No')
    db.change(code,host,'correct',player='a');db.change(code,host,'wrong',player='b')
    assert [p['score'] for p in db.read(code)['players']]==[0,2*correct+100,2*wrong-100]


@pytest.mark.parametrize('target,eligible,count',[('leader',{'a','b'},1),('last_player',{'c'},1),('all_players',{'a','b','c'},3),('random_player',{'a','b','c'},1)])
def test_effect_targets_exclude_host_and_resolve_ties(target,eligible,count):
    state=dict(host='h',players=[dict(id=name,name=name,score=score) for name,score in [('h',999),('a',100),('b',100),('c',-100)]])
    event=dict(title='Bonus',text='',effect=dict(type='bonus_points',amount=300,target=target,questions=8))
    applied=apply_event(state,event)
    assert len(applied['targets'])==count
    assert set(state['modifiers'])<=eligible and 'h' not in state['modifiers']
    assert all(value['amount']==300 and value['remaining']==8 for value in state['modifiers'].values())


@pytest.mark.parametrize('effect',[
    dict(type=[],target='all_players'),dict(type='unknown',target='all_players'),dict(type='shield',target=[]),
    dict(type='shield',target='all_players',questions=0),dict(type='shield',target='all_players',questions=1.5),
    dict(type='reward_multiplier',target='all_players',factor=.5),dict(type='reward_multiplier',target='all_players',factor=float('nan')),
    dict(type='reward_reduction',target='all_players',factor=1.1),dict(type='bonus_points',target='all_players',amount=-1),
    dict(type='penalty_points',target='all_players',amount=2.5),dict(type='penalty_multiplier',target='all_players')
])
def test_invalid_effect_parameters_are_rejected(effect):
    with pytest.raises(ValueError):normalize_effect(effect)


def test_effect_parameters_survive_publication_and_export(tmp_path):
    catalog=Catalog(tmp_path/'builder',tmp_path/'games',ROOT/'games')
    snapshot=catalog.create('Custom events');doc=copy.deepcopy(snapshot['document'])
    doc['rounds']=[dict(id='event',type='event',title='Bonus',effect=dict(type='bonus_points',amount=1500,target='leader',questions=12)),
                   dict(id='question',type='question',text='?',answer='Yes',points=3000,time_limit=7200)]
    snapshot=catalog.save(snapshot['id'],doc,snapshot['revision']);catalog.publish(snapshot['id'],snapshot['revision'])
    pack=load_pack(catalog.games/snapshot['id'])
    assert pack['questions'][0]['effect']==doc['rounds'][0]['effect']
    assert pack['questions'][1]['value']==3000 and pack['questions'][1]['seconds']==7200
    with zipfile.ZipFile(io.BytesIO(catalog.export(snapshot['id']))) as archive:
        assert json.loads(archive.read('game.json'))['rounds'][0]['effect']==doc['rounds'][0]['effect']


def test_question_and_audio_limits_use_values_outside_old_ranges(tmp_path):
    with wave.open(str(tmp_path/'long.wav'),'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(1);audio.setframerate(1);audio.writeframes(b'\x80'*100010)
    doc=dict(title='Long audio',rounds=[dict(id='long',type='question',text='?',answer='Yes',points=2500,time_limit=7200,media=dict(type='audio',file='long.wav',start=100000,end=100005)),
                                     dict(id='short',type='question',text='?',answer='Yes',points=0,time_limit=1)])
    (tmp_path/'game.json').write_text(json.dumps(doc),encoding='utf-8')
    pack=load_pack(tmp_path)
    assert pack['questions'][0]['media']['start']==100000 and pack['questions'][0]['seconds']==7200
    assert pack['questions'][1]['value']==0 and pack['questions'][1]['seconds']==1
    for field,value in [('points',-1),('time_limit',0),('time_limit',1.5)]:
        bad=copy.deepcopy(doc);bad['rounds'][1][field]=value
        (tmp_path/'game.json').write_text(json.dumps(bad),encoding='utf-8')
        with pytest.raises(ValueError):load_pack(tmp_path)


def test_custom_question_api_has_no_old_upper_limits(tmp_path,monkeypatch):
    from app import main
    monkeypatch.setattr(main,'store',Store(tmp_path/'game.sqlite3'));monkeypatch.setattr(main,'DEV_MODE',True)
    with TestClient(main.app) as client:
        auth=client.post('/api/login',json={'name':'Host'}).json();headers={'Authorization':'Bearer '+auth['token']}
        code=client.post('/api/rooms',headers=headers,json={'pack':'custom'}).json()['code']
        path='/api/rooms/'+code+'/questions'
        response=client.post(path,headers=headers,json=dict(text='?',answer='Yes',value=4000,seconds=3600,clip_start=100000,clip_end=100010))
        assert response.status_code==200
        question=response.json()['question_list'][0]
        assert question['value']==4000 and question['seconds']==3600
        assert client.post(path,headers=headers,json=dict(text='?',answer='Yes',seconds=0)).status_code==422
