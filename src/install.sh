#!/usr/bin/env bash

set -Eeuo pipefail

# DigiFlot Edge shared/system installer
#
# Canonical layout:
#   repository:   /opt/digiflot-edge
#   systemd:      digiflot.service
#   shared UI:    http://127.0.0.1:8000
#
# The installer NEVER uses the directory from which it is executed as the
# application directory. This prevents nested clones under /home/.../src and
# gives every local Linux user the same DigiFlot installation.

REPO_URL="${DIGIFLOT_REPO_URL:-https://github.com/GabrielHilgert/DigiFlot-Edge.git}"
BRANCH="${DIGIFLOT_BRANCH:-main}"
PORT="${DIGIFLOT_PORT:-8000}"

# Intentionally fixed shared installation path.
APP_DIR="/opt/digiflot-edge"
SRC_DIR="$APP_DIR/src"
VENV_DIR="$SRC_DIR/.venv"
REQUIREMENTS="$SRC_DIR/requirements.txt"

SERVICE_NAME="digiflot"
HEALTH_SERVICE_NAME="digiflot-healthcheck"
SERVICE_USER="${DIGIFLOT_SERVICE_USER:-digiflot}"
DEFAULT_SERVICE_HOME="/var/lib/digiflot-edge"
HEALTH_INTERVAL="${DIGIFLOT_HEALTH_INTERVAL:-30s}"
HEALTH_BOOT_DELAY="${DIGIFLOT_HEALTH_BOOT_DELAY:-90s}"
HEALTH_MAX_FAILURES="${DIGIFLOT_HEALTH_MAX_FAILURES:-2}"

GLOBAL_DATA_DIR="/usr/local/share/digiflot-edge"
GLOBAL_OPEN_SCRIPT="/usr/local/bin/digiflot-edge-open"
GLOBAL_STATUS_SCRIPT="/usr/local/bin/digiflot-status"
GLOBAL_HEALTH_SCRIPT="/usr/local/bin/digiflot-healthcheck"
GLOBAL_UPDATE_SCRIPT="/usr/local/sbin/digiflot-update"
GLOBAL_DESKTOP="/usr/share/applications/digiflot-edge.desktop"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
HEALTH_SERVICE_FILE="/etc/systemd/system/${HEALTH_SERVICE_NAME}.service"
HEALTH_TIMER_FILE="/etc/systemd/system/${HEALTH_SERVICE_NAME}.timer"

TMP_DIR=""
REPO_RESULT="unknown"
REQUIREMENTS_RESULT="unknown"
SHORTCUT_COUNT=0

