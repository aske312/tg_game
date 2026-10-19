from app.store import Store
import pytest
from app.modes import stages_from_doc
import asyncio
from concurrent.futures import ThreadPoolExecutor


def test_eight_simultaneous_answers_and_competing_grades_are_atomic(tmp_path):
    db=Store(tmp_path/'concurrent.sqlite3');host=dict(id='h',name='Host')
    players=[dict(id=str(i),name=str(i)) for i in range(8)]
    code=db.create(host,questions=[dict(id='q',text='?',answer='Yes',value=100,seconds=45)])
    for player in players:db.change(code,player,'join')
    db.change(code,host,'start');db.change(code,host,'next')
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda p:db.change(code,p,'answer',text='Yes'),players))
    assert db.read(code)['phase']=='review' and len(db.read(code)['answers'])==8
    def grade(action):
        try:return db.change(code,host,action,player='0')
        except ValueError:return False
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(grade,['correct','wrong']))
    assert sum(results)==1
    state=db.read(code)
    assert abs(state['players'][1]['score'])==100
    assert state['answers']['0']['points']==state['players'][1]['score']


def test_early_finish_records_partial_round_for_final_results(tmp_path):
    db=Store(tmp_path/'audit.sqlite3')
    host=dict(id='host',name='Host');player=dict(id='p',name='Player')
    code=db.create(host,questions=[dict(id='q'+str(i),text='?',answer='Yes',value=100,seconds=45) for i in range(3)])
    db.change(code,player,'join');db.change(code,host,'start');db.change(code,host,'next')
    db.change(code,player,'answer',text='Yes');db.change(code,host,'correct',player='p')
    db.change(code,host,'finish')
    result=db.read(code)['round_results']
    assert len(result)==1
    assert result[0]['players'][0]['round_points']==100
    assert result[0]['players'][0]['score']==100


def test_failed_room_does_not_stop_other_room_timers(monkeypatch):
    from app import main
    attempted=[];published=[]
    class Rooms:
        def running_rooms(self):return ['broken','healthy']
        def tick(self,code):
            attempted.append(code)
            if code=='broken':raise ValueError('Invalid room state')
            return True
    calls=[0]
    async def sleep(_):
        calls[0]+=1
        if calls[0]>1:raise asyncio.CancelledError
    async def publish(code):published.append(code)
    monkeypatch.setattr(main,'store',Rooms());monkeypatch.setattr(main,'publish',publish)
    monkeypatch.setattr(main.asyncio,'sleep',sleep)
    with pytest.raises(asyncio.CancelledError):asyncio.run(main.simulate())
    assert attempted==['broken','healthy']
    assert published==['healthy']


def test_slow_screen_does_not_block_updates_to_other_clients(monkeypatch):
    from app import main
    class Rooms:
        def public(self,*args):return dict(version=1)
    async def run():
        delivered=asyncio.Event()
        class Slow:
            async def send_json(self,_):await delivered.wait()
        class Fast:
            async def send_json(self,_):delivered.set()
        monkeypatch.setattr(main,'connections',{'room':{Slow():('s',True),Fast():('p',False)}})
        await asyncio.wait_for(main.publish('room'),timeout=.5)
        assert delivered.is_set()
    monkeypatch.setattr(main,'store',Rooms())
    asyncio.run(run())


@pytest.mark.parametrize('answer_penalties,trap_penalties,auto', [(a,t,n) for a in (False,True) for t in (False,True) for n in (False,True)])
def test_mixed_game_scenarios_survive_pause_and_restart(tmp_path,monkeypatch,answer_penalties,trap_penalties,auto):
    now=[1000.]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    stages=stages_from_doc({'stages':[
        dict(id='b',type='blitz',title='Blitz',auto_advance=auto,answer_penalties=answer_penalties,trap_penalties=trap_penalties),
        dict(id='g',type='grid',title='Grid',categories=['Topic'],answer_mode='all',answer_penalties=answer_penalties,trap_penalties=trap_penalties),
        dict(id='s',type='grid',title='Buzzer',categories=['Topic'],answer_mode='single',answer_penalties=answer_penalties,trap_penalties=trap_penalties),
        dict(id='c',type='binary',title='Choices',auto_advance=auto,answer_penalties=answer_penalties,trap_penalties=trap_penalties)]})
    questions=[]
    for stage in stages:
        for i in range(2):
            q=dict(id=stage['id']+str(i),stage=stage['id'],category='Topic',text='Question',answer='Yes',value=100,seconds=45)
            if stage['type']=='binary':q.update(choices=['Yes','No'],correct_choice=0)
            questions.append(q)
    db=Store(tmp_path/'mixed.sqlite3');host=dict(id='host',name='Host')
    players=[dict(id='p'+str(i),name='Player '+str(i)) for i in range(3)]
    screen=dict(id='screen',name='Screen')
    code=db.create(host,stages=stages,questions=questions)
    for player in players:db.change(code,player,'join')
    db.change(code,screen,'watch');db.change(code,host,'start')
    for stage in stages:
        assert db.read(code)['phase']=='intro'
        db.change(code,host,'next')
        for i in range(2):
            if stage['type']=='grid':db.change(code,host,'pick',question=stage['id']+str(i))
            qid=db.read(code)['active']
            db.change(code,host,'set_effect',player=players[0]['id'],effect=dict(type='double_penalty',questions=1))
            for viewer in (screen,players[0]):
                public=db.public(code,viewer['id'],display=viewer==screen)
                assert 'answer' not in public['question']
                assert 'correct_choice' not in public['question']
            before=db.read(code)
            with pytest.raises(ValueError):db.change(code,players[0],'next')
            assert db.read(code)==before
            db.change(code,host,'pause');now[0]+=100
            assert not db.tick(code)
            db=Store(db.path);assert db.read(code)['paused']
            db.change(code,host,'unpause')
            if stage.get('answer_mode')=='single':
                db.change(code,players[0],'buzz',question=qid)
                db.change(code,host,'wrong',player=players[0]['id'],question=qid)
                db.change(code,players[1],'buzz',question=qid)
                db.change(code,host,'correct',player=players[1]['id'],question=qid)
            else:
                for index,player in enumerate(players[:2]):
                    db.change(code,player,'answer',question=qid,**(dict(choice=index) if stage['type']=='binary' else dict(text='Yes')))
                assert db.public(code,screen['id'],display=True)['answers']=={}
                db.change(code,host,'close')
                if stage['type']!='binary':
                    db.change(code,host,'wrong',player=players[0]['id'],question=qid)
                    db.change(code,host,'correct',player=players[1]['id'],question=qid)
            state=db.read(code)
            assert state['phase']=='reveal'
            assert len(state['used'])==len(set(state['used']))
            assert set(db.public(code,players[0]['id'])['answers'])<={players[0]['id']}
            assert db.public(code,screen['id'],display=True)['answers']=={}
            if i==0:
                if auto and stage['type']!='grid':now[0]+=4;assert db.tick(code)
                else:db.change(code,host,'next')
        assert db.read(code)['display_scene']=='answer'
        assert db.read(code)['advance_at'] is None
        db.change(code,host,'end_round');db.change(code,host,'show_scores')
        assert db.public(code,screen['id'],display=True)['scores_visible']
        db=Store(db.path);db.change(code,host,'hide_scores');db.change(code,host,'next')
    final=db.read(code)
    assert final['phase']=='finished' and len(final['round_results'])==4
    for player in final['players'][1:]:
        assert player['score']==sum(next(p['round_points'] for p in r['players'] if p['id']==player['id']) for r in final['round_results'])
