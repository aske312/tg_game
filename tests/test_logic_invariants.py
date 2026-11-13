"""Regression scenarios found during the pre-production logic audit."""
import pytest

from app.store import Store


def game(tmp_path, mode='blitz', single=False, practice=False):
    db = Store(tmp_path/'logic.sqlite3')
    host, a, b = [dict(id=n, name=n) for n in ('h', 'a', 'b')]
    stage = dict(id='s', type=mode, title='Round', categories=['Topic'], chooser='winner',
                 auto_advance=False, answer_mode='single' if single else 'all')
    q = dict(id='q1', stage='s', category='Topic', text='Question', answer='Yes', value=100,
             media=dict(kind='audio', url='/question', start=1, end=3),
             attachments=[dict(kind='audio', url='/answer', start=2, end=9, answer=True)])
    if mode == 'binary': q.update(choices=['Yes', 'No'], correct_choice=0)
    code = db.create(host, stages=[stage], questions=[q, dict(q, id='q2')], practice=practice)
    if not practice:
        for user in (a, b): db.change(code, user, 'join')
        db.change(code, host, 'start'); db.change(code, host, 'next')
    if mode == 'grid': db.change(code, host, 'pick', question='q1')
    return db, code, host, a, b


def test_grid_winner_selects_only_after_host_opens_the_board(tmp_path):
    db, code, host, a, b = game(tmp_path, mode='grid')
    for user in (a, b): db.change(code, user, 'answer', text='Yes')
    db.change(code, host, 'correct', player='a'); db.change(code, host, 'wrong', player='b')
    assert not db.public(code, 'a')['can_pick']
    with pytest.raises(ValueError): db.change(code, a, 'pick', question='q2')
    db.change(code, host, 'display_answer')
    assert not db.public(code, 'a')['can_pick']
    db.change(code, host, 'display_board')
    assert db.public(code, 'a')['can_pick'] and not db.public(code, 'b')['can_pick']
    db.change(code, a, 'pick', question='q2')
    assert db.read(code)['active'] == 'q2'


@pytest.mark.parametrize('correct', [False, True])
def test_showing_answer_during_buzzer_review_cannot_reopen_the_question(tmp_path, correct):
    db, code, host, a, b = game(tmp_path, mode='grid', single=True)
    db.change(code, a, 'buzz'); db.change(code, a, 'answer', text='Yes')
    assert db.read(code)['phase'] == 'review'
    db.change(code, host, 'display_answer')
    assert db.read(code)['single_closed'] and db.read(code)['used'] == ['q1']
    db.change(code, host, 'correct' if correct else 'wrong', player='a')
    assert db.read(code)['phase'] == 'reveal'
    assert not db.public(code, 'b')['can_buzz']
    with pytest.raises(ValueError): db.change(code, b, 'buzz')
    assert db.read(code)['used'] == ['q1']


@pytest.mark.parametrize('mode', ['blitz', 'binary', 'grid'])
def test_solutions_and_answer_attachments_wait_for_host_on_players_too(tmp_path, mode):
    db, code, host, a, b = game(tmp_path, mode=mode)
    for user in (a, b): db.change(code, user, 'answer', **(dict(choice=0) if mode == 'binary' else dict(text='Yes')))
    if mode == 'binary': db.change(code, host, 'close')
    else:
        for user in (a, b): db.change(code, host, 'correct', player=user['id'])
    assert db.read(code)['phase'] == 'reveal'
    for user in (a, b):
        q = db.public(code, user['id'])['question']
        assert not {'answer', 'correct_choice'} & q.keys()
        assert not q['attachments']
    db.change(code, host, 'display_answer')
    for user in (a, b):
        q = db.public(code, user['id'])['question']
        assert q['answer'] == 'Yes' and q['attachments'][0]['answer']
    db.change(code, host, 'display_question')
    assert 'answer' not in db.public(code, 'a')['question']


@pytest.mark.parametrize('action', ['close', 'display_answer', 'display_question', 'display_board', 'end_round', 'next', 'finish'])
def test_delayed_host_commands_cannot_affect_the_next_question(tmp_path, action):
    db, code, host, a, b = game(tmp_path)
    db.change(code, host, 'close'); db.change(code, host, 'next')
    before = db.read(code)
    with pytest.raises(ValueError): db.change(code, host, action, question='q1')
    assert db.read(code) == before


def test_old_pause_notification_cannot_stop_a_replayed_answer(tmp_path):
    db, code, host, a, b = game(tmp_path)
    db.change(code, host, 'display_answer')
    old = db.read(code)['media_playback']['revision']
    db.change(code, host, 'display_question'); db.change(code, host, 'display_answer')
    before = db.read(code)
    assert before['media_playback']['revision'] > old
    assert not db.change(code, host, 'media_pause', question='q1', media_mode='full', media_revision=old)
    assert db.read(code) == before and before['media_playback']['playing']
    assert db.change(code, host, 'media_pause', question='q1', media_mode='full', media_revision=before['media_playback']['revision'])


def test_training_uses_a_fresh_answer_transport_instead_of_question_recording(tmp_path, monkeypatch):
    db, code, owner, a, b = game(tmp_path, practice=True)
    db.change(code, owner, 'answer', text='Yes')
    now = max(db.read(code)['bot_due'].values())+1
    monkeypatch.setattr('app.store.time.time', lambda: now)
    db.tick(code)
    monkeypatch.setattr('app.store.time.time', lambda: now+2)
    db.tick(code)
    state = db.read(code)
    assert state['phase'] == 'reveal' and state['display_scene'] == 'answer'
    assert state['media_playback']['mode'] == 'full' and state['media_playback']['playing']
    assert state['media_playback']['position'] == 0


def test_http_display_discards_old_playback_notifications(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    db, code, host, a, b = game(tmp_path)
    monkeypatch.setattr(main, 'store', db); monkeypatch.setattr(main, 'DEV_MODE', True)
    monkeypatch.setattr(main, 'connections', {})
    headers = {'Authorization':'Bearer '+db.session(host)}
    with TestClient(main.app) as client:
        screen = client.post('/api/display', json=dict(code=code)).json()
        path = '/api/rooms/'+code+'/action'
        first = client.post(path, headers=headers, json=dict(action='display_answer')).json()['media_playback']
        client.post(path, headers=headers, json=dict(action='display_question')).raise_for_status()
        latest = client.post(path, headers=headers, json=dict(action='display_answer')).json()['media_playback']
        result = client.post('/api/display/media', headers={'Authorization':'Bearer '+screen['token']},
            json=dict(action='media_pause', question='q1', media_mode='full', media_revision=first['revision']))
        assert result.status_code == 200 and result.json()['media_playback'] == latest
        invalid = client.post(path, headers=headers, json=dict(action='media_pause', question='q1', media_revision=True))
        assert invalid.status_code == 422


@pytest.mark.parametrize('mode', ['blitz', 'grid', 'binary'])
def test_repeated_scoped_close_is_harmless_and_never_penalizes_twice(tmp_path, mode):
    db, code, host, a, b = game(tmp_path, mode=mode)
    db.change(code, host, 'close', question='q1')
    before = db.read(code)
    assert not db.change(code, host, 'close', question='q1')
    assert db.read(code) == before
