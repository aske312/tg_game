import pytest
from fastapi.testclient import TestClient

from app.store import Store
from app.modes import stages_from_doc


@pytest.fixture
def game(tmp_path):
    db = Store(tmp_path / 'controls.sqlite3')
    host, a, b = [dict(id=name, name=name) for name in ('host', 'a', 'b')]
    stages = stages_from_doc({'stages': [dict(id='s1', type='blitz', title='First'), dict(id='s2', type='grid', title='Second', categories=['Music'])]})
    questions = [dict(id=qid, stage=sid, type='question', category='Music', text='?', answer='Yes', value=100, seconds=45)
                 for qid, sid in [('q1', 's1'), ('q2', 's1'), ('q3', 's2')]]
    code = db.create(host, stages=stages, questions=questions)
    for p in (a, b):
        db.change(code, p, 'join')
    db.change(code, host, 'start')
    db.change(code, host, 'next')
    return db, code, host, a, b


def test_score_adjustments_survive_grading_pause_and_restart(game):
    db, code, host, a, b = game
    db.change(code, a, 'answer', text='Yes')
    db.change(code, host, 'pause')
    db.change(code, host, 'adjust_score', player='a', delta=150)
    db.change(code, host, 'adjust_score', player='b', delta=-50)
    db = Store(db.path)
    assert [p['score'] for p in db.public(code, 'host')['players']] == [0, 150, -50]
    db.change(code, host, 'unpause')
    db.change(code, b, 'answer', text='No')
    db.change(code, host, 'correct', player='a')
    db.change(code, host, 'wrong', player='b')
    assert [p['score'] for p in db.read(code)['players']] == [0, 250, -150]


@pytest.mark.parametrize('action,extra', [
    ('adjust_score', dict(delta=100)), ('set_effect', dict(effect={'type': 'half_reward', 'questions': 2})),
    ('clear_effect', {}), ('skip_stage', {})])
def test_controls_are_host_only(game, action, extra):
    db, code, host, a, b = game
    db.change(code, dict(id='watcher', name='Watcher'), 'watch')
    before = db.read(code)
    for actor in (a, dict(id='watcher')):
        with pytest.raises(ValueError):
            db.change(code, actor, action, player='b', **extra)
    assert db.read(code) == before


@pytest.mark.parametrize('delta', [None, True, 1.5, '100', 2**53])
def test_invalid_score_adjustment_is_atomic(game, delta):
    db, code, host, a, b = game
    before = db.read(code)
    with pytest.raises(ValueError):
        db.change(code, host, 'adjust_score', player='a', delta=delta)
    assert db.read(code) == before


def test_effect_applies_to_open_question_expires_and_can_be_removed(game):
    db, code, host, a, b = game
    db.change(code, a, 'answer', text='Yes')
    db.change(code, host, 'pause')
    db.change(code, host, 'set_effect', player='a', effect={'type': 'half_reward', 'questions': 2})
    db.change(code, host, 'set_effect', player='b', effect={'type': 'double_penalty', 'questions': 1})
    db.change(code, host, 'clear_effect', player='b')
    db.change(code, host, 'unpause')
    db.change(code, b, 'answer', text='No')
    db.change(code, host, 'correct', player='a')
    db.change(code, host, 'wrong', player='b')
    assert db.read(code)['answers']['a']['points'] == 50
    assert db.read(code)['answers']['b']['points'] == -100
    assert db.read(code)['modifiers']['a']['remaining'] == 1
    db = Store(db.path)
    db.change(code, host, 'next')
    db.change(code, host, 'close')
    assert db.read(code)['modifiers'] == {}


def test_effect_changes_after_close_do_not_change_closed_question(game):
    db, code, host, a, b = game
    db.change(code, host, 'set_effect', player='a', effect={'type': 'half_reward', 'questions': 2})
    db.change(code, a, 'answer', text='Yes')
    db.change(code, b, 'answer', text='Yes')
    db.change(code, host, 'clear_effect', player='a')
    db.change(code, host, 'set_effect', player='b', effect={'type': 'double_reward', 'questions': 1})
    db.change(code, host, 'correct', player='a')
    db.change(code, host, 'correct', player='b')
    assert db.read(code)['answers']['a']['points'] == 50
    assert db.read(code)['answers']['b']['points'] == 100
    db.change(code, host, 'next')
    assert 'a' not in db.read(code)['round_modifiers']
    assert db.read(code)['round_modifiers']['b']['kind'] == 'double_reward'


@pytest.mark.parametrize('phase', ['question', 'review', 'reveal', 'paused'])
def test_skip_discards_ungraded_answers_and_preserves_awarded_scores(game, phase):
    db, code, host, a, b = game
    if phase in ('review', 'reveal'):
        db.change(code, a, 'answer', text='Yes')
        db.change(code, b, 'answer', text='Yes')
        db.change(code, host, 'correct', player='a')
        if phase == 'reveal':
            db.change(code, host, 'correct', player='b')
    if phase == 'paused':
        db.change(code, host, 'pause')
    scores = [p['score'] for p in db.read(code)['players']]
    db.change(code, host, 'skip_stage')
    state = Store(db.path).read(code)
    assert state['stage_index'] == 1 and state['phase'] == 'intro'
    assert set(state['used']) == {'q1', 'q2'}
    assert state['answers'] == {} and state['active'] is None and state['advance_at'] is None
    assert [p['score'] for p in state['players']] == scores
    assert state['paused'] == (phase == 'paused')
    db.change(code, host, 'skip_stage')
    assert db.read(code)['phase'] == 'finished' and not db.read(code)['paused']
    assert not db.tick(code)


def test_skip_event_and_grid_board(game):
    db, code, host, a, b = game
    event = dict(id='e', type='event', title='Trap', effect=dict(type='half_reward', target='all_players', questions=2))
    other = db.create(host, questions=[event, dict(id='q', text='?', answer='Yes', value=100)])
    db.change(other, a, 'join')
    db.change(other, host, 'start')
    db.change(other, host, 'next')
    db.change(other, host, 'skip_stage')
    assert db.read(other)['phase'] == 'finished'
    db.change(code, host, 'skip_stage')
    db.change(code, host, 'next')
    assert db.read(code)['phase'] == 'board'
    db.change(code, host, 'skip_stage')
    assert db.read(code)['phase'] == 'finished'


def test_http_controls_validate_and_publish_state(game, monkeypatch):
    from app import main
    db, code, host, a, b = game
    monkeypatch.setattr(main, 'store', db)
    headers = {'Authorization': 'Bearer ' + db.session(host)}
    path = '/api/rooms/' + code + '/action'
    with TestClient(main.app) as client:
        assert client.post(path, headers=headers, json=dict(action='adjust_score', player='a', delta=1.5)).status_code == 422
        response = client.post(path, headers=headers, json=dict(action='adjust_score', player='a', delta=-75))
        assert response.status_code == 200 and response.json()['players'][1]['score'] == -75
        response = client.post(path, headers=headers, json=dict(action='set_effect', player='a', effect=dict(type='double_penalty', questions=3)))
        assert response.status_code == 200 and response.json()['round_modifiers']['a']['remaining'] == 3
        assert client.post(path, headers=headers, json=dict(action='skip_stage')).json()['stage_number'] == 2
