#!/bin/bash
set -euo pipefail
install -d -o root -g caddy -m 750 /etc/rat-race/tls
install -o root -g caddy -m 640 /etc/letsencrypt/live/rat-race-ip/fullchain.pem /etc/rat-race/tls/fullchain.pem
install -o root -g caddy -m 640 /etc/letsencrypt/live/rat-race-ip/privkey.pem /etc/rat-race/tls/privkey.pem
caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile --force
if systemctl is-active --quiet rat-race-builder-proxy.service; then
    systemctl reload rat-race-builder-proxy.service
fi
