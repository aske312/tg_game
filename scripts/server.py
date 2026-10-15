"""Run application management commands over SSH; updates come only from GitHub."""
import argparse
import shlex
import sys

import paramiko

from server_admin import connect, run_remote


def update_script(target):
    if target not in ('app', 'builder', 'all'):
        raise ValueError('Invalid deployment target')
    # Bootstrap works on an existing server before rat-race itself is installed.
    return '''set -Eeuo pipefail
exec 9>/run/rat-race-deploy.lock
flock -n 9 || { echo 'Another server operation is running.' >&2; exit 1; }
repo=https://github.com/aske312/tg_game.git
base=/opt/rat-race
[ -d "$base" ] || { echo 'Run the GitHub installer first.' >&2; exit 1; }
if [ ! -d "$base/repo.git" ]; then git clone --bare "$repo" "$base/repo.git"; fi
git --git-dir="$base/repo.git" fetch "$repo" refs/heads/main
revision=$(git --git-dir="$base/repo.git" rev-parse FETCH_HEAD)
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
git --git-dir="$base/repo.git" archive "$revision" | tar -x -C "$temporary"
source "$temporary/deploy/common.sh"
fetch_release
''' + {
        'app': 'bash "$release/deploy/update.sh" --release "$release"\n',
        'builder': 'bash "$release/deploy/update_builder.sh" --release "$release"\n',
        'all': '''bash "$release/deploy/update.sh" --release "$release"
if [ -f /etc/rat-race/builder.env ]; then bash "$release/deploy/update_builder.sh" --release "$release"; fi
''',
    }[target]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['update', 'start', 'stop', 'restart', 'status', 'logs', 'health', 'version'])
    parser.add_argument('target', nargs='?', default='all', choices=['app', 'builder', 'all'])
    parser.add_argument('--follow', action='store_true', help='Follow live logs')
    args = parser.parse_args(argv)
    if args.follow and args.command != 'logs':
        parser.error('--follow is only supported for logs')
    if args.command == 'update':
        script = update_script(args.target)
    else:
        command = ['/usr/local/sbin/rat-race', args.command, args.target]
        if args.follow:
            command.append('--follow')
        script = 'exec '+shlex.join(command)+'\n'
    with connect() as client:
        return run_remote(client, 'if [ "$(id -u)" = 0 ]; then bash -s; else sudo -n bash -s; fi', script)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (paramiko.SSHException, OSError, KeyError, ValueError) as exc:
        print('Server command failed: '+type(exc).__name__, file=sys.stderr)
        sys.exit(1)
