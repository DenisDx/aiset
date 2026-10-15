# Test Protocol

## Automated suite

```sh
.venv/bin/python -m pytest          # 230 tests, about two seconds
./test.sh                          # suite plus descriptor diagnostics
```

| File | Covers |
|---|---|
| `tests/test_jsonsrc.py` | Source preservation: the SPEC 7.1 comment-ownership fixture, mixed types, single quotes, trailing commas, CRLF, BOM, missing final newline, Unicode, escaped keys, scalar/array/object edits, comment-conflict rejection, duplicate keys, template tokens. |
| `tests/test_descriptor.py` | Envelope and grammar rules, `id` overrides, duplicate fields, mutual exclusions, `key_pattern`/`key_enum`, hooks/helper shapes, invalid defaults, unknown-property reporting (default and strict), templates, fragment composition and conflicts, inheritance, authorized export. |
| `tests/test_resolver.py` | Precedence order, POSIX `:-`, single pass, conversions and their failures, no structural injection, defaults versus absent values, provenance. |
| `tests/test_validator.py` | Exact type rules (`bool` is not `int`), numeric range and bounds, string length and patterns, array constraints, unions, required/nullable, dynamic keys, operational limits. |
| `tests/test_store.py` | Revisions, sidecar lock and timeout, atomic replacement, three write attempts with commit-state reporting, backup chain and once-per-session rotation, rollback, conflicted copies and retention, size limits, symlink policy, BOM/CRLF round trip. |
| `tests/test_service.py` | Load/read/write pipeline, absent versus null versus default, source fragments with comments, permissions and secrets, read-only, revisions and conflicts, composite edits, changed paths, hooks refusal, callbacks (sync/async/timeout), subscriptions, descriptor views, LKG fallback and explicit LKG, external edits, rollback, restart persistence. |
| `tests/test_http.py` | Route parity with Python, envelopes, status mapping (400/403/404/409/413/422/428/500), merge route, static frontend and assets, sanitized internal errors. |
| `tests/test_cli_and_demo.py` | Merge contract, Config object and mount grammar, `aiset validate-descriptor` exit codes and formats, demo seeding, overrides, non-writable state, bind failure, and an end-to-end run of the real UI and API on an ephemeral port. |

## Descriptor diagnostics

```sh
.venv/bin/aiset validate-descriptor examples/descriptor.json5
.venv/bin/aiset validate-descriptor examples/aiset_descriptor.json5 --strict
```

The demo descriptor deliberately contains project-owned metadata (`x_demo`), so
the default mode reports `UNKNOWN_DESCRIPTOR_PROPERTY` warnings and exits `0`,
while `--strict` exits `1`. This is the documented behaviour, not a defect.

## Manual browser and demo protocol

Start the demo and open `http://127.0.0.1:8383`:

```sh
.venv/bin/python demo_app.py
```

1. **Read.** Enter `/log_level`, press **Read**. The field metadata line shows
   `union, live`; the textarea shows `"info"`; the status line shows the
   revision.
2. **Validate.** Change the text to `"critical"` and press **Validate**: the
   result must be "Valid and source-preservable".
3. **Save.** Press **Save**: status must show `Stored. Application: applied`.
   The file `.local/demo/config.json5` changes on disk, and every other byte,
   including all comments, stays identical.
4. **Server-only checks.** Enter `9` for `/counters/fraction` and press
   **Save**; the server must reject it with `Must be at most 1` even though the
   browser check only warns. Nothing is written.
5. **Absent versus null versus default.** Read `/optional_leaf` (absent),
   `/nullable_field` (explicit `null`) and `/text/level_default` (absent with a
   default, shown only in the effective view).
6. **Read-only.** Try to save `/version`; the server answers `FORBIDDEN`.
7. **Comment conflict.** Replace `/logging/sinks` with
   `{ other: { target: "x" } }`; validation must report
   `COMMENT_PRESERVATION_CONFLICT` and the file must stay unchanged.
8. **Secret boundary.** Read `/credentials/api_key` with the local demo
   principal: the source fragment is returned; a restricted principal receives
   `SECRET_ACCESS_DENIED` and never a redacted fragment.
9. **Two sessions.** Open two browser tabs, read the same path in both, save in
   the first, then save in the second: the second save must report a revision
   conflict and must keep the typed text; **Read** reconciles it.
10. **Persistence.** Restart the demo; the saved value is still there and the
    tracked examples under `examples/` are byte-identical.
11. **aiset's own document.** Switch the document field to `aiset`, read
    `/storage/backup_depth`, save `3`: the change is stored in
    `.local/demo/aiset.json5` and reported as `applied`.
12. **LKG.** After at least one successful save, run
    `curl -s -X POST http://127.0.0.1:8383/api/settings/load/lkg -H
    'Content-Type: application/json' -d '{"document":"demo"}'`; the answer is
    `loaded: "lkg"` and the file on disk is untouched.

## Acceptance matrix mapping (SPEC.md section 12)

| Area | Evidence |
|---|---|
| Descriptor | `test_descriptor.py`, `test_validator.py` |
| Descriptor metadata | `test_descriptor.py` (ignored at runtime, retained in the raw view, reported with severity, strict exit status, opaque values never echoed) |
| Encapsulation | The core imports no host module, FastAPI, MCP SDK, Redis, or UI framework; the demo and the tests run the same package |
| Standalone demo | `test_cli_and_demo.py` (own backend/frontend, seeding, path overrides, isolated state, non-writable paths, tracked examples untouched) |
| Demo behavior | `test_cli_and_demo.py` (default `0.0.0.0:8383`, CLI overrides, bind failure reported) |
| Type rules | `test_validator.py` |
| Paths | `test_service.py`, `test_jsonsrc.py` (escapes, dotted keys, numeric keys, arrays, malformed pointers, absent leaves, read-only root) |
| Source preservation | `test_jsonsrc.py` (exact bytes after every accepted edit) |
| Composite editing | `test_jsonsrc.py`, `test_service.py` |
| Template resolution | `test_resolver.py` |
| Validation | `test_service.py` (no partial write, exact persisted candidate re-parsed) |
| Persistence | `test_store.py`, `test_service.py` |
| Transport parity | `test_http.py` (identical payloads, statuses, conflict codes) |
| Security | `test_service.py`, `test_http.py` (permissions, secrets, limits, sanitized errors) |
| UI | Manual protocol steps 1-12 above |
| Host compatibility | Deferred to M3; no host adapter is shipped in this repository |
| UI helpers, hooks | Deferred to M2/M4; hook-bound paths are refused with `UNSUPPORTED_CAPABILITY` |

## Not claimed

No MCP transport, no lifecycle-hook execution, no generated forms or helper
micro-forms, no batch/delete/append/reordering operations, and no AI agent
runtime exist yet. The suite passing does not claim them.