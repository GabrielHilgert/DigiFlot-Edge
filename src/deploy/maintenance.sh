#!/usr/bin/env bash
# DigiFlot Edge deployment maintenance. The executable copy is root-owned
# under /usr/local/libexec/digiflot-edge, refreshed only by successful updates.
set -Eeuo pipefail

APP_DIR="/opt/digiflot-edge"
SRC_DIR="$APP_DIR/src"
DEPLOY_DIR="$SRC_DIR/deploy"
CONFIG="/etc/digiflot-edge/install.conf"
LIBEXEC_DIR="/usr/local/libexec/digiflot-edge"
SERVICE="digiflot.service"
HEALTH="digiflot-healthcheck"
STATE_LOCK="/run/lock/digiflot-maintenance.lock"
ACTION="${1:-}"
shift || true
FORCE=0
for argument in "$@"; do
    case "$argument" in
        --force) FORCE=1 ;;
        *) echo "[DigiFlot] Unknown option: $argument" >&2; exit 2 ;;
    esac
done

log() { printf '[DigiFlot] %s\n' "$*"; }
die() { printf '[DigiFlot] ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || die "Run this command with sudo."
command -v flock >/dev/null || die "flock is required (util-linux)."
exec 9>"$STATE_LOCK"
flock -x 9

install_config() {
    [[ -f "$CONFIG" ]] && return
    local user="${DIGIFLOT_SERVICE_USER:-}" port="${DIGIFLOT_PORT:-}" home="${DIGIFLOT_SERVICE_HOME:-}"
    local interval="${DIGIFLOT_HEALTH_INTERVAL:-}" boot="${DIGIFLOT_HEALTH_BOOT_DELAY:-}"
    local failures="${DIGIFLOT_HEALTH_MAX_FAILURES:-}" branch="${DIGIFLOT_BRANCH:-main}"
    local service_file="/etc/systemd/system/$SERVICE" timer_file="/etc/systemd/system/$HEALTH.timer"
    if [[ -f "$service_file" ]]; then
        [[ -n "$user" ]] || user="$(sed -n 's/^User=//p' "$service_file" | head -n1)"
        [[ -n "$home" ]] || home="$(sed -n 's/^Environment=HOME=//p' "$service_file" | head -n1)"
        [[ -n "$port" ]] || port="$(sed -nE 's/.*--port ([0-9]+).*/\1/p' "$service_file" | head -n1)"
    fi
    if [[ -f "$timer_file" ]]; then
        [[ -n "$interval" ]] || interval="$(sed -n 's/^OnUnitActiveSec=//p' "$timer_file" | head -n1)"
        [[ -n "$boot" ]] || boot="$(sed -n 's/^OnBootSec=//p' "$timer_file" | head -n1)"
    fi
    if [[ -z "$failures" && -f /usr/local/bin/digiflot-healthcheck ]]; then
        failures="$(sed -nE 's/^MAX_FAILURES="?([0-9]+)"?$/\1/p' /usr/local/bin/digiflot-healthcheck | head -n1)"
    fi
    user="${user:-digiflot}"; port="${port:-8000}"; home="${home:-/var/lib/digiflot-edge}"
    interval="${interval:-30s}"; boot="${boot:-90s}"; failures="${failures:-2}"
    [[ "$port" =~ ^[0-9]+$ ]] || die "Invalid DigiFlot port: $port"
    [[ "$failures" =~ ^[0-9]+$ ]] || die "Invalid watchdog threshold."
    id "$user" >/dev/null 2>&1 || die "DigiFlot service account not found: $user"
    install -d -m 0755 /etc/digiflot-edge
    {
        printf 'DIGIFLOT_SERVICE_USER=%q\n' "$user"
        printf 'DIGIFLOT_SERVICE_HOME=%q\n' "$home"
        printf 'DIGIFLOT_PORT=%q\n' "$port"
        printf 'DIGIFLOT_HEALTH_INTERVAL=%q\n' "$interval"
        printf 'DIGIFLOT_HEALTH_BOOT_DELAY=%q\n' "$boot"
        printf 'DIGIFLOT_HEALTH_MAX_FAILURES=%q\n' "$failures"
        printf 'DIGIFLOT_BRANCH=%q\n' "$branch"
    } > "$CONFIG"
    chmod 0600 "$CONFIG"
    log "Captured installed machine settings in $CONFIG"
}

read_config() {
    [[ -f "$CONFIG" ]] || die "Installation settings missing: $CONFIG (run the migration once)."
    [[ "$(stat -c '%u' "$CONFIG")" == 0 ]] || die "Machine configuration must be owned by root."
    # shellcheck source=/dev/null
    source "$CONFIG"
    [[ "$DIGIFLOT_PORT" =~ ^[0-9]+$ ]] || die "Invalid port in machine configuration."
    [[ "$DIGIFLOT_HEALTH_MAX_FAILURES" =~ ^[0-9]+$ ]] || die "Invalid watchdog configuration."
    id "$DIGIFLOT_SERVICE_USER" >/dev/null 2>&1 || die "Service account is unavailable."
    SERVICE_HOME="$DIGIFLOT_SERVICE_HOME"
    SERVICE_GROUP="$(id -gn "$DIGIFLOT_SERVICE_USER")"
    PYTHON="$SRC_DIR/.venv/bin/python"
    URL="http://127.0.0.1:$DIGIFLOT_PORT/"
}

as_service() {
    runuser -u "$DIGIFLOT_SERVICE_USER" -- env HOME="$SERVICE_HOME" "$@"
}

# The ordinary update/restart commands must not interrupt active experiments.
assert_safe() {
    [[ "$FORCE" == 1 ]] && { log "FORCE requested: acquisition safety check bypassed."; return; }
    systemctl is-active --quiet "$SERVICE" || return 0
    local state
    state="$(curl --silent --show-error --max-time 3 --fail "$URL"api/digiflot/state 2>/dev/null |
        python3 -c 'import json,sys; print(json.load(sys.stdin).get("state","Unknown"))' 2>/dev/null)" || state="Unknown"
    case "$state" in
        Idle|Completed|Aborted|Error) ;;
        *) die "Refusing to interrupt DigiFlot ($state). Finish/reset the experiment first, or explicitly use --force." ;;
    esac
}

