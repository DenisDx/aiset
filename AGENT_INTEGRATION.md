# AGENT_INTEGRATION.md - aiset integration guide for agents

Task-oriented guide for an agent that embeds aiset, extends it, or drives it
over HTTP. It is written to be consumed by a model: dense tables, exact
identifiers, explicit rules, no prose padding.

Read this file first, then the document it points to. Do not read the whole
repository.

| Need | Read |
|---|---|
| Integrate aiset into a new project | Sections 0 and 2a first |
| Embed aiset in a Python host | Sections 3-7 below |
| Drive aiset over HTTP or from JavaScript | Sections 6, 8-9 |
| Style the editor for a host, or adopt the reference theme | Section 8a |
| Write or fix a descriptor | Sections 7, 10 |
| Understand placeholders, views, absent/null/default | Sections 10-11 |
| Embed aiset in an async host | Section 3, and `SPEC_service.md` section 10a |
| Extend the library or the tree editor | Sections 12-14, 18 |
| Know what is forbidden | Section 1, Section 18 |
| Troubleshoot an integration | Section 16a |
| Normative interface detail | [SPEC_service.md](SPEC_service.md) |
| Full design and semantics | [SPEC.md](SPEC.md) (read-only) |
| Design rationale, invariants, pitfalls, user preferences | Section 19 |
| Commands to run | [commands.md](commands.md), [TEST.md](TEST.md) |
| Working rules of this repository | [AGENTS.md](AGENTS.md) (read-only) |

Status: M1-M4 implemented, one document set, `./test.sh` green. Nothing below is
aspirational; every route, field and code exists in `src/aiset/`. The package
version is `aiset.__version__` (`aiset --version`); a descriptor must declare
`descriptor_version: "1.0"`. There is no runtime library handshake - pin a
revision, then run the host's tests after an upgrade.

---

## 0. Integration checklist

Do these in order. Each item links to the section that explains it.

1. **Pin the library.** Add `aiset` as a Git submodule or install it from a
   pinned checkout; never copy files into the host tree (2a).
2. **Register every document at startup.** One `Service`, one
   `register(document_id, path, descriptor_source, resolver=...)` per file (3,
   4). The client never chooses a path.
3. **Authenticate every request.** Pass `principal_resolver` (WSGI) or
   `principal_from_scope` (ASGI). The default is `Principal.demo()` with every
   permission - acceptable only on a trusted local demo (3, 6, 9).
4. **Mount one transport at `{base}`.** `create_app` or `create_asgi_app`,
   never a hand-written bridge (3, 6).
5. **Serve the shipped assets from the package.** `include_assets(base=...)` or
   tags pointing at `{base}/assets/`, CSS before the host sheet, scripts in
   dependency order. Do not copy the files (8, 8a.1).
6. **Mount the editor and theme it by variables.** `aiset.mountTree(...)`;
   override `--aiset-*` in the host sheet; do not restyle by position (8, 8a).
7. **Implement the apply contract.** `SetResult.application.state` is `applied`,
   `reload_required` or `restart_required`; honour it and never pretend a
   restart is live (5).
8. **Write with revisions.** Send the `revision` and `descriptor_revision` from
   the read; a missing pair is `428`, a stale pair is `409` (5, 13).
9. **Test the integration, not only the library.** Assets through the proxy,
   permission denial, one end-to-end write, `aiset.classes()` coverage (8a.6,
   8a.7, 15).
10. **Know the failure map.** An empty page is almost always an asset path or
    script order; an unstyled tree is a missing stylesheet, not a broken editor
    (16a).

---

## 1. Hard rules

Rules 1-5 and 8 describe work **inside the aiset repository**. An agent embedding
aiset in another project uses that host's virtualenv, path and Git workflow; the
rules that always hold for an integration are 6 and 7. Do not copy aiset's
repository rules into a host and do not edit the host's protected files.

1. The system Python is never used. Every command goes through
   `.venv/bin/python`, `.venv/bin/aiset` or `./run_demo2.sh`.
2. `SPEC.md` and `AGENTS.md` are read-only. A required correction goes into
   `SPEC_.md` in the format of `AGENTS.md` (one section per correction: exact old
   text, reason, recommended new text).
3. Do not touch files outside this directory in this working session.
4. Do not modify `examples/` — it is the frozen fixture set (`test.sh` prints its
   digest). Demo material belongs in `demo2/`.
5. Git belongs to the user. No commit, amend, or push without an explicit ask.
6. Do not reimplement library behaviour inside a host: tree snapshots,
   operations, validation, revision handling and the editor are library
   contracts, not host utilities. Mount `create_asgi_app` rather than writing
   a WSGI bridge; a WSGI bridge cannot carry an asynchronous principal and
   `starlette.middleware.wsgi` is deprecated.
7. The server is authoritative. Browser-side checks are advisory and must never
   block a submission the server would accept.
8. After a change: tests, `./test.sh`, `SPEC_service.md` if the interface moved,
   `IMPLEMENTATION_LOG.md`, `memory/context.md`, `memory/history.md`, and
   `DOCUMENTS.MD` if a document was added.

## 2. Vocabulary

| Term | Meaning in aiset |
|---|---|
| document | One allowlisted configuration file registered by the host under an id; the client never passes a file path. |
| descriptor | The schema of a document: allowed keys, types, defaults, constraints, apply policy, `env` policy. |
| path | JSON Pointer. The root is the **empty string** `""`, never `"/"`. |
| view | Which value a read returns: `source` (bytes as written) or `effective` (resolved). |
| revision | Opaque hash of the file bytes (`revision`) or of the descriptor (`descriptor_revision`). |
| operation | One structural edit: `set`, `add`, `remove`, `move`, `rename`, `drop` (section 13). |
| batch | A list of operations validated and written as one candidate; any failure leaves the file unchanged. |
| principal | An authenticated actor carrying permissions; every read or write of a document takes one (registration and descriptor validation do not). |
| staged | An edit held in the browser until the user applies it; aiset never writes partially. |
| shape | One alternative of a `union` (`children_options[index]`). |
| template | A stored `${VAR}` / `${VAR:-default}` token; resolved for the effective view, never rewritten by a read. |
| absent / null / default | Three different states. Absent: key not in the file. Null: key present with `null`. Default: absent, descriptor supplies a value. |

## 2a. Installing into another project

aiset is a separate project with its own tests and history. A host consumes it
in one of two supported ways; both pin an exact revision.

**As a Git submodule (the aidir layout).** The importable package is
`<host>/aiset/src/aiset`, and the assets are `<host>/aiset/src/aiset/assets`.
Add the submodule, then put its `src` on `sys.path` before importing:

```sh
git submodule add https://github.com/DenisDx/aiset.git aiset
git submodule update --init --recursive
git -C aiset rev-parse HEAD          # record this revision in the host lock/README
```

```python
import sys
from pathlib import Path

AISET_SRC = Path(__file__).resolve().parent / "aiset" / "src"
if AISET_SRC.is_dir():
    sys.path.insert(0, str(AISET_SRC))
```

**As an installed package.** aiset requires Python 3.10 or newer and has no
runtime dependencies, so a normal install is enough and the assets travel inside
the wheel:

```sh
python -m pip install "./aiset"                         # from a local checkout
python -m pip install "git+https://github.com/DenisDx/aiset.git@<sha>"
```

**Do not vendor or copy the package into the host**, and do not edit files in
`aiset/` from the host repository: a copy silently rots and a local edit
disappears at the next update. A host change that aiset needs is a change to
aiset, made in aiset's repository.

**The namespace-package trap.** If the host root is on `sys.path` and contains
an `aiset/` directory but `aiset/src` is not importable, `import aiset` can still
succeed: Python treats the bare directory as a PEP 420 namespace package. The
result has no `resolver`, no `__version__` and no assets. Check what the host
actually imports, not the name:

```python
import importlib

REQUIRED = ("aiset.resolver", "aiset.service", "aiset.store", "aiset.asgi", "aiset.merge")
for name in REQUIRED:
    importlib.import_module(name)
```

If `import aiset.resolver` failed once, `sys.modules["aiset"]` may still hold the
stub. Discard `aiset` and every `aiset.*` entry before inserting the real `src`
path, then retry. A good host error names the missing path and the two install
commands instead of "No module named aiset".

**Version and compatibility.** `aiset.__version__` (and `aiset --version`) is
the package version; a descriptor must declare `descriptor_version: "1.0"`, and
an unsupported value is rejected at compile time. There is no library ABI
handshake: pin the submodule commit or package version, and run the host tests
after every upgrade. `aiset.assets.ASSETS_DIR` points at the installed assets;
`include_assets()` and the default `create_app`/`create_asgi_app` use them
without a `static_dir`.

---

## 3. Minimum viable integration

```python
import os
from pathlib import Path

from aiset.httpd import create_app
from aiset.resolver import Resolver
from aiset.service import Principal, Service

dotenv_mapping = {}  # parsed by the host; aiset never reads a .env by itself

service = Service()
service.register(
    "main",                                   # document id used by every later call
    "/srv/app/config.json5",                  # the only file this process may touch
    Path("descriptor.json5").read_text(),
    resolver=Resolver(overrides={}, dotenv=dotenv_mapping, environ=os.environ),
)

app = create_app(
    service,
    base="/api/settings",          # keyword-only
    principal_resolver=resolve_session,  # REQUIRED in production; see below
)
# wsgiref.simple_server.make_server(host, port, app).serve_forever()
```

