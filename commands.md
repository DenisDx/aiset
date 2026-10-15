# Commands

All commands run from the aiset directory and use the local virtual
environment `.venv/`. The system Python is never used, and aiset never creates
or switches an environment by itself (SPEC.md 3.4).

## One-time setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Tests

```sh
.venv/bin/python -m pytest                    # whole suite
.venv/bin/python -m pytest tests/test_jsonsrc.py -q   # source preservation only
.venv/bin/python -m pytest -k "comment"        # comment ownership and conflicts
./test.sh                                    # suite plus descriptor diagnostics
```

## Demo application

```sh
.venv/bin/python demo_app.py                                  # 0.0.0.0:8383
.venv/bin/python demo_app.py --aiset.port:12345              # override the port
.venv/bin/python demo_app.py --aiset.host:"127.0.0.1"         # override the bind address
.venv/bin/python demo_app.py --state-dir /tmp/aiset-demo     # isolated state
.venv/bin/python demo_app.py --config /tmp/x.json5 --descriptor /tmp/d.json5
```

The demo is a plain internal test app: HTTP only, no TLS, no Host/Origin/CSRF/CORS
checks, bind failure is reported instead of silently choosing another port.

## Descriptor diagnostics

```sh
.venv/bin/aiset validate-descriptor examples/descriptor.json5
.venv/bin/aiset validate-descriptor examples/aiset_descriptor.json5 --strict
.venv/bin/aiset validate-descriptor examples/descriptor.json5 --format text
cat examples/descriptor.json5 | .venv/bin/aiset validate-descriptor -
```

Exit status is `0` when `valid` is true, `1` when false, `2` on usage or I/O
error.

## Manual API checks against a running demo

```sh
BASE=http://127.0.0.1:8383/api/settings
curl -s "$BASE/value?document=demo&path=/log_level&view=source"
curl -s "$BASE/descriptor?document=demo"
curl -s -X POST "$BASE/validate" -H 'Content-Type: application/json' \
  -d '{"document":"demo","path":"/log_level","value_text":"\"critical\"",
       "expected_revision":"<rev>","expected_descriptor_revision":"<desc-rev>"}'
curl -s -X POST "$BASE/value" -H 'Content-Type: application/json' \
  -d '{"document":"demo","path":"/log_level","value_text":"\"critical\"",
       "expected_revision":"<rev>","expected_descriptor_revision":"<desc-rev>"}'
curl -s -X POST "$BASE/load/lkg" -H 'Content-Type: application/json' -d '{"document":"demo"}'
```

## Runtime state and Git

`git status --short` and `git diff --check` report aiset's own status, not the
parent aidir repository. `.local/`, `.venv/`, lock files, and backups are
ignored; tracked examples are never modified by the running backend.
The user controls Git: do not commit unless explicitly asked.