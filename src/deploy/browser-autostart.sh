#!/usr/bin/env bash
# Opt-in desktop-session autostart, intentionally independent of digiflot.service.
# Configure as the interactive user (never as root or the acquisition account).
set -Eeuo pipefail
[[ "$EUID" -ne 0 ]] || { echo "[DigiFlot] Run autostart setup as your desktop user, without sudo." >&2; exit 1; }
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
ENTRY="$AUTOSTART_DIR/digiflot-edge.desktop"
case "${1:-status}" in
    enable)
        mkdir -p "$AUTOSTART_DIR"
        if [[ -e "$ENTRY" ]] && ! grep -q '^X-DigiFlot-Managed=true$' "$ENTRY"; then
            echo "[DigiFlot] Existing autostart entry was not created by DigiFlot; it was left unchanged." >&2
            exit 1
        fi
        cat > "$ENTRY" <<'EOF_DESKTOP'
[Desktop Entry]
Type=Application
Name=DigiFlot Edge
Comment=Open the single Chromium fullscreen window after desktop login
Exec=/usr/local/bin/digiflot-edge-open
TryExec=/usr/local/bin/digiflot-edge-open
Terminal=false
X-DigiFlot-Managed=true
EOF_DESKTOP
        echo "[DigiFlot] Browser autostart enabled for this user. Backend remains independent."
        ;;
    disable)
        if [[ -f "$ENTRY" ]] && grep -q '^X-DigiFlot-Managed=true$' "$ENTRY"; then
            rm "$ENTRY"
            echo "[DigiFlot] Browser autostart disabled."
        else
            echo "[DigiFlot] No managed autostart entry to remove."
        fi
        ;;
    status)
        if [[ -f "$ENTRY" ]] && grep -q '^X-DigiFlot-Managed=true$' "$ENTRY"; then
            echo "DigiFlot browser autostart: enabled"
        else
            echo "DigiFlot browser autostart: disabled"
        fi
        ;;
    *) echo "Usage: digiflot-browser-autostart {enable|disable|status}" >&2; exit 2 ;;
esac
