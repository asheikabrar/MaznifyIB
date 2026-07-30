#!/usr/bin/env bash
set -euo pipefail

# StudyMate Single-Click Launcher for Mac/Linux
# Make this executable: chmod +x StudyMate.sh
# Then double-click or run: ./StudyMate.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "===================================="
echo "  StudyMate - Launching..."
echo "===================================="
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: Python 3 is not installed"
    echo "Please install Python 3 from https://www.python.org/downloads/mac-osx/"
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Creating virtual environment and installing dependencies..."
    ./install_mac.sh
else
    if [ ! -f .venv/bin/python ]; then
        echo "Virtual environment is incomplete. Rebuilding..."
        rm -rf .venv
        ./install_mac.sh
    fi
fi

source .venv/bin/activate
if [ ! -f .env ]; then
    cp .env.example .env
fi

echo "Starting StudyMate..."
echo "Open http://127.0.0.1:8000/revision-desk to use the revision desk"
python launcher.py