write_if_changed() {
    local source="$1" target="$2" mode="${3:-0644}" temporary
    if [[ -f "$target" ]] && cmp -s "$source" "$target"; then return 1; fi
    install -d -m 0755 "$(dirname "$target")"
    temporary="$(mktemp "$(dirname "$target")/.digiflot-sync.XXXXXXXX")"
    # Atomic rename preserves the inode of any currently running maintainer.
    # Never truncate the executable that is performing this very update.
    if ! install -m "$mode" "$source" "$temporary"; then
        rm -f "$temporary"
        die "Could not stage $target"
    fi
    mv -f "$temporary" "$target"
    log "Updated: $target"
    return 0
}

sync_integration() {
    [[ -f "$DEPLOY_DIR/maintenance.sh" && -f "$DEPLOY_DIR/browser-open.sh" &&
       -f "$DEPLOY_DIR/browser-autostart.sh" ]] ||
        die "Deployment sources missing from Git checkout."
    bash -n "$DEPLOY_DIR/maintenance.sh" && bash -n "$DEPLOY_DIR/browser-open.sh" &&
        bash -n "$DEPLOY_DIR/browser-autostart.sh" ||
        die "Deployment scripts failed syntax verification."
    # Do not promote an uncommitted local shell edit into a root-owned executable.
    as_service git -C "$APP_DIR" diff --quiet HEAD -- src/deploy/maintenance.sh ||
        die "Deployment manager has local edits; refusing privileged synchronization."
    local tmp backend_unit_changed=0 health_changed=0
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN

    cat > "$tmp/digiflot.service" <<EOF_UNIT
[Unit]
Description=DigiFlot Edge server
After=network.target local-fs.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=$DIGIFLOT_SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$SRC_DIR
Environment=HOME=$SERVICE_HOME
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON -m uvicorn app:app --host 0.0.0.0 --port $DIGIFLOT_PORT --workers 1
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
KillSignal=SIGTERM
UMask=0022

[Install]
WantedBy=multi-user.target
EOF_UNIT

    cat > "$tmp/$HEALTH.service" <<EOF_HEALTH_UNIT
[Unit]
Description=Check DigiFlot Edge HTTP responsiveness
After=$SERVICE

[Service]
Type=oneshot
ExecStart=/usr/local/bin/digiflot-healthcheck
EOF_HEALTH_UNIT

    cat > "$tmp/$HEALTH.timer" <<EOF_HEALTH_TIMER
[Unit]
Description=Periodically verify DigiFlot Edge is responsive

[Timer]
OnBootSec=$DIGIFLOT_HEALTH_BOOT_DELAY
OnUnitActiveSec=$DIGIFLOT_HEALTH_INTERVAL
AccuracySec=5s
Persistent=true
Unit=$HEALTH.service

[Install]
WantedBy=timers.target
EOF_HEALTH_TIMER

    cat > "$tmp/digiflot-healthcheck" <<'EOF_HEALTH'
#!/usr/bin/env bash
set -uo pipefail
SERVICE="digiflot.service"
STATE_FILE="/run/digiflot-healthcheck.failures"
log() { logger -t digiflot-healthcheck -- "$*"; printf '[DigiFlot health] %s\n' "$*"; }
if ! systemctl is-active --quiet "$SERVICE"; then
    log "Service inactive. Starting it."
    rm -f "$STATE_FILE"
    systemctl start "$SERVICE"
    exit $?
fi
if curl --silent --max-time 3 --output /dev/null "$DIGIFLOT_HEALTH_URL"; then
    rm -f "$STATE_FILE"
    exit 0
fi
failures=0
[[ -f "$STATE_FILE" ]] && read -r failures < "$STATE_FILE" || true
[[ "$failures" =~ ^[0-9]+$ ]] || failures=0
failures=$((failures + 1))
printf '%s\n' "$failures" > "$STATE_FILE"
if (( failures >= DIGIFLOT_MAX_FAILURES )); then
    log "HTTP check failed $failures times. Restarting DigiFlot."
    rm -f "$STATE_FILE"
    systemctl restart "$SERVICE"
else
    log "HTTP check failed ($failures/$DIGIFLOT_MAX_FAILURES)."
fi
EOF_HEALTH
    # Use a root-owned launcher to inject only the installation-specific constants.
    sed -i "2a DIGIFLOT_HEALTH_URL='$URL'\\nDIGIFLOT_MAX_FAILURES='$DIGIFLOT_HEALTH_MAX_FAILURES'" "$tmp/digiflot-healthcheck"

    cat > "$tmp/digiflot-edge-open" <<EOF_OPEN
#!/usr/bin/env bash
set -Eeuo pipefail
export DIGIFLOT_PORT="$DIGIFLOT_PORT"
exec /bin/bash /opt/digiflot-edge/src/deploy/browser-open.sh "\$@"
EOF_OPEN
    cat > "$tmp/digiflot-browser-autostart" <<'EOF_AUTOSTART'
#!/usr/bin/env bash
set -Eeuo pipefail
exec /bin/bash /opt/digiflot-edge/src/deploy/browser-autostart.sh "$@"
EOF_AUTOSTART
    cat > "$tmp/digiflot-update" <<'EOF_UPDATE'
#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID != 0 )); then exec sudo "$0" "$@"; fi
exec /bin/bash /usr/local/libexec/digiflot-edge/maintenance.sh update "$@"
EOF_UPDATE
    cat > "$tmp/digiflot-restart" <<'EOF_RESTART'
#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID != 0 )); then exec sudo "$0" "$@"; fi
exec /bin/bash /usr/local/libexec/digiflot-edge/maintenance.sh restart "$@"
EOF_RESTART
    cat > "$tmp/digiflot-sync" <<'EOF_SYNC'
#!/usr/bin/env bash
set -Eeuo pipefail
if (( EUID != 0 )); then exec sudo "$0" "$@"; fi
exec /bin/bash /usr/local/libexec/digiflot-edge/maintenance.sh sync "$@"
EOF_SYNC
    cat > "$tmp/digiflot-status" <<EOF_STATUS
#!/usr/bin/env bash
set -u
URL="$URL"
echo 'DigiFlot Edge'
echo '-------------'
echo "Install:      $APP_DIR"
printf 'Service:      '
if systemctl is-active --quiet "$SERVICE"; then echo active; else systemctl is-active "$SERVICE" 2>/dev/null || true; fi
printf 'Boot enabled: '
if systemctl is-enabled --quiet "$SERVICE"; then echo yes; else echo no; fi
printf 'Health timer: '
if systemctl is-active --quiet "$HEALTH.timer"; then echo active; else echo inactive; fi
printf 'HTTP:         '
if curl --silent --max-time 3 --output /dev/null "\$URL" 2>/dev/null; then echo responding; else echo 'NOT RESPONDING'; fi
echo "URL:          \$URL"
EOF_STATUS

    # Unit files are installed as root-owned copies; never symlink systemd
    # to files writable by the acquisition service account.
    if write_if_changed "$tmp/digiflot.service" "/etc/systemd/system/digiflot.service"; then backend_unit_changed=1; fi
    if write_if_changed "$tmp/$HEALTH.service" "/etc/systemd/system/$HEALTH.service"; then health_changed=1; fi
    if write_if_changed "$tmp/$HEALTH.timer" "/etc/systemd/system/$HEALTH.timer"; then health_changed=1; fi
    write_if_changed "$tmp/digiflot-healthcheck" /usr/local/bin/digiflot-healthcheck 0755 || true
    write_if_changed "$tmp/digiflot-edge-open" /usr/local/bin/digiflot-edge-open 0755 || true
    write_if_changed "$tmp/digiflot-browser-autostart" /usr/local/bin/digiflot-browser-autostart 0755 || true
    write_if_changed "$tmp/digiflot-update" /usr/local/sbin/digiflot-update 0755 || true
    write_if_changed "$tmp/digiflot-restart" /usr/local/bin/digiflot-restart 0755 || true
    write_if_changed "$tmp/digiflot-sync" /usr/local/sbin/digiflot-sync 0755 || true
    write_if_changed "$tmp/digiflot-status" /usr/local/bin/digiflot-status 0755 || true
    # A root-owned copy is the stable dispatcher for subsequent Git updates.
    install -d -m 0755 "$LIBEXEC_DIR"
    write_if_changed "$DEPLOY_DIR/maintenance.sh" "$LIBEXEC_DIR/maintenance.sh" 0755 || true

    if (( backend_unit_changed || health_changed )); then
        systemctl daemon-reload
        if (( health_changed )); then
            systemctl enable --now "$HEALTH.timer" >/dev/null
            systemctl try-restart "$HEALTH.timer" || true
        fi
    fi
    SYNC_BACKEND_UNIT_CHANGED="$backend_unit_changed"
    log "Deployment synchronization complete. Backend unit changed: $backend_unit_changed."
    rm -rf "$tmp"
    trap - RETURN
}

