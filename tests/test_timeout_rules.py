import pytest

from app.modes import stages_from_doc
from app.store import Store


def game(tmp_path, mode='blitz', single=False, media=False):
    db = Store(tmp_path/'timeout.sqlite3')
    host, a, b = [dict(id=n, name=n) for n in ('host', 'a', 'b')]
    stage = stages_from_doc(dict(stages=[dict(id='s', type=mode, categories=['Topic'], answer_mode='single' if single else 'all')]))[0]
    q = dict(id='q1', stage='s', text='Question', category='Topic', answer='Yes', value=100, seconds=45)
    if mode == 'binary': q.update(choices=['Yes', 'No'], correct_choice=0)
    if media: q['media'] = dict(kind='audio', url='/audio', start=10, end=20)
    code = db.create(host, stages=[stage], questions=[q, dict(q, id='q2')])
    for p in (a, b): db.change(code, p, 'join')
    db.change(code, host, 'start')
    db.change(code, host, 'next')
    if mode == 'grid':
        db.change(code, host, 'pick', question='q1')
    db.change(code, dict(id='screen', name='Screen'), 'watch')
    return db, code, host, a, b


@pytest.mark.parametrize('mode', ['blitz', 'grid', 'binary'])
def test_timeout_waits_for_host_without_reveal_grading_or_penalties(tmp_path, monkeypatch, mode):
    db, code, host, a, b = game(tmp_path, mode, media=True)
    db.change(code, a, 'answer', **(dict(choice=0) if mode == 'binary' else dict(text='Yes')))
    now = db.read(code)['deadline']+1
    monkeypatch.setattr('app.store.time.time', lambda: now)
    assert db.tick(code)
    assert not Store(db.path).tick(code)
    state = db.read(code)
    assert state['phase'] == 'question' and state['time_expired']
    assert state['used'] == [] and state['omission_penalties'] == {}
    assert state['media_playback']['mode'] == 'excerpt'
    assert not state['scores_visible'] and state['advance_at'] is None
    assert all(p['score'] == 0 for p in state['players'])
    for uid, display in [('a', False), ('b', False), ('screen', True)]:
        public = db.public(code, uid, display=display)
        assert 'answer' not in public['question'] and 'correct_choice' not in public['question']
        assert not public['can_answer']
    with pytest.raises(ValueError): db.change(code, b, 'answer', text='Yes')
    with pytest.raises(ValueError): db.change(code, host, 'correct', player='a')
    db.change(code, host, 'close')
    if mode != 'binary': db.change(code, host, 'correct', player='a')
    assert [p['score'] for p in db.read(code)['players']] == [0, 100, -100]
    assert db.read(code)['media_playback']['mode'] == 'full'


@pytest.mark.parametrize('effect,points', [(None, -100),
    (dict(type='double_penalty'), -200), (dict(type='shield'), 0),
    (dict(type='half_reward'), -100), (dict(type='penalty_points', amount=25), -125)])
def test_manual_close_penalizes_only_missing_answers_with_current_effect(tmp_path, effect, points):
    db, code, host, a, b = game(tmp_path)
    if effect: db.change(code, host, 'set_effect', player='b', effect=dict(effect, questions=1))
    db.change(code, a, 'answer', text='Yes')
    db.change(code, host, 'close')
    assert db.read(code)['phase'] == 'review'
    assert db.read(code)['omission_penalties'] == {'b': points}
    assert db.public(code, 'a')['omission_penalties'] == {}
    assert db.public(code, 'b')['omission_penalties'] == {'b': points}
    assert 'omission_penalties' not in db.public(code, 'screen', display=True)
    assert db.public(code, 'host')['answered_ids'] == ['a']
    with pytest.raises(ValueError): db.change(code, host, 'close')
    db.change(code, host, 'correct', player='a')
    assert [p['score'] for p in db.read(code)['players']] == [0, 100, points]
    if effect: assert db.read(code)['modifiers'] == {}
    db.change(code, host, 'next')
    assert db.read(code)['omission_penalties'] == {} and not db.read(code)['time_expired']


def test_single_responder_timeout_does_not_penalize_other_players(tmp_path, monkeypatch):
    db, code, host, a, b = game(tmp_path, 'grid', single=True)
    now = db.read(code)['deadline']+1
    db.change(code, a, 'buzz')
    monkeypatch.setattr('app.store.time.time', lambda: now)
    assert not db.tick(code) and db.read(code)['phase'] == 'question'
    db.change(code, host, 'close')
    assert db.read(code)['phase'] == 'reveal' and db.read(code)['omission_penalties'] == {}
    assert all(p['score'] == 0 for p in db.read(code)['players'])


def test_no_answers_at_timeout_still_requires_manual_close(tmp_path, monkeypatch):
    db, code, host, a, b = game(tmp_path)
    now = db.read(code)['deadline']+1
    monkeypatch.setattr('app.store.time.time', lambda: now)
    assert db.tick(code) and db.read(code)['phase'] == 'question'
    assert all(p['score'] == 0 for p in db.read(code)['players'])
    db.change(code, host, 'close')
    assert db.read(code)['phase'] == 'reveal' and db.read(code)['answers'] == {}
    assert [p['score'] for p in db.read(code)['players']] == [0, -100, -100]
