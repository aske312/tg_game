from concurrent.futures import ThreadPoolExecutor

import pytest

from app.modes import stages_from_doc
from app.pack_validation import publication_issues
from app.store import Store, media_position


def game(tmp_path, mode='all'):
    db = Store(tmp_path/'presentation.sqlite3')
    host, a, b = [dict(id=n, name=n) for n in ('host', 'a', 'b')]
    stage = dict(id='g', type='grid', title='Grid', categories=['Music'], answer_mode=mode,
                 chooser='host', auto_advance=False)
    questions = [dict(id=n, stage='g', type='question', category='Music', text='Song?', answer='Yes',
                      value=100, seconds=3600, media=dict(kind='audio', url='/song.wav', start=20, end=30)) for n in ('q1', 'q2')]
    code = db.create(host, questions=questions, stages=[stage])
    for user in (a, b): db.change(code, user, 'join')
    db.change(code, host, 'start')
    db.change(code, host, 'next')
    db.change(code, host, 'pick', question='q1')
    db.change(code, dict(id='screen', name='Screen'), 'watch')
    return db, code, host, a, b


def test_answer_recording_starts_only_on_host_command_and_resets_between_scenes(tmp_path):
    db, code, host, a, b = game(tmp_path)
    import json
    state=db.read(code)
    state['pack'][0]['attachments']=[dict(kind='audio',url='/answer.wav',start=5,end=125,answer=True)]
    with db.connect() as connection:
        connection.execute('UPDATE rooms SET state=? WHERE code=?',(json.dumps(state),code))
    for p in (a,b):db.change(code,p,'answer',text='Yes')
    assert db.read(code)['phase']=='review'
    assert 'answer' not in db.public(code,'a')['question']
    db.change(code,host,'correct',player='a');db.change(code,host,'wrong',player='b')
    assert db.read(code)['display_scene']=='question'
    assert 'answer' not in db.public(code,'screen',display=True)['question']
    db.change(code,host,'display_answer')
    s=db.read(code)
    assert s['media_playback']['playing'] and s['media_playback']['mode']=='full'
    assert media_position(s,s['media_playback']['updated_at']+60)==60
    display=db.public(code,'screen',display=True)
    assert 'media' not in display['question']
    assert display['question']['attachments'][0]['url']=='/answer.wav'
    assert display['question']['answer']=='Yes'
    assert not db.change(code,host,'media_pause',question='q1',position=10,media_mode='excerpt')
    db.change(code,host,'display_board')
    assert db.read(code)['media_playback'] is None
    db.change(code,host,'display_answer')
    assert db.read(code)['media_playback']['playing'] and db.read(code)['media_playback']['position']==0
    db.change(code,host,'display_question')
    assert not db.read(code)['media_playback']['playing']
    assert db.read(code)['media_playback']['mode']=='excerpt'
    assert db.read(code)['answers']==s['answers']


def test_buzzer_is_atomic_and_only_winner_can_answer(tmp_path):
    db, code, host, a, b = game(tmp_path, 'single')
    assert db.public(code, a['id'])['can_buzz'] and not db.public(code, a['id'])['can_answer']
    with pytest.raises(ValueError): db.change(code, a, 'answer', text='Yes')
    def buzz(user):
        try:
            db.change(code, user, 'buzz')
            return user
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = [u for u in pool.map(buzz, (a, b)) if u]
    assert len(winners) == 1
    winner = winners[0]
    loser = b if winner == a else a
    assert db.public(code, winner['id'])['can_answer']
    assert not db.public(code, loser['id'])['can_buzz']
    with pytest.raises(ValueError): db.change(code, loser, 'answer', text='Yes')
    assert not db.change(code, winner, 'buzz')
    db.change(code, winner, 'answer', text='Yes')
    assert db.read(code)['phase'] == 'review'
    db.change(code, host, 'correct', player=winner['id'])
    assert db.read(code)['phase'] == 'reveal'
    assert next(p for p in db.read(code)['players'] if p['id'] == loser['id'])['score'] == 0
    with pytest.raises(ValueError): db.change(code, loser, 'display_scores')


