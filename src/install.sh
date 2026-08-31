#!/usr/bin/env bash

set -euo pipefail

REPO_URL="https://github.com/GabrielHilgert/DigiFlot-Edge.git"
REPO_NAME="DigiFlot-Edge"

INSTALL_BASE="$(pwd)"
APP_DIR="$INSTALL_BASE/$REPO_NAME"
SRC_DIR="$APP_DIR/src"
VENV_DIR="$SRC_DIR/.venv"

echo "[DigiFlot] Starting installation..."

if [ -d "$APP_DIR/.git" ]; then
    echo "[DigiFlot] Repository already exists."
    echo "[DigiFlot] Updating repository..."

    git -C "$APP_DIR" pull --ff-only origin main
else
    if [ -e "$APP_DIR" ]; then
        echo "[DigiFlot] ERROR: $APP_DIR already exists but is not a Git repository."
        exit 1
    fi

    echo "[DigiFlot] Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
fi

if [ ! -d "$SRC_DIR" ]; then
    echo "[DigiFlot] ERROR: src directory not found."
    exit 1
fi

cd "$SRC_DIR"

if [ -d "$VENV_DIR" ]; then
    echo "[DigiFlot] Virtual environment already exists."
else
    echo "[DigiFlot] Creating virtual environment..."
    python3 -m venv .venv
fi

echo "[DigiFlot] Activating virtual environment..."
source .venv/bin/activate

echo "[DigiFlot] Updating pip..."
python -m pip install --upgrade pip

if [ -f "requirements.txt" ]; then
    echo "[DigiFlot] Installing requirements..."
    python -m pip install -r requirements.txt
elif [ -f "$APP_DIR/requirements.txt" ]; then
    echo "[DigiFlot] Installing requirements..."
    python -m pip install -r "$APP_DIR/requirements.txt"
else
    echo "[DigiFlot] WARNING: requirements.txt not found."
fi

echo "[DigiFlot] Virtual environment ready."
echo "[DigiFlot] Python: $(python --version)"
echo "[DigiFlot] Python path: $(which python)"

cd "$APP_DIR"

echo "[DigiFlot] Setting up launcher..."

LAUNCHER="$SRC_DIR/launch.sh"
DESKTOP_FILE="$SRC_DIR/digiflot-edge.desktop"

chmod +x "$LAUNCHER"
chmod +x "$DESKTOP_FILE"

mkdir -p "$HOME/.local/share/icons"
cp \
    "$APP_DIR/src/ui/img/squarelogo.ico" \
    "$HOME/.local/share/icons/digiflot-edge-icon.ico"

mkdir -p "$HOME/.local/share/applications"
cp \
    "$DESKTOP_FILE" \
    "$HOME/.local/share/applications/digiflot-edge.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" || true
fi

echo "[DigiFlot] Installation complete."
echo "[DigiFlot] Installation directory: $APP_DIR"
