import pytest

from app.store import Store
from app.modes import stages_from_doc


@pytest.fixture
def game(tmp_path, monkeypatch):
    now=[1000.]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    db=Store(tmp_path/'presentation.sqlite3')
    host,player=[dict(id=name,name=name) for name in ('host','player')]
    stages=stages_from_doc({'stages':[
        dict(id='grid',type='grid',title='Themes',categories=['Space','Music']),
        dict(id='blitz',type='blitz',title='Blitz',auto_advance=True),
    ]})
    questions=[dict(id=qid,stage=sid,type='question',category=category,text=qid,answer='4',value=100,seconds=45)
               for qid,sid,category in [('g1','grid','Space'),('g2','grid','Music'),('b1','blitz','Test'),('b2','blitz','Test')]]
    code=db.create(host,stages=stages,questions=questions)
    db.change(code,player,'join')
    db.change(code,host,'start')
    return db,code,host,player,now


def test_intro_is_shared_timed_and_shown_only_once(game):
    db,code,host,player,now=game
    state=db.public(code,player['id'])
    assert state['phase']=='intro' and state['stage']['categories']==['Space','Music']
    assert not db.public(code,host['id'])['can_pick']
    with pytest.raises(ValueError):db.change(code,host,'pick',question='g1')
    with pytest.raises(ValueError):db.change(code,player,'next')
    now[0]=state['intro_until']-.1
    assert not db.tick(code)
    now[0]+=.2
    assert db.tick(code) and db.read(code)['phase']=='board'
    db.change(code,host,'pick',question='g1')
    db.change(code,host,'close')
    db.change(code,host,'next')
    assert db.read(code)['phase']=='board'


def test_pause_freezes_question_and_restores_remaining_time_after_restart(game):
    db,code,host,player,now=game
    db.change(code,host,'next')
    db.change(code,host,'pick',question='g1')
    now[0]+=10
    db.change(code,host,'pause')
    state=db.public(code,player['id'])
    assert state['deadline']-state['paused_at']==35
    now[0]+=100
    db=Store(db.path)
    assert not db.tick(code) and db.read(code)['phase']=='question'
    with pytest.raises(ValueError):db.change(code,player,'answer',text='4')
    with pytest.raises(ValueError):db.change(code,player,'unpause')
    assert db.change(code,player,'reaction',text='🔥')
    db.change(code,host,'unpause')
    assert db.read(code)['deadline']-now[0]==35
    db.change(code,player,'answer',text='4')
    db.change(code,host,'correct',player=player['id'])
    assert db.read(code)['phase']=='reveal'


def test_pause_also_freezes_intro(game):
    db,code,host,player,now=game
    now[0]+=3
    db.change(code,host,'pause')
    remaining=db.read(code)['intro_until']-now[0]
    now[0]+=60
    assert not db.tick(code)
    db.change(code,host,'unpause')
    assert db.read(code)['intro_until']-now[0]==remaining
    now[0]+=remaining+.1
    assert db.tick(code) and db.read(code)['phase']=='board'


def test_round_scores_wait_for_host_even_with_auto_advance(game):
    db,code,host,player,now=game
    db.change(code,host,'next')
    for qid in ('g1','g2'):
        db.change(code,host,'pick',question=qid)
        db.change(code,player,'answer',text='4')
        db.change(code,host,'correct',player=player['id'])
    assert db.public(code,player['id'])['stage_complete']
    with pytest.raises(ValueError):db.change(code,player,'show_scores')
    db.change(code,host,'show_scores')
    assert db.public(code,player['id'])['scores_visible']
    db.change(code,host,'pause')
    now[0]+=100
    assert not db.tick(code)
    db.change(code,host,'unpause')
    db.change(code,host,'next')
    assert not db.read(code)['scores_visible'] and db.read(code)['active']=='b1'
    db.change(code,host,'close')
    now[0]=db.read(code)['advance_at']+.1
    db.tick(code)
    assert db.read(code)['active']=='b2'
    with pytest.raises(ValueError):db.change(code,host,'show_scores')
    db.change(code,host,'close')
    assert db.read(code)['advance_at'] is None
    now[0]+=30
    assert not db.tick(code)
    db.change(code,host,'show_scores')
    db.change(code,host,'next')
    assert db.read(code)['phase']=='finished' and db.read(code)['finished_at']==now[0]


def test_reactions_do_not_change_render_revision_or_interrupt_pause(game):
    db,code,host,player,now=game
    before=db.public(code,player['id'])
    db.change(code,player,'reaction',text='🔥')
    after=db.public(code,player['id'])
    assert after['version']>before['version'] and after['ui_version']==before['ui_version']
    for _ in range(10):assert db.change(code,player,'reaction',text='👏') is False
    assert len(db.read(code)['reactions'])==1
    db.change(code,host,'pause')
    assert db.public(code,player['id'])['ui_version']>after['ui_version']
