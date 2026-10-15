#!/bin/bash
set -Eeuo pipefail
umask 022
# shellcheck source=deploy/common.sh
source "$(dirname "$(readlink -f "$0")")/common.sh"
require_root
lock_deploy
if [ "$#" = 0 ]; then
    fetch_release
    exec bash "$release/deploy/update.sh" --release "$release"
fi
[ "$#" = 2 ] && [ "$1" = --release ] || die 'Usage: update.sh [--release /opt/rat-race/releases/SHA]'
release=$2
revision=${release##*/}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] && [ "$release" = "$base/releases/$revision" ] || die 'Invalid release path.'
[ -f "$config/app.env" ] || die 'Run the GitHub installer first.'
prepare_release
install -d -o ratrace -g ratrace -m 755 "$data/games" "$data/media"
backup_database
install -d -m 755 /usr/local/lib/rat-race
install -m 755 "$release/deploy/copy-certificate.sh" /usr/local/lib/rat-race/copy-certificate.sh
install -m 644 "$release/deploy/rat-race-cert-renew.service" /etc/systemd/system/
install -m 644 "$release/deploy/rat-race-cert-renew.timer" /etc/systemd/system/
begin_switch current release.env rat-race-web.service rat-race-bot.service
# On the first install these units do not exist yet.
if systemctl cat rat-race-bot.service >/dev/null 2>&1; then systemctl stop rat-race-bot.service; fi
if systemctl cat rat-race-web.service >/dev/null 2>&1; then systemctl stop rat-race-web.service; fi
activate_release
systemctl enable --now rat-race-cert-renew.timer
systemctl start rat-race-web.service
wait_health http://127.0.0.1:8010/api/health "$revision"
public=$("$release/.venv/bin/python" "$release/deploy/configure.py" get "$config/app.env" APP_URL)
wait_health "$public/api/health" "$revision"
systemctl start rat-race-bot.service
wait_service rat-race-bot.service
finish_switch
install_manager
echo "Application deployed: $revision"
