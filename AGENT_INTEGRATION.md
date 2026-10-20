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
| Style the editor for a host, or adopt the reference theme | Section 8a |
| Write or fix a descriptor | Sections 7, 10 |
| Understand placeholders, views, absent/null/default | Sections 10-11 |
| Embed aiset in an async host | Section 3, and `SPEC_service.md` section 10a |
| Extend the library or the tree editor | Sections 12-14, 18 |
| Know what is forbidden | Section 1, Section 18 |
| Normative interface detail | [SPEC_service.md](SPEC_service.md) |
| Full design and semantics | [SPEC.md](SPEC.md) (read-only) |
| Design rationale, invariants, pitfalls, user preferences | Section 19 |
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

`/assets/*` (and `{base}/assets/*`) is served from the installed package with or
without `static_dir`, so a host that mounts only the API at `{base}` still gets
the editor from the same mount.

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
| `validate_document(document_id, source, *, principal)` | `ValidateResult` | `settings_validate` | Validate a whole candidate document; writes nothing, no LKG. |
| `doctor(document_id, *, principal, fix=False, expected_revision=None, expected_descriptor_revision=None)` | `DoctorReport` | `settings_read_effective` / `settings_write` | Report every issue with a fix class; `fix` repairs the named classes. Writes only when the result is fully valid. |
| `set(document_id, path, value_text, *, expected_revision, expected_descriptor_revision, principal)` | `SetResult` | `settings_write` | One path; probes, hooks, callbacks, application. |
| `tree(document_id, path="", *, view="source", principal)` | `dict` | same as `get` | Snapshot; see section 12. |
| `apply_operations(document_id, operations, *, expected_revision, expected_descriptor_revision, principal, dry_run=False)` | `OperationsResult` | `settings_validate` / `settings_write` | Atomic batch; see section 13. |
| `env_status(document_id, names, *, principal)` | `dict[str, bool]` | `settings_read_source` | Presence only; max 64 names; values never returned. |
| `rollback(document_id, reason, *, principal)` | `SetResult` | `settings_write` | Restore the previous valid file. |
| `subscribe(document_id, paths, callback, *, principal=None)` | `Subscription` | `settings_read_effective` | Call `unsubscribe()` when done. |
| `descriptor(document_id, *, view="authorized", principal)` | `dict` | `settings_read_source` | `authorized` hides secret values, `raw` needs `settings_descriptor_raw`. |

Result objects expose `.to_dict()`; the HTTP layer returns exactly that.

`SetResult.application.state` is the host contract: `applied`,
`reload_required`, `restart_required`, or `apply_failed`, derived from the most
restrictive `apply` of the changed paths (SPEC_service.md section 4). `live` is
the only state that advances `active_revision`.

## 6. HTTP API

`create_app(service, base="/api/settings", *, principal_resolver, static_dir,
assets_dir, static_map, public_documents)` serves everything below.
`principal_resolver(environ)` must map the incoming request to a `Principal`; the
demo uses `Principal.demo()`. There is no authentication, TLS, CORS or CSRF logic
in the library: the host owns authentication and must wrap the app.

Every route requires a permission except `/health`, which is public. In
particular `GET /documents` requires `settings_read_source`; a host that wants a
public document list (a liveness probe) opts in with `public_documents=True`.

| Method | Route | Input | Success payload |
|---|---|---|---|
| GET | `/health` | - | `{"ok": true, "aiset": "..."}` |
| GET | `/descriptor` | `document`, `view=authorized\|raw` | descriptor envelope |
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
`/assets/`). A reference theme, `aiset-host-theme.css`, also ships but is **not**
loaded by `include_assets()` - a host opts into it (8a.4). Python helpers:
`aiset.assets.include_assets()`, `render_tree_editor(document)`,
`render_node_editor(document, path)`, `render_full_editor(document)`.

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

