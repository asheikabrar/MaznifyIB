#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d .venv ]; then
  echo "Virtual environment not found. Running installer first..."
  ./install_mac.sh
fi

source .venv/bin/activate

echo "Starting StudyMate..."
echo "Open this link in your browser: http://127.0.0.1:8000/revision-desk"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
