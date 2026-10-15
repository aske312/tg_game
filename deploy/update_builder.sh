#!/bin/bash
set -Eeuo pipefail
umask 022
# shellcheck source=deploy/common.sh
source "$(dirname "$(readlink -f "$0")")/common.sh"
require_root
lock_deploy
if [ "$#" = 0 ]; then
    fetch_release
    exec bash "$release/deploy/update_builder.sh" --release "$release"
fi
[ "$#" = 2 ] && [ "$1" = --release ] || die 'Usage: update_builder.sh [--release /opt/rat-race/releases/SHA]'
release=$2
revision=${release##*/}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] && [ "$release" = "$base/releases/$revision" ] || die 'Invalid release path.'
[ -f "$config/builder.env" ] || die 'Run the GitHub installer with the builder enabled first.'
for spec in '8011 rat-race-builder.service' '8443 rat-race-builder-proxy.service' '2020 rat-race-builder-proxy.service'; do
    read -r port service <<< "$spec"
    if ! systemctl is-active --quiet "$service" && [ -n "$(ss -ltnH "sport = :$port")" ]; then
        die "Port $port is already used by another service."
    fi
done
prepare_release
install -d -o ratrace -g ratrace -m 700 "$data/builder"
install -d -o ratrace -g ratrace -m 755 "$data/games"
install -d -o caddy -g caddy -m 700 /var/lib/rat-race-builder-proxy
public=$("$release/.venv/bin/python" "$release/deploy/configure.py" get "$config/builder.env" BUILDER_SITE)
export BUILDER_SITE="$public"
caddy validate --config "$release/deploy/builder.Caddyfile" --adapter caddyfile
begin_switch builder-current builder-release.env rat-race-builder.service rat-race-builder-proxy.service
install -o root -g caddy -m 640 "$release/deploy/builder.Caddyfile" "$config/builder.Caddyfile"
activate_release
systemctl restart rat-race-builder.service
wait_health http://127.0.0.1:8011/api/health "$revision"
systemctl restart rat-race-builder-proxy.service
wait_health "$public/api/health" "$revision"
finish_switch
install_manager
echo "Builder deployed: $revision"
