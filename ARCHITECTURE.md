# Architecture

Internal architecture of the `aiset` library and its reference hosts. Behaviour
and interface contracts are normative in [SPEC.md](SPEC.md) and
[SPEC_service.md](SPEC_service.md); this document describes how the implemented
components are organised and how data moves between them.

## Project file structure

| Path | Purpose |
|---|---|
| `src/aiset/` | The library. No runtime dependencies outside the standard library. |
| `src/aiset/assets/` | Stylesheet, browser editor, and optional host theme shipped as package data. |
| `src/aiset/httpd.py`, `src/aiset/asgi.py` | WSGI and ASGI adapters over the same dispatcher. |
| `src/aiset/cli.py` | `aiset` command: validate, doctor, and descriptor checks. |
| `demo_app.py`, `frontend/` | Standalone M1 demo editor and its page assets. |
| `examples/` | Descriptors and settings documents used by the demo and tests. |
| `demo2/` | Acceptance host: settings page, assistant, lifecycle actions, launcher. |
| `tests/`, `demo2/tests/` | Unit, integration, browser-asset, and host tests. |
| `AGENT_INTEGRATION.md`, `AGENTS.md` | Integration guide and the agent workflow. |
| `SPEC.md`, `SPEC_.md`, `SPEC_service.md` | Baseline specification, approved amendments, normative service contract. |
| `ARCHITECTURE.md`, `DOCUMENTS.md`, `README.md`, `TEST.md`, `commands.md` | Architecture, document map, user guide, test protocol, commands. |
| `memory/` | Agent working context and history. |
| `local_*` | Local overrides and working notes; excluded from Git. |

## Logical component structure

The core is a pipeline of independent modules; the service composes them and the
transports only translate.

- **`jsonsrc`** — source-preserving JSON5 parser and editing engine. It builds a
  concrete syntax tree that keeps whitespace, comments, quotes, and template
  tokens. `Document` exposes read access, JSON Pointer lookup, stored-value
  conversion, and the mutation operations (`apply_set`, `apply_add`,
  `apply_remove`, `apply_move`, `apply_rename`). Every mutation is textual and
  local to one node or batch. This module is the only writer of configuration
  source.
- **`descriptor`** — descriptor grammar, diagnostics, template expansion,
  fragment composition, and compilation into a `Node` tree. It accepts
  unknown project metadata at runtime and reports it through development
  validation. `Node` is the contract shared with validation, resolution, tree
  snapshots, and the doctor. `description` and `title` keep the default-language
  string; the full localized map travels with the node for locale-aware readers.
- **`validator`** — validates stored values against a compiled `Node`, including
  unions, regex limits, and secret markers. It returns structured `ValueIssue`s,
  never raises for ordinary invalid values.
- **`resolver`** — resolves `${VAR}` / `${VAR:-default}` templates and produces
  the effective configuration from stored values, defaults, and environment
  data. Provenance stays separate from the stored document.
- **`tree`** — builds one authorized snapshot for generated editors: kinds,
  labels, capabilities, union alternatives, comment-derived descriptions, and
  secret redaction. It is read-only. An optional `locale` resolves localized
  `description`/`title` for display while the full map stays in the snapshot.
- **`merge`**, **`config_obj`** — pure merge of configuration objects and the
  host-facing `Config` object with its mount grammar. `config_obj` keeps origin
  metadata for values assembled from several files.
- **`store`** — durable file access: revision hashing, locking, backups, last
  known good (LKG) handling, external-edit detection, and byte-exact writes. It
  never interprets configuration content.
- **`service`** — the shared orchestration layer. It registers allowlisted
  documents, enforces permissions and revisions, runs validate/set/operations and
  the doctor, and fires snapshot, application, veto, and save callbacks. All
  transports call this object; there is no separate editing logic per transport.
- **`httpd`**, **`asgi`** — adapters that turn HTTP requests into service calls
  and service results into the documented envelopes and status codes. They share
  the same route dispatcher and serve the bundled assets.
- **`cli`** — a thin process boundary over descriptor and document validation and
  the doctor, using explicit resolver inputs.
- **`doctor`** — diagnoses a document through the service and optionally applies
  the mechanically fixable part. It writes only a fully valid result.
- **Browser assets (`aiset.js`, `aiset-tree.js`, `aiset.css`)** — a dependency-free
  editor that consumes tree snapshots and stages edits; it owns no policy. The
  host supplies the page, layout, and optional theme.
- **`demo_app.py` / `demo2/`** — reference hosts. They own page structure,
  lifecycle, assistant integration, and their descriptors; they use the same
  public library surface a third-party host uses.

Autonomy boundaries: `src/aiset` is the replaceable library unit; each transport
is independently mountable; `demo2` is an independently executable host. Within
the library, `jsonsrc`, `descriptor`, `store`, and `service` have the strongest
boundaries because they isolate source fidelity, schema semantics, durability,
and policy respectively.

## Data structures and data flows

Principal representations:

- **Source text and CST.** Configuration and descriptors enter as text. The CST
  retains every span; edits produce new text without re-serializing untouched
  regions.
- **Stored value.** A plain Python value (objects, arrays, scalars) converted
  from the CST for validation and resolution.
- **Compiled descriptor.** `CompiledDescriptor` holds the raw descriptor, a
  `Node` root, a revision, and project metadata. Each `Node` carries type,
  constraints, children, UI metadata, secrets, hooks, and inherited flags.
- **Revision.** Content hash (`sha256:...`) of the stored bytes. Responses carry
  the document revision and the descriptor revision; writes require both.
- **Envelopes and issues.** Results and errors have stable codes and structured
  `ValueIssue`/`Issue` records. `tree` snapshots are the browser contract.

Principal flows:

1. **Registration.** A host calls `Service.register` with a document id, path,
   and descriptor source. The descriptor is compiled, the `Store` is created and
   symlink-checked, and the registration is kept in the service. Clients never
   choose file paths.
2. **Read.** The store reads bytes; `Document` parses them into the CST; the
   stored value is validated against the descriptor and, for the effective view,
   passed through resolution. `get`, `tree`, and `env_status` return authorized
   results; secret subtrees are refused unless the principal may read secrets.
3. **Single edit.** A candidate value text is parsed and applied to the current
   CST with a pointer-based mutation. The resulting source is re-parsed,
   validated, and resolved as required. Under the store lock the service checks
   that the on-disk revision still matches, writes the bytes, rotates a backup,
   and adopts the new revision. Callbacks and subscriptions run after commit and
   never roll it back.
4. **Structural edit.** A batch of operations is applied in order to a candidate
   CST, validated as one document, and written once. A failure leaves the file
   unchanged; the host can still recover through the LKG path.
5. **Effective configuration.** Stored values plus environment data and
   defaults produce the effective view. Resolution reports provenance separately
   and never writes resolved secrets.
6. **Browser editing.** The page loads the bundled assets and a tree snapshot.
   User actions stage `set` or `operations` calls with the revisions from the
   snapshot; the response refreshes the snapshot or reports issues. Search and
   reveal are browser-only.
7. **Failure handling.** Parse and validation problems are returned as issues;
   revision conflicts and permission failures are stable-coded errors. A failed
   external edit leaves the LKG selectable. The doctor can diagnose and repair
   the mechanically fixable part, writing only a fully valid result.
