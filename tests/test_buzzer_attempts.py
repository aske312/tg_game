import pytest

from app.store import Store


@pytest.fixture
def game(tmp_path, monkeypatch):
    now=[1000.]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    db=Store(tmp_path/'buzz.sqlite3')
    host,a,b=[dict(id=n,name=n) for n in ('host','a','b')]
    stage=dict(id='g',type='grid',title='Grid',categories=['Music'],answer_mode='single',chooser='winner',auto_advance=False)
    questions=[dict(id=n,stage='g',category='Music',text='Song?',answer='Yes',value=100,seconds=45,
                    media=dict(kind='audio',url='/song',start=10,end=20)) for n in ('q1','q2')]
    code=db.create(host,stages=[stage],questions=questions)
    for p in (a,b):db.change(code,p,'join')
    db.change(code,dict(id='screen',name='Screen'),'watch')
    db.change(code,host,'start');db.change(code,host,'next');db.change(code,host,'pick',question='q1')
    return db,code,host,a,b,now


@pytest.mark.parametrize('written',[False,True])
def test_wrong_answer_reopens_buzzer_until_first_correct_answer(game,written):
    db,code,host,a,b,now=game
    now[0]+=5
    db.change(code,a,'buzz')
    with pytest.raises(ValueError):db.change(code,host,'correct',player='a',question='stale-question')
    assert db.read(code)['buzz_remaining']==40 and db.read(code)['deadline'] is None
    now[0]+=100
    assert not db.tick(code)
    assert db.public(code,'a')['can_answer'] and not db.public(code,'b')['can_buzz']
    if written:db.change(code,a,'answer',text='Wrong')
    assert db.public(code,host['id'])['question_number']==1
    db=Store(db.path)
    db.change(code,host,'wrong',player='a')
    s=db.read(code)
    assert s['phase']=='question' and s['active']=='q1' and s['responder'] is None
    assert s['deadline']==now[0]+40 and s['used']==[]
    assert s['media_playback']['mode']=='excerpt' and not s['scores_visible']
    assert s['answers']['a']['points']==-100 and s['answers']['a']['verdict']=='wrong'
    assert not db.public(code,'a')['can_buzz'] and db.public(code,'b')['can_buzz']
    with pytest.raises(ValueError):db.change(code,a,'buzz')
    with pytest.raises(ValueError):db.change(code,host,'wrong',player='a')
    db.change(code,b,'buzz')
    if written:db.change(code,b,'answer',text='Yes')
    db.change(code,host,'correct',player='b')
    s=db.read(code)
    assert s['phase']=='reveal' and s['used']==['q1'] and s['chooser']=='b'
    assert s['media_playback']['mode']=='full'
    assert [p['score'] for p in s['players']]==[0,-100,100]
    assert s['answers']['b'].get('oral',False)==(not written)
    display=db.public(code,'screen',display=True)
    assert display['answers']=={} and display['messages']==[]
    db.change(code,host,'next');db.change(code,host,'pick',question='q2')
    assert db.public(code,'a')['can_buzz'] and db.public(code,'b')['can_buzz']


def test_host_can_only_grade_current_buzzer_winner_and_only_once(game):
    db,code,host,a,b,now=game
    with pytest.raises(ValueError):db.change(code,host,'correct',player='a')
    db.change(code,a,'buzz')
    with pytest.raises(ValueError):db.change(code,host,'correct',player='b')
    with pytest.raises(ValueError):db.change(code,b,'correct',player='a')
    db.change(code,host,'pause');now[0]+=200
    with pytest.raises(ValueError):db.change(code,host,'correct',player='a')
    db.change(code,host,'unpause')
    assert db.read(code)['buzz_remaining']==45
    db.change(code,host,'correct',player='a')
    with pytest.raises(ValueError):db.change(code,host,'correct',player='a')
    assert db.read(code)['players'][1]['score']==100


def test_all_wrong_attempts_wait_for_host_and_effects_expire_once_per_question(game):
    db,code,host,a,b,now=game
    db.change(code,host,'set_effect',player='a',effect=dict(type='double_penalty',questions=2))
    db.change(code,a,'buzz');db.change(code,host,'wrong',player='a')
    assert db.read(code)['modifiers']['a']['remaining']==2
    db.change(code,b,'buzz');db.change(code,b,'answer',text='Wrong');db.change(code,host,'wrong',player='b')
    assert not db.public(code,'a')['can_buzz'] and not db.public(code,'b')['can_buzz']
    now[0]=db.read(code)['deadline']+1
    assert db.tick(code) and db.read(code)['phase']=='question'
    db.change(code,host,'close')
    s=db.read(code)
    assert s['used']==['q1'] and s['phase']=='reveal' and s['omission_penalties']=={}
    assert [p['score'] for p in s['players']]==[0,-200,-100]
    assert s['modifiers']['a']['remaining']==1


def test_manual_close_can_cancel_unwritten_oral_attempt_without_penalizing_others(game):
    db,code,host,a,b,now=game
    db.change(code,a,'buzz');db.change(code,host,'close')
    assert db.read(code)['phase']=='reveal' and all(p['score']==0 for p in db.read(code)['players'])
    with pytest.raises(ValueError):db.change(code,host,'correct',player='a')


def test_effect_can_change_while_host_checks_a_written_single_answer(game):
    db,code,host,a,b,now=game
    db.change(code,a,'buzz');db.change(code,a,'answer',text='Yes')
    db.change(code,host,'set_effect',player='a',effect=dict(type='double_reward',questions=2))
    db.change(code,host,'correct',player='a')
    assert db.read(code)['players'][1]['score']==200
    assert db.read(code)['modifiers']['a']['remaining']==1


def test_host_practice_bots_take_turns_after_wrong_answer(game):
    db,old_code,host,a,b,now=game
    template=db.read(old_code)
    code=db.create(host,practice=True,host_practice=True,stages=template['stages'],questions=template['pack'])
    db.change(code,host,'start');db.change(code,host,'next');db.change(code,host,'pick',question='q1')
    now[0]=max(db.read(code)['bot_due'].values())+.1
    assert db.tick(code) and db.read(code)['phase']=='review'
    first=db.read(code)['responder'];db.change(code,host,'wrong',player=first)
    assert db.tick(code) and db.read(code)['phase']=='review'
    second=db.read(code)['responder'];assert second!=first
    db.change(code,host,'correct',player=second)
    assert db.read(code)['phase']=='reveal' and db.read(code)['used']==['q1']
