#!/usr/bin/env bash
set -e

source .venv/bin/activate
exec uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