A `union` node is edited through the control of the alternative its value
matched (`matched_option`): an enum string becomes a select, an `int`/`number` a
number field, a `bool` a checkbox, a string a text field, an object/array the raw
source. A `shape…` chooser switches the alternative and stages a sample of it.

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
every request returns `200`, every node renders, `Apply` writes the file. Since
items 4 and 6, `mountTree` warns once when no rule matches the editor root, and a
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
| `aiset-tree-badge <kind>` | span | `type`, `apply`, `origin`, `env`, `draft`, `absent`, `default`, `lock`, `unsupported`, `req`, `dirty`, `new`, `deleted` |
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
`aiset-tree-status` (+ `[data-state]` of `ok` / `error` / `pending`),
`aiset-tree-issues`, `aiset-tree-pending`, `aiset-tree-staged`,
`aiset-tree-staged-row`, `aiset-tree-staged-path`, `aiset-tree-staged-source`,
`aiset-tree-staged-op`, `aiset-form`, `aiset-form-title`, `aiset-form-row`,
`aiset-form-label`, `aiset-form-field`, `aiset-form-control`, `aiset-form-actions`.

### 8a.3 The five traps

| Trap | What happens | Do instead |
|---|---|---|
| `aiset-tree-badges` was unstyled | Badges ran together as one run of text, because the library styled the badge and not its wrapper. The library now paints the wrapper (`display: inline-flex; gap: 4px`); a host restyles it only to change the spacing | Leave it, or restyle the wrapper as a whole |
| Apply / Reload / Revert are styled by position | Since item 2 they carry `aiset-tree-button` plus `aiset-tree-apply` / `-reload` / `-revert`, so rank Apply by class (`:first-child` breaks when a button is added before it) | `.aiset-tree-apply { … }`, never `:first-child` |
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
<script src="/api/settings/assets/aiset.js"></script>
<script src="/api/settings/assets/aiset-tree.js"></script>
```

Verify before trusting the page:

```sh
curl -sI "http://localhost:8080/api/settings/assets/aiset-tree.js" | head -2
# expect: 200 and Content-Type: application/javascript - never text/html
```

### 8a.7 Verifying an integration without a browser

Static checks catch the three failures that HTTP tests cannot see, because their
requests are already authenticated and their assets are already served by the
backend, never by the proxy:

| Check | Catches |
|---|---|
| Every class `aiset.classes()` names has a rule in the host sheet | An undesigned class, which renders as bare markup |
| The host sheet is linked after `aiset.css` | A theme that silently loses the cascade |
| The host redefines `--aiset-*` rather than fighting selectors | A theme that breaks when the library adds a rule |
| No unscoped element selector in the host sheet | A rule that restyles the host's own page |
| `curl` the asset path through the proxy | HTML served as JavaScript |

The first one is the important one, and since item 1 it needs no knowledge of the
source layout: `aiset.classes()` returns `{name, element, role, required}` as
data, so the check is a set comparison against the selectors in the host sheet.
`webui/frontend/settings.css` and `test_settings_styles.py` in the aidir
repository are a working implementation; the library's own test
`test_host_theme_covers_every_emitted_class` does the same for the shipped theme.

### 8a.8 What the library should own, and what stays with the host

This split is now implemented (items 5 and 8); the table is the contract:

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
| `capabilities` | `edit`, `add`, `remove`, `reorder`, `add_child`, `remove_child`, `key_options`, `key_pattern`; `unsupported` names a recognized-but-unexecuted capability (for example `hooks`) and every action is then false. |
| `matched_option` | Index into `children_options` of the `union` alternative the stored value validated against; absent when none matches. |
| `field` | Descriptor metadata: type, description, default, constraints, `env`, `ui`, `nullable`, `required`, `read_only`. |
| `comments` | Source comments that introduce the node, markers removed, decorative rules dropped. |
| `template` | `name` and inline `default` of a stored `${VAR}` / `${VAR:-default}`. |
| `access_denied` | Set instead of values when a secret subtree is addressed. |
| `default_applied` | Effective view only: the descriptor default is in use. |

`kind` is decided by the parent, not by the node type: a string inside an array
is an `array_item`, because `remove` and `move` address the item path. A value
under a dynamic object key is a `dynamic_key` when it is an object, and keeps its
own shape (for example `leaf` for a scalar) otherwise; both carry `remove`.

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
```

