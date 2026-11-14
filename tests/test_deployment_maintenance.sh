#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
bash -n "$ROOT/src/install.sh" "$ROOT/src/launch.sh" \
    "$ROOT/src/deploy/maintenance.sh" "$ROOT/src/deploy/migrate.sh" \
    "$ROOT/src/deploy/browser-open.sh" "$ROOT/src/deploy/browser-autostart.sh"

# Browser duplicates must be prevented without relying on any external
# running Chromium or backend, so this test uses a fake browser executable.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/fake-chromium" <<'EOF_BROWSER'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DIGIFLOT_TEST_BROWSER_LOG"
sleep 0.8
EOF_BROWSER
chmod +x "$TMP/fake-chromium"
export XDG_CACHE_HOME="$TMP/cache" XDG_CONFIG_HOME="$TMP/config"
export DIGIFLOT_CHROMIUM_BIN="$TMP/fake-chromium" DIGIFLOT_WAIT_FOR_HTTP=0
export DIGIFLOT_TEST_BROWSER_LOG="$TMP/browser.log"
bash "$ROOT/src/deploy/browser-open.sh" > "$TMP/first.log" 2>&1 &
FIRST_PID=$!
sleep 0.2
bash "$ROOT/src/deploy/browser-open.sh" > "$TMP/second.log" 2>&1
wait "$FIRST_PID"
[[ "$(wc -l < "$TMP/browser.log")" == 1 ]] || { echo "Second launch started a duplicate Chromium." >&2; exit 1; }
grep -q "already running" "$TMP/second.log"
grep -q -- '--start-fullscreen' "$TMP/browser.log"
grep -q -- '--user-data-dir=' "$TMP/browser.log"
! grep -q -- '--kiosk' "$TMP/browser.log"

# Closing the previous instance must release the lock and allow a new launch.
bash "$ROOT/src/deploy/browser-open.sh" > "$TMP/third.log" 2>&1
[[ "$(wc -l < "$TMP/browser.log")" == 2 ]] || { echo "Chromium lock was not released." >&2; exit 1; }

# Restart/update/sync commands and experiment-state safety are versioned.
grep -q 'case "$ACTION" in' "$ROOT/src/deploy/maintenance.sh"
grep -q 'Restarting DigiFlot backend only' "$ROOT/src/deploy/maintenance.sh"
grep -q 'Refusing to interrupt DigiFlot' "$ROOT/src/deploy/maintenance.sh"
grep -q 'write_if_changed "$tmp/digiflot-restart"' "$ROOT/src/deploy/maintenance.sh"
grep -q 'write_if_changed "$DEPLOY_DIR/maintenance.sh"' "$ROOT/src/deploy/maintenance.sh"
grep -q 'bash "$SRC_DIR/deploy/maintenance.sh" bootstrap' "$ROOT/src/install.sh"
# Desktop-login autostart must be opt-in and reversible for the current user.
bash "$ROOT/src/deploy/browser-autostart.sh" enable > "$TMP/autostart-enable.log"
grep -q 'X-DigiFlot-Managed=true' "$TMP/config/autostart/digiflot-edge.desktop"
bash "$ROOT/src/deploy/browser-autostart.sh" status | grep -q enabled
bash "$ROOT/src/deploy/browser-autostart.sh" disable > "$TMP/autostart-disable.log"
[[ ! -e "$TMP/config/autostart/digiflot-edge.desktop" ]] || { echo "Autostart was not removed." >&2; exit 1; }
grep -q 'export DIGIFLOT_PORT=' "$ROOT/src/deploy/maintenance.sh"
echo "DigiFlot deployment migration, Chromium deduplication and restart wiring passed"
