# AGENT_INTEGRATION.md - aiset integration guide for agents

Task-oriented guide for an agent that embeds aiset, extends it, or drives it
over HTTP. It is written to be consumed by a model: dense tables, exact
identifiers, explicit rules, no prose padding.

Read this file first, then the document it points to. Do not read the whole
repository.

| Need | Read |
|---|---|
| Embed aiset in a Python host | Sections 3-7 below |
| Drive aiset over HTTP or from JavaScript | Sections 6, 8-9 |
| Write or fix a descriptor | Sections 7, 10 |
| Understand placeholders, views, absent/null/default | Sections 10-11 |
| Embed aiset in an async host | Section 3, and `SPEC_service.md` section 10a |
| Extend the library or the tree editor | Sections 12-14, 18 |
| Know what is forbidden | Section 1, Section 18 |
| Normative interface detail | [SPEC_service.md](SPEC_service.md) |
| Full design and semantics | [SPEC.md](SPEC.md) (read-only) |
| Implementation reasoning, pitfalls, user preferences | [_AGENT_NOTES.md](_AGENT_NOTES.md) |
| Commands to run | [commands.md](commands.md), [TEST.md](TEST.md) |
| Working rules of this repository | [AGENTS.md](AGENTS.md) (read-only) |

Status: M1-M4 implemented, one document set, `./test.sh` green. Nothing below is
aspirational; every route, field and code exists in `src/aiset/`.

---

## 1. Hard rules

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
| operation | One atomic structural edit: `set`, `add`, `remove`, `move`. |
| principal | An authenticated actor carrying permissions; every service call takes one. |
| staged | An edit held in the browser until the user applies it; aiset never writes partially. |
| absent / null / default | Three different states. Absent: key not in the file. Null: key present with `null`. Default: absent, descriptor supplies a value. |

## 3. Minimum viable integration

```python
from aiset.service import Principal, Service
from aiset.resolver import Resolver
from aiset.httpd import create_app

service = Service()
service.register(
    "main",                                   # document id used by every later call
    "/srv/app/config.json5",                  # the only file this process may touch
    Path("descriptor.json5").read_text(),
    resolver=Resolver(overrides={}, dotenv=dotenv_mapping, environ=os.environ),
)

principal = Principal(id="user-42", permissions=frozenset({
    "settings_read_source", "settings_read_effective",
    "settings_validate", "settings_write", "settings_read_secret",
}))

app = create_app(service, base="/api/settings")
# wsgiref.simple_server.make_server(host, port, app).serve_forever()
```

An async host (FastAPI, Starlette, uvicorn) mounts the ASGI adapter instead of
building a WSGI bridge of its own. It shares the dispatcher, and
`principal_from_scope` covers the case the synchronous `principal_resolver`
cannot:

```python
from aiset.asgi import create_asgi_app

app = create_asgi_app(service, base="/api/settings", principal_from_scope=resolve_session)
```

`/assets/*` is served from the installed package with or without `static_dir`,
so an API-only host still gets the editor.

Rules for that snippet:

- Registration compiles the descriptor and refuses unknown documents; nothing
  else may add a file later.
- `Resolver` inputs are injected, never read from a global; tests must not depend
  on the process environment.
- A principal without `settings_read_secret` never receives a secret subtree: the
  whole subtree is denied, not redacted.

## 4. Object model and lifecycle

```
Service
├── documents: {document_id -> DocumentRegistration{document_id, store, descriptor, resolver}}
├── states:    {document_id -> DocumentState{document, revision, provenance, invalid_on_disk, ...}}
├── register(document_id, path, descriptor_source, resolver=, typedef_sources=, fragments=)
├── load / load_lkg / reread        read a document (validate, keep LKG)
├── get / validate / set            one path, source or effective view
├── tree                            one authorized snapshot of a subtree
├── apply_operations                one atomic batch (dry_run for validation)
├── env_status                      which variables are set (booleans only)
├── rollback                        restore the last known good file
├── subscribe / on_probe_changes / on_after_save / on_application
└── descriptor / validate_descriptor
```

Call order for a host: `register` once at startup, then per request
`get`/`tree` (read) or `apply_operations` (write). `load` is implicit on first
use and re-reads after an external change or `POST /load`.

## 5. Python API

All methods require a `principal`. `expected_revision` and
`expected_descriptor_revision` are mandatory for every write: pass the values a
previous read returned, or `None` to accept whatever is current.

