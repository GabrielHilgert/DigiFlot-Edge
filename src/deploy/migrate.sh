#!/usr/bin/env bash
# One-time migration from the original installer-generated maintenance scripts.
# No apt operation, venv recreation, checkout deletion or experiment reset.
set -Eeuo pipefail
if (( EUID != 0 )); then exec sudo /bin/bash "$0" "$@"; fi
SCRIPT="/opt/digiflot-edge/src/deploy/maintenance.sh"
[[ -f "$SCRIPT" ]] || { echo "[DigiFlot] New deployment sources are not checked out. Run the existing sudo digiflot-update first." >&2; exit 1; }
echo "[DigiFlot] Migrating existing installation to Git-managed maintenance."
/bin/bash "$SCRIPT" bootstrap "$@"
echo "[DigiFlot] Migration complete. Future updates: sudo digiflot-update"
echo "[DigiFlot] Restart backend: sudo digiflot-restart"
echo "[DigiFlot] Sync system units: sudo digiflot-sync"
