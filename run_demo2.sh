#!/bin/sh
# Supported entry point for the demo2 host (proposal_demo2.md section 4).
#
# It seeds missing local state, checks the local virtual environment and runs
# demo2/app.py with it. It never activates a shell environment, creates a venv,
# installs packages, overwrites an existing local file, or uses the system
# Python.
#
#   ./run_demo2.sh
#   ./run_demo2.sh --demo2.server.port:8384

set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PY="$ROOT/.venv/bin/python"
STATE="${DEMO2_STATE_DIR:-$ROOT/demo2}"

# 1. Seed editable state only when the destination does not exist.
if [ ! -e "$STATE/config.json5" ]; then
  cp "$STATE/config.json5.example" "$STATE/config.json5"
  echo "seeded $STATE/config.json5"
fi
if [ ! -e "$STATE/.env" ]; then
  cp "$STATE/.env.example" "$STATE/.env"
  echo "seeded $STATE/.env"
fi

# 2. The local interpreter must exist and be executable.
if [ ! -x "$PY" ]; then
  echo "run_demo2.sh: $PY is missing." >&2
  echo "  create it with: python3 -m venv .venv && .venv/bin/python -m pip install -e \".[dev]\"" >&2
  exit 2
fi

# 3. Run the host, forwarding every argument and the Python exit code.
DEMO2_STATE_DIR="$STATE"
export DEMO2_STATE_DIR
exec "$PY" "$ROOT/demo2/app.py" "$@"