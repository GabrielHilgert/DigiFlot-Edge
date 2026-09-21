#!/usr/bin/env bash

set -Eeuo pipefail

# DigiFlot Edge installer
# - clones/updates the repository
# - installs the Python environment
# - installs and enables a systemd service
# - installs a watchdog-style HTTP health check using a systemd timer
# - creates a global application launcher and Desktop shortcuts for local users
#
# Run as a normal user. sudo is used only for system-wide operations.

REPO_URL="${DIGIFLOT_REPO_URL:-https://github.com/GabrielHilgert/DigiFlot-Edge.git}"
REPO_NAME="${DIGIFLOT_REPO_NAME:-DigiFlot-Edge}"
BRANCH="${DIGIFLOT_BRANCH:-main}"
PORT="${DIGIFLOT_PORT:-8000}"
INSTALL_BASE="${DIGIFLOT_INSTALL_BASE:-$(pwd)}"

SERVICE_NAME="digiflot"
HEALTH_SERVICE_NAME="digiflot-healthcheck"
HEALTH_INTERVAL="${DIGIFLOT_HEALTH_INTERVAL:-30s}"
HEALTH_BOOT_DELAY="${DIGIFLOT_HEALTH_BOOT_DELAY:-90s}"
HEALTH_MAX_FAILURES="${DIGIFLOT_HEALTH_MAX_FAILURES:-2}"

APP_DIR="$INSTALL_BASE/$REPO_NAME"
SRC_DIR="$APP_DIR/src"
VENV_DIR="$SRC_DIR/.venv"
REQUIREMENTS="$SRC_DIR/requirements.txt"
LAUNCHER="$SRC_DIR/launch.sh"

GLOBAL_DATA_DIR="/usr/local/share/digiflot-edge"
GLOBAL_ICON=""
GLOBAL_OPEN_SCRIPT="/usr/local/bin/digiflot-edge-open"
GLOBAL_STATUS_SCRIPT="/usr/local/bin/digiflot-status"
GLOBAL_HEALTH_SCRIPT="/usr/local/bin/digiflot-healthcheck"
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

if [[ ${EUID} -eq 0 && -z "${SUDO_USER:-}" ]]; then
    die "Run this installer as a normal user, not directly as root."
fi

INSTALL_USER="${SUDO_USER:-$(id -un)}"
INSTALL_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
INSTALL_GROUP="$(id -gn "$INSTALL_USER")"
[[ -n "$INSTALL_HOME" ]] || die "Could not determine the home directory for $INSTALL_USER."

run_as_install_user() {
    if [[ $(id -un) == "$INSTALL_USER" ]]; then
        "$@"
    else
        sudo -u "$INSTALL_USER" -H "$@"
    fi
}

