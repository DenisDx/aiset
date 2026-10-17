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
.venv/bin/python -m pytest                    # library + demo2 suite
.venv/bin/python -m pytest tests              # library suite only
.venv/bin/python -m pytest demo2/tests        # demo2 host and assistant only
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

## demo2 acceptance host

```sh
./run_demo2.sh                                   # 0.0.0.0:8383 by default
./run_demo2.sh --demo2.server.port:8384          # document-scoped override
./run_demo2.sh --server.port:8384                # bare path override
DEMO2_STATE_DIR=/tmp/demo2 ./run_demo2.sh        # isolated state
```

The launcher seeds `demo2/config.json5` and `demo2/.env` from their `.example`
files only when they are absent, then runs `demo2/app.py` with `.venv/bin/python`.

Host routes: `GET /api/demo2/health`, `GET /api/demo2/status`,
`POST /api/demo2/reload`, `POST /api/demo2/restart`, `POST /api/demo2/chat`.

## Descriptor diagnostics

```sh
.venv/bin/aiset validate-descriptor examples/descriptor.json5
.venv/bin/aiset validate-descriptor examples/aiset_descriptor.json5 --strict
.venv/bin/aiset validate-descriptor examples/descriptor.json5 --format text
.venv/bin/aiset validate-descriptor demo2/descriptor.json5 --strict \
  --typedef demo2/conf2/descriptor.json5   # the component descriptor owns the templates
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