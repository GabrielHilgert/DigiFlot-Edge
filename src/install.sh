#!/usr/bin/env bash

set -euo pipefail

REPO_URL="https://github.com/GabrielHilgert/DigiFlot-Edge.git"
REPO_NAME="DigiFlot-Edge"
BRANCH="main"

# The repository will be installed in the directory
# from which this installer is executed.
INSTALL_BASE="$(pwd)"

APP_DIR="$INSTALL_BASE/$REPO_NAME"
SRC_DIR="$APP_DIR/src"
VENV_DIR="$SRC_DIR/.venv"

LAUNCHER="$SRC_DIR/launch.sh"
DESKTOP_SOURCE="$SRC_DIR/digiflot-edge.desktop"

ICON_SOURCE="$SRC_DIR/ui/img/squarelogo.ico"
ICON_DIR="$HOME/.local/share/icons"
ICON_DEST="$ICON_DIR/digiflot-edge-icon.ico"

APPLICATIONS_DIR="$HOME/.local/share/applications"
DESKTOP_DEST="$APPLICATIONS_DIR/digiflot-edge.desktop"


echo
echo "========================================"
echo "       DigiFlot Edge Installer"
echo "========================================"
echo

echo "[DigiFlot] Installation directory:"
echo "           $APP_DIR"
echo


# ------------------------------------------------------------
# Clone / update repository
# ------------------------------------------------------------

if [ -d "$APP_DIR/.git" ]; then

    echo "[DigiFlot] Repository already exists."
    echo "[DigiFlot] Checking for updates..."

    git -C "$APP_DIR" fetch origin "$BRANCH"

    LOCAL_COMMIT="$(git -C "$APP_DIR" rev-parse HEAD)"
    REMOTE_COMMIT="$(git -C "$APP_DIR" rev-parse "origin/$BRANCH")"

    if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
        echo "[DigiFlot] Repository is up to date."
    else
        echo "[DigiFlot] Repository is not up to date."
        echo "[DigiFlot] Updating repository..."

        git -C "$APP_DIR" pull --ff-only origin "$BRANCH"

        echo "[DigiFlot] Repository updated."
    fi

else

    if [ -e "$APP_DIR" ]; then
        echo "[DigiFlot] ERROR:"
        echo "           $APP_DIR"
        echo "           already exists but is not a Git repository."
        exit 1
    fi

    echo "[DigiFlot] Cloning repository..."

    git clone \
        --branch "$BRANCH" \
        "$REPO_URL" \
        "$APP_DIR"

    echo "[DigiFlot] Repository cloned."

fi

# ------------------------------------------------------------
# Dependencies
# ------------------------------------------------------------


echo "[DigiFlot] Installing system dependencies..."

sudo apt update

sudo apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-picamera2 \
    python3-libcamera \
    libcamera-tools \
    ffmpeg


# ------------------------------------------------------------
# Check src/
# ------------------------------------------------------------

if [ ! -d "$SRC_DIR" ]; then
    echo "[DigiFlot] ERROR: src directory not found:"
    echo "           $SRC_DIR"
    exit 1
fi

cd "$SRC_DIR"


# ------------------------------------------------------------
# Virtual environment
# ------------------------------------------------------------

if [ -d "$VENV_DIR" ]; then

    echo "[DigiFlot] Virtual environment already exists."

else

    echo "[DigiFlot] Creating virtual environment..."

    python3 -m venv "$VENV_DIR"

fi


echo "[DigiFlot] Activating virtual environment..."

source "$VENV_DIR/bin/activate"


echo "[DigiFlot] Updating pip..."

python -m pip install --upgrade pip


# ------------------------------------------------------------
# Python requirements
# ------------------------------------------------------------

if [ ! -f "$SRC_DIR/requirements.txt" ]; then
    echo "[DigiFlot] ERROR: requirements.txt not found:"
    echo "           $SRC_DIR/requirements.txt"
    exit 1
fi


echo "[DigiFlot] Installing Python requirements..."

python -m pip install \
    -r "$SRC_DIR/requirements.txt"


echo "[DigiFlot] Virtual environment ready."
echo "[DigiFlot] Python: $(python --version)"
echo "[DigiFlot] Python path: $(which python)"


# ------------------------------------------------------------
# Launcher
# ------------------------------------------------------------

echo "[DigiFlot] Setting up launcher..."


if [ ! -f "$LAUNCHER" ]; then
    echo "[DigiFlot] ERROR: launch.sh not found:"
    echo "           $LAUNCHER"
    exit 1
fi


chmod +x "$LAUNCHER"


# ------------------------------------------------------------
# Icon
# ------------------------------------------------------------

if [ -f "$ICON_SOURCE" ]; then

    echo "[DigiFlot] Installing icon..."

    mkdir -p "$ICON_DIR"

    cp \
        "$ICON_SOURCE" \
        "$ICON_DEST"

else

    echo "[DigiFlot] WARNING: icon not found:"
    echo "           $ICON_SOURCE"

fi


# ------------------------------------------------------------
# Desktop launcher
# ------------------------------------------------------------

echo "[DigiFlot] Installing application shortcut..."

mkdir -p "$APPLICATIONS_DIR"


#
# We generate the installed .desktop file here instead of
# simply copying the repository version.
#
# This is necessary because the installed .desktop lives in
# ~/.local/share/applications, while launch.sh lives in src/.
#

cat > "$DESKTOP_DEST" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DigiFlot Edge
Comment=DigiFlot Edge Launcher
Exec=bash -lc 'cd "$SRC_DIR" && exec ./launch.sh'
Icon=digiflot-edge-icon
Terminal=true
Categories=Science;Education;
StartupNotify=true
EOF


chmod +x "$DESKTOP_DEST"


# ------------------------------------------------------------
# Refresh desktop database
# ------------------------------------------------------------

if command -v update-desktop-database >/dev/null 2>&1; then

    update-desktop-database \
        "$APPLICATIONS_DIR" \
        >/dev/null 2>&1 || true

fi


echo
echo "========================================"
echo "   DigiFlot Edge Installation Complete"
echo "========================================"
echo
echo "[DigiFlot] Repository:"
echo "           $APP_DIR"
echo
echo "[DigiFlot] Source:"
echo "           $SRC_DIR"
echo
echo "[DigiFlot] Virtual environment:"
echo "           $VENV_DIR"
echo
echo "[DigiFlot] Launcher:"
echo "           $LAUNCHER"
echo
echo "[DigiFlot] Desktop entry:"
echo "           $DESKTOP_DEST"
echo
x