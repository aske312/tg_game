import json

import pytest

from app.modes import stages_from_doc
from app.store import Store


def round_game(tmp_path, mode='blitz', media=None):
    db = Store(tmp_path/'rounds.sqlite3')
    host, a, b = [dict(id=n, name=n) for n in ('host', 'a', 'b')]
    stages = stages_from_doc(dict(stages=[
        dict(id='s1', type=mode, title='First', auto_advance=True, categories=['Topic']),
        dict(id='s2', type='blitz', title='Second', auto_advance=True),
    ]))
    first = dict(id='q1', stage='s1', text='Question', category='Topic', answer='Yes', value=100, seconds=45)
    if mode == 'binary': first.update(choices=['Yes', 'No'], correct_choice=0)
    if media: first['media'] = dict(kind=media, url='/recording', start=20, end=30)
    code = db.create(host, stages=stages, questions=[first, dict(id='q2', stage='s2', text='Next', answer='Yes', value=100)])
    for p in (a, b): db.change(code, p, 'join')
    db.change(code, host, 'start')
    db.change(code, host, 'next')
    if mode == 'grid':
        db.change(code, host, 'pick', question='q1')
    return db, code, host, a, b


@pytest.mark.parametrize('mode', ['blitz', 'grid', 'binary'])
def test_completed_round_waits_for_host_to_choose_scores_or_progression(tmp_path, monkeypatch, mode):
    now = [1000.]
    monkeypatch.setattr('app.store.time.time', lambda: now[0])
    db, code, host, a, b = round_game(tmp_path, mode)
    kwargs = dict(choice=0) if mode == 'binary' else dict(text='Yes')
    db.change(code, a, 'answer', **kwargs)
    assert not db.read(code)['scores_visible']
    db.change(code, b, 'answer', **kwargs)
    if mode != 'binary':
        db.change(code, host, 'correct', player='a')
        assert not db.read(code)['scores_visible']
        db.change(code, host, 'correct', player='b')
    state = db.read(code)
    assert not state['scores_visible'] and state['phase'] == 'reveal' and state['display_scene'] == 'round_end'
    assert len(state['round_results']) == 1
    assert state['advance_at'] is None and state['stage_index'] == 0
    now[0] += 1000
    db = Store(db.path)
    assert not db.tick(code) and not db.read(code)['scores_visible']
    with pytest.raises(ValueError): db.change(code, a, 'next')
    db.change(code, host, 'adjust_score', player='a', delta=25)
    assert next(p for p in db.public(code, 'a')['players'] if p['id'] == 'a')['score'] == 125
    db.change(code, host, 'show_scores')
    assert db.read(code)['scores_visible'] and db.read(code)['scores_round'] == 's1'
    db.change(code, host, 'next')
    assert db.read(code)['phase'] == 'intro' and not db.read(code)['scores_visible']
    db.change(code, host, 'next')
    assert db.read(code)['active'] == 'q2'
    db.change(code, host, 'close')
    assert not db.read(code)['scores_visible'] and db.read(code)['display_scene'] == 'round_end'
    results = db.read(code)['round_results']
    assert [r['stage_id'] for r in results] == ['s1', 's2']
    assert [(p['round_points'], p['score']) for p in results[0]['players']] == [(125, 125), (100, 100)]
    assert [(p['round_points'], p['score']) for p in results[1]['players']] == [(-100, 25), (-100, 0)]
    db.change(code, host, 'show_scores', question='s1')
    assert db.read(code)['scores_round'] == 's1'
    with pytest.raises(ValueError): db.change(code, a, 'show_scores', question='s2')
    db.change(code, host, 'hide_scores')
    assert not db.read(code)['scores_visible'] and db.read(code)['display_scene'] == 'round_end'
    assert not db.tick(code)
    db.change(code, host, 'next')
    assert db.read(code)['phase'] == 'finished'


