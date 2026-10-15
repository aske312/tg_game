import pytest

from scripts.server_access import settings, save_builder_access


def access_file(root, text):
    path = root / 'data/builder-server-access.txt'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8-sig')
    return path


def test_combined_access_file_supports_assignments_and_password_punctuation(tmp_path):
    access_file(tmp_path, 'Конструктор игр: https://example.com:8443\nПароль: web-password\n'
                'IP=example.com\nPORT=2222\nUSER=operator\nPSW=ssh:password=with:punctuation\n')
    result = settings(tmp_path)
    assert result == dict(IP='example.com', PORT=2222, USER='operator', PSW='ssh:password=with:punctuation')


def test_colon_keys_and_legacy_fallback(tmp_path):
    access_file(tmp_path, 'Конструктор игр: https://example.com\nПароль: editor\n')
    (tmp_path / 'server.txt').write_text('IP: example.com\nUSER: root\nPSW: secret\n')
    assert settings(tmp_path)['PORT'] == 22
    access_file(tmp_path, 'ip: other.example.com\nuser: root\npsw: new-secret\n')
    assert settings(tmp_path)['IP'] == 'other.example.com'


@pytest.mark.parametrize('port', ['2222/SSH', '2222 (SSH)'])
def test_port_accepts_ssh_annotation(tmp_path, port):
    access_file(tmp_path, 'IP=example.com\nUSER=root\nPSW=secret\nPORT='+port)
    assert settings(tmp_path)['PORT'] == 2222


@pytest.mark.parametrize('port', ['bad', '0', '65536'])
def test_invalid_access_errors_never_include_credentials(tmp_path, port):
    access_file(tmp_path, 'IP=example.com\nUSER=root\nPSW=hidden-secret\nPORT='+port)
    with pytest.raises(ValueError) as error:
        settings(tmp_path)
    assert 'hidden-secret' not in str(error.value)


def test_editor_credential_refresh_retains_server_credentials(tmp_path):
    path = access_file(tmp_path, 'Конструктор игр: https://old.example.com\nПароль: old-editor\n'
                       'Демонстрация игр: https://example.com/display\n'
                       'IP=example.com\nUSER=operator\nPSW=ssh-password\n')
    save_builder_access(path, 'https://example.com:8443', 'new-editor')
    assert settings(tmp_path)['PSW'] == 'ssh-password'
    text = path.read_text(encoding='utf-8')
    assert 'https://example.com/display' in text and 'new-editor' in text
    assert 'old-editor' not in text and 'old.example.com' not in text