| Call | Returns | Permission | Notes |
|---|---|---|---|
| `register(document_id, path, descriptor_source, *, resolver=None, typedef_sources=(), fragments=())` | `DocumentRegistration` | none | Once per document; refuses a symlinked target. |
| `load(document_id, *, principal)` | `LoadResult` | `settings_read_effective` | Validates and caches; returns `revision`, `descriptor_revision`, `provenance`, `issues`. |
| `load_lkg(document_id, *, principal)` | `LoadResult` | `settings_load_lkg` | Falls back to the last valid file when the current one is invalid. |
| `reread(document_id, *, principal=None)` | `LoadResult` | none | Explicit re-read after an external edit. |
| `get(document_id, path, *, view="source", principal)` | `GetResult` | `settings_read_source` / `settings_read_effective` | `value_text` is the source fragment; `effective` the resolved value. |
| `validate(document_id, path, value_text, *, expected_revision, expected_descriptor_revision, principal)` | `ValidateResult` | `settings_validate` | `valid`, `preservable`, `issues`; writes nothing. |
| `set(document_id, path, value_text, *, expected_revision, expected_descriptor_revision, principal)` | `SetResult` | `settings_write` | One path; probes, hooks, callbacks, application. |
| `tree(document_id, path="", *, view="source", principal)` | `dict` | same as `get` | Snapshot; see section 12. |
| `apply_operations(document_id, operations, *, expected_revision, expected_descriptor_revision, principal, dry_run=False)` | `OperationsResult` | `settings_validate` / `settings_write` | Atomic batch; see section 13. |
| `env_status(document_id, names, *, principal)` | `dict[str, bool]` | `settings_read_source` | Presence only; max 64 names; values never returned. |
| `rollback(document_id, reason, *, principal)` | `SetResult` | `settings_write` | Restore the previous valid file. |
| `subscribe(document_id, paths, callback, *, principal=None)` | `Subscription` | `settings_read_effective` | Call `unsubscribe()` when done. |
| `descriptor(document_id, *, view="authorized", principal)` | `dict` | `settings_read_source` | `authorized` hides secret values, `raw` needs `settings_descriptor_raw`. |

Result objects expose `.to_dict()`; the HTTP layer returns exactly that.

## 6. HTTP API

`create_app(service, base="/api/settings", *, principal_resolver, static_dir,
assets_dir, static_map)` serves everything below. `principal_resolver(environ)`
must map the incoming request to a `Principal`; the demo uses `Principal.demo()`.
There is no authentication, TLS, CORS or CSRF logic in the library: the host
owns authentication and must wrap the app.

| Method | Route | Input | Success payload |
|---|---|---|---|
| GET | `/health` | - | `{"ok": true, "aiset": "..."}` |
| GET | `/descriptor` | `document`, `view=authorized\|raw` | descriptor envelope |
| GET | `/value` | `document`, `path`, `view=source\|effective` | `GetResult` |
| GET | `/tree` | `document`, `path`, `view` | `{"ok": true, ...snapshot}` |
| GET | `/documents` | - | `{"ok": true, "documents": [...]}` |
| POST | `/validate` | `document`, `path`, `value_text`, revisions | `ValidateResult` |
| POST | `/value` | same | `SetResult` |
| POST | `/operations` | `document`, `operations`, revisions | `OperationsResult` (writes) |
| POST | `/operations/validate` | same | `OperationsResult` with `dry_run: true` |
| POST | `/env` | `document`, `names` | `{"ok": true, "present": {...}}` |
| POST | `/load` | `document` | `LoadResult` |
| POST | `/load/lkg` | `document` | `LoadResult` |
| POST | `/descriptor/validate` | `descriptor_source`, `mode=default\|strict` | diagnostic |
| POST | `/merge` | `base`, `update` | `{"ok": true, "merged": ...}` |

Success envelope: `{"ok": true, ...}`.
Error envelope: `{"ok": false, "error": {"code", "message", "issues"?}}`.

