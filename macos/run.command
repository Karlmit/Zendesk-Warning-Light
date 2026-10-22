#!/usr/bin/env bash
# Double-click to run Zendesk Warning Light from source, without building an app.
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Setting up the virtual environment (first run only)..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --quiet --require-hashes -r requirements-build.txt
fi
exec ./.venv/bin/python main.py "$@"
