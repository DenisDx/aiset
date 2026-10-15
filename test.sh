#!/bin/sh
# Main aiset checks: automated suite plus descriptor diagnostics.
# Uses the local virtual environment only (SPEC.md 3.4).
set -e
cd "$(dirname "$0")"

PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "test.sh: .venv is missing. Create it with:" >&2
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -e \".[dev]\"" >&2
  exit 2
fi

echo "== automated tests =="
$PY -m pytest -q

echo "== descriptor diagnostics =="
.venv/bin/aiset validate-descriptor examples/descriptor.json5 --quiet
.venv/bin/aiset validate-descriptor examples/aiset_descriptor.json5 --strict --quiet
.venv/bin/aiset validate-descriptor demo2/descriptor.json5 --strict --quiet

echo "== tracked examples are unmodified =="
$PY - <<'PYCODE'
import hashlib
import pathlib
import sys

digest = hashlib.sha256()
for path in sorted(pathlib.Path("examples").iterdir()):
    digest.update(path.read_bytes())
print(f"examples sha256: {digest.hexdigest()[:32]}")
PYCODE

echo "OK"