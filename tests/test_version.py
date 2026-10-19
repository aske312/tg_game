from fastapi.testclient import TestClient

from app.version import APP_VERSION, ROOT, version_info
from builder.auth import hash_password
from builder.main import create_app
from builder.store import Catalog


def test_version_file_and_build_invalidate_all_first_party_assets(monkeypatch):
    from app.version import versioned_html
    assert APP_VERSION == (ROOT/'VERSION').read_text().strip()
    monkeypatch.setenv('BUILD_SHA', '1234567')
    for path in (ROOT/'static/index.html', ROOT/'builder/static/index.html'):
        html = versioned_html(path)
        assert f'/static/app.js?v={APP_VERSION}-1234567' in html or f'/static/builder.js?v={APP_VERSION}-1234567' in html
        assert '?v=31"' not in html
    monkeypatch.setenv('BUILD_SHA', 'abcdef1')
    assert f'?v={APP_VERSION}-abcdef1' in versioned_html(ROOT/'static/index.html')


def test_release_label_uses_seven_commit_characters(monkeypatch):
    monkeypatch.setenv('BUILD_SHA', 'ABCDEF1234567890ABCDEF1234567890ABCDEF12')
    info = version_info()
    assert info['version'] == APP_VERSION
    assert info['label'] == f'{APP_VERSION} build abcdef1'
    assert info['build'] == 'abcdef1234567890abcdef1234567890abcdef12'


def test_invalid_build_is_not_rendered(monkeypatch):
    monkeypatch.setenv('BUILD_SHA', '<script>alert(1)</script>')
    assert version_info()['label'] == f'{APP_VERSION} build local'


def test_app_and_display_render_the_same_release_before_login(monkeypatch, tmp_path):
    from app import main
    from app.store import Store
    monkeypatch.setenv('BUILD_SHA', '1234567890abcdef1234567890abcdef12345678')
    monkeypatch.setattr(main, 'store', Store(tmp_path/'game.sqlite3'))
    with TestClient(main.app) as client:
        for url in ('/', '/display'):
            page = client.get(url)
            assert page.status_code == 200
            assert f'{APP_VERSION} build 1234567' in page.text
            assert '__APP_VERSION_LABEL__' not in page.text
            assert 'id="app-version"' in page.text
        assert client.get('/api/version').json()['version'] == APP_VERSION
        assert client.get('/api/health').json()['build'] == '1234567890abcdef1234567890abcdef12345678'
        assert client.get('/favicon.ico').status_code == 200


def test_builder_renders_its_own_deployed_build(tmp_path, monkeypatch):
    monkeypatch.setenv('BUILD_SHA', 'abcdef1234567890abcdef1234567890abcdef12')
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    with TestClient(create_app(catalog, hash_password('test-password'))) as client:
        response = client.get('/')
        assert f'{APP_VERSION} build abcdef1' in response.text
        assert '__APP_VERSION_LABEL__' not in response.text
        assert client.get('/api/version').json()['label'] == f'{APP_VERSION} build abcdef1'
        assert client.get('/api/health').json()['service'] == 'builder'
        assert client.get('/favicon.ico').status_code == 200
