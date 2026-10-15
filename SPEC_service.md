# aiset Service and Transport Contract

Status: interface specification, first edition. Normative for the Python, HTTP,
and MCP interfaces of aiset; maintained in sync with the project.

This document specifies the aiset service interface: Python/HTTP signatures,
authorized descriptor/source/effective views, request/response/error envelopes,
revisions, optional-field results, and the standalone descriptor-validation CLI.
It is used for host integration. Where it fixes a concrete interface shape that
differs from the illustrative examples elsewhere in [SPEC_.md](SPEC_.md), this
document is authoritative for the interface; the semantic rules (descriptor
grammar, storage, resolver, security) remain in SPEC_.md.

## 1. Scope and conventions

- Applies to the first milestone (M1) and later phases; the core is shared by
  Python, HTTP, and MCP.
- The server is always authoritative (SPEC_.md section 9).
- Clients select a document ID and a JSON Pointer path, never a filesystem path.
- Placeholders are resolved by the resolver policy in SPEC_.md section 6.
- Operations and their results are transport-neutral; HTTP and MCP are thin
  adapters over the same service.

## 2. Common value types

| Type | Meaning |
|---|---|
| Document ID | Registered, allowlisted identifier (never a path). |
| Path | JSON Pointer (SPEC_.md section 5.3). `""` is the root. |
| View | `source`, `effective`, or a descriptor view (`authorized`, `raw`). |
| Revision | Opaque token; see section 4. |
| Principal | Authenticated actor, or the explicit local-demo principal. |
| Issue | Structured validation problem; see section 7. |

## 3. Python service API

A `Service` object is built from a host registration. The core operations are
synchronous; HTTP/MCP adapters may wrap them asynchronously.

```python
service.load(document_id, *, principal) -> LoadResult
service.get(document_id, path, *, view="source", principal) -> GetResult
service.validate(document_id, path, value_text, *,
                 expected_revision, expected_descriptor_revision,
                 principal) -> ValidateResult
service.set(document_id, path, value_text, *,
            expected_revision, expected_descriptor_revision,
            principal) -> SetResult
service.descriptor(document_id, *, view="authorized", principal) -> DescriptorResult
service.validate_descriptor(descriptor_source, *, mode="default",
                            principal=None) -> DescriptorDiagnostic
service.load_lkg(document_id, *, principal) -> LoadResult   # SPEC_.md 14.8.4
service.subscribe(document_id, paths, callback, *, principal) -> Subscription
```

Argument rules:

- `document_id`: string, required.
- `path`: JSON Pointer string; `""` denotes the root.
- `view`: `"source"` | `"effective"` for `get`; `"authorized"` | `"raw"` for
  `descriptor`.
- `value_text`: string containing exactly one JSON5 value or template value.
- `expected_revision`, `expected_descriptor_revision`: opaque strings, required
  for `validate` and `set`.
- `principal`: required for anything that reads or writes; it is `None` only
  for `validate_descriptor` (which has no document).
- `paths`, `callback`: used by `subscribe`; see section 13.

## 4. Revisions

Revision channels:

- `source_revision`: opaque; changes on any byte change, including comments and
  whitespace (SPEC_.md 7.3).
- `descriptor_revision`: opaque; separate from the source revision.
- `layer_revision`: internal opaque token for the host layer/provenance snapshot.
- `hook_registry_revision`: internal opaque token for hook registrations.

Rules:

- `validate` and `set` require both `expected_revision` (source) and
  `expected_descriptor_revision`.
- Clients do not send layer, resolver, or hook-registry revisions. The server
  captures them while preparing the candidate and verifies that same internal
  snapshot before commit.
- Missing required revision: error `REVISION_REQUIRED` (HTTP 428).
- A stale client source/descriptor revision or changed internal
  resolver/layer/hook-registry snapshot returns `REVISION_CONFLICT` (HTTP 409);
  never a blind retry.
- `stored_revision` is what is on disk after commit; `active_revision` is what
  the host has applied. They are distinct (SPEC_.md section 10).
- Token format is opaque to clients. The HTTP representation is a strong `ETag`
  equal to `sha256(source_revision + ":" + descriptor_revision)`, also returned
  as the `etag` field.