- `add` on an array uses the `-` append token; on an object it names a key the
  descriptor permits.
- `remove` is refused for `required`, `const` and `read_only` nodes.
- `remove` on an object entry names its key, so a dynamic key (`/obj/some-key`)
  is deleted the same way an array item is; the entry keeps its comments with it.
- `rename` changes one object key in place, keeping the value and its comments as
  one entry (never a `remove` plus an `add`). `to` is the new key, checked like
  an `add` key; the editor stages this when the user edits a key field.
- `move` carries the item with its comments.
- `drop` removes a key the descriptor does **not** declare. It exists for the
  doctor: `remove` resolves the node first and answers `NOT_FOUND` for exactly
  that case. `drop` refuses a declared path, a read-only parent and a secret
  subtree without `settings_edit_secret`.
- One batch, one revision, all-or-nothing: the first failure aborts everything
  and the file stays byte-for-byte unchanged.
- Validate with `dry_run=True` (or `POST /operations/validate`) before applying.
- `value_text` is JSON5 source text: strings carry their quotes.

### 13.1 Repairing a drifted document: `doctor`

`doctor` reports every issue with the one fix class that could handle it, and
`fix` applies the named classes. `fix=True` means `clamp` only.

| Class | Repair | Safe? |
|---|---|---|
| `clamp` | number to its declared `minimum`/`maximum` | yes |
| `coerce` | `"8080"` to `8080` for an unambiguous literal | opt-in |
| `drop_unknown` | remove a key the descriptor does not declare | lossy |

Report-only: `const`, `enum`, `pattern`, lengths, unions, keys, `required`
(there is no default for a required node in this grammar), `env_*`, secrets,
read-only nodes and parse errors.

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
| New operation | `jsonsrc.py` (source edit), `service.py` (authorize, validate), `SPEC_.md`, `tests/test_tree_and_operations.py` |
| New snapshot field | `tree.py`, editor rendering, `SPEC_service.md` section 19 (snapshot) and 21 (editor), `tests/test_tree_and_operations.py` |
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
---

## 19. Rationale, invariants and pitfalls

The working notes that used to sit in a separate file are folded in here. They
are normative for an integrator, not history.

### 19.1 How the work is judged

| Preference | Consequence |
|---|---|
| The simplest solution that satisfies the requirement | No speculative abstraction, no "future-proofing" that adds concepts |
| The public interface stays small | Fewer concepts beats more capability; the tree editor API is the ceiling |
| No transactions, locks or atomicity across a batch | v1 has independent sequential operations; recovery is the Last Known Good file, not a rollback protocol |
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
- **Secrets never leave the server.** Environment diagnostics expose variable
  names only, never values.
- **Pin, never follow.** An install uses a pinned revision; an incompatible
  version fails with a clear compatibility error instead of changing behaviour
  silently.
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
- **A valid external edit is adopted; an invalid one is restored.** Do not
  clobber either with a stale in-memory copy, and never serve stale data.
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
- **`Service.register` is lenient, the CLI is not.** Unknown properties are
  warnings at runtime so host metadata is accepted; `validate-descriptor
  --strict` turns them into errors. That split is deliberate: the runtime must
  not reject a host's own annotations, and the CLI is the typo gate.

### 19.5 What the implementation actually is

- **Zero runtime dependencies.** The JSON5 template engine (`jsonsrc.py`), the
  WSGI adapter (`httpd.py`) and the console script (`cli.py`) ship with the
  package.
- **Hooks compile but do not execute.** A write touching a hook-bound node is
  refused with `UNSUPPORTED_CAPABILITY`, and the snapshot reports
  `capabilities.unsupported = "hooks"` with every action false.
- **No MCP transport and no helper execution in this revision.** The Python and
  HTTP surfaces are complete; do not plan around an MCP endpoint that does not
  exist yet.
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
