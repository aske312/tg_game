#!/bin/bash
set -Eeuo pipefail
# shellcheck source=deploy/common.sh
source /usr/local/lib/rat-race/common.sh

usage() {
    cat <<'HELP'
Usage: sudo rat-race COMMAND [app|builder|all]
  update                  Fetch latest published release, test and deploy (default: all installed)
  start | stop | restart  Control services (default: all installed)
  status                  Show systemd status
  logs                    Last 100 journal entries (add --follow for live logs)
  health                  Check local/public HTTPS endpoints and running revisions
  version                 Show installed GitHub revisions
  help                    Show this help
Examples: rat-race update app; rat-race logs builder --follow
HELP
}

command=${1:-help}
target=${2:-all}
case "$command" in help|-h|--help) usage; exit 0;; esac
case "$command" in update|start|stop|restart|status|logs|health|version) ;; *) usage >&2; exit 2;; esac
case "$target" in app|builder|all) ;; *) usage >&2; exit 2;; esac
if [ "$#" -gt 2 ]; then
    [ "$command" = logs ] && [ "$#" = 3 ] && [ "$3" = --follow ] || { usage >&2; exit 2; }
fi
require_root
components=()
units=()
if [ "$target" != builder ] && [ -L "$base/current" ]; then
    components+=(app)
    units+=(rat-race-web.service rat-race-bot.service)
fi
if [ "$target" != app ] && [ -L "$base/builder-current" ]; then
    components+=(builder)
    units+=(rat-race-builder.service rat-race-builder-proxy.service)
fi
[ "${#components[@]}" -gt 0 ] || die "No installed services for target: $target"

case "$command" in
    update)
        # Use one pinned SHA even if main changes between the two deployments.
        lock_deploy
        fetch_release
        snapshot=$release
        for component in "${components[@]}"; do
            script=update.sh
            [ "$component" != builder ] || script=update_builder.sh
            bash "$snapshot/deploy/$script" --release "$snapshot"
        done
        ;;
    start|stop|restart)
        lock_deploy
        if [ "$command" = stop ]; then
            for ((index=${#units[@]}-1; index>=0; index--)); do systemctl stop "${units[index]}"; done
        else
            for unit in "${units[@]}"; do systemctl "$command" "$unit"; done
            "$0" health "$target"
        fi
        ;;
    status) systemctl --no-pager --full status "${units[@]}";;
    logs)
        args=(--no-pager -n 100)
        [ "${3:-}" != --follow ] || args+=(--follow)
        for unit in "${units[@]}"; do args+=(-u "$unit"); done
        journalctl "${args[@]}"
        ;;
    version)
        for component in "${components[@]}"; do
            link=current
            [ "$component" != builder ] || link=builder-current
            printf '%s: %s build %s\n' "$component" "$(cat "$base/$link/VERSION")" "$(basename "$(readlink -f "$base/$link")")"
        done
        ;;
    health)
        for unit in "${units[@]}"; do systemctl is-active --quiet "$unit" || die "Inactive: $unit"; done
        for component in "${components[@]}"; do
            if [ "$component" = app ]; then
                link=current; url=http://127.0.0.1:8010; envfile=app.env; urlkey=APP_URL
            else
                link=builder-current; url=http://127.0.0.1:8011; envfile=builder.env; urlkey=BUILDER_SITE
            fi
            expected=$(basename "$(readlink -f "$base/$link")")
            wait_health "$url/api/health" "$expected" || die "Health/version check failed: $component"
            public=$("$base/$link/.venv/bin/python" "$base/$link/deploy/configure.py" get "$config/$envfile" "$urlkey")
            wait_health "$public/api/health" "$expected" || die "HTTPS/version check failed: $component"
            echo "$component: OK ($expected)"
        done
        ;;
esac