@pytest.mark.parametrize('media', ['audio', 'video'])
def test_last_media_question_plays_in_full_then_waits_for_host(tmp_path, media):
    db, code, host, a, b = round_game(tmp_path, media=media)
    for p in (a, b): db.change(code, p, 'answer', text='Yes')
    for p in (a, b): db.change(code, host, 'correct', player=p['id'])
    assert db.read(code)['media_playback']['mode'] == 'full'
    assert not db.read(code)['scores_visible'] and db.read(code)['advance_at'] is None
    screen = dict(id='screen', name='Display', role='display', room=code)
    db.change(code, screen, 'watch')
    db.change(code, screen, 'media_pause', question='q1', position=10, duration=60, media_mode='full')
    assert not db.read(code)['scores_visible']
    db.change(code, host, 'media_play', question='q1')
    db.change(code, screen, 'media_pause', question='q1', position=60, duration=60, media_mode='full')
    assert not db.read(code)['scores_visible'] and db.read(code)['display_scene'] == 'round_end'
    db.change(code, host, 'show_scores')
    # A delayed second display must not close the results selected by the host.
    db.change(code, screen, 'media_pause', question='q1', position=60, duration=60, media_mode='full')
    assert db.read(code)['scores_visible']
    assert not db.tick(code)
    db.change(code, host, 'next')
    assert db.read(code)['stage_index'] == 1


def test_legacy_scheduled_transition_waits_at_round_end(tmp_path, monkeypatch):
    db, code, host, a, b = round_game(tmp_path)
    db.change(code, host, 'close')
    state = db.read(code)
    state.update(scores_visible=False, advance_at=1000)
    with db.connect() as conn:
        conn.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(state), code))
    monkeypatch.setattr('app.store.time.time', lambda: 1001)
    assert db.tick(code)
    assert db.read(code)['stage_index'] == 0 and db.read(code)['display_scene'] == 'round_end'
    assert not db.read(code)['scores_visible']


def test_event_at_end_of_round_also_waits_for_host_choice(tmp_path):
    db = Store(tmp_path/'event.sqlite3')
    host, player = dict(id='h', name='Host'), dict(id='p', name='Player')
    stage = dict(id='s', type='blitz', title='Events', chooser='host', auto_advance=True)
    questions = [dict(id='q', stage='s', text='Question', answer='Yes', value=100),
                 dict(id='e', stage='s', type='event', title='Trap', text='',
                      effect=dict(type='double_penalty', target='all_players', questions=1))]
    code = db.create(host, stages=[stage], questions=questions)
    db.change(code, player, 'join'); db.change(code, host, 'start')
    db.change(code, host, 'next')
    db.change(code, host, 'close'); db.change(code, host, 'next')
    state = db.read(code)
    assert not state['scores_visible'] and state['phase'] == 'event' and state['display_scene'] == 'round_end'
    assert state['advance_at'] is None and not db.tick(code)
    assert state['modifiers']['p']['kind'] == 'double_penalty'
    db.change(code, host, 'next')
    assert db.read(code)['phase'] == 'finished'


def test_player_practice_stops_at_each_round_boundary(tmp_path, monkeypatch):
    now = [1000.]
    monkeypatch.setattr('app.store.time.time', lambda: now[0])
    db = Store(tmp_path/'practice.sqlite3')
    player = dict(id='p', name='Player')
    stages = stages_from_doc(dict(stages=[dict(id=s, type='blitz', auto_advance=True) for s in ('a', 'b')]))
    code = db.create(player, practice=True, stages=stages,
                     questions=[dict(id=s, stage=s, text='Question', answer='Yes', value=100, seconds=45) for s in ('a', 'b')])
    db.change(code, player, 'answer', text='Yes')
    now[0] = max(db.read(code)['bot_due'].values())+.1
    db.tick(code); now[0] += 2; db.tick(code)
    assert not db.read(code)['scores_visible'] and db.read(code)['advance_at'] is None
    assert db.read(code)['display_scene'] == 'round_end'
    now[0] += 100
    assert not db.tick(code) and db.read(code)['stage_index'] == 0
    db.change(code, player, 'next')
    assert db.read(code)['stage_index'] == 1