**The default principal is a demo principal with every permission.** When
`principal_resolver` (WSGI) and `principal_from_scope` (ASGI) are both omitted,
the dispatcher uses `Principal.demo()`, just like the standalone demo. That is
convenient for a local acceptance page and unacceptable for a host that is
reachable by anyone else: pass a resolver that authenticates the request and
returns a `Principal` with only the permissions that actor needs (section 9).
The library does no authentication, TLS, CORS or CSRF work itself.

```python
# WSGI: environ -> Principal. Return an empty-permission principal, not None,
# when the request is anonymous; auth is the host's decision.
VIEWER = frozenset({"settings_read_source", "settings_read_effective"})
EDITOR = VIEWER | {"settings_validate", "settings_write"}

def resolve_session(environ):
    session = read_session(environ)          # host code
    if session is None:
        return Principal(id="anonymous", permissions=frozenset())
    return Principal(id=session.user_id, permissions=EDITOR if session.can_edit else VIEWER)
```

```python
# ASGI: scope -> Principal | None. May be async; an awaitable is awaited first.
async def resolve_session(scope):
    session = await read_session(scope)      # host code
    if session is None:
        return None                          # falls back to the WSGI resolver
    return Principal(id=session.user_id, permissions=EDITOR if session.can_edit else VIEWER)
```

A typical split is viewer (`read_source`, `read_effective`), editor (`+ validate`,
`write`) and administrator (`+ read_secret`, `edit_secret`, `load_lkg`,
`descriptor_raw`). Do not give the editor `settings_read_secret` or
`settings_edit_secret` unless it is meant to see and change secrets.

An async host (FastAPI, Starlette, uvicorn) mounts the ASGI adapter instead of
building a WSGI bridge of its own. It shares the dispatcher, and
`principal_from_scope` covers the case the synchronous `principal_resolver`
cannot:

```python
from aiset.asgi import create_asgi_app

app = create_asgi_app(service, base="/api/settings", principal_from_scope=resolve_session)
```

FastAPI/Starlette mount (the prefix is stripped by the mount, so `base=""`):

```python
from fastapi import FastAPI
from aiset.asgi import create_asgi_app

host = FastAPI()
host.mount(
    "/api/settings",
    create_asgi_app(service, base="", principal_from_scope=resolve_session),
)
# Browser: /api/settings/tree, /api/settings/assets/aiset-tree.js, ...
# Python tests: the mounted app receives /tree and /assets/... .
```

The service is synchronous. `create_asgi_app` runs dispatch in a worker thread
(`asyncio.to_thread`) whenever a loop is running, so a large snapshot does not
stall the host's event loop. `principal_from_scope` is the only hook that may
await; a slow synchronous authentication call still blocks the worker, which is
the intended boundary.

`/assets/*` (and `{base}/assets/*`) is served from the installed package with or
without `static_dir`, so a host that mounts only the API at `{base}` still gets
the editor from the same mount.

**Mount prefix vs `base`.** `base` must match the path the application actually
receives, not the public URL:

- A reverse proxy that forwards `/api/settings/...` unchanged (nginx
  `proxy_pass http://backend;`) keeps the path; use `base="/api/settings"`.
- A framework mount strips the prefix before the app sees it (Starlette
  `app.mount("/api/settings", asgi)`, WSGI `DispatcherMiddleware`); use
  `base=""` and let the mount supply the prefix. Do not pass
  `base="/api/settings"` there, or every route becomes `/api/settings/tree` and
  the app sees only `/tree`.
- The browser still requests the public URL. With a mount at `/api/settings`
  and `base=""`, the assets are `/api/settings/assets/...`; with
  `base="/api/settings"`, they are also `/api/settings/assets/...` but the app
  handles the prefix itself.
- `apiBase` in `mountTree` and `include_assets(base=...)` take the **public**
  path, independent of `base`.

Rules for that snippet:

- Registration compiles the descriptor and fixes the allowlist. Register every
  document once at startup, before serving; a request can name only a registered
  id, never a file path.
- `Resolver` inputs are injected, never read from a global; tests must not depend
  on the process environment. Precedence is host overrides, process environment,
  the supplied `.env` mapping, the inline `:-` default, then the descriptor
  default (section 10).
- A principal without `settings_read_secret` never receives a secret subtree: the
  whole subtree is denied, not redacted.
- `principal_from_scope` may be sync or async; an awaitable is awaited before
  dispatch. Returning anything other than a `Principal` falls back to the other
  resolver, and eventually to the demo principal - do not rely on that fallback.
- `Service(settings=Settings(...))` overrides backup depth, lock and callback
  timeouts, symlink policy and the `Limits` (file/body size, depth, collection
  size, string length). It does **not** enable file polling; call `reread`/`load`
  yourself. Keep the defaults unless the host has a measured reason to change
  them.

## 4. Object model and lifecycle

```
Service
├── documents: {document_id -> DocumentRegistration{document_id, store, descriptor, resolver}}
├── states:    {document_id -> DocumentState{document, revision, provenance, invalid_on_disk, ...}}
├── register(document_id, path, descriptor_source, resolver=, typedef_sources=, fragments=)
├── load / load_lkg / reread        read a document (validate, keep LKG)
├── get / validate / set            one path, source or effective view
├── validate_document               validate a whole candidate source
├── tree                            one authorized snapshot of a subtree
├── apply_operations                one atomic batch (dry_run for validation)
├── doctor                          diagnose and optionally repair a file
├── env_status                      which variables are set (booleans only)
├── rollback                        restore the last known good file
├── list_documents                  ids visible to a principal
├── subscribe / on_probe_changes / on_after_save / on_application
└── descriptor / validate_descriptor
```

Call order for a host: `register` once at startup, then per request
`get`/`tree` (read) or `apply_operations` (write). `load` is implicit on first
use. The service caches that state: an external edit is adopted on `reread` /
`POST /load`, not by a plain `get`/`tree`. A write against a stale cache fails
with `REVISION_CONFLICT` (409), so re-read before retrying. This build does not
poll the file; `Settings.reread_interval_seconds` is carried but unused.

Callback contracts. Arguments are positional and fixed; a callback that cannot
receive them is refused at registration with `TypeError`. Each may be sync or
async.

| Registration | Callback receives | When |
|---|---|---|
| `on_probe_changes(cb)` | `(previous_stored, new_stored, changed_paths)`; return a `Rejection` to veto | before persistence |
| `on_application(cb)` | `(previous_effective, new_effective, changed_paths)` | after commit, only for `live`/`reload` changes |
| `on_after_save(cb)` | `(previous_stored, new_stored, event)`, where `event` is `ChangeEvent.to_dict()` | after commit |
| `subscribe(document_id, paths, cb, ...)` | `(event)`, where `event` is a `ChangeEvent` object | after commit, when a covered path changed |

`ChangeEvent` fields: `document`, `changed_paths`, `previous_revision`,
`revision`, `application_state`, `active_revision`. Callbacks run outside the
lock, are bounded by the callback timeout, and never undo a committed write.

## 5. Python API

Every method except `register`, `reread` and `validate_descriptor` requires a
`principal`. Every write signature requires **both** revision keywords and a
non-empty value: pass the `revision` and `descriptor_revision` a previous read
returned. `None` or a missing pair is refused with `REVISION_REQUIRED` (HTTP
428), not treated as "whatever is current". `doctor` may omit them for a
report-only run; a repair without them still writes only after the normal
revision check.

| Call | Returns | Permission | Notes |
|---|---|---|---|
| `register(document_id, path, descriptor_source, *, resolver=None, typedef_sources=(), fragments=())` | `DocumentRegistration` | none | Once per document at startup; the allowlist. A symlink is allowed unless `Settings.symlinks_allowed=False`. |
| `load(document_id, *, principal)` | `LoadResult` | `settings_read_effective` | Validates and caches; returns `revision`, `descriptor_revision`, `provenance`, `issues`. |
| `load_lkg(document_id, *, principal)` | `LoadResult` | `settings_load_lkg` | Falls back to the last valid file when the current one is invalid. |
| `reread(document_id, *, principal=None)` | `LoadResult` | none | Explicit re-read after an external edit. Host-internal: it returns effective values and is not exposed over HTTP. |
| `get(document_id, path, *, view="source", principal)` | `GetResult` | `settings_read_source` / `settings_read_effective` | `value_text` is the source fragment; `effective` the resolved value. |
| `validate(document_id, path, value_text, *, expected_revision, expected_descriptor_revision, principal)` | `ValidateResult` | `settings_validate` | `valid`, `preservable`, `issues`; writes nothing. |
| `validate_document(document_id, source, *, principal)` | `ValidateResult` | `settings_validate` | Validate a whole candidate document; writes nothing, no LKG. |
| `doctor(document_id, *, principal, fix=False, expected_revision=None, expected_descriptor_revision=None)` | `DoctorReport` | `settings_read_effective`; `settings_write` only when `fix` requests a write | Report every issue with a fix class; `fix` repairs the named classes. Writes only when the result is fully valid; the revisions are optional for a report. |
| `set(document_id, path, value_text, *, expected_revision, expected_descriptor_revision, principal)` | `SetResult` | `settings_write` | One path; probes, hooks, callbacks, application. |
| `tree(document_id, path="", *, view="source", principal)` | `dict` | same as `get` | Snapshot; see section 12. |
| `apply_operations(document_id, operations, *, expected_revision, expected_descriptor_revision, principal, dry_run=False)` | `OperationsResult` | `settings_validate` / `settings_write` | Atomic batch; see section 13. |
| `env_status(document_id, names, *, principal)` | `dict[str, bool]` | `settings_read_source` | Presence only; at most 64 valid names; values never returned. |
| `rollback(document_id, reason, *, principal)` | `SetResult` | `settings_write` | Restore the previous valid file. No revision pair; it is a host recovery action, not a user edit. |
| `subscribe(document_id, paths, callback, *, principal=None)` | `Subscription` | `settings_read_effective` when a principal is given | Host-internal callbacks may omit it; pass one for a user-facing subscription. Call `unsubscribe()` when done. |
| `list_documents(*, principal)` | `list[str]` | `settings_read_source` | Sorted registered ids; `public_documents=True` exposes it without a principal over HTTP. |
| `descriptor(document_id, *, view="authorized", principal)` | `DescriptorResult` | none for `authorized`; `settings_descriptor_raw` for `raw` | `authorized` hides project metadata and raw definitions; `raw` is trusted-host only. A descriptor carries no stored values. |
| `validate_descriptor(descriptor_source, *, mode="default", principal=None)` | `DescriptorResult` | none | Development operation; needs no registered document and writes nothing. |

