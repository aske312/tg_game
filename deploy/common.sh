#!/bin/bash
# Shared server operations. Source only; callers enable strict mode.
base=/opt/rat-race
config=/etc/rat-race
data=/var/lib/rat-race
units_dir=/etc/systemd/system
repo=https://github.com/aske312/tg_game.git

die() { echo "$*" >&2; exit 1; }
require_root() { [ "$(id -u)" = 0 ] || die 'Run with sudo.'; }
lock_deploy() {
    # Reuse the inherited open file description when a manager invokes a child.
    if [ "$(readlink /proc/self/fd/9 2>/dev/null || true)" != /run/rat-race-deploy.lock ]; then
        exec 9>/run/rat-race-deploy.lock
    fi
    flock -n 9 || die 'Another installation, deployment or service operation is running.'
}

published_release_tag() {
    curl --retry 3 --connect-timeout 10 --max-time 30 -fsS https://api.github.com/repos/aske312/tg_game/releases/latest |
        python3 -c 'import json,re,sys; d=json.load(sys.stdin); tag=d.get("tag_name", ""); assert not d.get("draft") and not d.get("prerelease") and re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)",tag), "Invalid published release"; print(tag)'
}

fetch_release() {
    local tag
    tag=$(published_release_tag) || die 'No published stable GitHub Release is available; running services were not changed.'
    install -d -m 755 "$base/releases"
    if [ ! -d "$base/repo.git" ]; then git clone --bare "$repo" "$base/repo.git" >&2; fi
    # Never trust a changed origin or the checkout of the calling script.
    git --git-dir="$base/repo.git" fetch "$repo" "refs/tags/$tag" >&2
    revision=$(git --git-dir="$base/repo.git" rev-parse 'FETCH_HEAD^{commit}')
    [[ "$revision" =~ ^[0-9a-f]{40}$ ]] || die 'Invalid GitHub revision.'
    release="$base/releases/$revision"
    if [ ! -d "$release" ]; then
        local staging
        staging=$(mktemp -d "$base/releases/.download-XXXXXX")
        if ! (set -o pipefail; git --git-dir="$base/repo.git" archive "$revision" | tar -x -C "$staging"); then
            rm -rf -- "$staging"
            die 'Could not extract the GitHub release.'
        fi
        chmod 755 "$staging"
        mv -T "$staging" "$release"
    fi
    [ "$(cat "$release/VERSION")" = "${tag#v}" ] || die 'Published release tag does not match VERSION.'
}

prepare_release() {
    command -v node >/dev/null || die 'Node.js is required for UI checks. Run the GitHub installer to install server dependencies.'
    # Separate dependencies make rollback independent of the new requirements.
    if [ ! -f "$release/.venv/.dependencies-ready" ]; then
        python3 -m venv "$release/.venv"
        "$release/.venv/bin/python" -m pip -q install -r "$release/requirements.txt"
        touch "$release/.venv/.dependencies-ready"
    fi
    local sandbox result=0
    sandbox=$(mktemp -d)
    (
        set -e
        cd "$release"
        export DATABASE_PATH="$sandbox/game.sqlite3" BUILDER_DATA_DIR="$sandbox/builder"
        export GAME_PACKS_DIR="$sandbox/games" DEV_MODE=false BOT_TOKEN=''
        "$release/.venv/bin/python" -m pytest -q || exit $?
        node --test tests/ui_game.test.cjs tests/ui_builder.test.cjs || exit $?
    ) || result=$?
    rm -rf -- "$sandbox"
    [ "$result" = 0 ] || die 'Release checks failed; running services were not changed.'
}