## 5. Views and authorization

Views:

- `source`: exact fragment, including comments, quotes, and template text.
- `effective`: resolved/defaulted/merged value with provenance.
- `authorized` descriptor: recognized and authorized properties only (browser
  default).
- `raw` descriptor: lossless descriptor, including project metadata (trusted
  host only; SPEC_.md 4.5).

Permissions:

| Permission | Grants |
|---|---|
| `settings_read_source` | `get(view=source)` |
| `settings_read_effective` | `get(view=effective)`, `load` |
| `settings_validate` | `validate` |
| `settings_write` | `set` |
| `settings_read_secret` | read secret subtrees |
| `settings_edit_secret` | write secret subtrees |
| `settings_load_lkg` | `load_lkg` |
| `settings_descriptor_raw` | `descriptor(view=raw)` |

Secret handling:

- Resolved secret values never appear in descriptors, errors, audit events, or
  logs.
- A source or effective fragment that contains an inaccessible secret is denied
  entirely: error `SECRET_ACCESS_DENIED` (HTTP 403). No partially redacted
  fragment is returned, to avoid overwriting the real value accidentally.

## 6. Principals

- HTTP: derived from the host's authentication; local demo mode uses an explicit
  local-demo principal (never a fabricated user).
- MCP: derived from the host's MCP authentication; write capability is never
  inherited from read or inference capability.
- Python: passed explicitly by the caller.

Audit records the principal, document, changed paths, old and new revisions,
and the result.

## 7. Issues and errors

An issue:

```json
{
  "path": "/redis/port",
  "rule": "maximum",
  "message": "Must be at most 65535",
  "severity": "error",
  "line": 12,
  "column": 18
}
```

- `severity` is `error` or `warning`.
- `line` and `column` are included when the source location is known.
- Secret values are never included.

