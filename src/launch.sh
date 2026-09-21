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
    command -v xdg-open >/dev/null 2>&1 || die "xdg-open is not available. Open $URL manually."
    xdg-open "$URL" >/dev/null 2>&1 &
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
        die "Global update helper is not installed. Run the shared install.sh first."
        ;;
    --foreground)
        run_foreground
        ;;
    *)
        cat >&2 <<USAGE
Usage: ./launch.sh [--open|--status|--update|--foreground]

  --open        Open the local DigiFlot UI (default)
  --status      Show server/watchdog status
  --update      Update /opt/digiflot-edge and restart the service
  --foreground  Debug only: run Uvicorn directly if systemd is stopped
USAGE
        exit 2
        ;;
esac