| Code | HTTP | Cause and fix |
|---|---|---|
| `BAD_REQUEST`, `PARSE_ERROR` | 400 | Malformed request or source fragment. |
| `UNAUTHORIZED`, `FORBIDDEN`, `SECRET_ACCESS_DENIED` | 401/403 | Principal lacks the permission, or a secret subtree was addressed. |
| `NOT_FOUND` | 404 | Unknown document, path, route, or no valid backup. |
| `REVISION_CONFLICT`, `COMMENT_PRESERVATION_CONFLICT` | 409 | The file changed underneath, or comments cannot be preserved. Re-read and re-apply; never overwrite. |
| `PAYLOAD_TOO_LARGE` | 413 | A limits rule was exceeded. |
| `VALIDATION_ERROR`, `INVALID_DESCRIPTOR` | 422 | Candidate violates the descriptor; `issues` carries path, code, message. |
| `REVISION_REQUIRED` | 428 | A write arrived without `expected_revision`. Always send it. |
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
        required: true,
        read_only: false,
        secret: false,               // subtree denied without settings_read_secret
        apply: "live",               // live | reload | restart
        env: { allowed: true, convert: "int" },   // convert: string int number bool
        ui: { widget: "textarea", rows: 3, placeholder: "…" },
        key_pattern: "^[a-z]+$", key_enum: ["a", "b"],   // dynamic object keys
        children: {},                // object members, or the item type of an array
        additional_children: {},     // dynamic member type
        children_options: [],        // shapes of a union
        typedef: "name",             // reuse a declared template
        validators: [], hooks: {}, helper: {}, title: "", id: "stable-id",
      },
      tags: {
        type: "array",
        children: { type: "string", description: "One tag" },   // the item type
      },
    },
  },
}
```

- `type: "any"` is the opaque type: a region the host owns and the library does
  not inspect. It accepts every JSON value including `null`, keeps no composite
  key or key constraint, is a `leaf` in a snapshot, and is edited as source text.
  Operational limits still apply; a `${VAR}` inside it stays literal.
- A `union` as the type of an object member is resolved through the alternative
  that declares that member; validation still accepts every alternative and
  reports one issue when none fits.
- Unknown properties are warnings by default and errors under `--strict`.
- Validate before shipping: `.venv/bin/aiset validate-descriptor <file> --strict`
  (exit `0` valid, `1` invalid, `2` usage/IO error).
- Reference files: `examples/descriptor.json5` (full fixture matrix, frozen),
  `demo2/descriptor.json5` (editable demo), `demo_aidir_config.template.json5`
  (host descriptor for aidir).

## 8. Frontend integration

Shipped assets: `aiset.js`, `aiset.css`, `aiset-tree.js` (served from
`/assets/`). Python helpers: `aiset.assets.include_assets()`,
`render_tree_editor(document)`, `render_node_editor(document, path)`,
`render_full_editor(document)`.

```html
<link rel="stylesheet" href="/assets/aiset.css">
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

| Option | Default | Meaning |
|---|---|---|
| `document` | required | Document id. |
| `apiBase` | `/api/settings` | Transport base. |
| `view` | `source` | Snapshot view. |
| `lifecycle` | `[]` | Host buttons; the editor never restarts a process itself. |
| `viewButtons` | `true` | Show **Expand all** / **Collapse all**. |
| `valuesAsText` | `false` | Show the stored text of objects and arrays. |
| `showAbsent` | `false` | Show declared keys the file does not contain yet. |

| Instance method | Effect |
|---|---|
| `getPendingOperations()` | Copy of the staged batch. |
| `stageOperations(operations, source)` | Add or replace staged operations. |
| `revert(path)` | Drop staged operations for one path. |
| `validatePending()` / `applyPending()` | Validate / commit the batch. |
| `reload(confirmFirst)` | Re-read from the server. |
| `expandAll()` / `collapseAll()` | Open or close every section (root stays open). |
| `setValuesAsText(flag)` / `setShowAbsent(flag)` | View switches. |
| `runLifecycle(action)` | POST a host lifecycle route. |
| `on(event, handler)` | `loaded`, `staged`, `validated`, `applied`, `status`, `lifecycle`, `viewchange`, `env`. |
| `destroy()` | Detach listeners and clear the host element. |

Every node offers three editing modes: the typed control per declared type, raw
source editing (`{..}` button, subtree hidden, server-validated `set`), and the
placeholder mode (variable name + typed inline fallback; an empty name stores
the inline value). A node whose descriptor sets `env.allowed` gets a `.env`
button that switches it into placeholder mode.

Browser rules that are not optional:

- Load the scripts with `defer` in dependency order; touching the DOM before
  `DOMContentLoaded` leaves the page silently empty.
- No framework, no build step, no CDN; the assets must stay framework-free.
- Serve static assets with `Cache-Control: no-cache` (aiset does); a stale cached
  script is indistinguishable from a broken one.

## 9. Permissions

| Permission | Grants |
|---|---|
| `settings_read_source` | Stored fragments, tree snapshots, descriptor, env presence. |
| `settings_read_effective` | Resolved values, `load`, `subscribe`. |
| `settings_validate` | `validate`, `apply_operations(dry_run=True)`. |
| `settings_write` | `set`, `apply_operations`, `rollback`. |
| `settings_read_secret` | Values under a `secret: true` node. |
| `settings_edit_secret` | Writes under a secret node. |
| `settings_load_lkg` | `load_lkg`. |
| `settings_descriptor_raw` | Unredacted descriptor export. |

A secret subtree is denied as a whole, never field by field.

## 10. Paths and edits

- Root is `""`. `"/"` is a key with an empty name and is normally not declared.
- Escaping: `~` becomes `~0`, `/` becomes `~1`.
- Array items are addressed by index: `/fixtures/tags/1`.
- Templates: `${VAR}` and `${VAR:-default}` only; POSIX `:-` semantics;
  substitution is single-pass and values are data, never structure.
