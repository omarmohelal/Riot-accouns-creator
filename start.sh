#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "========================================"
echo "  Riot Creator Control v2.4"
echo "========================================"

PYTHON_CMD="${PYTHON_CMD:-python3}"
if ! command -v "$PYTHON_CMD" >/dev/null 2>&1; then
  echo "Python 3.11+ is required."
  exit 1
fi

if [ ! -d "backend/.venv" ]; then
  "$PYTHON_CMD" -m venv backend/.venv
  backend/.venv/bin/python -m pip install --upgrade pip
  backend/.venv/bin/python -m pip install -r backend/requirements.txt
  backend/.venv/bin/python -m playwright install chromium
fi

if [ ! -d "frontend/node_modules" ]; then
  (cd frontend && npm install)
fi

if [ ! -f "frontend/dist/index.html" ]; then
  (cd frontend && npm run build)
fi

exec backend/.venv/bin/python backend/launcher.py