write_root_file_if_changed() {
    local source="$1"
    local destination="$2"
    local mode="${3:-0644}"
    if sudo test -f "$destination" && sudo cmp -s "$source" "$destination"; then
        log "Already up to date: $destination"
        return 1
    fi
    sudo install -D -m "$mode" "$source" "$destination"
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
printf '       DigiFlot Edge Installer\n'
printf '========================================\n\n'
log "Install user: $INSTALL_USER"
log "Installation directory: $APP_DIR"
log "HTTP endpoint: http://127.0.0.1:${PORT}"
printf '\n'

# -----------------------------------------------------------------------------
# System dependencies
# -----------------------------------------------------------------------------
log "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y \
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

# Give the service user access to the usual Raspberry Pi hardware groups.
for group in video i2c dialout; do
    if getent group "$group" >/dev/null 2>&1; then
        if id -nG "$INSTALL_USER" | tr ' ' '\n' | grep -qx "$group"; then
            log "User $INSTALL_USER already belongs to group '$group'."
        else
            sudo usermod -aG "$group" "$INSTALL_USER"
            log "Added $INSTALL_USER to group '$group'."
        fi
    fi
done

# -----------------------------------------------------------------------------
# Clone / update repository
# -----------------------------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]]; then
    log "Repository already exists. Checking for updates..."

    if run_as_install_user git -C "$APP_DIR" fetch origin "$BRANCH"; then
        LOCAL_COMMIT="$(run_as_install_user git -C "$APP_DIR" rev-parse HEAD)"
        REMOTE_COMMIT="$(run_as_install_user git -C "$APP_DIR" rev-parse "origin/$BRANCH")"
        log "Local commit : ${LOCAL_COMMIT:0:12}"
        log "Remote commit: ${REMOTE_COMMIT:0:12}"

        if [[ "$LOCAL_COMMIT" == "$REMOTE_COMMIT" ]]; then
            REPO_RESULT="up to date"
            log "Repository is up to date; no Git update required."
        else
            if [[ -n "$(run_as_install_user git -C "$APP_DIR" status --porcelain)" ]]; then
                die "Repository has local changes and the remote branch changed. Commit/stash them before updating."
            fi
            if ! run_as_install_user git -C "$APP_DIR" merge-base --is-ancestor "$LOCAL_COMMIT" "$REMOTE_COMMIT"; then
                die "Local and remote branches diverged. Automatic fast-forward update was refused."
            fi
            log "Repository update required. Applying fast-forward update..."
            run_as_install_user git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
            REPO_RESULT="updated"
            log "Repository updated successfully."
        fi
    else
        REPO_RESULT="not checked (offline/fetch failed)"
        warn "Could not contact Git remote. Continuing with the installed checkout."
    fi
else
    if [[ -e "$APP_DIR" ]]; then
        die "$APP_DIR already exists but is not a Git repository."
    fi
    log "Cloning repository..."
    run_as_install_user git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    REPO_RESULT="cloned"
    log "Repository cloned successfully."
fi

[[ -d "$SRC_DIR" ]] || die "Source directory not found: $SRC_DIR"
[[ -f "$REQUIREMENTS" ]] || die "requirements.txt not found: $REQUIREMENTS"

# -----------------------------------------------------------------------------
# Python virtual environment
# -----------------------------------------------------------------------------
if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment with Raspberry Pi system packages enabled..."
    run_as_install_user python3 -m venv --system-site-packages "$VENV_DIR"
    VENV_CREATED=1
else
    VENV_CREATED=0
    log "Virtual environment already exists."
fi

PYTHON="$VENV_DIR/bin/python"
[[ -x "$PYTHON" ]] || die "Virtual environment Python not found: $PYTHON"

if [[ $VENV_CREATED -eq 1 ]]; then
    log "Updating pip in the new virtual environment..."
    run_as_install_user "$PYTHON" -m pip install --upgrade pip
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
    run_as_install_user "$PYTHON" -m pip install -r "$REQUIREMENTS"
    printf '%s\n' "$REQ_HASH" | if [[ $(id -un) == "$INSTALL_USER" ]]; then cat > "$REQ_STAMP"; else sudo -u "$INSTALL_USER" tee "$REQ_STAMP" >/dev/null; fi
    REQUIREMENTS_RESULT="installed/updated"
fi

log "Python: $(run_as_install_user "$PYTHON" --version 2>&1)"

# Picamera2 is normally supplied by apt, hence --system-site-packages above.
if run_as_install_user "$PYTHON" -c 'import picamera2' >/dev/null 2>&1; then
    log "Picamera2 import: OK"
else
    warn "Picamera2 is not importable inside the venv. Cameras will not work until this is fixed."
    warn "If this venv predates this installer, recreate it with --system-site-packages."
fi

if [[ -f "$LAUNCHER" ]]; then
    chmod +x "$LAUNCHER" || true
fi

# -----------------------------------------------------------------------------
# Build system integration files in a temporary directory
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
User=$INSTALL_USER
Group=$INSTALL_GROUP
WorkingDirectory="$SRC_DIR"
Environment=HOME="$INSTALL_HOME"
Environment=PYTHONUNBUFFERED=1
ExecStart="$PYTHON" -m uvicorn app:app --host 0.0.0.0 --port $PORT --workers 1
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

# A stopped/crashed process should be started immediately.
if ! systemctl is-active --quiet "\$SERVICE"; then
    log "Service is not active. Starting it."
    rm -f "\$STATE_FILE"
    systemctl start "\$SERVICE"
    exit \$?
fi

# Any HTTP response means Uvicorn/FastAPI is alive. We intentionally do not
# use curl --fail because a 404/redirect still proves the HTTP server responds.
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
    log "HTTP check failed (\$failures/\$MAX_FAILURES). Waiting for next check before restarting."
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

# Give the boot service a few seconds to become ready if the user logs in fast.
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

# -----------------------------------------------------------------------------
# Icon
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
    sudo mkdir -p "$GLOBAL_DATA_DIR"
    if sudo test -f "$GLOBAL_ICON" && sudo cmp -s "$ICON_SOURCE" "$GLOBAL_ICON"; then
        log "Global icon is already up to date."
    else
        sudo install -m 0644 "$ICON_SOURCE" "$GLOBAL_ICON"
        log "Installed/updated global icon: $GLOBAL_ICON"
    fi
    DESKTOP_ICON="$GLOBAL_ICON"
else
    warn "No DigiFlot logo found under src/ui/img; using the system science icon."
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
# Install system files
# -----------------------------------------------------------------------------
SYSTEMD_CHANGED=0
write_root_file_if_changed "$TMP_DIR/${SERVICE_NAME}.service" "$SERVICE_FILE" 0644 && SYSTEMD_CHANGED=1 || true
write_root_file_if_changed "$TMP_DIR/digiflot-healthcheck" "$GLOBAL_HEALTH_SCRIPT" 0755 || true
write_root_file_if_changed "$TMP_DIR/${HEALTH_SERVICE_NAME}.service" "$HEALTH_SERVICE_FILE" 0644 && SYSTEMD_CHANGED=1 || true
write_root_file_if_changed "$TMP_DIR/${HEALTH_SERVICE_NAME}.timer" "$HEALTH_TIMER_FILE" 0644 && SYSTEMD_CHANGED=1 || true
write_root_file_if_changed "$TMP_DIR/digiflot-edge-open" "$GLOBAL_OPEN_SCRIPT" 0755 || true
write_root_file_if_changed "$TMP_DIR/digiflot-status" "$GLOBAL_STATUS_SCRIPT" 0755 || true
write_root_file_if_changed "$TMP_DIR/digiflot-edge.desktop" "$GLOBAL_DESKTOP" 0755 || true

if [[ $SYSTEMD_CHANGED -eq 1 ]]; then
    log "systemd configuration changed; reloading daemon."
else
    log "systemd configuration did not require changes."
fi
sudo systemctl daemon-reload

# -----------------------------------------------------------------------------
# Desktop shortcuts for existing and future local users
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
    local user_group
    local desktop_dir
    local desktop_file

    [[ -d "$user_home" ]] || return 0
    user_group="$(id -gn "$username")"
    desktop_dir="$(get_desktop_dir "$user_home")"
    desktop_file="$desktop_dir/DigiFlot Edge.desktop"

    sudo install -d -m 0755 -o "$username" -g "$user_group" "$desktop_dir"
    sudo install -m 0755 -o "$username" -g "$user_group" "$TMP_DIR/digiflot-edge.desktop" "$desktop_file"
    SHORTCUT_COUNT=$((SHORTCUT_COUNT + 1))
    log "Desktop shortcut installed for $username: $desktop_file"

    # Some desktop environments use this metadata bit. It can fail outside a
    # graphical session, so failure is intentionally ignored.
    if command -v gio >/dev/null 2>&1; then
        sudo -u "$username" gio set "$desktop_file" metadata::trusted true >/dev/null 2>&1 || true
    fi
}

