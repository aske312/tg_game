import json
from pathlib import Path
import subprocess
import socket
import socketserver
import threading
import time

import pytest
from fastapi.testclient import TestClient

from builder.auth import hash_password
from builder.main import create_app
from builder.server_control import ControlError, ControlUnavailable
from builder import server_control as control_client
from builder.store import Catalog
from deploy import server_control as control


@pytest.fixture
def client(tmp_path):
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', Path(__file__).resolve().parents[1]/'games')
    with TestClient(create_app(catalog, hash_password('server-test-password')),
                    headers={'X-Builder-Request': '1'}) as session:
        yield session


def login(client):
    assert client.post('/api/login', json={'password': 'server-test-password'}).status_code == 200


def test_server_endpoints_require_login_and_csrf(client, monkeypatch):
    calls = []
    monkeypatch.setattr('builder.main.request_control', lambda action: calls.append(action) or {'available': True})
    assert client.get('/api/server').status_code == 401
    assert client.post('/api/server/action', json={'action': 'update'}).status_code == 401
    login(client)
    assert client.post('/api/server/action', json={'action': 'update'}, headers={'X-Builder-Request': '0'}).status_code == 403
    assert client.post('/api/server/action', json={'action': 'rollback'}, headers={'Origin': 'https://other.example'}).status_code == 403
    assert not calls
    assert client.get('/api/server').json()['available']
    assert client.post('/api/server/action', json={'action': 'update'}).status_code == 202
    assert client.post('/api/server/action', json={'action': 'rollback'}).status_code == 202
    assert client.post('/api/server/action', json={'action': 'restart;whoami'}).status_code == 422
    assert calls == ['status', 'update', 'rollback']


def test_unavailable_controller_and_conflicting_operations_are_reported(client, monkeypatch):
    login(client)
    def unavailable(action):
        raise ControlUnavailable()
    monkeypatch.setattr('builder.main.request_control', unavailable)
    assert client.get('/api/server').json()['available'] is False
    assert client.post('/api/server/action', json={'action': 'update'}).status_code == 503
    def busy(action):
        raise ControlError('Операция уже выполняется')
    monkeypatch.setattr('builder.main.request_control', busy)
    response = client.post('/api/server/action', json={'action': 'rollback'})
    assert response.status_code == 409
    assert response.json()['detail'] == 'Операция уже выполняется'


def versions(previous=True):
    return {'app': {'current': {'version': '0.5.0', 'build': 'a'*40},
                    'previous': {'version': '0.4.0', 'build': 'b'*40} if previous else None}}


def test_job_runs_fixed_command_once_and_persists_result(tmp_path, monkeypatch):
    monkeypatch.setattr(control, 'installed_versions', versions)
    started, finish = threading.Event(), threading.Event()
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['start_new_session']
        kwargs['stdout'].write(b'working\n')
        started.set()
        assert finish.wait(5)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(control.subprocess, 'run', run)
    manager = control.Controller(tmp_path)
    job = manager.start('update')
    assert started.wait(5)
    try:
        assert job['status'] == 'running'
        assert manager.snapshot()['log'] == 'working\n'
        with pytest.raises(ValueError, match='уже выполняется'):
            manager.start('rollback')
        with pytest.raises(ValueError):
            manager.handle({'action': 'update', 'command': 'arbitrary'})
        assert commands == [[control.MANAGER, 'update', 'all']]
    finally:
        finish.set()
    for _ in range(100):
        if manager.snapshot()['status'] != 'running':
            break
        time.sleep(.01)
    assert manager.snapshot()['status'] == 'succeeded'
    assert json.loads((tmp_path/'job.json').read_text())['exit_code'] == 0
    assert control.Controller(tmp_path).snapshot()['id'] == job['id']


def test_missing_rollback_and_interrupted_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(control, 'installed_versions', lambda: versions(False))
    manager = control.Controller(tmp_path)
    with pytest.raises(ValueError, match='Предыдущая версия'):
        manager.start('rollback')
    assert manager.snapshot() is None
    (tmp_path/'job.json').write_text(json.dumps(dict(id='test', action='update', status='running')))
    manager = control.Controller(tmp_path)
    assert manager.snapshot()['status'] == 'interrupted'
    assert json.loads((tmp_path/'job.json').read_text())['status'] == 'interrupted'


def test_failed_job_and_log_size(tmp_path, monkeypatch):
    monkeypatch.setattr(control, 'installed_versions', versions)
    monkeypatch.setattr(control.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 7))
    manager = control.Controller(tmp_path)
    manager.job = dict(id='test', action='rollback', status='running')
    manager.run('rollback')
    assert manager.snapshot()['status'] == 'failed'
    assert manager.snapshot()['exit_code'] == 7
    (tmp_path/'operation.log').write_bytes(b'x'*50000)
    assert len(manager.snapshot()['log']) == 16000


def test_invalid_local_protocol_cannot_launch_commands(tmp_path, monkeypatch):
    manager = control.Controller(tmp_path)
    for request in ({'action': 'stop'}, {'action': 'update', 'release': '../../tmp'}, [], None, 'update'):
        with pytest.raises(ValueError):
            manager.handle(request)
    assert manager.snapshot() is None


def test_release_metadata_never_reads_arbitrary_directory(tmp_path):
    # Real Linux symlinks are needed to exercise the same pointer contract as systemd.
    release = tmp_path/'releases'/('a'*40)
    release.mkdir(parents=True)
    (release/'VERSION').write_text('0.4.0\n')
    try:
        (tmp_path/'current').symlink_to(release, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink privileges unavailable')
    assert control.release_info('current', tmp_path)['version'] == '0.4.0'
    outside = tmp_path/'outside'
    outside.mkdir()
    (outside/'VERSION').write_text('private contents')
    (tmp_path/'builder-current').symlink_to(outside, target_is_directory=True)
    assert control.release_info('builder-current', tmp_path) is None


@pytest.mark.skipif(not hasattr(socket, 'AF_UNIX'), reason='Unix socket integration requires Linux')
def test_local_socket_protocol_and_builder_client(tmp_path, monkeypatch):
    path = str(tmp_path/'control.sock')
    monkeypatch.setattr(control_client, 'SOCKET_PATH', path)
    monkeypatch.setattr(control, 'metrics', lambda: {'cpu_percent': 20})
    monkeypatch.setattr(control, 'services', lambda: {'rat-race-web.service': 'active'})
    monkeypatch.setattr(control, 'installed_versions', versions)
    manager = control.Controller(tmp_path/'state')
    with socketserver.ThreadingUnixStreamServer(path, control.Handler) as server:
        server.controller = manager
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result = control_client.request_control('status')
            assert result['available']
            assert result['metrics']['cpu_percent'] == 20
            assert result['services']['rat-race-web.service'] == 'active'
            assert result['job'] is None
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(path)
                connection.sendall(b'{"action":"update","command":"whoami"}\n')
                with connection.makefile('rb') as stream:
                    assert json.loads(stream.readline())['error']
            assert manager.snapshot() is None
            manager.job = dict(id='active', action='update', status='running')
            with pytest.raises(ControlError, match='уже выполняется'):
                control_client.request_control('update')
        finally:
            server.shutdown()
            worker.join(timeout=5)
