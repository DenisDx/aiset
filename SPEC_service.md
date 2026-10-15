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
| `render_full_editor(document)` | an HTML fragment editing the whole document |

The helpers take a document ID (and, where applicable, a JSON Pointer path) and
an API base URL or transport callbacks supplied by the host. They use the same
HTTP contract (section 10) and perform only optional best-effort browser checks
(SPEC_.md section 9). No framework or build step is required.

## 18. Determinism and parity

- Python, HTTP, and MCP return the same values, issue paths, and status codes.
- The server is authoritative; browser checks are optional and advisory
  (SPEC_.md section 9).
- Effective snapshots are immutable and isolated from caller mutation.

## 19. Maintenance and change control

- This document is the authoritative interface specification for aiset. It is
  kept in sync with the implementation and with SPEC_.md as the project evolves.
- Any change to the Python, HTTP, or MCP interface must be reflected here in the
  same change, including the affected signatures, envelopes, and examples.
- When SPEC_.md's semantic rules change (descriptor grammar, storage, resolver,
  security), the corresponding interface statements here are updated in the same
  change.
- Interface versioning follows the release/API versioning decision recorded in
  the discussion register of SPEC_.md section 16. Incompatible changes are
  versioned and documented rather than applied silently.