log()  { printf '[DigiFlot] %s\n' "$*"; }
warn() { printf '[DigiFlot] WARNING: %s\n' "$*" >&2; }
die()  { printf '[DigiFlot] ERROR: %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT
trap 'printf "[DigiFlot] ERROR: installation failed at line %s.\n" "$LINENO" >&2' ERR

# Cache sudo credentials early when run as a regular user.
if (( EUID != 0 )); then
    sudo -v
fi

as_root() {
    if (( EUID == 0 )); then
        "$@"
    else
        sudo "$@"
    fi
}

run_as_service() {
    if [[ "$(id -un)" == "$SERVICE_USER" ]]; then
        HOME="$SERVICE_HOME" "$@"
    else
        sudo -u "$SERVICE_USER" -H env HOME="$SERVICE_HOME" "$@"
    fi
}

write_root_file_if_changed() {
    local source="$1"
    local destination="$2"
    local mode="${3:-0644}"

    if as_root test -f "$destination" && as_root cmp -s "$source" "$destination"; then
        log "Already up to date: $destination"
        return 1
    fi
    as_root install -D -m "$mode" "$source" "$destination"
    log "Installed/updated: $destination"
    return 0
}

wait_for_http() {
    local attempts="${1:-20}"
    local i
    for ((i=1; i<=attempts; i++)); do
        if curl --silent --show-error --max-time 2 --output /dev/null "http://127.0.0.1:${PORT}/" 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    return 1
}

printf '\n========================================\n'
printf '    DigiFlot Edge Shared Installer\n'
printf '========================================\n\n'
log "Shared installation directory: $APP_DIR"
log "Source directory:              $SRC_DIR"
log "Service account:               $SERVICE_USER"
log "Local URL:                     http://127.0.0.1:${PORT}/"
printf '\n'

# -----------------------------------------------------------------------------
# System dependencies
# -----------------------------------------------------------------------------
log "Installing system dependencies..."
as_root apt-get update
as_root apt-get install -y \
    git \
    curl \
    ffmpeg \
    i2c-tools \
    desktop-file-utils \
    python3 \
    python3-venv \
    python3-pip \
    python3-picamera2 \
    python3-libcamera \
    libcamera-tools

# -----------------------------------------------------------------------------
# Service account
# -----------------------------------------------------------------------------
if id "$SERVICE_USER" >/dev/null 2>&1; then
    SERVICE_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
    [[ -n "$SERVICE_HOME" ]] || die "Could not determine home directory for existing service user $SERVICE_USER."
    log "Using existing service account: $SERVICE_USER ($SERVICE_HOME)"
else
    log "Creating dedicated DigiFlot service account: $SERVICE_USER"
    as_root useradd \
        --system \
        --user-group \
        --create-home \
        --home-dir "$DEFAULT_SERVICE_HOME" \
        --shell /usr/sbin/nologin \
        "$SERVICE_USER"
    SERVICE_HOME="$DEFAULT_SERVICE_HOME"
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
fi

as_root install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$SERVICE_HOME"

# Hardware access for the process that owns cameras, I2C and serial ports.
for group in video i2c dialout; do
    if getent group "$group" >/dev/null 2>&1; then
        if id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -qx "$group"; then
            log "Service user already belongs to '$group'."
        else
            as_root usermod -aG "$group" "$SERVICE_USER"
            log "Added service user to '$group'."
        fi
    fi
done

# -----------------------------------------------------------------------------
# Shared repository under /opt
# -----------------------------------------------------------------------------
as_root install -d -m 0755 /opt

if [[ -e "$APP_DIR" && ! -d "$APP_DIR" ]]; then
    die "$APP_DIR exists and is not a directory."
fi

if [[ -d "$APP_DIR/.git" ]]; then
    # Older installs may have been created by root/a different user. Normalize
    # ownership before using git as the service account.
    as_root chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR"

    log "Shared repository already exists. Checking for updates..."
    if run_as_service git -C "$APP_DIR" fetch origin "$BRANCH"; then
        LOCAL_COMMIT="$(run_as_service git -C "$APP_DIR" rev-parse HEAD)"
        REMOTE_COMMIT="$(run_as_service git -C "$APP_DIR" rev-parse "origin/$BRANCH")"
        log "Local commit : ${LOCAL_COMMIT:0:12}"
        log "Remote commit: ${REMOTE_COMMIT:0:12}"

        if [[ "$LOCAL_COMMIT" == "$REMOTE_COMMIT" ]]; then
            REPO_RESULT="up to date"
            log "Repository is up to date; no Git update required."
        else
            if [[ -n "$(run_as_service git -C "$APP_DIR" status --porcelain)" ]]; then
                die "The shared repository has local changes and cannot be updated safely. Commit/stash them first."
            fi
            if ! run_as_service git -C "$APP_DIR" merge-base --is-ancestor "$LOCAL_COMMIT" "$REMOTE_COMMIT"; then
                die "Local and remote branches diverged. Automatic non-fast-forward update refused."
            fi
            log "Repository update required. Applying fast-forward update..."
            run_as_service git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
            REPO_RESULT="updated"
            log "Repository updated successfully."
        fi
    else
        REPO_RESULT="not checked (offline/fetch failed)"
        warn "Could not contact Git remote. Continuing with the installed checkout."
    fi
elif [[ -d "$APP_DIR" ]] && [[ -n "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
    die "$APP_DIR already exists and is not an empty Git repository directory. Move/remove it before installing."
else
    log "Cloning repository into shared location $APP_DIR ..."
    as_root install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$APP_DIR"
    run_as_service git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    REPO_RESULT="cloned"
    log "Repository cloned successfully."
fi

# Keep ownership deterministic after git operations.
as_root chown -R "$SERVICE_USER:$SERVICE_GROUP" "$APP_DIR"

[[ -d "$SRC_DIR" ]] || die "Source directory not found: $SRC_DIR"
[[ -f "$REQUIREMENTS" ]] || die "requirements.txt not found: $REQUIREMENTS"

# -----------------------------------------------------------------------------
# Python virtual environment
# -----------------------------------------------------------------------------
if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment with Raspberry Pi system packages enabled..."
    run_as_service python3 -m venv --system-site-packages "$VENV_DIR"
    VENV_CREATED=1
else
    VENV_CREATED=0
    log "Virtual environment already exists."
fi

PYTHON="$VENV_DIR/bin/python"
[[ -x "$PYTHON" ]] || die "Virtual environment Python not found: $PYTHON"

if [[ $VENV_CREATED -eq 1 ]]; then
    log "Updating pip in the new virtual environment..."
    run_as_service "$PYTHON" -m pip install --upgrade pip
fi

REQ_HASH="$(sha256sum "$REQUIREMENTS" | awk '{print $1}')"
REQ_STAMP="$VENV_DIR/.digiflot_requirements.sha256"
OLD_REQ_HASH=""
[[ -f "$REQ_STAMP" ]] && OLD_REQ_HASH="$(cat "$REQ_STAMP" 2>/dev/null || true)"

if [[ "$REQ_HASH" == "$OLD_REQ_HASH" ]]; then
    REQUIREMENTS_RESULT="up to date"
    log "Python requirements are unchanged; pip install not required."
else
    log "Python requirements changed or have not been installed yet. Installing..."
    run_as_service "$PYTHON" -m pip install -r "$REQUIREMENTS"
    printf '%s\n' "$REQ_HASH" | as_root tee "$REQ_STAMP" >/dev/null
    as_root chown "$SERVICE_USER:$SERVICE_GROUP" "$REQ_STAMP"
    REQUIREMENTS_RESULT="installed/updated"
fi

log "Python: $(run_as_service "$PYTHON" --version 2>&1)"
if run_as_service "$PYTHON" -c 'import picamera2' >/dev/null 2>&1; then
    log "Picamera2 import: OK"
else
    warn "Picamera2 is not importable inside the venv. Cameras will not work until this is fixed."
fi

if [[ -f "$SRC_DIR/launch.sh" ]]; then
    as_root chmod +x "$SRC_DIR/launch.sh" || true
fi

# -----------------------------------------------------------------------------
# Generate system integration files
# -----------------------------------------------------------------------------
TMP_DIR="$(mktemp -d)"

cat > "$TMP_DIR/${SERVICE_NAME}.service" <<EOF_SERVICE
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
ExecStart=$PYTHON -m uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGTERM
UMask=0022

[Install]
WantedBy=multi-user.target
EOF_SERVICE

cat > "$TMP_DIR/digiflot-healthcheck" <<EOF_HEALTH
#!/usr/bin/env bash
set -uo pipefail
SERVICE="${SERVICE_NAME}.service"
URL="http://127.0.0.1:${PORT}/"
STATE_FILE="/run/digiflot-healthcheck.failures"
MAX_FAILURES="${HEALTH_MAX_FAILURES}"

log() {
    logger -t digiflot-healthcheck -- "\$*"
    printf '[DigiFlot health] %s\\n' "\$*"
}

if ! systemctl is-active --quiet "\$SERVICE"; then
    log "Service is not active. Starting it."
    rm -f "\$STATE_FILE"
    systemctl start "\$SERVICE"
    exit \$?
fi

# Any HTTP response proves the FastAPI/Uvicorn process is responsive.
if curl --silent --show-error --max-time 3 --output /dev/null "\$URL"; then
    if [[ -f "\$STATE_FILE" ]]; then
        rm -f "\$STATE_FILE"
        log "HTTP response recovered; failure counter reset."
    fi
    exit 0
fi

failures=0
if [[ -f "\$STATE_FILE" ]]; then
    read -r failures < "\$STATE_FILE" || failures=0
fi
[[ "\$failures" =~ ^[0-9]+$ ]] || failures=0
failures=\$((failures + 1))
printf '%s\\n' "\$failures" > "\$STATE_FILE"

if (( failures >= MAX_FAILURES )); then
    log "HTTP server failed \$failures consecutive checks. Restarting DigiFlot."
    rm -f "\$STATE_FILE"
    systemctl restart "\$SERVICE"
else
    log "HTTP check failed (\$failures/\$MAX_FAILURES). Waiting for next check."
fi
EOF_HEALTH

cat > "$TMP_DIR/${HEALTH_SERVICE_NAME}.service" <<EOF_HEALTH_SERVICE
[Unit]
Description=Check DigiFlot Edge HTTP responsiveness
After=${SERVICE_NAME}.service

[Service]
Type=oneshot
ExecStart=$GLOBAL_HEALTH_SCRIPT
EOF_HEALTH_SERVICE

cat > "$TMP_DIR/${HEALTH_SERVICE_NAME}.timer" <<EOF_HEALTH_TIMER
[Unit]
Description=Periodically verify DigiFlot Edge is responsive

[Timer]
OnBootSec=$HEALTH_BOOT_DELAY
OnUnitActiveSec=$HEALTH_INTERVAL
AccuracySec=5s
Persistent=true
Unit=${HEALTH_SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF_HEALTH_TIMER

cat > "$TMP_DIR/digiflot-edge-open" <<EOF_OPEN
#!/usr/bin/env bash
set -u
URL="http://127.0.0.1:${PORT}/"

# The system service normally starts at boot. Wait briefly in case the desktop
# session comes up faster than the server.
for _ in {1..15}; do
    if curl --silent --max-time 1 --output /dev/null "\$URL" 2>/dev/null; then
        break
    fi
    sleep 1
done
exec xdg-open "\$URL"
EOF_OPEN

cat > "$TMP_DIR/digiflot-status" <<EOF_STATUS
#!/usr/bin/env bash
set -u
URL="http://127.0.0.1:${PORT}/"

echo "DigiFlot Edge"
echo "-------------"
echo "Install:      $APP_DIR"
printf 'Service:      '
if systemctl is-active --quiet ${SERVICE_NAME}.service; then echo active; else systemctl is-active ${SERVICE_NAME}.service 2>/dev/null || true; fi
printf 'Boot enabled: '
if systemctl is-enabled --quiet ${SERVICE_NAME}.service; then echo yes; else echo no; fi
printf 'Health timer: '
if systemctl is-active --quiet ${HEALTH_SERVICE_NAME}.timer; then echo active; else systemctl is-active ${HEALTH_SERVICE_NAME}.timer 2>/dev/null || true; fi
printf 'HTTP:         '
if curl --silent --max-time 3 --output /dev/null "\$URL" 2>/dev/null; then echo responding; else echo NOT RESPONDING; fi
echo "URL:          \$URL"
EOF_STATUS

cat > "$TMP_DIR/digiflot-update" <<EOF_UPDATE
#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="$APP_DIR"
SRC_DIR="$SRC_DIR"
VENV_DIR="$VENV_DIR"
REQUIREMENTS="$REQUIREMENTS"
SERVICE_USER="$SERVICE_USER"
SERVICE_HOME="$SERVICE_HOME"
BRANCH="$BRANCH"

as_service() {
    sudo -u "\$SERVICE_USER" -H env HOME="\$SERVICE_HOME" "\$@"
}

[[ "\${EUID}" -eq 0 ]] || { echo '[DigiFlot] Run as root: sudo digiflot-update' >&2; exit 1; }
[[ -d "\$APP_DIR/.git" ]] || { echo '[DigiFlot] Shared repository is missing.' >&2; exit 1; }

printf '[DigiFlot] Checking shared repository for updates...\\n'
as_service git -C "\$APP_DIR" fetch origin "\$BRANCH"
local_commit="\$(as_service git -C "\$APP_DIR" rev-parse HEAD)"
remote_commit="\$(as_service git -C "\$APP_DIR" rev-parse "origin/\$BRANCH")"
printf '[DigiFlot] Local : %s\\n' "\${local_commit:0:12}"
printf '[DigiFlot] Remote: %s\\n' "\${remote_commit:0:12}"

if [[ "\$local_commit" == "\$remote_commit" ]]; then
    echo '[DigiFlot] Already up to date; no restart required.'
    exit 0
fi

[[ -z "\$(as_service git -C "\$APP_DIR" status --porcelain)" ]] || {
    echo '[DigiFlot] Local changes detected; refusing automatic update.' >&2
    exit 1
}
as_service git -C "\$APP_DIR" merge-base --is-ancestor "\$local_commit" "\$remote_commit" || {
    echo '[DigiFlot] Branch diverged; refusing automatic update.' >&2
    exit 1
}

as_service git -C "\$APP_DIR" pull --ff-only origin "\$BRANCH"
as_service "\$VENV_DIR/bin/python" -m pip install -r "\$REQUIREMENTS"
sha256sum "\$REQUIREMENTS" | awk '{print \$1}' > "\$VENV_DIR/.digiflot_requirements.sha256"
chown "\$SERVICE_USER:$(id -gn "$SERVICE_USER")" "\$VENV_DIR/.digiflot_requirements.sha256"
systemctl restart ${SERVICE_NAME}.service
echo '[DigiFlot] Update installed and service restarted.'
EOF_UPDATE

# -----------------------------------------------------------------------------
# Shared icon and desktop launcher
# -----------------------------------------------------------------------------
ICON_SOURCE=""
for candidate in \
    "$SRC_DIR/ui/img/DigiFlotEdge.png" \
    "$SRC_DIR/ui/img/squarelogo.png" \
    "$SRC_DIR/ui/img/squarelogo.ico"; do
    if [[ -f "$candidate" ]]; then
        ICON_SOURCE="$candidate"
        break
    fi
done

if [[ -n "$ICON_SOURCE" ]]; then
    ICON_EXT="${ICON_SOURCE##*.}"
    GLOBAL_ICON="$GLOBAL_DATA_DIR/digiflot-edge.${ICON_EXT}"
    as_root mkdir -p "$GLOBAL_DATA_DIR"
    if as_root test -f "$GLOBAL_ICON" && as_root cmp -s "$ICON_SOURCE" "$GLOBAL_ICON"; then
        log "Global icon is already up to date."
    else
        as_root install -m 0644 "$ICON_SOURCE" "$GLOBAL_ICON"
        log "Installed/updated global icon: $GLOBAL_ICON"
    fi
    DESKTOP_ICON="$GLOBAL_ICON"
else
    warn "No DigiFlot logo found under src/ui/img; using system science icon."
    DESKTOP_ICON="applications-science"
fi

cat > "$TMP_DIR/digiflot-edge.desktop" <<EOF_DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=DigiFlot Edge
Comment=Open DigiFlot Edge
Exec=$GLOBAL_OPEN_SCRIPT
Icon=$DESKTOP_ICON
Terminal=false
Categories=Science;Education;
StartupNotify=true
EOF_DESKTOP

# -----------------------------------------------------------------------------
# Validate and install system files
# -----------------------------------------------------------------------------
log "Validating generated systemd units..."
VERIFY_OUTPUT="$(systemd-analyze verify \
    "$TMP_DIR/${SERVICE_NAME}.service" \
    "$TMP_DIR/${HEALTH_SERVICE_NAME}.service" \
    "$TMP_DIR/${HEALTH_SERVICE_NAME}.timer" 2>&1)" || {
    printf '%s\n' "$VERIFY_OUTPUT" >&2
    die "Generated systemd configuration is invalid; nothing was installed."
}
log "systemd unit validation: OK"

SYSTEMD_CHANGED=0
write_root_file_if_changed "$TMP_DIR/${SERVICE_NAME}.service" "$SERVICE_FILE" 0644 && SYSTEMD_CHANGED=1 || true
write_root_file_if_changed "$TMP_DIR/digiflot-healthcheck" "$GLOBAL_HEALTH_SCRIPT" 0755 || true
write_root_file_if_changed "$TMP_DIR/${HEALTH_SERVICE_NAME}.service" "$HEALTH_SERVICE_FILE" 0644 && SYSTEMD_CHANGED=1 || true
write_root_file_if_changed "$TMP_DIR/${HEALTH_SERVICE_NAME}.timer" "$HEALTH_TIMER_FILE" 0644 && SYSTEMD_CHANGED=1 || true
write_root_file_if_changed "$TMP_DIR/digiflot-edge-open" "$GLOBAL_OPEN_SCRIPT" 0755 || true
write_root_file_if_changed "$TMP_DIR/digiflot-status" "$GLOBAL_STATUS_SCRIPT" 0755 || true
write_root_file_if_changed "$TMP_DIR/digiflot-update" "$GLOBAL_UPDATE_SCRIPT" 0755 || true
write_root_file_if_changed "$TMP_DIR/digiflot-edge.desktop" "$GLOBAL_DESKTOP" 0755 || true

if [[ $SYSTEMD_CHANGED -eq 1 ]]; then
    log "systemd configuration changed; reloading daemon."
else
    log "systemd configuration did not require changes."
fi
as_root systemctl daemon-reload

# -----------------------------------------------------------------------------
# Desktop shortcuts for every existing interactive user + /etc/skel
# -----------------------------------------------------------------------------
get_desktop_dir() {
    local user_home="$1"
    local cfg="$user_home/.config/user-dirs.dirs"
    local raw=""

    if [[ -r "$cfg" ]]; then
        raw="$(sed -n 's/^XDG_DESKTOP_DIR="\([^"]*\)"/\1/p' "$cfg" | head -n1)"
    fi
    if [[ -n "$raw" ]]; then
        raw="${raw//\$HOME/$user_home}"
        case "$raw" in
            "$user_home"/*) printf '%s\n' "$raw"; return 0 ;;
        esac
    fi
    for candidate in "$user_home/Desktop" "$user_home/Schreibtisch" "$user_home/Área de Trabalho"; do
        if [[ -d "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    printf '%s\n' "$user_home/Desktop"
}

install_user_shortcut() {
    local username="$1"
    local user_home="$2"
    local user_group desktop_dir desktop_file

    [[ -d "$user_home" ]] || return 0
    user_group="$(id -gn "$username")"
    desktop_dir="$(get_desktop_dir "$user_home")"
    desktop_file="$desktop_dir/DigiFlot Edge.desktop"

    as_root install -d -m 0755 -o "$username" -g "$user_group" "$desktop_dir"
    as_root install -m 0755 -o "$username" -g "$user_group" "$TMP_DIR/digiflot-edge.desktop" "$desktop_file"
    SHORTCUT_COUNT=$((SHORTCUT_COUNT + 1))
    log "Desktop shortcut installed for $username: $desktop_file"

    if command -v gio >/dev/null 2>&1; then
        sudo -u "$username" gio set "$desktop_file" metadata::trusted true >/dev/null 2>&1 || true
    fi
}

while IFS=: read -r username _ uid _ _ user_home user_shell; do
    if (( uid >= 1000 && uid < 65534 )) \
       && [[ "$user_home" == /home/* ]] \
       && [[ "$user_shell" != */nologin ]] \
       && [[ "$user_shell" != */false ]]; then
        install_user_shortcut "$username" "$user_home"
    fi
done < <(getent passwd)

as_root install -d -m 0755 /etc/skel/Desktop
as_root install -m 0755 "$TMP_DIR/digiflot-edge.desktop" "/etc/skel/Desktop/DigiFlot Edge.desktop"
log "Installed default Desktop shortcut for future users."

if command -v update-desktop-database >/dev/null 2>&1; then
    as_root update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

# -----------------------------------------------------------------------------
# Enable/start server and watchdog
# -----------------------------------------------------------------------------
log "Service WorkingDirectory: $SRC_DIR"
log "Service Python:           $PYTHON"
log "Enabling DigiFlot at boot..."
as_root systemctl enable "$SERVICE_NAME.service" >/dev/null
as_root systemctl enable "$HEALTH_SERVICE_NAME.timer" >/dev/null

log "Starting/restarting DigiFlot service..."
if ! as_root systemctl restart "$SERVICE_NAME.service"; then
    warn "DigiFlot service could not start. Showing status and recent logs."
    as_root systemctl --no-pager --full status "$SERVICE_NAME.service" || true
    as_root journalctl -u "$SERVICE_NAME.service" -n 50 --no-pager || true
    exit 1
fi
as_root systemctl restart "$HEALTH_SERVICE_NAME.timer"

SERVICE_STATE="$(systemctl is-active "$SERVICE_NAME.service" 2>/dev/null || true)"
TIMER_STATE="$(systemctl is-active "$HEALTH_SERVICE_NAME.timer" 2>/dev/null || true)"
if wait_for_http 20; then
    HTTP_STATE="responding"
else
    HTTP_STATE="NOT RESPONDING"
    warn "Service is running but HTTP did not respond within 20 seconds."
fi

printf '\n========================================\n'
printf '   DigiFlot Edge Installation Complete\n'
printf '========================================\n\n'
printf '[DigiFlot] Shared repository:    %s\n' "$APP_DIR"
printf '[DigiFlot] Repository status:    %s\n' "$REPO_RESULT"
printf '[DigiFlot] Python requirements:  %s\n' "$REQUIREMENTS_RESULT"
printf '[DigiFlot] Service account:       %s\n' "$SERVICE_USER"
printf '[DigiFlot] Service:               %s\n' "$SERVICE_STATE"
printf '[DigiFlot] HTTP:                  %s\n' "$HTTP_STATE"
printf '[DigiFlot] Health timer:          %s\n' "$TIMER_STATE"
printf '[DigiFlot] Desktop shortcuts:     %s existing user(s) + future users\n' "$SHORTCUT_COUNT"
printf '[DigiFlot] URL:                   http://127.0.0.1:%s/\n\n' "$PORT"
printf 'Useful commands:\n'
printf '  digiflot-status\n'
printf '  sudo digiflot-update\n'
printf '  sudo systemctl restart %s\n' "$SERVICE_NAME"
printf '  journalctl -u %s -f\n' "$SERVICE_NAME"
printf '\n'