Transport-neutral error envelope:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Candidate configuration is invalid",
    "issues": []
  }
}
```

Stable error codes: `BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`,
`REVISION_REQUIRED`, `REVISION_CONFLICT`, `COMMENT_PRESERVATION_CONFLICT`,
`PAYLOAD_TOO_LARGE`, `VALIDATION_ERROR`, `SECRET_ACCESS_DENIED`, `LOCK_TIMEOUT`,
`CALLBACK_TIMEOUT`, `NO_VALID_BACKUP`, `STORAGE_ERROR`,
`UNSUPPORTED_CAPABILITY`.

HTTP status mapping:

| Condition | Status |
|---|---|
| Malformed JSON, envelope, or pointer | 400 |
| Unauthorized / forbidden | 401 / 403 |
| Unknown document or undeclared path | 404 |
| No valid backup for LKG loading | 404 |
| Stale revision or preservation conflict | 409 |
| Body too large | 413 |
| Candidate validation failure | 422 |
| Missing required revision | 428 |
| Pre-commit callback timeout | 504 |
| Lock timeout | 503 |
| Unexpected storage failure | 500 |

## 8. Read results

Every response carries a uniform `ok` field. This is normative for the interface
and replaces the bare read example in SPEC_.md section 8.2.

GET `value` with `view=source`:

```json
{
  "ok": true,
  "document": "main",
  "path": "/logging/level",
  "view": "source",
  "exists": true,
  "value_text": "\"${LOG_LEVEL:-error}\"",
  "format": "json5-template",
  "revision": "opaque-source-revision",
  "descriptor_revision": "opaque-descriptor-revision",
  "etag": "opaque-etag",
  "origin": {"kind": "file", "document": "main"}
}
```

`format` is `json5-template` when the fragment contains recognized, enabled
placeholder syntax (even inside a quoted string); otherwise `json5`.

Optional-field results, all views:

| Case | `exists` | `value_text` | Extra |
|---|---|---|---|
| Absent optional leaf, source view | false | omitted | — |
| Explicit null | true | `"null"` | — |
| Absent optional leaf, effective view with default | false | the default value text | `default_applied: true` |
| Absent optional leaf, effective view without default | false | omitted | — |

Root (`path: ""`) is readable; it is not writable in v1.

Explicit LKG load:

```json
{
  "ok": true,
  "document": "main",
  "loaded": "lkg",
  "revision": "opaque-backup-source-revision",
  "descriptor_revision": "opaque-descriptor-revision",
  "reason": "explicit_lkg_request"
}
```

`load_lkg` is read-only: it selects and validates the newest valid backup but
does not replace the current file. If none is valid, it returns
`NO_VALID_BACKUP`. The operation requires `settings_load_lkg` and records an
audit event without exposing resolved secrets or an absolute filesystem path.

## 9. Write results

Validate:

```json
{
  "ok": true,
  "valid": true,
  "preservable": true,
  "issues": [],
  "revision": "opaque-source-revision",
  "descriptor_revision": "opaque-descriptor-revision"
}
```

`preservable: false` means the candidate validates but cannot be persisted
without a comment-preservation conflict (SPEC_.md 7.1 and 5.3).

Set:

```json
{
  "ok": true,
  "stored": true,
  "revision": "new-source-revision",
  "descriptor_revision": "opaque-descriptor-revision",
  "application": {
    "state": "restart_required",
    "active_revision": "previous-active-revision"
  },
  "hook_results": []
}
```

Application states: `applied`, `reload_required`, `restart_required`,
`apply_failed`. A missing host application callback cannot report `applied`. A
committed write whose callback fails returns `stored: true` with `apply_failed`
and an explicit application error, never a generic write failure.

## 10. HTTP routes

`{base}` denotes the configured mount prefix (for example `/api/settings`).

| Method | Route | Operation |
|---|---|---|
| GET | `{base}/descriptor?document=&view=authorized` | `descriptor` |
| GET | `{base}/value?document=&path=&view=source` | `get` |
| POST | `{base}/validate` | `validate` |
| POST | `{base}/value` | `set` |
| POST | `{base}/load` | `load` |
| POST | `{base}/load/lkg` | `load_lkg` |
| GET | `{base}/tree?document=&path=&view=source` | `tree` (section 19) |
| POST | `{base}/operations/validate` | `apply_operations(dry_run=True)` (section 20) |
| POST | `{base}/operations` | `apply_operations` (section 20) |
| POST | `{base}/descriptor/validate` | `validate_descriptor` (development) |

`POST` body for `validate` and `set`:

```json
{
  "document": "main",
  "path": "/logging/level",
  "value_text": "\"warning\"",
  "expected_revision": "opaque-source-revision",
  "expected_descriptor_revision": "opaque-descriptor-revision"
}
```

Revisions are carried canonically in the body (works for HTTP and MCP). HTTP may
additionally accept `If-Match` with the `etag`, but the body fields remain
authoritative. Cookie-based writes require the host's CSRF and origin
protections (SPEC_.md 3.3 and 11).

`POST {base}/load/lkg` accepts `{"document": "main"}` and returns the LKG result
from section 8. It does not accept a filesystem path or modify the document.

## 11. MCP tools

Register `settings_get`, `settings_validate`, `settings_set`, and
`settings_descriptor`, plus `settings_load_lkg`, with the same
document/path/value/revision inputs and the same result shapes as HTTP.
`settings_load_lkg` accepts a document ID and returns the section 8 LKG result.
Tool schemas describe request envelopes, not a second configuration schema.

- Application validation failures use MCP's error-result mechanism
  (`isError: true`) while retaining the shared `code` and `issues` in structured
  content.
- A committed `set` with `apply_failed` retains `stored: true`.
- Write tools are independently permissioned and must not inherit write from a
  read or inference capability.

## 12. Descriptor-validation CLI

The console entry point is `aiset` with a `validate-descriptor` subcommand:

```sh
aiset validate-descriptor <descriptor-file> [--strict] [--format json|text] [--quiet]
```

- `<descriptor-file>`: a path, or `-` for standard input.
- `--strict`: unknown-property diagnostics become errors.
- `--format json` (default) prints the diagnostic object; `text` prints a human
  summary.
- Exit status: `0` when `valid` is true, `1` when false, `2` on usage or I/O
  error.
- JSON output matches SPEC_.md 4.5: `{"valid": true, "issues": [...]}`.
- Runs without starting a server or loading project settings.

## 13. Change subscriptions

A host (or another service) can subscribe callbacks to changes of specific
document paths, so it can re-read and reapply configuration when a subscribed
key changes.

```python
service.subscribe(document_id, paths, callback, *, principal) -> Subscription
subscription.unsubscribe()
```

- `paths`: a nonempty list of JSON Pointers. A subscription may cover a single
  leaf, a subtree root, or the document root (`""`).
- `callback`: invoked after a durable commit, outside the file lock, with an
  immutable event containing the document ID, the changed paths, the previous
  and new source revisions, the stored and active revisions, and the application
  state.
- Delivery is in-process and after-commit. It is a notification, not a durable
  queue: exactly-once delivery and delivery across a process crash are not
  promised (SPEC_.md section 10).
- A callback must not perform recursive writes to the same store; a later
  independent edit is a new revision-checked operation.
- Subscribing requires a principal with `settings_read_effective` on the covered
  paths. Resolved secret values are never passed to a callback.
- `unsubscribe()` removes the subscription; a subscription is also released when
  its process ends.

The web UI uses polling in the first version: it re-reads revisions on an
interval and refreshes when they change. Server-push (SSE/WebSocket) is not
provided initially. Cross-process distribution and acknowledgements remain host
concerns (SPEC_.md section 10). Registration via MCP (resource notifications) is
a later phase.

## 14. Merge API

`merge` assembles a configuration value from a base and an update. It is a pure
function: it does not read or write the store, does not use revisions, and does
not preserve source comments. Its full semantics are in SPEC_.md section 10.1.

```python
aiset.merge(base, update) -> merged
```

- `base`, `update`: JSON-compatible values (in practice, objects).
- `merged`: a new value; the inputs are not mutated.
- The update has priority; recursion and replacement rules are in SPEC_.md
  10.1.
- To apply several updates, chain the calls over a single base
  (`aiset.merge(aiset.merge(base, u1), u2)`); the host owns that sequencing.

Merge is available in Python. An HTTP route and an MCP tool are optional
conveniences for hosts that want to merge without importing aiset:

| Method | Route | Body | Result |
|---|---|---|---|
| POST | `{base}/merge` | `{"base": {...}, "update": {...}}` | `{"ok": true, "merged": {...}}` |

The route uses the same authorization as reads and carries ordinary JSON values
(no document IDs or revisions are involved).

## 15. Config object API

A Config object bundles data with origin and metadata and provides creation,
update, and save. Its semantics are in SPEC_.md section 10.2.

```python
Config.load(path, *, mount=None, typedef_sources=None, principal) -> Config
config.data                        # the JSON-compatible value
config.origin                      # {file, loaded_at, mount}
config.update(other) -> Config     # merge other onto this (SPEC_.md 10.1)
config.reload()                    # re-read from disk (SPEC_.md 10.4)
config.save(*, expected_revision, expected_descriptor_revision) -> SetResult
config.subscribe(paths, callback, *, principal) -> Subscription
config.rollback(reason)
```

- `path`: the file to load.
- `mount`: where this Config belongs in a base, for example `workers.myworker`
  or `workers.items.[id=myworker]` (SPEC_.md 10.2).
- `typedef_sources`: an optional list of files whose `typedef` definitions
  (SPEC_.md 4.6.10) are added to the template registry when this Config is
  loaded. This is how a component keeps its template in its own folder; the core
  collects the list (see the example in SPEC_.md 10.2). Template-name collisions
  across the main descriptor and the sources are descriptor errors (SPEC_.md
  4.3).
- `config.update(other)`: uses the merge operation (section 14); returns a new
  Config; the base is not mutated.
- `config.reload()`: re-reads the file (and layers) from disk and applies the
  external-edit rules of SPEC_.md 10.4.
- `config.save(...)`: validates, persists, and reports application status
  through the same pipeline as `service.set`.
- `config.rollback(reason)`: shifts the backup chain down by one level (undoing
  the last change, SPEC_.md 10.3/14.8.4), audit-logs the reason, and reports
  `restart_required`; the host owns the decision and performs the restart.

## 16. Save callbacks

Two callbacks may be registered per Config (or globally on the service), each
synchronous or asynchronous (SPEC_.md 10.3). Each receives the full
configuration before and after the change, not a branch:

```python
config.on_probe_changes(callback)   # sync or async; may reject
config.on_after_save(callback)      # sync or async; notification
```

- `probe_changes(before, after) -> ok | Rejection`: a rejection carries the
  fields that were not accepted and a text explanation (the shared issue
  format); returning it cancels the save. It may also be called for intermediate
  validation without a following save.
- `after_save(before, after, event)`: called after a durable commit, outside the
  file lock.
- For an asynchronous `probe_changes`, aiset awaits the decision before
  proceeding.
- Every save callback uses the same bounded timeout policy as descriptor hooks:
  30 seconds by default, configurable globally, and optionally shortened per
  registration. An unbounded registration is invalid.
- A `probe_changes` timeout returns `CALLBACK_TIMEOUT` before persistence. An
  application timeout returns `stored: true` with `apply_failed`. An
  `after_save` timeout returns `stored: true` with a callback-failure receipt;
  it does not change the application result or trigger rollback. Unknown late
  outcomes are explicit and are not retried blindly.

The application callback is registered separately and applies a committed change
to the running host:

```python
service.on_application(callback)    # sync or async
```

- `application(before, after, changed_paths) -> applied | apply_failed(issues)`:
  receives immutable old and new snapshots and the changed paths, and returns
  whether the change was applied. It runs after commit, before the `after_*`
  hooks and `after_save` (order in SPEC_.md 10.3). It is distinct from
  `after_save`, which is only a notification.

## 17. UI asset API

The library ships ready-to-include assets and helper functions that return HTML
fragments, so a host can embed editing with minimal effort (SPEC_.md section 9).
These are browser/JS helpers, not server calls: the host includes the shipped JS
files and inserts the returned fragment.

| Helper | Returns |
|---|---|
| `include_assets()` | an HTML string that includes the library's JS/CSS assets |
| `render_node_editor(document, path)` | an HTML fragment editing one node/subtree |
| `render_full_editor(document)` | an HTML fragment editing the whole document (the generated tree editor, section 21) |
| `render_tree_editor(document, options=None)` | an HTML fragment of the generated tree editor |

The helpers take a document ID (and, where applicable, a JSON Pointer path) and
an API base URL or transport callbacks supplied by the host. They use the same
HTTP contract (section 10) and perform only optional best-effort browser checks
(SPEC_.md section 9). No framework or build step is required.

## 18. Determinism and parity

- Python, HTTP, and MCP return the same values, issue paths, and status codes.
- The server is authoritative; browser checks are optional and advisory
  (SPEC_.md section 9).
- Effective snapshots are immutable and isolated from caller mutation.

## 19. Tree snapshots

One consistent, authorized snapshot of a subtree, so a generated editor renders
the whole document from a single revision instead of issuing one request per
node (proposal `proposal_demo2.md` section 8.1).

```python
service.tree(document_id, path="", *, view="source", principal) -> dict
```

HTTP:

```http
GET {base}/tree?document=main&path=&view=source
```

Response:

```json
{
  "ok": true,
  "document": "main",
  "path": "",
  "view": "source",
  "exists": true,
  "revision": "opaque-source-revision",
  "descriptor_revision": "opaque-descriptor-revision",
  "invalid_on_disk": false,
  "loaded_from": "file",
  "node": { "...": "recursive node" }
}
```

Each node carries:

| Field | Meaning |
|---|---|
| `path` | JSON Pointer of the node |
| `exists` | `false` for an absent permitted optional leaf |
| `value_text` | Exact source fragment, or `null` |
| `effective` | Resolved value when `view=effective` |
| `origin` | `file`, `environment` (with `variable`), `default`, or `absent` |
| `default_applied` | `true` when an effective default is shown |
| `type`, `apply`, `field` | Descriptor metadata; `field` is the authorized node description |
| `access_denied` | `true` for a secret node the principal may not read; its values are omitted, never redacted |
| `kind` | `object`, `dynamic_key`, `array_item`, `leaf`, or `undeclared` |
| `capabilities` | `edit`, `add`, `remove`, `reorder`, `add_child`, `remove_child`, `key_options`, `key_pattern` |
| `kind` | `array`, `array_item`, `object`, `dynamic_key`, `leaf` or `undeclared` |
| `comments` | Comments of the source file that introduce the node, markers removed; decorative section rules are dropped |
| `template` | `name` and inline `default` of a stored `${VAR}` / `${VAR:-default}`; absent for a plain value |

`kind` is decided by the parent, not by the node type: a string inside an array
is an `array_item`, because `remove` and `move` address the item path itself.
`remove` and `reorder` therefore belong to the item, and an item of a
`read_only` array carries neither.

The editor shows `comments` and `field` in the tooltip of the node name: the
source comments first, then the descriptor description, the flags (`required`,
`nullable`, `read_only`, `secret`), the apply policy, the environment
conversion, the default, the constraints and the value as written. A node whose
`field.default` is declared also gets a small button that stages that default;
the button is disabled while the stored value already is the default.
| `children`, `items` | Recursive nodes for objects and arrays |
| `additional_child` | Field description of dynamic values, used to create a property |

The snapshot is consistent with one source and one descriptor revision; a
secret subtree is reported as `access_denied` without values, while the
single-value `get` API still denies such a fragment entirely (section 5).

## 20. Atomic structural operations

One batch of structural operations, applied to a single in-memory candidate and
committed as one durable write. This is a staged user batch, not a transaction
system: there are no partial commits and no rollback log (see `SPEC_.md`
Correction 1).

```python
service.apply_operations(document_id, operations, *,
                         expected_revision, expected_descriptor_revision,
                         principal, dry_run=False) -> OperationsResult
