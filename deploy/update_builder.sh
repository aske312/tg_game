#!/bin/bash
# Independently deploy authoring from GitHub without restarting the game or its proxy.
set -euo pipefail
base=/opt/rat-race
if [ "$(id -u)" != 0 ]; then echo 'Run as root.' >&2; exit 1; fi
if [ ! -f /etc/rat-race/builder.env ]; then echo 'Configure builder.env first.' >&2; exit 1; fi
exec 9>/run/rat-race-builder-deploy.lock
flock -n 9 || { echo 'Another authoring deployment is running.' >&2; exit 1; }
git --git-dir="$base/repo.git" fetch origin main
revision=$(git --git-dir="$base/repo.git" rev-parse FETCH_HEAD)
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 1
release="$base/releases/$revision"
if [ ! -d "$release" ]; then
    mkdir "$release"
    git --git-dir="$base/repo.git" archive "$revision" | tar -x -C "$release"
fi
for spec in '8011 rat-race-builder.service' '8443 rat-race-builder-proxy.service' '2020 rat-race-builder-proxy.service'; do
    read -r port service <<< "$spec"
    if ! systemctl is-active --quiet "$service" && ss -ltnH "sport = :$port" | grep -q .; then
        echo "Port $port is already used by another service." >&2
        exit 1
    fi
done
"$base/.venv/bin/pip" -q install -r "$release/requirements.txt"
cd "$release"
DATABASE_PATH=/var/lib/rat-race/deploy-test.sqlite3 BUILDER_DATA_DIR=/var/lib/rat-race/builder/deploy-test "$base/.venv/bin/python" -m pytest -q
install -d -o ratrace -g ratrace -m 700 /var/lib/rat-race/builder
install -d -o ratrace -g ratrace -m 755 /var/lib/rat-race/games
install -d -o caddy -g caddy -m 700 /var/lib/rat-race-builder-proxy
install -m 644 "$release/deploy/rat-race-builder.service" /etc/systemd/system/rat-race-builder.service
install -m 644 "$release/deploy/rat-race-builder-proxy.service" /etc/systemd/system/rat-race-builder-proxy.service
install -o root -g caddy -m 640 "$release/deploy/builder.Caddyfile" /etc/rat-race/builder.Caddyfile
set -a
source /etc/rat-race/builder.env
set +a
caddy validate --config /etc/rat-race/builder.Caddyfile --adapter caddyfile
previous=$(readlink -f "$base/builder-current" || true)
printf 'BUILD_SHA=%s\n' "$revision" > /etc/rat-race/builder-release.env
chmod 600 /etc/rat-race/builder-release.env
ln -sfn "$release" "$base/builder-current-next"
mv -Tf "$base/builder-current-next" "$base/builder-current"
systemctl daemon-reload
systemctl enable rat-race-builder.service rat-race-builder-proxy.service
systemctl restart rat-race-builder.service
ready=false
for attempt in {1..20}; do
    if curl -fsS http://127.0.0.1:8011/api/health > /dev/null; then ready=true; break; fi
    sleep 1
done
if [ "$ready" != true ]; then
    if [ -n "$previous" ]; then
        ln -sfn "$previous" "$base/builder-current"
        printf 'BUILD_SHA=%s\n' "$(basename "$previous")" > /etc/rat-race/builder-release.env
        systemctl restart rat-race-builder.service
    fi
    echo 'Authoring failed its health check; previous release restored when available.' >&2
    exit 1
fi
systemctl restart rat-race-builder-proxy.service
if command -v ufw >/dev/null && ufw status | grep -q 'Status: active'; then
    ufw allow 8443/tcp comment 'Rat Race game authoring'
fi
curl --retry 8 --retry-connrefused --retry-delay 1 -fsS "$BUILDER_SITE/api/health"
install -m 755 "$release/deploy/copy-certificate.sh" /usr/local/lib/rat-race/copy-certificate.sh
echo "Authoring deployed: $revision"