restart_backend() {
    assert_safe
    log "Restarting DigiFlot backend only; Chromium stays open."
    systemctl restart "$SERVICE"
    systemctl is-active --quiet "$SERVICE" || die "DigiFlot service did not become active."
    log "DigiFlot backend is active."
}

update_repo() {
    assert_safe
    [[ -d "$APP_DIR/.git" ]] || die "Git checkout is missing."
    local previous remote current changed req_hash stamp old_hash needs_restart=0
    [[ -f "$PYTHON" ]] || die "Python virtual environment is missing."
    if as_service git -C "$APP_DIR" ls-files --error-unmatch src/config.json >/dev/null 2>&1; then
        as_service git -C "$APP_DIR" update-index --skip-worktree src/config.json
    fi
    [[ -z "$(as_service git -C "$APP_DIR" status --porcelain)" ]] ||
        die "Local Git changes found. Update aborted without modifying the checkout."
    previous="$(as_service git -C "$APP_DIR" rev-parse HEAD)"
    log "Fetching Git updates for $DIGIFLOT_BRANCH..."
    as_service git -C "$APP_DIR" fetch origin "$DIGIFLOT_BRANCH"
    remote="$(as_service git -C "$APP_DIR" rev-parse "origin/$DIGIFLOT_BRANCH")"
    as_service git -C "$APP_DIR" merge-base --is-ancestor "$previous" "$remote" ||
        die "Local branch is not an ancestor of remote. Refusing non-fast-forward update."
    if [[ "$previous" != "$remote" ]]; then
        as_service git -C "$APP_DIR" pull --ff-only origin "$DIGIFLOT_BRANCH"
        log "Updated: ${previous:0:12} -> ${remote:0:12}"
    else
        log "Git checkout already up to date."
    fi
    current="$(as_service git -C "$APP_DIR" rev-parse HEAD)"
    changed="$(as_service git -C "$APP_DIR" diff --name-only "$previous" "$current")"

    req_hash="$(sha256sum "$SRC_DIR/requirements.txt" | awk '{print $1}')"
    stamp="$SRC_DIR/.venv/.digiflot_requirements.sha256"
    old_hash=""
    [[ -f "$stamp" ]] && old_hash="$(cat "$stamp")"
    if [[ "$old_hash" != "$req_hash" ]]; then
        log "Python requirements changed; updating the existing venv."
        as_service "$PYTHON" -m pip install --ignore-installed --no-deps typing_extensions
        as_service "$PYTHON" -m pip install --upgrade-strategy only-if-needed -r "$SRC_DIR/requirements.txt"
        printf '%s\n' "$req_hash" > "$stamp"
        chown "$DIGIFLOT_SERVICE_USER:$SERVICE_GROUP" "$stamp"
        needs_restart=1
    fi

    SYNC_BACKEND_UNIT_CHANGED=0
    sync_integration
    (( SYNC_BACKEND_UNIT_CHANGED )) && needs_restart=1
    if grep -Eq '^(src/(app\.py|api/|lib/|config\.json|requirements\.txt)|src/ui/html/[^/]*\.py)' <<<"$changed"; then
        needs_restart=1
    fi
    if (( needs_restart )); then
        log "Backend sources/configuration changed; restarting backend."
        assert_safe
        systemctl restart "$SERVICE"
    else
        log "No backend restart needed (browser/frontend/deployment-only update)."
    fi
    log "Update complete. Chromium window was not relaunched."
}

case "$ACTION" in
    bootstrap)
        install_config
        read_config
        sync_integration
        ;;
    sync)
        read_config
        assert_safe
        sync_integration
        if (( SYNC_BACKEND_UNIT_CHANGED )); then
            assert_safe
            systemctl restart "$SERVICE"
        fi
        ;;
    restart)
        read_config
        restart_backend
        ;;
    update)
        read_config
        update_repo
        ;;
    *)
        echo 'Usage: maintenance.sh {bootstrap|update|restart|sync} [--force]' >&2
        exit 2
        ;;
esac