Result objects expose `.to_dict()`; the HTTP layer returns exactly that.

`SetResult.application.state` is the host contract: `applied`,
`reload_required`, `restart_required`, or `apply_failed`, derived from the most
restrictive `apply` of the changed paths (SPEC_service.md section 4). `live` is
the only state that advances `active_revision`.

## 6. HTTP API

`create_app(service, *, base="/api/settings", principal_resolver=None,
static_dir=None, assets_dir=None, static_map=None, public_documents=False)`
serves everything below. `principal_resolver(environ)` must map the incoming
request to a `Principal`; when it is omitted the demo principal is used. There is
no authentication, TLS, CORS or CSRF logic in the library: the host owns
authentication and must wrap the app.

`/health` is public. `GET /descriptor` (`authorized`) and
`POST /descriptor/validate` need no permission; every other route checks the
permission named in sections 5 and 9. In particular `GET /documents` requires
`settings_read_source`; a host that wants a public document list (a liveness
probe) opts in with `public_documents=True`.

| Method | Route | Input | Success payload |
|---|---|---|---|
| GET | `/health` (also `/api/health` and `{base}/health`) | - | `{"ok": true, "aiset": "..."}` |
| GET | `/descriptor` | `document`, `view=authorized\|raw` | descriptor envelope; `authorized` needs no permission, `raw` needs `settings_descriptor_raw` |
| GET | `/value` | `document`, `path`, `view=source\|effective` | `GetResult` |
| GET | `/tree` | `document`, `path`, `view` | `{"ok": true, ...snapshot}` |
| GET | `/documents` | - | `{"ok": true, "documents": [...]}` |
| POST | `/validate` | `document`, `path`, `value_text`, revisions | `ValidateResult` |
| POST | `/value` | same | `SetResult` |
| POST | `/document/validate` | `document`, `source` | `ValidateResult` for a whole candidate |
| POST | `/document/doctor` | `document`, `fix`, revisions | `DoctorReport` |
| POST | `/operations` | `document`, `operations`, revisions | `OperationsResult` (writes) |
| POST | `/operations/validate` | same | `OperationsResult` with `dry_run: true` |
| POST | `/env` | `document`, `names` | `{"ok": true, "present": {...}}` |
| POST | `/load` | `document` | `LoadResult` |
| POST | `/load/lkg` | `document` | `LoadResult` |
| POST | `/descriptor/validate` | `descriptor_source`, `mode=default\|strict` | diagnostic; no document and no permission |
| POST | `/merge` | `base`, `update`, `prefer=base\|update` | `{"ok": true, "prefer": ..., "merged": ...}` |

Success envelope: `{"ok": true, ...}`.
Error envelope: `{"ok": false, "error": {"code", "message", "issues"?}}`.

Writes and validation require **both** `expected_revision` and
`expected_descriptor_revision` in the JSON body; a missing pair is `428`.
`POST /document/doctor` accepts them optionally for a report-only run. A read
returns both values, and `GetResult` also carries `etag`, a strong hash of the
pair; use the two fields, not the `etag`, for a write.

| Code | HTTP | Cause and fix |
|---|---|---|
| `BAD_REQUEST`, `PARSE_ERROR` | 400 | Malformed request or source fragment. |
| `UNAUTHORIZED`, `FORBIDDEN`, `SECRET_ACCESS_DENIED` | 401/403 | Principal lacks the permission, or a secret subtree was addressed. |
| `NOT_FOUND` | 404 | Unknown document, path or route. |
| `NO_VALID_BACKUP` | 404 | `rollback`/`load_lkg` found no valid backup. |
| `REVISION_CONFLICT`, `COMMENT_PRESERVATION_CONFLICT` | 409 | The file changed underneath, or comments cannot be preserved. Re-read and re-apply; never overwrite. |
| `PAYLOAD_TOO_LARGE` | 413 | A limits rule was exceeded. |
| `VALIDATION_ERROR`, `INVALID_DESCRIPTOR` | 422 | Candidate violates the descriptor; `issues` carries path, code, message. |
| `REVISION_REQUIRED` | 428 | A write arrived without `expected_revision` or `expected_descriptor_revision`. Always send both. |
| `LOCK_TIMEOUT` | 503 | Another writer holds the sidecar lock. Retry, do not force. |
| `CALLBACK_TIMEOUT` | 504 | A host callback exceeded its budget. |
| `STORAGE_ERROR`, `INTERNAL_ERROR` | 500 | Disk or unexpected failure; details are sanitized. |
| `UNSUPPORTED_CAPABILITY` | 501 | The host asked for something not implemented. |

## 7. Descriptor grammar in one screen

```json5
{
  descriptor_version: "1.0",
  project: "myapp",
  config_version: "1.0",
  root: {
    type: "object",
    description: "…",
    children: {
      port: {
        type: "int",                  // string int number bool null object array union any
        description: "Listen port",
        minimum: 1, maximum: 65535,  // min_length max_length pattern enum const
        min_items: 0, max_items: 16, unique_items: true,   // arrays
        default: 8383,               // absent key -> effective value, never written
        nullable: false,             // explicit null allowed
        // required: true,           // NOT with default; required means present
        read_only: false,
        secret: false,               // subtree denied without settings_read_secret
        apply: "live",               // live | reload | restart (inherited)
        env: { allowed: true, convert: "int" },   // convert: string int number bool
        ui: { widget: "textarea", rows: 3, placeholder: "…" },
        // children: {},             // object members, or the item type of an array
        // additional_children: {},  // dynamic member type
        // children_options: [],     // shapes of a union
        // typedef: "name",          // reuse a declared template
        validators: [], hooks: {}, helper: {}, title: "", id: "stable-id",
      },
      tags: {
        type: "array",
        children: { type: "string", description: "One tag" },   // the item type
      },
      entries: {
        type: "object",
        additional_children: { type: "string", description: "One entry" },
        key_pattern: "^[a-z]+$", key_enum: ["a", "b"],   // dynamic object keys only
      },
    },
  },
}
```

This is a property reference, not a valid node: use the properties that fit the
type. `children` (object members or array item type), `additional_children`
(dynamic object), `children_options` (union) and `typedef` are alternatives, not
simultaneous declarations.

- `type: "any"` is the opaque type: a region the host owns and the library does
  not inspect. It accepts every JSON value including `null`, keeps no composite
  key or key constraint, is a `leaf` in a snapshot, and is edited as source text.
  Operational limits still apply; a `${VAR}` inside it stays literal.
- `type: "null"` accepts only an explicit `null`. It is distinct from
  `nullable: true`, which lets any of the other types store `null`.
- `required: true` and `default` are mutually exclusive: a required key must be
  present, so the grammar rejects a declared default for it. The doctor cannot
  invent a required value and reports it instead (section 13.1).
- `apply`, `secret` and `read_only` are inherited from the nearest ancestor when
  the node does not set them. A node with no `apply` asks for `restart`; `live`
  must be stated explicitly. `secret` denies reads without
  `settings_read_secret` and writes without `settings_edit_secret`;
  `read_only` refuses every write below it.
- `default` is an effective-view value only: it is never written back and does
  not change `exists`.
- A `union` is a list of alternatives in `children_options`; each alternative is
  an ordinary inline node or a `typedef`. Validation accepts a value that fits
  any alternative. For a child path, `node_at` resolves through the first
  alternative that declares the key, which is why a union object can be edited
  member by member even though the union itself is a leaf in the descriptor.
- `key_pattern` and `key_enum` constrain the keys of an object that has
  `additional_children`; they do not describe fixed `children`.
- `validators`, `helper` and `hooks` are recognized and carried into
  `describe()`. The library does not execute custom validators; a host that needs
  them runs its own check. Helper forms are a browser extension:
  `node_form` is built in, and another tag requires
  `aiset.registerHelper(tag, factory)`. Hook bindings are recognized but **not
  executed** in this revision: a write touching one is refused with
  `UNSUPPORTED_CAPABILITY`, and the snapshot reports
  `capabilities.unsupported = "hooks"` with every action false. Do not build a
  host around hooks yet.
- Unknown properties are warnings by default and errors under `--strict`.
  `.venv/bin/aiset validate-descriptor <file> --strict` is the typo gate; at
  runtime unknown project metadata is accepted on purpose.