while IFS=: read -r username _ uid _ _ user_home user_shell; do
    if (( uid >= 1000 && uid < 65534 )) && [[ "$user_home" == /home/* ]] && [[ "$user_shell" != */nologin ]] && [[ "$user_shell" != */false ]]; then
        install_user_shortcut "$username" "$user_home"
    fi
done < <(getent passwd)

sudo install -d -m 0755 /etc/skel/Desktop
sudo install -m 0755 "$TMP_DIR/digiflot-edge.desktop" "/etc/skel/Desktop/DigiFlot Edge.desktop"
log "Installed default Desktop shortcut for future users in /etc/skel/Desktop."

if command -v update-desktop-database >/dev/null 2>&1; then
    sudo update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi

# -----------------------------------------------------------------------------
# Enable and start service + health timer
# -----------------------------------------------------------------------------
log "Enabling DigiFlot at boot..."
sudo systemctl enable "$SERVICE_NAME.service" >/dev/null
sudo systemctl enable "$HEALTH_SERVICE_NAME.timer" >/dev/null

log "Starting/restarting DigiFlot service..."
if ! sudo systemctl restart "$SERVICE_NAME.service"; then
    warn "DigiFlot service could not start. Port $PORT may already be occupied."
    sudo systemctl --no-pager --full status "$SERVICE_NAME.service" || true
    if command -v ss >/dev/null 2>&1; then
        sudo ss -ltnp 2>/dev/null | grep -E ":${PORT}([[:space:]]|$)" || true
    fi
    exit 1
fi

sudo systemctl restart "$HEALTH_SERVICE_NAME.timer"

SERVICE_STATE="$(systemctl is-active "$SERVICE_NAME.service" 2>/dev/null || true)"
TIMER_STATE="$(systemctl is-active "$HEALTH_SERVICE_NAME.timer" 2>/dev/null || true)"

if wait_for_http 20; then
    HTTP_STATE="responding"
else
    HTTP_STATE="NOT RESPONDING"
    warn "Service is running but HTTP did not respond within 20 seconds. Check: journalctl -u $SERVICE_NAME -n 100"
fi

printf '\n========================================\n'
printf '   DigiFlot Edge Installation Complete\n'
printf '========================================\n\n'
printf '[DigiFlot] Repository:          %s\n' "$REPO_RESULT"
printf '[DigiFlot] Python requirements: %s\n' "$REQUIREMENTS_RESULT"
printf '[DigiFlot] Service:             %s\n' "$SERVICE_STATE"
printf '[DigiFlot] HTTP:                %s\n' "$HTTP_STATE"
printf '[DigiFlot] Health timer:        %s\n' "$TIMER_STATE"
printf '[DigiFlot] Desktop shortcuts:   %s existing user(s) + future users\n' "$SHORTCUT_COUNT"
printf '[DigiFlot] URL:                 http://127.0.0.1:%s/\n\n' "$PORT"
printf 'Useful commands:\n'
printf '  digiflot-status\n'
printf '  sudo systemctl status %s\n' "$SERVICE_NAME"
printf '  sudo systemctl restart %s\n' "$SERVICE_NAME"
printf '  journalctl -u %s -f\n' "$SERVICE_NAME"
printf '  systemctl list-timers %s.timer\n' "$HEALTH_SERVICE_NAME"
printf '\n'