wait_health() {
    local url=$1 expected=$2 payload attempt
    for attempt in {1..30}; do
        if payload=$(curl --connect-timeout 2 --max-time 5 -fsS "$url" 2>/dev/null) &&
            printf '%s' "$payload" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" and d.get("build")==sys.argv[1] else 1)' "$expected"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

wait_service() {
    local service=$1 attempt
    for ((attempt=0; attempt<10; attempt++)); do
        if systemctl is-active --quiet "$service"; then
            sleep 3
            systemctl is-active --quiet "$service" && return 0
        fi
        sleep 1
    done
    return 1
}

backup_database() {
    install -d -m 700 "$data/backups"
    python3 - "$data" <<'PY'
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
root = Path(sys.argv[1])
source = root / 'game.sqlite3'
if source.is_file():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    with sqlite3.connect(source) as src, sqlite3.connect(root / 'backups' / (stamp+'.sqlite3')) as dst:
        src.backup(dst)
PY
}

install_manager() {
    install -d -m 755 /usr/local/lib/rat-race
    install -m 755 "$release/deploy/manage.sh" /usr/local/sbin/rat-race
    install -m 644 "$release/deploy/common.sh" /usr/local/lib/rat-race/common.sh
}

# Save unit files too, so an existing installation can roll back during migration.
begin_switch() {
    switch_link=$1
    switch_env=$2
    shift 2
    switch_units=("$@")
    previous=''
    if [ -L "$base/$switch_link" ]; then previous=$(readlink -f "$base/$switch_link"); fi
    transaction=$(mktemp -d)
    for unit in "${switch_units[@]}"; do
        if [ -f "$units_dir/$unit" ]; then cp -p "$units_dir/$unit" "$transaction/$unit"; fi
        if systemctl is-active --quiet "$unit"; then touch "$transaction/$unit.active"; fi
        if systemctl is-enabled --quiet "$unit"; then touch "$transaction/$unit.enabled"; fi
    done
    if [ -f "$config/$switch_env" ]; then cp -p "$config/$switch_env" "$transaction/release.env"; fi
    if [ "$switch_link" = builder-current ] && [ -f "$config/builder.Caddyfile" ]; then
        cp -p "$config/builder.Caddyfile" "$transaction/builder.Caddyfile"
    fi
    trap rollback_switch ERR
}

rollback_switch() {
    local result=$?
    trap - ERR
    set +e
    echo 'Deployment failed; restoring previous release and service files.' >&2
    systemctl stop "${switch_units[@]}"
    if [ -n "$previous" ]; then
        ln -sfn "$previous" "$base/$switch_link-next"
        mv -Tf "$base/$switch_link-next" "$base/$switch_link"
    else
        rm -f -- "$base/$switch_link"
    fi
    for unit in "${switch_units[@]}"; do
        if [ -f "$transaction/$unit" ]; then
            cp -p "$transaction/$unit" "$units_dir/$unit"
        else
            systemctl disable "$unit"
            rm -f -- "$units_dir/$unit"
        fi
    done
    if [ -f "$transaction/release.env" ]; then
        cp -p "$transaction/release.env" "$config/$switch_env"
    else
        rm -f -- "$config/$switch_env"
    fi
    if [ "$switch_link" = builder-current ]; then
        if [ -f "$transaction/builder.Caddyfile" ]; then
            cp -p "$transaction/builder.Caddyfile" "$config/builder.Caddyfile"
        else
            rm -f -- "$config/builder.Caddyfile"
        fi
    fi
    systemctl daemon-reload
    for unit in "${switch_units[@]}"; do
        if [ -f "$transaction/$unit" ]; then
            if [ -f "$transaction/$unit.enabled" ]; then systemctl enable "$unit"; else systemctl disable "$unit"; fi
        fi
        if [ -f "$transaction/$unit.active" ]; then systemctl start "$unit"; fi
    done
    rm -rf -- "$transaction"
    echo 'Inspect journalctl for the failed service. Database backups are not restored automatically.' >&2
    exit "$result"
}

activate_release() {
    local unit
    for unit in "${switch_units[@]}"; do install -m 644 "$release/deploy/$unit" "$units_dir/$unit"; done
    printf 'BUILD_SHA=%s\n' "$revision" > "$config/$switch_env"
    chmod 600 "$config/$switch_env"
    ln -sfn "$release" "$base/$switch_link-next"
    mv -Tf "$base/$switch_link-next" "$base/$switch_link"
    systemctl daemon-reload
    systemctl enable "${switch_units[@]}"
}

finish_switch() { trap - ERR; rm -rf -- "$transaction"; }