- Validate before shipping: `.venv/bin/aiset validate-descriptor <file> --strict`
  (exit `0` valid, `1` invalid, `2` usage/IO error).
- Reference files: `examples/descriptor.json5` (full fixture matrix, frozen),
  `demo2/descriptor.json5` (editable demo), `demo_aidir_config.template.json5`
  (host descriptor for aidir).

## 8. Frontend integration

Shipped assets: `aiset.js`, `aiset.css`, `aiset-tree.js` (served from
`/assets/`). A reference theme, `aiset-host-theme.css`, also ships but is **not**
loaded by `include_assets()` - a host opts into it (8a.4). Python helpers:
`include_assets(base="/assets")` returns the `<link>` and `<script>` tags;
`render_tree_editor(document)`, `render_node_editor(document, path)` and
`render_full_editor(document)` return HTML fragments that include those tags.
The fragments are **not auto-mounted**: call `aiset.mountTree(...)` after the
DOM is ready, or render only the empty `<div>` and mount it yourself.
`render_tree_editor("main")` produces `[data-aiset-tree="main"]`, so a host can
mount it with
`aiset.mountTree('[data-aiset-tree="main"]', {document: "main", ...})`; the div
must be in the DOM first.

`include_assets()` emits plain tags (no `defer`). Put them after the mount point,
or load the host script with `defer` in the same order as the manual example
below; aiset must be defined before the host calls `mountTree`.

`assets_dir` on `create_app`/`create_asgi_app` points at a different directory of
asset files (a host-owned copy, for example). Leave it unset to serve the
package's own files; those are the files the library tests exercise.
`static_dir` plus `static_map` serve host-owned files through the same app:
`static_map` is `{URL path: file name inside static_dir}`. The bundled
`/assets/*` routes are independent of both.

`aiset.classes()` returns the class inventory as data
(`{name, element, role, required}`), for a host coverage check (8a.2, 8a.7).

```html
<link rel="stylesheet" href="/assets/aiset.css">
<link rel="stylesheet" href="/assets/aiset-host-theme.css">  <!-- optional -->
<link rel="stylesheet" href="/styles.css">
<script src="/assets/aiset.js" defer></script>
<script src="/assets/aiset-tree.js" defer></script>
<script src="/app.js" defer></script>
<div id="settings-tree"></div>
```

```js
const tree = aiset.mountTree("#settings-tree", {
  document: "demo2",
  apiBase: "/api/settings",
  lifecycle: [{ id: "restart", label: "Restart", url: "/api/demo2/restart", confirm: "…?" }],
});
tree.on("staged", (operations) => console.log(operations));
```

A lifecycle action is `{id, label, url, confirm?, body?, reloadAfter?}`. The
editor only POSTs it and, by default, reloads the tree afterwards; it never
restarts a process itself. A host that restarts must keep the staged batch in the
browser and reconnect after the restart.

The mount target is owned by the editor: `mountTree` clears it and builds the
toolbar, tree, staged list, status and issues blocks. Mount one instance per
target and call `destroy()` before replacing it (switching documents, for
example); instances share no mutable state.

| Option | Default | Meaning |
|---|---|---|
| `document` | required | Document id. |
| `apiBase` | `/api/settings` | Transport base. |
| `view` | `source` | Snapshot view. |
| `lifecycle` | `[]` | Host buttons; the editor never restarts a process itself. |
| `viewButtons` | `true` | Show **Expand all** / **Collapse all**. |
| `valuesAsText` | `false` | Show the stored text of objects and arrays. |
| `showAbsent` | `false` | Show declared keys the file does not contain yet. A union object/array alternative's declared keys are its template and are always shown (see below). |

| Instance method | Effect |
|---|---|
| `getPendingOperations()` | Copy of the staged batch. |
| `stageOperations(operations, source)` | Add or replace staged operations. |
| `revert(path)` | Drop staged operations for one path. |
| `validatePending()` / `applyPending()` | Validate / commit the batch. |
| `reload(confirmFirst)` | Re-read from the server. |
| `expandAll()` / `collapseAll()` | Open or close every section (root stays open). |
| `setValuesAsText(flag)` / `getValuesAsText()` | View switch and its current value. |
| `setShowAbsent(flag)` / `getShowAbsent()` | View switch and its current value. |
| `runLifecycle(action)` | POST `action.url` with `action.body` (default `{document}`); reload unless `action.reloadAfter === false`. |
| `on(event, handler)` | `loaded`, `staged`, `validated`, `applied`, `status`, `lifecycle`, `viewchange`, `env`. |
| `destroy()` | Detach listeners and clear the host element. |

Every node offers three editing modes: the typed control per declared type, raw
source editing (`{..}` button, subtree hidden, server-validated `set`), and the
placeholder mode (variable name + typed inline fallback; an empty name stores
the inline value). A node whose descriptor sets `env.allowed` gets a `.env`
button that switches it into placeholder mode.

A `union` node is edited through the control of its active alternative: an enum
string becomes a select, an `int`/`number` a number field, a `bool` a checkbox, a
string a text field, a substitution its variable plus a typed fallback, and an
object/array an expanded subtree. The active alternative is, in order, the shape
the user picked, `matched_option`, or the one inferred from `value_text`. A
union object/array alternative's declared keys are the template of the shape and
are rendered even when `showAbsent` is off; if the snapshot does not contain the
shape, its children are synthetic and a field edit composes one `set` on the
union path. The `shape…` chooser never rewrites a value that already matches the
chosen alternative, and stages a sample only when it replaces it.

Browser rules that are not optional:

- Load the scripts with `defer` in dependency order; touching the DOM before
  `DOMContentLoaded` leaves the page silently empty.
- No framework, no build step, no CDN; the assets must stay framework-free.
- Serve static assets with `Cache-Control: no-cache` (aiset does); a stale cached
  script is indistinguishable from a broken one.

## 8a. Host stylesheet: the design is the host's job

aiset emits the markup and ships `aiset.css` as **light-theme defaults only**. It
does not ship a design, and it must not: it cannot know whether a host is dark,
light, dense or airy. **A host that loads `aiset.css` and nothing else gets a
correct, working tree** - the library now owns the structure that makes a tree a
tree (row layout, the nesting indent, the guide line, a focus ring), so the
undesigned case degrades to *plain*, not *unreadable*. The colours are neutral
light defaults routed through `--aiset-*` custom properties, so a host theme is a
variable block, not a specificity contest.

A fully undesigned editor still has no failure signal of its own: it mounts,
every request returns `200`, every node renders, `Apply` writes the file.
`mountTree` therefore warns once when no rule matches the editor root, and a
reference theme ships for a host to adopt (see 8a.4).

| Who owns | What |
|---|---|
| Library | Markup, behaviour, semantics, the `--aiset-*` variable defaults, and enough structure that a tree is never *unreadable* (see the split in 8a.8) |
| Host | Every colour, size, spacing, font and state treatment, expressed as variable overrides and rules |

### 8a.1 Load order, and why it is not optional

```html
<link rel="stylesheet" href="/assets/aiset.css">          <!-- library defaults -->
<link rel="stylesheet" href="/assets/aiset-host-theme.css"> <!-- optional theme -->
<link rel="stylesheet" href="/host-settings.css">          <!-- host design, LAST -->
```

`aiset.css` declares its palette and its structural tunables as `--aiset-*`
custom properties on `:root`, so a host overrides *values*, not selectors, and
the cascade stops being a contest. The host sheet should still come last: it
overrides the library's structural defaults (row layout, indent) by load order,
and its variable block must win.

Do not edit `aiset.css`, do not copy it, and do not fork it: it is served from
the installed package and your copy will silently rot at the next upgrade.
Override it from the host sheet - ideally by redefining the `--aiset-*`
variables. A ready-made starting point ships as `aiset-host-theme.css` (8a.4);
it is **not** loaded by `include_assets()`, so adopt it by linking it yourself.

### 8a.2 The class inventory

`aiset-tree.js` emits 54 classes. This table is the contract; `aiset.classes()`
returns the same list as data (`{name, element, role, required}`) - a library
test parses the source and fails if the two disagree, so a host can write its
coverage check against `aiset.classes()` instead of a regular expression over
the JavaScript (8a.7).

Every class the inventory marks `required: true` carries a rule in `aiset.css`:
the library paints the structure that makes a tree a tree (row layout, the
nesting indent, the guide line, the toggle) **and** the containers and shell
around it - the toolbar, the wrapper of a node's badges, the status and issues
blocks, the staged list. `required` is therefore a guarantee the library keeps,
not a request to the host: a host that writes no stylesheet still gets a
readable tree. Everything else is design, and the host owns it.

**The classes that carry the tree:**

| Class | Element | Meaning |
|---|---|---|
| `aiset-tree-editor` | div | Editor root. Theme scope for the host sheet. |
| `aiset-tree-row` | div | One node line: toggle, name, badges, value, controls. |
| `aiset-tree-children` | div | Nested group. **Indentation and guide line go here.** |
| `aiset-tree-desc` | div | Descriptor description of the node above it. |
| `aiset-tree-badges` | span | Wrapper around a node's badges. The library paints the wrapper and the badge. |
| `aiset-tree-badge <kind>` | span | `type`, `apply`, `origin`, `draft`, `absent`, `default`, `lock`, `unsupported`, `req`, `dirty`, `renamed`, `new`, `deleted` |
| `aiset-tree-name` | span | Key label, or a `.aiset-tree-key` input for a self-named child. |
| `aiset-tree-value` | span | Wrapper around the value control(s). |
| `aiset-tree-toolbar` | div | Holds Apply / Reload / Revert all / Expand all / Collapse all. |
| `aiset-tree-type <kind>` | span | Type mark of a leaf, in the toggle slot: `int`, `number`, `string`, `bool`, `container`, `other`. |

