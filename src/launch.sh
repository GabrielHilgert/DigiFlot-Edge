#!/usr/bin/env bash

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="main"

cd "$APP_DIR"

git fetch origin "$BRANCH"

LOCAL_COMMIT="$(git rev-parse HEAD)"
REMOTE_COMMIT="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
    echo "[DigiFlot] Repository is up to date."
else
    echo "[DigiFlot] Repository is not up to date. Updating..."

    git pull --ff-only origin "$BRANCH"

    echo "[DigiFlot] Repository updated successfully."
fi

source .venv/bin/activate

exec uvicorn app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1