def test_grid_answer_mode_is_compatible_and_validated():
    stage = dict(id='g', type='grid', title='Grid', categories=['Music'])
    doc = dict(title='Game', stages=[stage], rounds=[])
    assert stages_from_doc(doc)[0]['answer_mode'] == 'all'
    stage['answer_mode'] = 'single'
    assert stages_from_doc(doc)[0]['answer_mode'] == 'single'
    stage['answer_mode'] = 'bad'
    with pytest.raises(ValueError): stages_from_doc(doc)
    assert any(i['field'] == 'answer_mode' for i in publication_issues(doc))


def test_score_screen_pauses_and_resumes_question_without_losing_time(tmp_path, monkeypatch):
    now = [1000.]
    monkeypatch.setattr('app.store.time.time', lambda: now[0])
    db, code, host, a, b = game(tmp_path)
    db.change(code,host,'media_play',question='q1')
    now[0] += 5
    with pytest.raises(ValueError): db.change(code, a, 'display_scores')
    db.change(code, host, 'display_scores')
    paused = db.read(code)
    assert paused['paused'] and paused['display_scene'] == 'question' and paused['pause_view'] == 'scores'
    assert media_position(paused, now[0]) == 5
    assert paused['deadline'] is None
    now[0] += 100
    assert not db.tick(code)
    assert not db.change(code, host, 'display_scores')
    assert db.read(code)['paused_at'] == paused['paused_at']
    with pytest.raises(ValueError): db.change(code, a, 'answer', text='Yes')
    db.change(code, host, 'unpause')
    resumed = db.read(code)
    assert resumed['deadline'] is None
    assert resumed['display_scene'] == 'question' and not resumed['paused']
    assert resumed['media_playback']['playing'] and media_position(resumed, now[0]) == 5


def test_pause_and_score_views_switch_without_changing_saved_time(tmp_path, monkeypatch):
    now = [1000.]
    monkeypatch.setattr('app.store.time.time', lambda: now[0])
    db, code, host, a, b = game(tmp_path)
    db.change(code,host,'media_play',question='q1')
    now[0] += 7
    db.change(code, host, 'pause')
    paused = db.read(code)
    assert paused['pause_view'] == 'break'
    assert paused['deadline'] is None
    now[0] += 100
    db.change(code, host, 'display_scores')
    assert db.read(code)['pause_view'] == 'scores'
    assert db.read(code)['paused_at'] == paused['paused_at']
    assert media_position(db.read(code), now[0]) == 7
    with pytest.raises(ValueError): db.change(code, a, 'display_scores')
    db.change(code, host, 'pause')
    assert db.read(code)['pause_view'] == 'break'
    assert not db.change(code, host, 'pause')
    now[0] += 100
    db = Store(db.path)
    assert not db.tick(code)
    db.change(code, host, 'unpause')
    resumed = db.read(code)
    assert resumed['deadline'] is None
    assert media_position(resumed, now[0]) == 7 and resumed['pause_view'] == 'break'


@pytest.mark.parametrize('kind', ['audio', 'video'])
def test_full_media_prevents_three_second_auto_advance(tmp_path, kind):
    db = Store(tmp_path/'auto.sqlite3')
    host, player = dict(id='h', name='Host'), dict(id='p', name='Player')
    stage = dict(id='s', type='blitz', title='Media', chooser='host', auto_advance=True)
    questions = [dict(id=str(i), stage='s', text='Question', answer='Yes', category='Media', value=100,
                      media=dict(kind=kind, url='/media', start=10, end=12)) for i in range(2)]
    code = db.create(host, questions=questions, stages=[stage])
    db.change(code, player, 'join'); db.change(code, host, 'start')
    db.change(code, host, 'next')
    db.change(code, player, 'answer', text='Yes')
    db.change(code, host, 'correct', player='p')
    s = db.read(code)
    assert s['media_playback']['mode'] == 'excerpt' and not s['media_playback']['playing']
    assert s['advance_at'] is None and not db.tick(code)
    assert media_position(s, s['media_playback']['updated_at']+20) == 0
    db.change(code,host,'media_play',question='0')
    s=db.read(code)
    assert media_position(s,s['media_playback']['updated_at']+20)==2
