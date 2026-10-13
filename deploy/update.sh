#!/bin/bash
# Pull an immutable release from GitHub; application data lives outside the checkout.
set -euo pipefail
base=/opt/rat-race
repo=https://github.com/aske312/tg_game.git
if [ "$(id -u)" != 0 ]; then
    echo 'Run with sudo.' >&2
    exit 1
fi
exec 9>/run/rat-race-deploy.lock
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
install -d -m 755 "$base/releases"
if [ ! -d "$base/repo.git" ]; then
    git clone --bare "$repo" "$base/repo.git"
fi
git --git-dir="$base/repo.git" fetch origin main
revision=$(git --git-dir="$base/repo.git" rev-parse FETCH_HEAD)
if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
    echo 'Invalid revision.' >&2
    exit 1
fi
release="$base/releases/$revision"
if [ ! -d "$release" ]; then
    mkdir "$release"
    git --git-dir="$base/repo.git" archive "$revision" | tar -x -C "$release"
fi
"$base/.venv/bin/pip" -q install -r "$release/requirements.txt"
cd "$release"
DATABASE_PATH=/var/lib/rat-race/deploy-test.sqlite3 "$base/.venv/bin/python" -m pytest -q
install -d -m 700 /var/lib/rat-race/backups
if [ -f /var/lib/rat-race/game.sqlite3 ]; then
    "$base/.venv/bin/python" - <<'PY'
import sqlite3
from datetime import datetime, timezone
path='/var/lib/rat-race/'
stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
with sqlite3.connect(path+'game.sqlite3') as src, sqlite3.connect(path+'backups/'+stamp+'.sqlite3') as dst:
    src.backup(dst)
PY
fi
previous=$(readlink -f "$base/current" || true)
install -m 644 "$release/deploy/rat-race-web.service" /etc/systemd/system/rat-race-web.service
install -m 644 "$release/deploy/rat-race-bot.service" /etc/systemd/system/rat-race-bot.service
printf 'BUILD_SHA=%s\n' "$revision" > /etc/rat-race/release.env
chmod 600 /etc/rat-race/release.env
ln -sfn "$release" "$base/current-next"
mv -Tf "$base/current-next" "$base/current"
systemctl daemon-reload
systemctl enable rat-race-web.service rat-race-bot.service
systemctl restart rat-race-web.service
ready=false
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8010/api/health > /dev/null; then ready=true; break; fi
    sleep 1
done
if [ "$ready" != true ]; then
    if [ -n "$previous" ]; then
        ln -sfn "$previous" "$base/current"
        printf 'BUILD_SHA=%s\n' "$(basename "$previous")" > /etc/rat-race/release.env
        systemctl restart rat-race-web.service
    fi
    echo 'New server failed its health check; previous checkout restored when available.' >&2
    exit 1
fi
systemctl restart rat-race-bot.service
echo "Deployed $revision"
