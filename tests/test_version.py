from fastapi.testclient import TestClient

from app.version import version_info
from builder.auth import hash_password
from builder.main import create_app
from builder.store import Catalog


def test_release_label_uses_seven_commit_characters(monkeypatch):
    monkeypatch.setenv('BUILD_SHA', 'ABCDEF1234567890ABCDEF1234567890ABCDEF12')
    info = version_info()
    assert info['version'] == '0.0.5'
    assert info['label'] == '0.0.5 build abcdef1'
    assert info['build'] == 'abcdef1234567890abcdef1234567890abcdef12'


def test_invalid_build_is_not_rendered(monkeypatch):
    monkeypatch.setenv('BUILD_SHA', '<script>alert(1)</script>')
    assert version_info()['label'] == '0.0.5 build local'


def test_app_and_display_render_the_same_release_before_login(monkeypatch, tmp_path):
    from app import main
    from app.store import Store
    monkeypatch.setenv('BUILD_SHA', '1234567890abcdef1234567890abcdef12345678')
    monkeypatch.setattr(main, 'store', Store(tmp_path/'game.sqlite3'))
    with TestClient(main.app) as client:
        for url in ('/', '/display'):
            page = client.get(url)
            assert page.status_code == 200
            assert '0.0.5 build 1234567' in page.text
            assert '__APP_VERSION_LABEL__' not in page.text
            assert 'id="app-version"' in page.text
        assert client.get('/api/version').json()['version'] == '0.0.5'
        assert client.get('/api/health').json()['build'] == '1234567890abcdef1234567890abcdef12345678'
        assert client.get('/favicon.ico').status_code == 200


def test_builder_renders_its_own_deployed_build(tmp_path, monkeypatch):
    monkeypatch.setenv('BUILD_SHA', 'abcdef1234567890abcdef1234567890abcdef12')
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    with TestClient(create_app(catalog, hash_password('test-password'))) as client:
        response = client.get('/')
        assert '0.0.5 build abcdef1' in response.text
        assert '__APP_VERSION_LABEL__' not in response.text
        assert client.get('/api/version').json()['label'] == '0.0.5 build abcdef1'
        assert client.get('/api/health').json()['service'] == 'builder'
        assert client.get('/favicon.ico').status_code == 200
