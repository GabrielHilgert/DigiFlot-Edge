#!/usr/bin/env bash

set -Eeuo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SRC_DIR/.." && pwd)"
VENV_DIR="$SRC_DIR/.venv"
SERVICE_NAME="digiflot.service"
BRANCH="${DIGIFLOT_BRANCH:-main}"
PORT="${DIGIFLOT_PORT:-8000}"
URL="http://127.0.0.1:${PORT}/"

log() { printf '[DigiFlot] %s\n' "$*"; }
die() { printf '[DigiFlot] ERROR: %s\n' "$*" >&2; exit 1; }

open_ui() {
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 &
    fi
}

run_foreground() {
    [[ -x "$VENV_DIR/bin/python" ]] || die "Virtual environment not found: $VENV_DIR"
    cd "$SRC_DIR"
    exec "$VENV_DIR/bin/python" -m uvicorn app:app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --workers 1
}

update_repo() {
    cd "$APP_DIR"
    log "Checking repository updates..."

    if ! git fetch origin "$BRANCH"; then
        die "Could not contact Git remote."
    fi

    local_commit="$(git rev-parse HEAD)"
    remote_commit="$(git rev-parse "origin/$BRANCH")"

    log "Local commit : ${local_commit:0:12}"
    log "Remote commit: ${remote_commit:0:12}"

    if [[ "$local_commit" == "$remote_commit" ]]; then
        log "Repository is already up to date; no update required."
        return 0
    fi

    [[ -z "$(git status --porcelain)" ]] || die "Working tree has local changes. Commit/stash them first."
    git merge-base --is-ancestor "$local_commit" "$remote_commit" || die "Branch diverged; refusing a non-fast-forward update."

    git pull --ff-only origin "$BRANCH"
    log "Repository updated successfully."

    if [[ -x "$VENV_DIR/bin/python" && -f "$SRC_DIR/requirements.txt" ]]; then
        log "Refreshing Python requirements..."
        "$VENV_DIR/bin/python" -m pip install -r "$SRC_DIR/requirements.txt"
    fi
}

case "${1:-open}" in
    open|--open)
        if systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
            if ! systemctl is-active --quiet "$SERVICE_NAME"; then
                log "DigiFlot service is installed but not running."
                log "Starting it requires system privileges..."
                sudo systemctl start "$SERVICE_NAME"
            else
                log "DigiFlot service is already running."
            fi
            log "Opening $URL"
            open_ui
        else
            log "systemd service is not installed; starting DigiFlot in the foreground."
            run_foreground
        fi
        ;;

    --foreground)
        if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
            die "The systemd DigiFlot service is already running. Stop it first to avoid two servers on port $PORT."
        fi
        run_foreground
        ;;

    --status)
        if command -v digiflot-status >/dev/null 2>&1; then
            exec digiflot-status
        fi
        systemctl --no-pager --full status "$SERVICE_NAME"
        ;;

    --update)
        update_repo
        if systemctl cat "$SERVICE_NAME" >/dev/null 2>&1; then
            log "Restarting systemd service to load the updated code..."
            sudo systemctl restart "$SERVICE_NAME"
            log "Update complete."
        else
            log "Update complete. systemd service is not installed."
        fi
        ;;

    *)
        cat >&2 <<USAGE
Usage: ./launch.sh [--open|--foreground|--status|--update]

  --open        Open DigiFlot; start the systemd service if necessary (default)
  --foreground  Run Uvicorn directly in this terminal
  --status      Show DigiFlot service/HTTP status
  --update      Fast-forward Git, refresh requirements, restart the service
USAGE
        exit 2
        ;;
esac
