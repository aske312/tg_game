"""Create private server configuration; never print tokens or passwords."""
import argparse
import getpass
import ipaddress
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlsplit

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from builder.auth import hash_password


def site_settings(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or parsed.port not in (None, 443)):
        raise ValueError('APP_URL must be https://DOMAIN or https://PUBLIC_IP, without a path or custom port')
    host = parsed.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
                                     for label in host.split('.')) or '.' not in host:
            raise ValueError('Invalid public hostname')
        is_ip = False
    else:
        if not address.is_global:
            raise ValueError('APP_URL needs a public IP address')
        is_ip = True
    authority = '['+host+']' if ':' in host else host
    return dict(APP_URL='https://'+authority, BUILDER_SITE='https://'+authority+':8443',
                ACME_HOST=host, ACME_IS_IP='true' if is_ip else 'false')


def write_private(path, values):
    # Quotes are compatible with dotenv and systemd EnvironmentFile, not shell code.
    text = ''.join(key+'="'+str(value).replace('\\', '\\\\').replace('"', '\\"')+'"\n'
                   for key, value in values.items())
    if any('\n' in str(value) or '\r' in str(value) or '\0' in str(value) for value in values.values()):
        raise ValueError('Configuration values must be single-line strings')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)


def initialize(directory, supplied, with_builder=True, ask=input, ask_secret=getpass.getpass):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    app_file = directory / 'app.env'
    if app_file.exists():
        app = dotenv_values(app_file, interpolate=False)
        sites = site_settings(app.get('APP_URL', ''))
    else:
        url = supplied.get('APP_URL') or ask('Public HTTPS URL (https://domain or https://IP): ').strip()
        sites = site_settings(url)
        token = supplied.get('BOT_TOKEN') or ask_secret('Telegram bot token: ').strip()
        username = (supplied.get('BOT_USERNAME') or ask('Bot username (without @): ')).strip().lstrip('@')
        if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+', token):
            raise ValueError('Invalid BOT_TOKEN format')
        if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', username):
            raise ValueError('Invalid BOT_USERNAME')
        write_private(app_file, dict(DEV_MODE='false', BOT_TOKEN=token, BOT_USERNAME=username,
                                   APP_URL=sites['APP_URL'], DATABASE_PATH='/var/lib/rat-race/game.sqlite3',
                                   GAME_PACKS_DIR='/var/lib/rat-race/games'))
    if not (directory / 'install.env').exists():
        email = supplied.get('ACME_EMAIL') or ask('Email for HTTPS certificate: ').strip()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise ValueError('Invalid certificate email')
        write_private(directory / 'install.env', dict(ACME_HOST=sites['ACME_HOST'],
                      ACME_IS_IP=sites['ACME_IS_IP'], ACME_EMAIL=email))
    if with_builder and not (directory / 'builder.env').exists():
        password = supplied.get('BUILDER_PASSWORD') or secrets.token_urlsafe(24)
        if len(password) < 12 or len(password) > 256 or any(char in password for char in '\r\n\0'):
            raise ValueError('BUILDER_PASSWORD must contain 12 to 256 characters on one line')
        write_private(directory / 'builder.env', dict(BUILDER_PASSWORD_HASH=hash_password(password),
                      BUILDER_DATA_DIR='/var/lib/rat-race/builder', GAME_PACKS_DIR='/var/lib/rat-race/games',
                      BUILDER_SITE=sites['BUILDER_SITE']))
        write_private(directory / 'builder-access.txt', dict(URL=sites['BUILDER_SITE'], PASSWORD=password))
        print('Builder URL and password saved in /etc/rat-race/builder-access.txt (root only).')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('init')
    create.add_argument('--input', type=Path, help='Private dotenv file with installation settings')
    create.add_argument('--app-only', action='store_true')
    read = sub.add_parser('get')
    read.add_argument('file', type=Path)
    read.add_argument('key', choices=['APP_URL', 'BUILDER_SITE', 'ACME_HOST', 'ACME_IS_IP', 'ACME_EMAIL'])
    args = parser.parse_args()
    if args.command == 'get':
        value = dotenv_values(args.file, interpolate=False).get(args.key)
        if not value:
            raise ValueError('Missing configuration key: '+args.key)
        print(value)
    else:
        supplied = dotenv_values(args.input, interpolate=False) if args.input else {}
        if args.input and not args.input.is_file():
            raise ValueError('Installation settings file does not exist')
        initialize(Path('/etc/rat-race'), supplied, not args.app_only)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, EOFError) as exc:
        print('Configuration failed: '+str(exc), file=sys.stderr)
        sys.exit(1)
