#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/opt/digiflot-edge"
SRC_DIR="$APP_DIR/src"
PORT="${DIGIFLOT_PORT:-8000}"
SERVICE_USER="${DIGIFLOT_SERVICE_USER:-digiflot}"

log() { printf '[DigiFlot repair] %s\n' "$*"; }
die() { printf '[DigiFlot repair] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -f "$SRC_DIR/app.py" ]] || die "$SRC_DIR/app.py does not exist. Run install.sh first to create the shared installation."
[[ -x "$SRC_DIR/.venv/bin/python" ]] || die "Shared virtual environment does not exist. Run install.sh first."
id "$SERVICE_USER" >/dev/null 2>&1 || die "Service user '$SERVICE_USER' does not exist. Run install.sh first."

SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

cat > "$TMP" <<EOF_UNIT
[Unit]
Description=DigiFlot Edge server
After=network.target local-fs.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$SRC_DIR
Environment=HOME=$SERVICE_HOME
Environment=PYTHONUNBUFFERED=1
ExecStart=$SRC_DIR/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGTERM
UMask=0022

[Install]
WantedBy=multi-user.target
EOF_UNIT

log "Canonical repository: $APP_DIR"
log "WorkingDirectory:     $SRC_DIR"
log "Service user:         $SERVICE_USER"
log "Validating unit..."
systemd-analyze verify "$TMP"
log "Validation OK. Installing service..."
sudo install -m 0644 "$TMP" /etc/systemd/system/digiflot.service
sudo systemctl daemon-reload
sudo systemctl enable digiflot.service >/dev/null
sudo systemctl restart digiflot.service
systemctl --no-pager --full status digiflot.service || true