- Precedence: host overrides → process environment → `.env` → inline `:-`
  default → descriptor `default`.
- An unquoted placeholder requires `env.allowed`; inside a string it stays
  literal when `allowed` is false.
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
no per-node requests, no client-side guessing.

| Field | Meaning |
|---|---|
| `path`, `type`, `kind`, `exists` | Identity. `kind` is `array`, `array_item`, `object`, `dynamic_key`, `leaf`, `undeclared`. |
| `value_text`, `effective` | Source fragment and resolved value (`view=source` omits `effective`). |
| `origin` | `file`, `default`, `environment`, `absent`. |
| `capabilities` | `edit`, `add`, `remove`, `reorder`, `add_child`, `remove_child`, `key_options`, `key_pattern`. |
| `field` | Descriptor metadata: type, description, default, constraints, `env`, `ui`, `nullable`, `required`, `read_only`. |
| `comments` | Source comments that introduce the node, markers removed, decorative rules dropped. |
| `template` | `name` and inline `default` of a stored `${VAR}` / `${VAR:-default}`. |
| `access_denied` | Set instead of values when a secret subtree is addressed. |
| `default_applied` | Effective view only: the descriptor default is in use. |

`kind` is decided by the parent, not by the node type: a string inside an array
is an `array_item`, because `remove` and `move` address the item path.

## 13. Operations

```json
{"op": "set",    "path": "/server/port", "value_text": "8384"}
{"op": "add",    "path": "/fixtures/tags/-", "value_text": "\"new\""}
{"op": "add",    "path": "/server/host",  "value_text": "\"0.0.0.0\""}
{"op": "remove", "path": "/fixtures/tags/1"}
{"op": "move",   "from": "/fixtures/tags/1", "path": "/fixtures/tags/0"}
```

- `add` on an array uses the `-` append token; on an object it names a key the
  descriptor permits.
- `remove` is refused for `required`, `const` and `read_only` nodes.
- `move` carries the item with its comments.
- One batch, one revision, all-or-nothing: the first failure aborts everything
  and the file stays byte-for-byte unchanged.
- Validate with `dry_run=True` (or `POST /operations/validate`) before applying.
- `value_text` is JSON5 source text: strings carry their quotes.

## 14. Extending the library

| Change | Files that must move together |
|---|---|
| New service method | `service.py`, `httpd.py` route, `SPEC_service.md`, `tests/test_service.py`, `tests/test_http.py` |
| New transport or route | `httpd.py` dispatcher (shared), `asgi.py` when a transport changes shape, `SPEC_service.md`, `tests/test_asgi.py`, `tests/test_http.py` |
| Resolver behaviour | `resolver.py`, `descriptor.py` node_at, `SPEC_.md` correction, `tests/test_resolver.py` |
| New descriptor property | `descriptor.py` (parse, validate, `describe`), `SPEC.md` correction in `SPEC_.md`, `tests/test_descriptor.py` |
| New operation | `jsonsrc.py` (source edit), `service.py` (authorize, validate), `SPEC_.md`, `tests/test_tree_and_operations.py` |
| New snapshot field | `tree.py`, editor rendering, `SPEC_service.md` section 20/21, `tests/test_tree_and_operations.py` |
| Editor behaviour | `src/aiset/assets/aiset-tree.js`, its styles, `tests/test_ui_assets.py` (node smoke with a DOM stub) |
| New host route | `demo2/app.py`, `demo2/tests/test_app.py`, `commands.md` |

Interface changes are documented in `SPEC_service.md` in the same change; new
behaviour goes to `IMPLEMENTATION_LOG.md`, decisions with rationale to
`_AGENT_NOTES.md`.

## 15. Testing an integration

```sh
.venv/bin/python -m pytest -q          # whole suite, about 13 seconds
.venv/bin/python -m pytest tests -q    # library only
.venv/bin/python -m pytest demo2/tests -q
./test.sh                              # suite plus descriptor diagnostics
.venv/bin/python -m pyflakes src/aiset demo2 tests
node --check src/aiset/assets/aiset-tree.js
```

A new host needs, at minimum: startup with a temporary state directory, every
route, permission denial, and one end-to-end write. Editor changes need a node
smoke test that evaluates the real assets against a DOM stub (see
`tests/test_ui_assets.py`); Python-only stubs never prove browser behaviour.
Manual browser steps live in `TEST.md`.

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
- Do not parse JSON5 with `eval`, or cut JSON in half when truncating for a
  model; bound a structure structurally instead.
- Do not assume an HTTP `200` means success: check `ok` in the envelope.
- Do not keep every change in memory only: `memory/context.md` carries context
  between sessions and must stay under 20000 characters.
- Do not reformat `examples/`, do not use the system Python, and do not commit
  without being asked.