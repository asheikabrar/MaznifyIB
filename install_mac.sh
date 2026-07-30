#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "===================================="
echo "  StudyMate macOS installer"
echo "===================================="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required but was not found."
  echo "Install Python 3 from https://www.python.org/downloads/mac-osx/ and try again."
  exit 1
fi

echo "Creating local virtual environment in .venv..."
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
  echo "You can edit .env later if you want to add an Anthropic key."
fi

python -m app.seed >/dev/null 2>&1 || true

echo
echo "Installation complete."
echo "Run ./StudyMate.sh to start the app."
echo "Then open http://127.0.0.1:8000/revision-desk"
