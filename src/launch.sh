#!/usr/bin/env bash
set -e
git fetch origin

if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    git pull --ff-only origin main
    sudo systemctl restart digiflot
fi

source .venv/bin/activate
exec uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
