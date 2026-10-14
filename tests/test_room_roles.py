import pytest

from app.store import Store


@pytest.fixture
def room(tmp_path):
    store = Store(tmp_path / 'roles.sqlite3')
    host = dict(id='host', name='Host')
    player = dict(id='player', name='Player')
    screen = dict(id='screen', name='Screen')
    code = store.create(host, questions=[dict(id='q', type='question', text='2+2?', answer='4', value=100, seconds=45)])
    store.change(code, player, 'join')
    return store, code, host, player, screen


def test_display_does_not_take_player_slot_or_control_game(room):
    store, code, host, player, screen = room
    store.change(code, screen, 'watch')
    assert len(store.public(code, screen['id'], display=True)['players']) == 2
    for action in ('start', 'answer', 'reaction', 'pick'):
        with pytest.raises(ValueError):
            store.change(code, screen, action, text='🔥')
    with pytest.raises(ValueError):
        store.public(code, screen['id'])
    store.change(code, host, 'start')
    # Screens can connect after the game starts, without joining the roster.
    store.change(code, dict(id='late-screen', name='Late'), 'watch')
    assert len(store.read(code)['players']) == 2


def test_display_hides_host_solution_and_pending_answers(room):
    store, code, host, player, screen = room
    store.change(code, host, 'start')
    store.change(code, screen, 'watch')
    for uid in (host['id'], screen['id']):
        state = store.public(code, uid, display=True)
        assert 'answer' not in state['question']
        assert not state['can_pick']
    store.change(code, player, 'answer', text='4')
    state = store.public(code, screen['id'], display=True)
    assert state['phase'] == 'review'
    assert state['answers'] == {} and state['messages'] == []
    assert 'answer' not in state['question']
    store.change(code, host, 'correct', player=player['id'])
    assert store.public(code, screen['id'], display=True)['question']['answer'] == '4'


def test_reactions_broadcast_during_question_and_are_limited(room, monkeypatch):
    store, code, host, player, screen = room
    store.change(code, host, 'start')
    store.change(code, screen, 'watch')
    store.change(code, player, 'reaction', text='🔥')
    assert store.public(code, host['id'])['reactions'][0]['emoji'] == '🔥'
    assert store.public(code, screen['id'], display=True)['reactions'][0]['emoji'] == '🔥'
    assert store.read(code)['answers'] == {}
    with pytest.raises(ValueError):
        store.change(code, player, 'reaction', text='👏')
    with pytest.raises(ValueError):
        store.change(code, host, 'reaction', text='arbitrary text')
    now = store.read(code)['reactions'][0]['time'] + 3
    monkeypatch.setattr('app.store.time.time', lambda: now)
    store.change(code, player, 'reaction', text='👏')
    assert len(store.read(code)['reactions']) == 2


def test_display_websocket_keeps_role_when_room_updates(room, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    store, code, host, player, screen = room
    monkeypatch.setattr(main, 'store', store)
    monkeypatch.setattr(main, 'DEV_MODE', True)
    monkeypatch.setattr(main, 'connections', {})
    host_token, screen_token = store.session(host), store.session(screen)
    with TestClient(main.app) as client:
        response = client.post(f'/api/rooms/{code}/watch', headers={'Authorization': 'Bearer '+screen_token})
        assert response.status_code == 200 and response.json()['display']
        with client.websocket_connect(f'/ws/{code}') as ws:
            ws.send_json({'token': screen_token, 'display': True})
            assert ws.receive_json()['display']
            response = client.post(f'/api/rooms/{code}/action', json={'action': 'start'}, headers={'Authorization': 'Bearer '+host_token})
            assert response.status_code == 200
            state = ws.receive_json()
            assert state['display'] and state['phase'] == 'question'
            assert 'answer' not in state['question']
            assert len(state['players']) == 2
