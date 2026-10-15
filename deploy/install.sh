#!/bin/bash
# Download this entry point from GitHub; all other code is fetched from GitHub main.
set -Eeuo pipefail
umask 022
repo=https://github.com/aske312/tg_game.git
base=/opt/rat-race
if [ "${1:-}" = --help ]; then
    echo 'Usage: sudo bash install.sh [--app-only] [--config /root/rat-race-install.env]'
    echo 'Requires Debian 12+ or Ubuntu 24.04+, systemd, public ports 80/443 (8443 for builder).'
    exit 0
fi
app_only=false
config_args=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --app-only) app_only=true; config_args+=(--app-only); shift;;
        --config) [ "$#" -ge 2 ] || exit 2; config_args+=(--input "$2"); shift 2;;
        *) echo "Unknown installer option: $1" >&2; exit 2;;
    esac
done
[ "$(id -u)" = 0 ] || { echo 'Run with sudo.' >&2; exit 1; }
[ -d /run/systemd/system ] || { echo 'A systemd host is required.' >&2; exit 1; }
source /etc/os-release
case "$ID" in
    ubuntu) dpkg --compare-versions "$VERSION_ID" ge 24.04;;
    debian) dpkg --compare-versions "$VERSION_ID" ge 12;;
    *) echo 'Supported: Debian 12+ and Ubuntu 24.04+.' >&2; exit 1;;
esac
exec 9>/run/rat-race-deploy.lock
flock -n 9 || { echo 'Another server operation is running.' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl ca-certificates python3 python3-venv nodejs util-linux iproute2
if ! command -v caddy >/dev/null; then
    # The distribution package provides a systemd service and the caddy user.
    apt-get install -y caddy
fi
id ratrace >/dev/null 2>&1 || useradd --system --home-dir /var/lib/rat-race --shell /usr/sbin/nologin ratrace
install -d -o ratrace -g ratrace -m 750 /var/lib/rat-race
install -d -m 755 /etc/rat-race
install -d -m 755 "$base/releases"
if [ ! -d "$base/repo.git" ]; then git clone --bare "$repo" "$base/repo.git"; fi
git --git-dir="$base/repo.git" fetch "$repo" refs/heads/main
revision=$(git --git-dir="$base/repo.git" rev-parse FETCH_HEAD)
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 1
release="$base/releases/$revision"
if [ ! -d "$release" ]; then
    staging=$(mktemp -d "$base/releases/.download-XXXXXX")
    git --git-dir="$base/repo.git" archive "$revision" | tar -x -C "$staging"
    chmod 755 "$staging"
    mv -T "$staging" "$release"
fi
# shellcheck source=deploy/common.sh
source "$release/deploy/common.sh"
prepare_release
"$release/.venv/bin/python" "$release/deploy/configure.py" init "${config_args[@]}"
read_setting() { "$release/.venv/bin/python" "$release/deploy/configure.py" get /etc/rat-race/install.env "$1"; }
host=$(read_setting ACME_HOST)
email=$(read_setting ACME_EMAIL)
is_ip=$(read_setting ACME_IS_IP)

# An existing installation keeps its proxy and certificate configuration.
if [ ! -f /etc/letsencrypt/live/rat-race-ip/fullchain.pem ]; then
    if [ -L "$base/current" ]; then die 'Existing installation has no rat-race-ip certificate; inspect HTTPS configuration.'; fi
    for port in 80 443; do
        # A fresh Caddy package may already be serving its default page.
        if [ -n "$(ss -ltnH "sport = :$port")" ] && ! systemctl is-active --quiet caddy; then
            die "Port $port is occupied; configure a separate host for this installation."
        fi
    done
    # Do not replace an unrelated Caddy site's configuration.
    if [ -f /etc/caddy/Caddyfile ] && ! grep -q '^# Managed by rat-race installer$' /etc/caddy/Caddyfile; then
        default_sum=$(dpkg-query -W -f='${Conffiles}\n' caddy | awk '$1 == "/etc/caddy/Caddyfile" { print $2 }')
        read -r actual_sum _ < <(md5sum /etc/caddy/Caddyfile)
        if [ -z "$default_sum" ] || [ "$actual_sum" != "$default_sum" ]; then
            die 'Custom /etc/caddy/Caddyfile found. Preserve its sites and configure the Rat Race proxy manually.'
        fi
    fi
    install -d -m 755 /var/www/rat-race-acme
    if [ -f /etc/caddy/Caddyfile ] && [ ! -f /etc/rat-race/Caddyfile.before-install ]; then
        cp -p /etc/caddy/Caddyfile /etc/rat-race/Caddyfile.before-install
    fi
    cat > /etc/caddy/Caddyfile <<'CADDY'
# Managed by rat-race installer
{
    auto_https off
}
:80 {
    root * /var/www/rat-race-acme
    file_server
}
CADDY
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
    systemctl enable --now caddy
    systemctl reload caddy
    python3 -m venv "$base/certbot-venv"
    "$base/certbot-venv/bin/pip" -q install 'certbot>=5.4,<6'
    cert_args=(-d "$host")
    if [ "$is_ip" = true ]; then cert_args=(--ip-address "$host" --preferred-profile shortlived); fi
    "$base/certbot-venv/bin/certbot" certonly --non-interactive --agree-tos --email "$email" \
        --cert-name rat-race-ip --webroot -w /var/www/rat-race-acme "${cert_args[@]}"
fi
# Also finish HTTPS setup when a previous run stopped just after certificate issuance.
if grep -q '# Managed by rat-race installer' /etc/caddy/Caddyfile; then
    install -d -o root -g caddy -m 750 /etc/rat-race/tls
    install -o root -g caddy -m 640 /etc/letsencrypt/live/rat-race-ip/fullchain.pem /etc/rat-race/tls/fullchain.pem
    install -o root -g caddy -m 640 /etc/letsencrypt/live/rat-race-ip/privkey.pem /etc/rat-race/tls/privkey.pem
    site=$("$release/.venv/bin/python" "$release/deploy/configure.py" get /etc/rat-race/app.env APP_URL)
    {
        cat <<'CADDY'
# Managed by rat-race installer
{
    auto_https off
}
:80 {
    handle /.well-known/acme-challenge/* {
        root * /var/www/rat-race-acme
        file_server
    }
    handle {
        respond "HTTPS required" 404
    }
}
CADDY
        printf '%s {\n' "$site"
        cat <<'CADDY'
    tls /etc/rat-race/tls/fullchain.pem /etc/rat-race/tls/privkey.pem
    encode gzip
    request_body {
        max_size 26MB
    }
    reverse_proxy 127.0.0.1:8010
}
CADDY
    } > /etc/caddy/Caddyfile
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
    systemctl reload caddy
fi
if [ ! -x "$base/certbot-venv/bin/certbot" ]; then
    python3 -m venv "$base/certbot-venv"
    "$base/certbot-venv/bin/pip" -q install 'certbot>=5.4,<6'
fi
install_manager
# Child deployments reuse the inherited common lock.
bash "$release/deploy/update.sh" --release "$release"
if [ "$app_only" != true ]; then bash "$release/deploy/update_builder.sh" --release "$release"; fi
echo 'Installation complete. Use: sudo rat-race status; sudo rat-race health'
