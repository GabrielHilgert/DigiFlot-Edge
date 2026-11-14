#!/usr/bin/env bash
# Open the single DigiFlot Chromium window for this desktop user.
# A file lock is kept by the Chromium process, so repeated launches do not
# forward a URL to an existing browser (which would otherwise create a tab).
set -Eeuo pipefail

PORT="${DIGIFLOT_PORT:-8000}"
URL="${DIGIFLOT_BROWSER_URL:-http://127.0.0.1:${PORT}/}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/digiflot-edge"
PROFILE_DIR="${DIGIFLOT_BROWSER_PROFILE:-${XDG_CONFIG_HOME:-$HOME/.config}/digiflot-edge/chromium}"
mkdir -p "$CACHE_DIR" "$PROFILE_DIR"
chmod 700 "$CACHE_DIR" "$PROFILE_DIR"

# Lock across the lifetime of the GUI process, not just browser startup.
exec 9>"$CACHE_DIR/chromium.lock"
if ! flock -n 9; then
    printf '[DigiFlot] Chromium is already running for this user; no new tab opened.\n'
    exit 0
fi

if [[ -n "${DIGIFLOT_CHROMIUM_BIN:-}" ]]; then
    BROWSER="$DIGIFLOT_CHROMIUM_BIN"
elif command -v chromium >/dev/null 2>&1; then
    BROWSER="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
    BROWSER="$(command -v chromium-browser)"
else
    echo '[DigiFlot] Chromium is missing. Install chromium (or chromium-browser) to use the graphical launcher.' >&2
    exit 127
fi

if [[ "${DIGIFLOT_WAIT_FOR_HTTP:-1}" != 0 ]]; then
    for _ in {1..15}; do
        curl --silent --max-time 1 --output /dev/null "$URL" 2>/dev/null && break
        sleep 1
    done
fi

# Conventional fullscreen: F11 remains available. Do not use --kiosk.
# A dedicated user-data-dir prevents Chromium's ordinary profile from
# receiving URLs or mixing windows with this application.
exec "$BROWSER" --start-fullscreen --new-window --no-first-run \
    --no-default-browser-check --disable-session-crashed-bubble \
    --user-data-dir="$PROFILE_DIR" "$URL"