```

Operation shapes:

```json
{"op": "set",    "path": "/server/port", "value_text": "8384"}
{"op": "add",    "path": "/fixtures/tags/-", "value_text": "\"new\""}
{"op": "add",    "path": "/fixtures/dynamic/new_key", "value_text": "1"}
{"op": "remove", "path": "/fixtures/tags/1"}
{"op": "move",   "from": "/fixtures/items/2", "path": "/fixtures/items/0"}
```

HTTP:

```http
POST {base}/operations/validate
POST {base}/operations
```

Request body for both routes:

```json
{
  "document": "main",
  "operations": [{"op": "set", "path": "/server/port", "value_text": "8384"}],
  "expected_revision": "opaque-source-revision",
  "expected_descriptor_revision": "opaque-descriptor-revision"
}
```

Rules:

- `add` on an array uses the `-` append token; `add` on an object names a key
  the descriptor permits (`children` entry, `additional_children`,
  `key_enum`, `key_pattern`).
- `remove` is refused for required, `const`, and `read_only` nodes and for fixed
  declared children of an object without `additional_children`.
- `move` takes an array item to another index, carrying its comments with it.
- Every affected path is authorized (secret and read-only descendants included)
  and validated before anything is written.
- Operations are applied in order to one candidate document; the first failure
  aborts the batch and the file stays byte-for-byte unchanged.
- `apply_operations(..., dry_run=True)` requires only `settings_validate` and
  returns the issues without writing. `dry_run: true` marks the response.

Result:

```json
{
  "ok": true,
  "document": "main",
  "valid": true,
  "dry_run": false,
  "stored": true,
  "operations": [{"op": "set", "path": "/server/port", "value_text": "8384"}],
  "issues": [],
  "revision": "new-source-revision",
  "descriptor_revision": "opaque-descriptor-revision",
  "application": {"state": "reload_required", "active_revision": "previous-active-revision"},
  "changed_paths": ["/server/port"]
}
```

An invalid committed batch raises `VALIDATION_ERROR` (HTTP 422) with the shared
issue list and writes nothing; permission failures keep their own status
(`FORBIDDEN`, `SECRET_ACCESS_DENIED`), and stale revisions return
`REVISION_CONFLICT` as for single-value writes. Backup, audit, callback,
application-state and subscription semantics are identical to `set`.

## 21. UI asset API for generated editors

The shipped assets add a generated tree editor. The host integration stays two
lines; see `proposal_demo2.md` section 7.1.

| Helper | Responsibility |
|---|---|
| `renderTreeEditor(document, options)` | Return the complete tree-editor host fragment |
| `mountTree(target, options)` | Mount one editor and return its instance |
| `instance.getPendingOperations()` | Copy of the staged operations |
| `instance.stageOperations(operations, source)` | Stage user or agent operations |
| `instance.validatePending()` | Validate the complete staged batch |
| `instance.applyPending()` | Validate and commit the batch |
| `instance.reload()` | Re-read and re-render from the server |
| `instance.revert(path)` | Drop staged operations for one path |
| `instance.expandAll()` | Open every composite section of the snapshot |
| `instance.collapseAll()` | Close every section; the document root stays open |
| `instance.isExpanded(path)` | Whether one path is currently open |
| `instance.setValuesAsText(flag)` | Show or hide the stored text of objects and arrays |
| `instance.getValuesAsText()` | Read the current text representation |
| `instance.setShowAbsent(flag)` | Show or hide keys the descriptor allows but the file does not contain |
| `instance.getShowAbsent()` | Read the current absent-key representation |
| `instance.on(event, handler)` | `loaded`, `staged`, `validated`, `applied`, `status`, `lifecycle`, `viewchange` |

```js
aiset.mountTree("#settings-tree", { document: "demo2", apiBase: "/api/settings" });
```

```python
from aiset.assets import render_tree_editor
page = render_tree_editor("demo2")
```

`options.lifecycle` adds host buttons (for example Reload and Restart) that POST
to a host route; the editor never restarts a process itself. The editor itself
offers **Expand all** and **Collapse all** in its toolbar; `options.viewButtons:
false` suppresses them when the host renders its own toolbar.

A node can also be edited as raw source: the mode replaces the subtree of that
node with a textarea holding the stored fragment, and leaving it stages one
`set` operation only after the server accepted it; otherwise the server issues
are shown and nothing is staged (SPEC_.md correction 4).

A node whose stored value is a placeholder renders two controls: the variable
name and the inline fallback, the latter with the control of the declared type.
Editing either rewrites the token instead of dropping the substitution, and an
empty name stores the inline value again. A node whose descriptor sets
`env.allowed` also offers a button that switches it into that mode. The tree
snapshot never carries an environment value: `POST <base>/env` with
`{"document": ..., "names": [...]}` answers which variables are set and nothing
more.

An object or an array is edited through its children, never as a single value,
so no composite value control is rendered. `options.showAbsent` (default
`false`) and `instance.setShowAbsent()` decide whether the declared keys that the
file does not contain are rendered; they carry `exists: false` and the usual
`default` or `absent` badge. A leaf with nothing to show (an unwritten
read-only node) renders a coloured type mark instead of an empty control:
`i` for `int`, `n` for `number`, `"` for `string`, `b` for `bool` and `?` for any
other type; red is never used. `options.valuesAsText` (default
`false`) and `instance.setValuesAsText()` add the stored source fragment of each
composite node as a read-only `pre.aiset-tree-source` block. Structural actions
(add, remove, reorder, explicit null) are square icon buttons that carry no text
and explain themselves through the button `title`, which browsers also show on a
long press. Every mounted
instance owns its document, revisions, staged operations and status: no mutable
state is shared between instances through module globals. `renderFullEditor()`
is the generated tree editor; `renderNodeEditor()` remains the single path/value
editor of section 17.

## 22. Maintenance and change control

- This document is the authoritative interface specification for aiset. It is
  kept in sync with the implementation and with SPEC_.md as the project evolves.
- Any change to the Python, HTTP, or MCP interface must be reflected here in the
  same change, including the affected signatures, envelopes, and examples.
- When SPEC_.md's semantic rules change (descriptor grammar, storage, resolver,
  security), the corresponding interface statements here are updated in the same
  change.
- Interface versioning follows the release/API versioning decision recorded in
  the discussion register of SPEC.md section 16. Incompatible changes are
  versioned and documented rather than applied silently.
- Corrections to the protected `SPEC.md` are proposed in `SPEC_.md`; the
  interfaces of sections 19-21 were added for `demo2` and are recorded there.