**Node state**, on the node element, never on the row:

| Selector | Meaning |
|---|---|
| `.aiset-tree-node[data-absent="true"]` | Declared in the descriptor, not in the file. |
| `.aiset-tree-node.is-staged` | Has a staged change. |
| `.aiset-tree-node.is-deleted` | Removal staged; stays visible until Apply. |

**Optional polish:** `aiset-tree-actions`, `aiset-tree-action` (+ `.pill` for the
captioned ones: `.env`, `{..}`, `⌂`, `↺`), `aiset-tree-icon`, `aiset-tree-icon-text`,
`aiset-tree-toggle`, `aiset-tree-toggle-type`, `aiset-tree-key`, `aiset-tree-shape`,
`aiset-tree-null`, `aiset-tree-secret`, `aiset-tree-value-readonly` (the read-only
value text; it is `aiset-tree-value` plus this state class),
`aiset-tree-template`, `aiset-tree-env`, `aiset-tree-env-state` (+ `.on` / `.off`),
`aiset-tree-union`, `aiset-tree-chooser`, `aiset-tree-button` (+ `aiset-tree-apply`,
`aiset-tree-reload`, `aiset-tree-revert`; the toolbar's commit controls, 8a.3),
`aiset-tree-view`, `aiset-tree-lifecycle` (the Expand/Collapse and reload/restart
buttons), `aiset-tree-raw`, `aiset-tree-raw-title`,
`aiset-tree-raw-text`, `aiset-tree-raw-actions`, `aiset-tree-source`,
`aiset-tree-status` (+ `[data-state]` of `ok` / `error` / `pending` / `info`),
`aiset-tree-issues`, `aiset-tree-pending`, `aiset-tree-staged`,
`aiset-tree-staged-row`, `aiset-tree-staged-path`, `aiset-tree-staged-source`,
`aiset-tree-staged-op`, `aiset-form`, `aiset-form-title`, `aiset-form-row`,
`aiset-form-label`, `aiset-form-field`, `aiset-form-control`, `aiset-form-actions`.

### 8a.3 The five traps

| Trap | What happens | Do instead |
|---|---|---|
| `aiset-tree-badges` was unstyled | Badges ran together as one run of text, because the library styled the badge and not its wrapper. The library now paints the wrapper (`display: inline-flex; gap: 4px`); a host restyles it only to change the spacing | Leave it, or restyle the wrapper as a whole |
| Apply / Reload / Revert are styled by position | They carry `aiset-tree-button` plus `aiset-tree-apply` / `-reload` / `-revert`, so rank Apply by class (`:first-child` breaks when a button is added before it) | `.aiset-tree-apply { … }`, never `:first-child` |
| Unscoped element selectors | `input[type="number"]` rules silently strip the steppers from **every** number field on the host page | Scope every rule to `.aiset-tree-editor`, `.aiset-tree-value` or `.aiset-form` |
| The host's own controls use `style="…"` | An inline declaration beats a stylesheet rule of equal specificity, so a theme can never reach them | No inline styles on host chrome; theme them from the sheet |
| Recolouring the focus ring | The library ships `.aiset-tree-editor :focus-visible { outline: 2px solid var(--aiset-accent); … }`; a host that overrides the outline must keep an affordance | Set `--aiset-accent`, or restate the `:focus-visible` rule; never leave a keyboard user with no ring |

Also worth knowing:

- **`.aiset-form` is `position: fixed; z-index: 20`.** A host with a sticky header
  or a high `z-index` topbar will cover the helper dialog. Raise the host's
  stacking context or the value.
- **`.aiset-tree-row` uses `flex-wrap: wrap`.** On a narrow viewport the value
  control wraps to its own line. That is acceptable; set a `min-width` on
  `.aiset-tree-name` so a short name does not collide with its input.
- **The host's CSS reset reaches the editor.** A global
  `* { margin: 0; padding: 0 }` removes the default padding the library sets on
  `input`, `button` and `select` inside the editor. Scope the reset or restate it.
- **Set `color-scheme`** (`dark` or `light`) so native select popups, checkbox
  ticks, scrollbars and the date picker match the host palette. It cannot be done
  from the editor, because those widgets are drawn by the browser.

### 8a.4 Reference theme

A ready-made theme ships as `src/aiset/assets/aiset-host-theme.css`. It is a
starting point, not a contract: it is **not** loaded by `include_assets()`, so
adopt it by linking it after `aiset.css` (8a.1) and edit it freely.

```html
<link rel="stylesheet" href="/assets/aiset.css">
<link rel="stylesheet" href="/assets/aiset-host-theme.css">
```

It overrides about twenty `--aiset-*` variables for a dark surface, sets
`color-scheme: dark`, and styles every class in 8a.2. A host that wants its own
palette redefines the variables instead of rewriting the sheet:

```css
:root {
  color-scheme: dark;
  --aiset-surface: #1a1d27;
  --aiset-surface-strong: #1f2331;
  --aiset-input-bg: #1a1d27;
  --aiset-border: #2a2d3a;
  --aiset-text: #d0d4e8;
  --aiset-text-soft: #d0d4e8;
  --aiset-muted: #6b7090;
  --aiset-accent: #5b8af7;
  --aiset-ok: #4caf86;
  --aiset-pending: #f0a500;
  --aiset-warn: #f0a500;
  --aiset-err: #e05555;
  --aiset-type-int: #4caf86;
  --aiset-type-string: #5b8af7;
  --aiset-type-bool: #b48ef0;
  --aiset-type-other: #6b7090;
  --aiset-indent: 22px;
  --aiset-row-pad: 2px 0;
}
```

The library's own defaults, and every name a host may override, are declared on
`:root` at the top of `aiset.css` (palette, the `--aiset-type-*` marks, and the
structural tunables `--aiset-indent`, `--aiset-guide`, `--aiset-row-gap`,
`--aiset-row-pad`). `demo2` links this theme, so there is one theme to maintain
rather than a copy per host.

### 8a.5 Host chrome: the controls around the editor

The document selector, the view checkboxes and the lifecycle buttons are the
host's own markup, not the library's. Theme them from the host sheet too, and
give them no inline `style` attributes: an inline declaration outranks a
stylesheet rule of equal specificity, so a theme can never reach it.

```html
<div class="host-settings-row">
  <label for="cfg-document">Document</label>
  <select id="cfg-document"></select>
</div>
<div class="host-settings-row">
  <label class="host-check"><input type="checkbox" id="cfg-show-absent"> Show settings that are not in the file</label>
</div>
<div class="host-lifecycle">
  <button id="cfg-reload-btn" type="button">Reload settings</button>
  <button id="cfg-restart-btn" type="button">Restart</button>
</div>
```

```css
.host-settings-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.host-settings-row > label { color: #6b7090; font-size: 12px; }
.host-check { display: flex; align-items: center; gap: 6px; font-size: 12px; cursor: pointer; }
.host-check input { accent-color: #5b8af7; width: 14px; height: 14px; margin: 0; }
#cfg-document {
  background: #1a1d27; color: #d0d4e8; border: 1px solid #2a2d3a;
  border-radius: 6px; padding: 6px 8px; font: inherit; font-size: 13px; min-width: 320px;
}
.host-lifecycle { display: flex; gap: 10px; align-items: center; margin-top: 14px; padding-top: 12px; border-top: 1px solid #2a2d3a; }
.host-lifecycle button { padding: 7px 12px; border-radius: 6px; font: inherit; font-size: 13px; cursor: pointer; }
```

Watch for a class-name clash: the host page may already have `.cfg-row`,
`.pane` or `.card` of its own. **Scope host page rules to the card or section
that contains `#settings-tree`** rather than relying on load order.

### 8a.6 Reverse proxies

Request the assets from a path the proxy actually forwards. The library serves
them at the application root **and** below the mount prefix; a proxy that forwards
only the API prefix will answer a root request for `/assets/aiset.js` with its SPA
page and status `200`, and the browser can only report that as a missing global.

```html
<!-- apiBase is /api/settings, so the assets travel the same prefix -->
<link rel="stylesheet" href="/api/settings/assets/aiset.css">
<script src="/api/settings/assets/aiset.js" defer></script>
<script src="/api/settings/assets/aiset-tree.js" defer></script>
```

`include_assets(base="/api/settings/assets")` emits the same three tags (without
`defer`) if the host renders them from Python.

The proxy must forward the asset prefix with the same precedence as the API, and
a missing file must be a **404**, never the SPA page. An nginx fragment that does
this:

```nginx
location ^~ /api/settings/assets/ { proxy_pass http://127.0.0.1:8000; }
location ^~ /api/settings/         { proxy_pass http://127.0.0.1:8000; }
location /                          { try_files $uri /index.html; }
```

`^~` keeps the SPA fallback from swallowing `/api/settings/assets/...`. If the
proxy serves the assets itself, use `try_files $uri =404;` for that location;
do not answer a missing `.js` with `index.html` and status 200, because the
browser can only report the missing global much later.

Verify before trusting the page:

```sh
curl -sI "http://localhost:8080/api/settings/assets/aiset-tree.js" | head -2
# expect: 200 and Content-Type: application/javascript - never text/html
curl -sI "http://localhost:8080/api/settings/assets/missing.js" | head -1
# expect: 404 - not 200 with the SPA page
```

The same check applies to `/assets/` if the host forwards the root asset path
instead of the prefixed one.

### 8a.7 Verifying an integration without a browser

Static checks catch the three failures that HTTP tests cannot see, because their
requests are already authenticated and their assets are already served by the
backend, never by the proxy:

| Check | Catches |
|---|---|
| Every class `aiset.classes()` names is either styled by the host or already painted by `aiset.css` | An undesigned class, which renders as bare markup |
| The host sheet is linked after `aiset.css` | A theme that silently loses the cascade |
| The host redefines `--aiset-*` rather than fighting selectors | A theme that breaks when the library adds a rule |
| No unscoped element selector in the host sheet | A rule that restyles the host's own page |
| `curl` the asset path through the proxy | HTML served as JavaScript |

The first one is the important one, and it needs no knowledge of the source
layout: `aiset.classes()` returns `{name, element, role, required}` as data, so
the check is a set comparison against the host selectors plus the selectors
already in `aiset.css`. `required: true` is the library's promise; optional
classes are the host's choice.
`webui/frontend/settings.css` and `test_settings_styles.py` in the aidir
repository are a working implementation; the library's own test
`test_host_theme_covers_every_emitted_class` does the same for the shipped theme.

### 8a.8 What the library should own, and what stays with the host

This split is the contract:

| Property | Owner | Reason |
|---|---|---|
| Row layout, the indent of `.aiset-tree-children`, the guide line, the focus ring, the toolbar shell and the badge/value wrappers | **Library** | Without them the tree is *unreadable*, not merely ugly. A host that ships no design still gets a tree. Every `required` class in 8a.2 is painted here. |
| The `--aiset-*` variable *defaults* (a neutral light palette) | **Library** | The library must work with no host sheet. |
| The variable *values*, spacing, font, radius, every state treatment | **Host** | A generated interface cannot guess a palette. |
| `color-scheme`, host chrome, proxy paths | **Host** | They are properties of the host page. |

A host overrides the structural tunables (`--aiset-indent`, `--aiset-guide`,
`--aiset-row-gap`, `--aiset-row-pad`) and the palette; it does not restate the
structure rules. `demo2/frontend/styles.css` keeps only the demo's own layout,
and the tree theme lives in `aiset-host-theme.css` (8a.4). See
`proposal_improvement4.md`.

## 9. Permissions

| Permission | Grants |
|---|---|
| `settings_read_source` | `get(view=source)`, `tree(view=source)`, `env_status`, `list_documents`. |
| `settings_read_effective` | `get(view=effective)`, `tree(view=effective)`, `load`, `subscribe`. |
| `settings_validate` | `validate`, `validate_document`, `apply_operations(dry_run=True)`. |
| `settings_write` | `set`, `apply_operations`, `rollback`, `doctor(fix=...)`. |
| `settings_read_secret` | Values under a `secret: true` node. |
| `settings_edit_secret` | Writes under a secret node. |
| `settings_load_lkg` | `load_lkg`. |
| `settings_descriptor_raw` | Unredacted descriptor export (`view=raw`). |

The `authorized` descriptor and `validate_descriptor` need no permission: they
expose the declared shape, not values. `principal_resolver` /
`principal_from_scope` is the only place authentication happens; the library
does not infer a user from a session, header or cookie.

`Principal.demo()` carries **every** permission. It exists for the standalone
demo and local acceptance runs; never return it from a production resolver.
Permissions are enforced by the service on every call, so hiding a button in a
UI is not authorization. A secret subtree is denied as a whole, never field by
field, and `secret` is inherited by descendants.

## 10. Paths and edits

- Root is `""`. `"/"` is a key with an empty name and is normally not declared.
- Escaping: `~` becomes `~0`, `/` becomes `~1`.
- Array items are addressed by index: `/fixtures/tags/1`.
- Templates: `${VAR}` and `${VAR:-default}` only; POSIX `:-` semantics.
  Substitution is single-pass: a value that looks like another placeholder is
  inserted literally, never resolved again. A resolved value is data, never
  structure: it cannot create keys or array items.
- Precedence: host overrides → process environment → the `.env` mapping supplied
  to `Resolver` → inline `:-` default → descriptor `default`. The library never
  reads a `.env` file itself.
- An empty value in `env`, `overrides` or `.env` falls through to the next
  source **only when the placeholder has an inline default**; without one it is
  the empty string. This matches POSIX `:-`.
- An unquoted placeholder requires `env.allowed`; inside a string it stays
  literal when `allowed` is false. `env.convert` (`string`, `int`, `number`,
  `bool`) converts the resolved text to the declared type; a failed conversion
  is a validation issue, not a silent fallback.
- Secrets: put the variable name in the file and the value in `.env` or the
  environment. A read never substitutes a secret into a response unless the
  principal has `settings_read_secret`.
- Writes preserve everything else byte-for-byte: comments, quoting, trailing
  commas, CRLF, BOM, Unicode, final newline.

## 11. Views, absent, null, default

| State | In the file | `source` | `effective` |
|---|---|---|---|
| stored | present | fragment | resolved value |
| absent | key missing | `exists: false` | descriptor `default`, or `origin.kind = "absent"` |
| explicit null | `null` | `"null"` | `null`, distinct from absent |
| default applied | key missing | `exists: false` | `default_applied: true` |

Never merge these three states in a host; the difference is what the user sees
and what a re-read must preserve.

## 12. Tree snapshot

`GET /tree` (or `service.tree`) returns one authorized snapshot per revision:
no per-node requests, and the stored document is never re-derived by a client.
(After a staged re-shape the editor may synthesize the fields of the shape the
user is about to apply; that preview is not part of the snapshot.)

| Field | Meaning |
|---|---|
| `path`, `type`, `kind`, `exists` | Identity. `kind` is `array`, `array_item`, `object`, `dynamic_key`, `leaf`, `undeclared`. |
| `value_text`, `effective` | Source fragment and resolved value (`view=source` omits `effective`). |
| `origin` | `file`, `default`, `environment`, `absent`. |
| `capabilities` | `edit`, `add`, `remove`, `reorder`, `add_child`, `remove_child`, `key_options`, `key_pattern`; `unsupported` names a recognized-but-unexecuted capability (for example `hooks`) and every action is then false. |
| `matched_option` | Index into `children_options` of the `union` alternative the stored value validated against; absent when none matches (a substitution is a common case). The editor infers the alternative from `value_text` when this is absent. |
| `children` / `items` | Child nodes. For a union, these are the **active alternative's** object children or array items; the union keeps `type: "union"` and the shape chooser. Do not re-derive them in a client. |
| `field` | Descriptor metadata: `type`, `title`, `description`, `default`, constraints, `enum`, `apply`, `env`, `ui`, `nullable`, `required`, `read_only`, `secret`, `children_options`, `children` (an array's item shape) and `additional_children`. |
| `additional_child` | The descriptor of a permitted dynamic key, when the node is an object collection. |
| `comments` | Source comments that introduce the node, markers removed, decorative rules dropped. |
| `template` | `name` and inline `default` of a stored `${VAR}` / `${VAR:-default}`. |
| `access_denied` | Set instead of values when a secret subtree is addressed. |
| `default_applied` | Effective view only: the descriptor default is in use. |

`kind` is decided by the parent, not by the node type: a string inside an array
is an `array_item`, because `remove` and `move` address the item path. A value
under a dynamic object key is a `dynamic_key` when it is an object, and keeps its
own shape (for example `leaf` for a scalar) otherwise; both carry `remove`. A
union whose active alternative is an object or array takes that alternative's
`kind` (`object`/`array`) and its container capabilities; a scalar union stays
`leaf`.

`remove` is set for an array, one array item, and an entry of a dynamic object
collection. `add_child` means the object accepts a new member; `remove_child`
means this node may be removed from its parent.

## 13. Operations

```json
{"op": "set",    "path": "/server/port", "value_text": "8384"}
{"op": "add",    "path": "/fixtures/tags/-", "value_text": "\"new\""}
{"op": "add",    "path": "/server/host",  "value_text": "\"0.0.0.0\""}
{"op": "remove", "path": "/fixtures/tags/1"}
{"op": "move",   "from": "/fixtures/tags/1", "path": "/fixtures/tags/0"}
{"op": "rename", "path": "/fixtures/dynamic/old_key", "to": "new_key"}
{"op": "drop",   "path": "/endpoints/0/context_builder_worker"}
```

- Operations run **in order against one candidate document**. A later operation
  sees the result of an earlier one, so one batch may create an object and then
  fill its fields (`set /tool {}` followed by `set /tool/worker`). If any
  operation fails, the batch aborts and the file is left byte-for-byte
  unchanged; there is no partial write.
- Both `expected_revision` and `expected_descriptor_revision` are required and
  non-empty. A missing pair is `REVISION_REQUIRED` (428), a stale pair is
  `REVISION_CONFLICT` (409).
- `add` on an array uses the `-` append token; on an object it names a key the
  descriptor permits. The append token is invalid for every other operation.
- `move` is an array operation (`from` and `path` are item paths).
- `remove` is refused for `required`, `const` and `read_only` nodes, and for a
  fixed declared child of an object that has no `additional_children`.
- `remove` on an object entry names its key, so a dynamic key (`/obj/some-key`)
  is deleted the same way an array item is; the entry keeps its comments with it.
- `rename` changes one object key in place, keeping the value and its comments as
  one entry (never a `remove` plus an `add`). `to` is the new key, checked like
  an `add` key; a fixed declared child is refused. The editor stages this when
  the user edits a key field.
- `move` carries the item with its comments.
- `drop` removes a key the descriptor does **not** declare. It exists for the
  doctor: `remove` resolves the node first and answers `NOT_FOUND` for exactly
  that case. `drop` refuses a declared path, a read-only parent, a union whose
  alternatives are read-only or `const`, and a secret subtree without
  `settings_edit_secret`.
- One batch, one revision, all-or-nothing: the first failure aborts everything
  and the file stays byte-for-byte unchanged.
- `value_text` is JSON5 source text: strings carry their quotes. `rename` uses
  `to` (the new key) and no `value_text`; `move` uses `from` and `path`.
- `dry_run=True` (or `POST /operations/validate`) returns the same result shape
  with `dry_run: true`, `valid` and `issues`, and writes nothing. It needs
  `settings_validate`, not `settings_write`.

### 13.1 Repairing a drifted document: `doctor`

`doctor` reports every issue with the one fix class that could handle it, and
`fix` applies the named classes. `fix=True` means `clamp` only.

| Class | Repair | Safe? |
|---|---|---|
| `clamp` | number to its declared `minimum`/`maximum` | yes |
| `coerce` | `"8080"` to `8080` for an unambiguous literal | opt-in |
| `drop_unknown` | remove a key the descriptor does not declare | lossy |

Report-only: `const`, `enum`, `pattern`, lengths, keys, `required` (there is no
default for a required node in this grammar), `env_*`, secrets, read-only nodes
and parse errors. A `union` is report-only except for the undeclared-key case
below.

- A `union` issue that names an `undeclared_field` is repaired by dropping that
  key under the union path, but only when no alternative declares it.
- The file is written **only if the repairs make it fully valid**; a partial fix
  of an invalid file is refused and explained in `skipped`.
- A secret/read-only/`const` ancestor is never repaired and never appears in
  `before`/`after`.
- The file on disk is inspected, never the LKG fallback.
- CLI: `aiset doctor --config F --descriptor D [--env F] [--fix] [--class C]...`;
  exit `0` valid, `1` issues remain, `2` repairs applied but issues remain.
- HTTP: `POST {base}/document/doctor`; `fix` is a boolean, a class name or a
  list.

## 14. Extending the library

| Change | Files that must move together |
|---|---|
| New service method | `service.py`, `httpd.py` route, `SPEC_service.md`, `tests/test_service.py`, `tests/test_http.py` |
| New transport or route | `httpd.py` dispatcher (shared), `asgi.py` when a transport changes shape, `SPEC_service.md`, `tests/test_asgi.py`, `tests/test_http.py` |
| Resolver behaviour | `resolver.py`, `descriptor.py` node_at, `SPEC_.md` correction, `tests/test_resolver.py` |
| New descriptor property | `descriptor.py` (parse, validate, `describe`), `SPEC.md` correction in `SPEC_.md`, `tests/test_descriptor.py` |
| New operation | `jsonsrc.py` (source edit), `service.py` (authorize, validate, changed paths), `tree.py` (kind/capabilities), `SPEC_service.md` section 20, `tests/test_tree_and_operations.py` |
| New snapshot field or union expansion | `tree.py`, `aiset-tree.js`, `SPEC_service.md` sections 19 (snapshot) and 21 (editor), `tests/test_tree_and_operations.py`, `tests/test_ui_assets.py` |
| New permission | `service.py` checks, `SPEC_service.md` section 5, `tests/test_service.py` and `tests/test_http.py` |
| Editor behaviour | `src/aiset/assets/aiset-tree.js`, its styles, `tests/test_ui_assets.py` (node smoke with a DOM stub) |
| Renamed or removed emitted class | `aiset-tree.js` `CLASS_INVENTORY`, `aiset.css`, `SPEC_service.md` section 21.1, `AGENT_INTEGRATION.md` section 8a.2, `aiset-host-theme.css`, host stylesheets |
| New host route | `demo2/app.py`, `demo2/tests/test_app.py`, `commands.md` |

Interface changes are documented in `SPEC_service.md` in the same change; new
behaviour goes to `IMPLEMENTATION_LOG.md`, and the standing rationale for a
decision belongs in section 19.3 of this file so it stays next to the rules.

## 15. Testing an integration

```sh
.venv/bin/python -m pytest -q          # whole suite
.venv/bin/python -m pytest tests -q    # library only
.venv/bin/python -m pytest demo2/tests -q
./test.sh                              # suite plus descriptor diagnostics
.venv/bin/aiset validate-descriptor <descriptor.json5> [--strict]
.venv/bin/aiset validate-document --config <config.json5> --descriptor <descriptor.json5> [--typedef <f>] [--env <f>]
.venv/bin/aiset doctor --config <config.json5> --descriptor <descriptor.json5> [--typedef <f>] [--fix] [--class <c>] [--format json|text]
.venv/bin/python -m pyflakes src/aiset demo2 tests
node --check src/aiset/assets/aiset-tree.js
```

A new host needs, at minimum:

1. Startup with a temporary state directory and a descriptor that validates
   under `--strict`.
2. Every route it mounts, through the real transport (WSGI and/or ASGI),
   including `health`, `documents`, `tree` and one write.
3. Permission denial for each permission it partitions, and a secret subtree
   with a principal that may not read it.
4. A stale revision: `409`, and a missing pair: `428`.
5. One end-to-end write that keeps comments, quoting and the final newline, then
   a reload that sees the change.
6. The asset path through the proxy (section 8a.6), and a missing asset that
   returns `404`, not the SPA page.
7. `aiset.classes()` coverage of the host sheet and a mount with the host sheet
   loaded after `aiset.css`.
8. For an editor change: a node smoke test that evaluates the real assets against
   a DOM stub (see `tests/test_ui_assets.py`). A Python-only stub never proves
   browser behaviour; manual browser steps live in `TEST.md`.

The suite prints the current count; do not hardcode a count in a host document.
`node` is needed for the asset smoke tests; they skip when it is unavailable,
which is not a substitute for running them in CI.

## 16. Running the demo hosts

```sh
./run_demo2.sh                                   # 0.0.0.0:8383
./run_demo2.sh --demo2.server.port:8384          # document-scoped override
./run_demo2.sh --server.port:8384                # bare path override
DEMO2_STATE_DIR=/tmp/demo2 ./run_demo2.sh        # isolated state
```

`run_demo2.sh` seeds `demo2/config.json5` and `demo2/.env` only when absent and
never overwrites them. A detached run needs `setsid`: a plain `nohup … &` dies
with the shell that started it, which leaves a silently dead port.

`demo2` is an acceptance host, not a starter template: its config and chat page
are deliberately minimal. Copy the integration patterns (register, mount, apply
contract, asset check), not the demo's files or its `config.json5`.

## 16a. Troubleshooting an integration

| Symptom | First check | Fix |
|---|---|---|
| Empty settings area, no toolbar | Network tab: `/assets/aiset.js` and `/assets/aiset-tree.js` must be `200` and JavaScript, not HTML | Fix the proxy prefix (8a.6); load the assets through `{base}/assets` |
| `aiset is not defined` | Script order and `defer`: `aiset.js` before `aiset-tree.js`, host script last | Load in dependency order; do not call `mountTree` before the element exists |
| Tree renders as bare text | `aiset.css` missing, or the host sheet is loaded before it | Load `aiset.css`, then the optional theme, then the host sheet (8a.1) |
| Tree is readable but plain | No host design; this is the documented fallback, not a bug | Adopt the theme or override `--aiset-*` (8a.4) |
| `mountTree: target not found` | The selector and the script timing | Mount after `DOMContentLoaded`; use a real element id |
| `401`/`403` on every call | `principal_resolver` / `principal_from_scope` returns `None` or a principal without the required permission | Return a real `Principal`; check section 9 |
| `403` on `GET /documents` only | It requires `settings_read_source` | Grant it, or set `public_documents=True` deliberately |
| `404` under the mount prefix | Proxy forwards only a different prefix, or `base` differs from the URL | Align `base`, proxy location and `apiBase` |
| `409` on Apply | The file changed after the read | Reload, re-apply the batch; never retry the same revisions |
| `428` on Apply | `expected_revision` or `expected_descriptor_revision` missing/empty | Send both from the last read |
| `422` with `issues` | Descriptor or candidate violation | Show `issues[].path`/`message`; fix the value, not the HTTP status |
| Apply stages nothing | The batch did not validate | Listen to `validated`/`status`; the issues list names the path |
| `${VAR}` seems ignored | The `.env` mapping was not passed to `Resolver`, or the field is unquoted without `env.allowed` | Pass `dotenv=`; set `env.allowed`; remember empty-value precedence (section 10) |
| A live field reports `restart_required` | `apply` is unset and inherits `restart` | Set `apply: "live"` on the field or its nearest ancestor |
| A union object is one text area | The browser is running an older `aiset-tree.js` | Hard-reload; the current snapshot expands the alternative (section 12) |
| The view jumps to the top after a click | An older asset cleared the tree without restoring scroll | Hard-reload; the editor preserves the host and ancestor scroll offsets |
| `register` raises `InvalidDescriptor` | `descriptor_version` or an unknown type/property | `.venv/bin/aiset validate-descriptor <f> --strict` |
| A secret field is missing | The principal lacks `settings_read_secret` | Expected; do not send the value to the browser |
| Two editors share state | A second `mountTree` on the same element without `destroy()` | One instance per mount; `destroy()` before remount |

If a static check disagrees with the browser, trust the browser for assets and
the service for values: asset requests may be answered by a proxy that the
Python tests never exercise, and a browser-side check is advisory (section 1,
rule 7).

---

## 17. Running things you should not

- Do not start a second demo on the same port; both hosts bind 8383 and report a
  bind failure instead of choosing another port.
- Do not leave verification instances running: use a free port, stop them in the
  same command, and check `pgrep -af 'demo2/app.py'` afterwards.
- Do not edit `demo2/config.json5` or `demo2/.env` to "fix" a test: both are
  local ignored state; the sources are the `.example` files.
- Do not expose `demo2` outside a trusted network: it has no authentication by
  design and says so on the page.

## 18. Do not

- Do not add a second source of truth for paths, defaults or validation in a
  host; extend `src/aiset/` instead.
- Do not resolve templates in the browser and write the result back; that
  destroys the substitution and the `.env` contract.
- Do not write a file without `expected_revision`; a blind write is a lost
  update, and the server answers `428`.
- Do not treat `absent`, `null` and `default` as interchangeable.
- Do not send a secret value to the browser; use the descriptor `secret: true`
  and a principal without `settings_read_secret`.
- Do not return `Principal.demo()` from a production resolver; it carries every
  permission. Authenticate the request or return an empty-permission principal.
- Do not copy `aiset.css` or `aiset-tree.js` into the host; serve
  `aiset.assets.ASSETS_DIR` so an upgrade cannot leave a stale fork.
- Do not parse JSON5 with `eval`, or cut JSON in half when truncating for a
  model; bound a structure structurally instead.
- Do not assume an HTTP `200` means success: check `ok` in the envelope.
- Do not keep every change in memory only: `memory/context.md` carries context
  between sessions and must stay under 20000 characters.
- Do not reformat `examples/`, do not use the system Python, and do not commit
  without being asked.

---

## 19. Rationale, invariants and pitfalls

The working notes that used to sit in a separate file are folded in here. They
are normative for an integrator, not history.

### 19.1 How the work is judged

| Preference | Consequence |
|---|---|
| The simplest solution that satisfies the requirement | No speculative abstraction, no "future-proofing" that adds concepts |
| The public interface stays small | Fewer concepts beats more capability; the tree editor API is the ceiling |
| A batch is one candidate and one write | Operations run in order on an in-memory candidate; any failure aborts the whole batch and leaves the file unchanged. Recovery from external damage is still the Last Known Good file, not a cross-batch transaction log |
| Fail fast on a schema error | A descriptor conflict is a development bug: stop with a clear error, never resolve it silently |
| Encapsulation | Everything about a component lives in that component's folder, descriptor templates included |
| Callbacks receive the whole configuration | The callback decides what matters; do not hand it a branch |
| English in documents, chat in the language of the request | |
| Short, meaningful comments; concise answers | Do not explain the obvious |

### 19.2 Invariants

- **Source preservation is non-negotiable.** Never serialise the effective
  dictionary and rebuild the file. A read with no edit leaves the bytes
  identical, and there is no parse-and-dump fallback.
- **The core imports nothing host-shaped.** No host modules, FastAPI, MCP SDK,
  Redis or UI framework inside `src/aiset/`; those are optional extras.
  Importing the library reads no configuration, mutates no environment and
  starts nothing.
- **Secrets never leave the server to a principal without
  `settings_read_secret`.** Environment diagnostics expose variable names only,
  never values; a read of a subtree containing a secret is denied as a whole,
  not redacted.
- **Pin, never follow.** An install uses a pinned Git commit, tag or package
  version. The descriptor's `descriptor_version` is checked at compile time; the
  library itself has no ABI handshake, so run the host tests after an upgrade
  instead of assuming a newer checkout is compatible.
- **`bool` is not `int`.** Integer input stays within
  `[-9007199254740991, 9007199254740991]`; `NaN` and `Infinity` are rejected.
- **Optional integrations are separate dependencies.** A conflict with a host
  dependency is reported, not resolved by picking one.

### 19.3 Why the design is what it is

The rules are in `SPEC.md`; this is the reasoning behind the ones hosts question
most often.

| Decision | Reason |
|---|---|
| One resolver policy for every host (SPEC 6) | Host overrides -> environment -> `.env` -> inline default -> config default, with POSIX `:-` semantics and a single pass. A per-host policy would make the same file behave differently in two hosts. |
| `set` replaces, never merges (SPEC 5.3) | A silently deep-merged `set` makes an edit's effect impossible to predict from the request. Merging exists separately, for layers. |
| Merge is pure; an update cannot delete a base field (SPEC 10.1) | Removing a base field is a decision the host should make explicitly; chaining is its job. |
| Application state derives from `apply`, not from a callback (SPEC 8.2) | The descriptor knows what a change requires; the presence of a callback is not a policy. |
| An invalid external edit is preserved before restore (SPEC 10.4) | The operator's bytes are evidence. They go to `<file>.conflicted.<UTC-ISO>.back`, and the restore is refused if that copy cannot be written. |
| Revisions include every byte (SPEC 7.3) | Two files that differ only in whitespace are different files; a revision that ignored that would lose an edit. |

### 19.4 Pitfalls

- **Any byte changes the revision**, whitespace included. Never normalise line
  endings or a trailing newline.
- **On reread/load, a valid external edit is adopted; an invalid one is
  restored.** Do not clobber either with a stale in-memory copy, and never serve
  stale data. A plain `get`/`tree` serves the cached state; the host calls
  `reread` or `POST /load` after an external change.
- **Two different things are called "mount".** A descriptor fragment mounts at a
  subtree (SPEC 4.3); a Config targets a data location (SPEC 10.2). Name them so
  the difference is visible.
- **Two path syntaxes.** JSON Pointer for edits (SPEC 5.3); `[id=value]` for
  Config mount addressing (SPEC 10.2).
- **The application callback is not `after_save`.** The first applies to the
  runtime, the second is a notification; the order is fixed in SPEC 10.3.
- **Active revision is not stored revision.** The host owns application, the
  library owns storage.
- **`min_length` / `max_length` count Unicode code points.** Pick one unit and
  stay with it.
- **`SPEC.md` and `SPEC_service.md` overlap on purpose.** `SPEC_service.md` is
  authoritative for the interface; when one changes, change the other in the same
  commit.
- **The default principal is the demo principal.** Omitting the resolver is a
  security hole outside a local demo, not a harmless default.
- **A union object's declared fields are a template.** They are shown even when
  `showAbsent` is off; do not "fix" that by hiding them in a host.
- **The mount target is not always the scroll container.** A host may mount the
  editor inside a pane that owns `overflow: auto` (demo2 does); the editor
  preserves the host and ancestor offsets itself, but a host that replaces the
  pane during a re-render must keep its own scroll position.
- **Assets are package files.** Serve `aiset.assets.ASSETS_DIR`; a copied
  stylesheet or script is a fork that will drift.
- **`Service.register` is lenient, the CLI is not.** Unknown properties are
  warnings at runtime so host metadata is accepted; `validate-descriptor
  --strict` turns them into errors. That split is deliberate: the runtime must
  not reject a host's own annotations, and the CLI is the typo gate.

### 19.5 What the implementation actually is

- **Zero runtime dependencies.** The JSON5 template engine (`jsonsrc.py`), the
  WSGI and ASGI adapters (`httpd.py`, `asgi.py`) and the console script
  (`cli.py`) ship with the package.
- **Hooks compile but do not execute.** A write touching a hook-bound node is
  refused with `UNSUPPORTED_CAPABILITY`, and the snapshot reports
  `capabilities.unsupported = "hooks"` with every action false.
- **No MCP transport in this revision.** The Python and HTTP surfaces are
  complete; do not plan around an MCP endpoint that does not exist yet.
- **Helpers are a browser extension.** The built-in `node_form` is registered;
  a host registers another tag with `aiset.registerHelper(tag, factory)`. The
  Python service only carries the binding in `field.helper` and never executes
  it. Custom `validators` are likewise carried for a host, not executed by the
  library.
- **`PARSE_ERROR` (400) and `INVALID_DESCRIPTOR` (422)** are additive codes on
  top of the error table in section 6.

### 19.6 What a host test suite should cover

Exact source preservation comes first, because it is the highest-risk area:
compare bytes, not parsed values. Then descriptor composition conflicts, dynamic
keys, unions, absent versus null versus default, the resolver policy, comment
ownership and conflict rejection, stale revisions, lock timeout, atomic-write
fault injection, valid and invalid external edits, merge rules, callbacks and
rollback, transport parity (Python, HTTP, ASGI), secret handling and the limits.

Run the same library revision against more than one host adapter without changing
it. That is the point of a library.

### 19.7 Where each rule lives

| Question | Document |
|---|---|
| Goal, grammar, storage, security, phases, hooks | `SPEC.md` |
| Python and HTTP signatures, envelopes, revisions, CLI | `SPEC_service.md`, authoritative for the interface |
| Task-shaped integration steps, design rationale, pitfalls | This file |
| What changed, and when | `IMPLEMENTATION_LOG.md` |
| Runnable commands | `TEST.md`, `commands.md` |
