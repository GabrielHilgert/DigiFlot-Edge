#!/usr/bin/env bash

set -Eeuo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SRC_DIR/.venv"
SERVICE_NAME="digiflot.service"
PORT="${DIGIFLOT_PORT:-8000}"
URL="http://127.0.0.1:${PORT}/"

log() { printf '[DigiFlot] %s\n' "$*"; }
die() { printf '[DigiFlot] ERROR: %s\n' "$*" >&2; exit 1; }

open_ui() {
    if command -v digiflot-edge-open >/dev/null 2>&1; then
        digiflot-edge-open >/dev/null 2>&1 &
    elif [[ -f "$SRC_DIR/deploy/browser-open.sh" ]]; then
        bash "$SRC_DIR/deploy/browser-open.sh" >/dev/null 2>&1 &
    else
        command -v xdg-open >/dev/null 2>&1 || die "No supported browser launcher found. Open $URL manually."
        xdg-open "$URL" >/dev/null 2>&1 &
    fi
}

run_foreground() {
    [[ -x "$VENV_DIR/bin/python" ]] || die "Virtual environment not found: $VENV_DIR"
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        die "The systemd DigiFlot service is already running. Stop it first to avoid two servers on port $PORT."
    fi
    cd "$SRC_DIR"
    exec "$VENV_DIR/bin/python" -m uvicorn app:app --host 0.0.0.0 --port "$PORT" --workers 1
}

case "${1:-open}" in
    open|--open)
        if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
            log "DigiFlot service is running."
        else
            log "DigiFlot service is not active. Requesting start..."
            sudo systemctl start "$SERVICE_NAME"
        fi
        log "Opening $URL"
        open_ui
        ;;
    --status)
        if command -v digiflot-status >/dev/null 2>&1; then
            exec digiflot-status
        fi
        systemctl --no-pager --full status "$SERVICE_NAME"
        ;;
    --update)
        if [[ -x /usr/local/sbin/digiflot-update ]]; then
            exec sudo /usr/local/sbin/digiflot-update
        fi
        die "Global update helper is not installed. Migrate once with: sudo bash /opt/digiflot-edge/src/deploy/migrate.sh"
        ;;
    --restart)
        if command -v digiflot-restart >/dev/null 2>&1; then
            exec digiflot-restart
        fi
        die "Restart helper not installed. Migrate once with: sudo bash /opt/digiflot-edge/src/deploy/migrate.sh"
        ;;
    --foreground)
        run_foreground
        ;;
    *)
        cat >&2 <<USAGE
Usage: ./launch.sh [--open|--status|--update|--restart|--foreground]

  --open        Open the local DigiFlot UI (default)
  --status      Show server/watchdog status
  --update      Update Git, dependencies and installed services when needed
  --restart     Safely restart only the DigiFlot backend (browser stays open)
  --foreground  Debug only: run Uvicorn directly if systemd is stopped
USAGE
        exit 2
        ;;
esac
