from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.store import Store


@pytest.fixture
def web_screen(tmp_path, monkeypatch):
    from app import main
    db = Store(tmp_path/'display.sqlite3')
    host, player = dict(id='tg-host', name='Host'), dict(id='tg-player', name='Player')
    (tmp_path/'media').mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1]/'static/demo/signals.wav', tmp_path/'media/sample.wav')
    code = db.create(host, questions=[dict(id='q', text='What sound?', answer='Signals', value=100, seconds=3600,
                                          media=dict(kind='audio', url='/api/media/sample', start=1, end=2))],
                     assets=[dict(id='sample', kind='audio', mime='audio/wav', filename='sample.wav')])
    db.change(code, player, 'join')
    monkeypatch.setattr(main, 'store', db)
    monkeypatch.setattr(main, 'DEV_MODE', False)
    monkeypatch.setattr(main, 'connections', {})
    with TestClient(main.app) as client:
        yield client, db, code, host, player


def test_display_page_and_session_work_without_telegram_in_production(web_screen):
    client, db, code, host, player = web_screen
    page = client.get('/display')
    assert page.status_code == 200 and 'id="display-form"' in page.text
    assert 'telegram.org/js/telegram-web-app.js' not in page.text
    assert 'data-role="display"' not in client.get('/').text
    assert client.get('/api/config').json()['dev_mode'] is False
    result = client.post('/api/display', json=dict(code=code.lower()))
    assert result.status_code == 200
    session = result.json()
    assert session['user']['role'] == 'display' and session['user']['room'] == code
    assert session['state']['display'] and not session['state']['can_pick']
    assert len(session['state']['players']) == 2
    assert 'httponly' in result.headers['set-cookie'].lower()
    assert client.cookies.get('ratrace_session') is None
    assert client.post('/api/display', json=dict(code=code)).json()['token'] == session['token']
    assert len(db.read(code)['observers']) == 1
    assert len(db.read(code)['players']) == 2


@pytest.mark.parametrize('code,status', [('A', 422), ('<CODE>', 422), ('AAAAAA', 400)])
def test_bad_invitation_creates_no_session(web_screen, code, status):
    client, db, _, host, player = web_screen
    assert client.post('/api/display', json=dict(code=code)).status_code == status
    with db.connect() as connection:
        assert connection.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0


def test_guest_token_cannot_use_player_host_or_account_endpoints(web_screen):
    client, db, code, host, player = web_screen
    session = client.post('/api/display', json=dict(code=code)).json()
    headers = {'Authorization': 'Bearer '+session['token']}
    for path in ('/api/me', '/api/packs', '/api/rooms/'+code):
        assert client.get(path, headers=headers).status_code == 401
    for path in ('/api/rooms', '/api/practice', '/api/rooms/'+code+'/join', '/api/rooms/'+code+'/watch'):
        assert client.post(path, headers=headers, json={}).status_code == 401
    for action in ('start', 'answer', 'reaction', 'pause', 'next', 'skip_stage', 'adjust_score', 'set_effect'):
        result = client.post('/api/rooms/'+code+'/action', headers=headers, json=dict(action=action, text='Signals', player=player['id'], delta=100))
        assert result.status_code == 401
    assert db.read(code)['phase'] == 'lobby'
    assert [p['score'] for p in db.read(code)['players']] == [0, 0]


def test_websocket_forces_display_role_and_hides_pending_answers(web_screen):
    client, db, code, host, player = web_screen
    guest = client.post('/api/display', json=dict(code=code)).json()
    host_headers = {'Authorization': 'Bearer '+db.session(host)}
    player_headers = {'Authorization': 'Bearer '+db.session(player)}
    path = '/api/rooms/'+code+'/action'
    with client.websocket_connect('/ws/'+code) as ws:
        ws.send_json(dict(token=guest['token'], display=False))
        assert ws.receive_json()['display']
        client.post(path, headers=host_headers, json=dict(action='start')).raise_for_status()
        assert ws.receive_json()['phase'] == 'intro'
        client.post(path, headers=host_headers, json=dict(action='next')).raise_for_status()
        state = ws.receive_json()
        assert state['display'] and state['phase'] == 'question' and 'answer' not in state['question']
        client.post(path, headers=player_headers, json=dict(action='answer', text='Signals')).raise_for_status()
        state = ws.receive_json()
        assert state['phase'] == 'review' and state['answers'] == {} and state['messages'] == []
        assert 'answer' not in state['question']
        client.post(path, headers=host_headers, json=dict(action='correct', player=player['id'])).raise_for_status()
        state = ws.receive_json()
        assert state['question']['answer'] == 'Signals'
        assert state['players'][1]['score'] == 100


def test_guest_is_scoped_to_invited_room_and_media(web_screen):
    client, db, code, host, player = web_screen
    other = db.create(host, questions=[dict(id='q', text='?', answer='Yes', value=100)],
                      assets=[dict(id='other-sample', kind='audio', mime='audio/wav', filename='sample.wav')])
    guest = client.post('/api/display', json=dict(code=code)).json()
    assert client.get('/api/media/sample').status_code == 200
    assert client.get('/api/media/sample', headers={'Range': 'bytes=0-7'}).status_code == 206
    assert client.get('/api/media/other-sample').status_code in (401, 404)
    with client.websocket_connect('/ws/'+other) as ws:
        ws.send_json(dict(token=guest['token'], display=True))
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 1008
    # A token cannot gain media access merely by moving it into another room's cookie.
    client.cookies.set('ratrace_display_'+other, guest['token'], domain='testserver.local', path='/')
    assert client.get('/api/media/other-sample').status_code in (401, 404)
    second = client.post('/api/display', json=dict(code=other)).json()
    assert second['token'] != guest['token']
    assert client.get('/api/media/sample').status_code == 200
    assert client.get('/api/media/other-sample').status_code == 200


def test_display_does_not_replace_host_login_and_can_renew(web_screen):
    client, db, code, host, player = web_screen
    token = db.session(host)
    headers = {'Authorization': 'Bearer '+token}
    client.get('/api/me', headers=headers).raise_for_status()
    guest = client.post('/api/display', json=dict(code=code)).json()
    assert client.cookies.get('ratrace_session') == token
    assert client.get('/api/me', headers=headers).json()['id'] == host['id']
    assert client.post('/api/rooms/'+code+'/action', headers=headers, json=dict(action='start')).status_code == 200
    with db.connect() as connection:
        connection.execute('UPDATE sessions SET expires=0 WHERE token=?', (guest['token'],))
    renewed = client.post('/api/display', json=dict(code=code)).json()
    assert renewed['token'] != guest['token'] and renewed['state']['phase'] == 'intro'
    assert len(renewed['state']['players']) == 2
