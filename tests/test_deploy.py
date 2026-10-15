"""Server configuration and deployment failure recovery without a real server."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from dotenv import dotenv_values

from builder.auth import check_password
from deploy.configure import initialize, site_settings, write_private

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('url', ['http://example.com', 'https://127.0.0.1', 'https://10.0.0.1',
    'https://example.com/path', 'https://user:pass@example.com', 'https://example.com:8443',
    'https://example.com?x=1', 'https://example.com#x', 'https://bad_name.com', 'https://-bad.com'])
def test_installer_rejects_invalid_sites(url):
    with pytest.raises(ValueError):
        site_settings(url)


def test_installer_supports_domains_and_public_ipv6():
    assert site_settings('https://example.com/')['APP_URL'] == 'https://example.com'
    result = site_settings('https://[2606:4700:4700::1111]')
    assert result['BUILDER_SITE'] == 'https://[2606:4700:4700::1111]:8443'
    assert result['ACME_IS_IP'] == 'true'


def test_installer_preserves_secrets_on_repeat_and_can_add_builder(tmp_path, capsys):
    values = dict(APP_URL='https://example.com', BOT_TOKEN='123456:secret_token',
                  BOT_USERNAME='example_bot', ACME_EMAIL='owner@example.com',
                  BUILDER_PASSWORD='test-password-very-private')
    initialize(tmp_path, values, with_builder=False)
    app = (tmp_path / 'app.env').read_bytes()
    assert not (tmp_path / 'builder.env').exists()
    initialize(tmp_path, values)
    builder = dotenv_values(tmp_path / 'builder.env')
    assert check_password(values['BUILDER_PASSWORD'], builder['BUILDER_PASSWORD_HASH'])
    assert dotenv_values(tmp_path / 'app.env')['DEV_MODE'] == 'false'
    assert values['BOT_TOKEN'] not in capsys.readouterr().out
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    initialize(tmp_path, {}, ask=lambda _: pytest.fail('Repeat installation must not prompt'))
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert (tmp_path / 'app.env').read_bytes() == app
    if os.name != 'nt':
        assert (tmp_path / 'builder-access.txt').stat().st_mode & 0o777 == 0o600


def test_private_config_roundtrip_and_no_overwrite(tmp_path):
    path = tmp_path / 'private.env'
    secret = 'dollar$literal\\quote"and spaces'
    write_private(path, {'SECRET': secret})
    assert dotenv_values(path, interpolate=False)['SECRET'] == secret
    with pytest.raises(FileExistsError):
        write_private(path, {'SECRET': 'replacement'})
    with pytest.raises(ValueError):
        write_private(tmp_path / 'invalid', {'SECRET': 'line\nbreak'})
    assert not (tmp_path / 'invalid').exists()


def test_config_get_cannot_expose_secrets(tmp_path):
    result = subprocess.run([os.sys.executable, str(ROOT/'deploy/configure.py'),
                             'get', str(tmp_path/'app.env'), 'BOT_TOKEN'], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'invalid choice' in result.stderr


def bash_test(tmp_path, body):
    if os.name == 'nt' or not shutil.which('bash'):
        pytest.skip('Deployment transaction tests require Linux Bash and symlinks')
    harness = '''set -Eeuo pipefail
source "$PROJECT/deploy/common.sh"
base="$SANDBOX/opt"
config="$SANDBOX/etc"
data="$SANDBOX/data"
units_dir="$SANDBOX/units"
mkdir -p "$base/releases/old" "$base/releases/new/deploy" "$config" "$units_dir"
revision=new
release="$base/releases/new"
printf 'new unit' > "$release/deploy/example.service"
systemctl() {
    printf '%s\\n' "$*" >> "$SANDBOX/commands"
    case "$1" in
        is-active|is-enabled) [ -f "$SANDBOX/previous-active" ];;
        *) return 0;;
    esac
}
''' + body
    return subprocess.run(['bash', '-c', harness], env={**os.environ, 'PROJECT': str(ROOT),
        'SANDBOX': str(tmp_path)}, capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize('component', ['app', 'builder'])
def test_failed_deployment_restores_link_units_config_and_running_service(tmp_path, component):
    link = 'current' if component == 'app' else 'builder-current'
    body = f'''ln -s "$base/releases/old" "$base/{link}"
printf 'old unit' > "$units_dir/example.service"
printf 'BUILD_SHA=old' > "$config/release.env"
printf 'old proxy' > "$config/builder.Caddyfile"
touch "$SANDBOX/previous-active"
begin_switch {link} release.env example.service
activate_release
printf 'new proxy' > "$config/builder.Caddyfile"
false
'''
    result = bash_test(tmp_path, body)
    assert result.returncode != 0
    assert (tmp_path/'opt'/link).resolve() == tmp_path/'opt/releases/old'
    assert (tmp_path/'units/example.service').read_text() == 'old unit'
    assert (tmp_path/'etc/release.env').read_text() == 'BUILD_SHA=old'
    if component == 'builder':
        assert (tmp_path/'etc/builder.Caddyfile').read_text() == 'old proxy'
    assert 'start example.service' in (tmp_path/'commands').read_text()


def test_failed_first_deployment_removes_new_pointer_and_units(tmp_path):
    result = bash_test(tmp_path, '''begin_switch current release.env example.service
activate_release
false
''')
    assert result.returncode != 0
    assert not (tmp_path/'opt/current').is_symlink()
    assert not (tmp_path/'units/example.service').exists()
    assert not (tmp_path/'etc/release.env').exists()


def test_successful_deployment_keeps_new_release(tmp_path):
    result = bash_test(tmp_path, '''begin_switch current release.env example.service
activate_release
finish_switch
''')
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'opt/current').resolve() == tmp_path/'opt/releases/new'
    assert (tmp_path/'units/example.service').read_text() == 'new unit'


def test_health_check_rejects_wrong_revision(tmp_path):
    result = bash_test(tmp_path, '''curl() { printf '%s' '{"status":"ok","build":"old"}'; }
sleep() { :; }
wait_health http://localhost/api/health new
''')
    assert result.returncode != 0


def test_release_checks_stop_after_python_failure(tmp_path):
    result = bash_test(tmp_path, '''mkdir -p "$release/.venv/bin"
touch "$release/.venv/.dependencies-ready"
printf '#!/bin/bash\\nexit 7\\n' > "$release/.venv/bin/python"
chmod +x "$release/.venv/bin/python"
node() { touch "$SANDBOX/node-was-run"; }
prepare_release
''')
    assert result.returncode != 0
    assert not (tmp_path/'node-was-run').exists()
    assert 'Release checks failed' in result.stderr
