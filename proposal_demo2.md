# Demo2 Host Application Proposal

Status: proposed; implementation starts only after approval.
Date: 2026-10-15.

## 1. Goal

Add a second standalone test host named `demo2`. Unlike the existing minimal
`demo_app.py`, it is a complete host application that:

- uses aiset as the only configuration storage, validation, and editing layer;
- runs in aiset's existing `.venv`;
- serves an AIDIR-styled two-pane page on port `8383` by default;
- presents the complete `demo2` configuration as an editable tree;
- supports adding and removing values where allowed by the descriptor;
- exposes **Apply**, **Reload**, and **Restart** actions;
- includes an AI chat whose configured model can inspect and change the same
  configuration through aiset;
- acts as an acceptance host for all supported descriptor and value shapes.

This proposal defines both the host and the missing reusable aiset capabilities.
The tree editor must not be implemented as a private `demo2` editor.

## 2. Scope and boundaries

### 2.1 In scope

1. A tracked `demo2/` host with its own backend, frontend, descriptor, examples,
   and tests.
2. A root-level `run_demo2.sh`.
3. Local runtime files `demo2/config.json5` and `demo2/.env`, seeded from their
   tracked `.example` files.
4. Reusable tree-editor, structural-edit, and staged-change capabilities in
   aiset.
5. An OpenAI-compatible configuration agent implemented by the host and limited
   to aiset's public service.
6. Automated backend/API tests and manual browser acceptance tests.

### 2.2 Out of scope

- Production authentication, multi-user isolation, TLS, CORS, and internet
  exposure.
- A general autonomous agent framework in aiset.
- Editing `.env` in the browser.
- Persisting chat history across application restarts.
- Supporting provider protocols other than OpenAI-compatible Chat Completions
  in the first version.
- Replacing the existing `demo_app.py`.

`demo2` is an internal test host. It must bind to the configured host and fail
clearly if the configured port is unavailable; it must not silently select
another port.

## 3. Proposed file layout

```text
aiset/
  run_demo2.sh
  proposal_demo2.md
  demo2/
    app.py
    config.json5.example
    config.json5                 # local, ignored, created on first run
    descriptor.json5
    .env.example
    .env                         # local, ignored, created on first run
    frontend/
      index.html
      app.js
      styles.css
    tests/
      test_app.py
      test_agent.py
```

The host may split `app.py` into small Python modules if implementation makes a
single file difficult to test, but all host-specific code remains under
`demo2/`. Reusable editor code belongs under `src/aiset/`.

## 4. Startup contract

`run_demo2.sh` is the supported entry point. It must:

1. resolve the aiset root from the script's own location;
2. use `set -eu`;
3. copy `demo2/config.json5.example` to `demo2/config.json5` only when the
   destination does not exist;
4. copy `demo2/.env.example` to `demo2/.env` only when the destination does not
   exist;
5. verify that `.venv/bin/python` exists and is executable;
6. execute `demo2/app.py` with `.venv/bin/python`;
7. forward all command-line arguments and return the Python process exit code.

The script must not activate a shell environment, create a venv, install
packages, overwrite an existing local file, or use the system Python.

Example:

```sh
./run_demo2.sh
./run_demo2.sh --demo2.port:8384
```

Command-line overrides follow the existing `--<dotted.path>:<value>` demo
convention and have the highest precedence for the running process. They are
not written to `config.json5`.

## 5. Environment and configuration

### 5.1 `.env.example`

The tracked environment template will contain safe examples only:

```dotenv
DEMO2_HOST=0.0.0.0
DEMO2_PORT=8383
DEMO2_AI_BASE_URL=http://127.0.0.1:11434/v1
DEMO2_AI_API_KEY=
```

The implementation must parse `demo2/.env` as data and pass the resulting
mapping to `aiset.resolver.Resolver`. It must not copy values into logs, API
responses, HTML, or saved JSON5.

### 5.2 `config.json5.example`

The server settings use environment placeholders:

```json5
server: {
  host: "${DEMO2_HOST:-0.0.0.0}",
  port: "${DEMO2_PORT:-8383}",
}
```

The descriptor declares `server.port` as `int` with environment conversion.
Therefore the effective value is an integer even though the source is a
placeholder string.

The AI model is selected in the configuration, not hard-coded:

```json5
ai: {
  enabled: true,
  provider: {
    type: "openai",
    base_url: "${DEMO2_AI_BASE_URL:-http://127.0.0.1:11434/v1}",
    api_key: "${DEMO2_AI_API_KEY}",
  },
  model: "qwen3:8b",
  timeout_seconds: 60,
  temperature: 0.2,
  max_tool_rounds: 8,
  require_change_confirmation: true,
}
```

The exact example model may be changed before implementation if the local test
environment uses a different default. The application must show a clear
configuration error when AI is disabled, the model is empty, or the provider
cannot be reached.

### 5.3 Descriptor coverage

`demo2/descriptor.json5` is the authoritative UI and validation template.
Descriptions are required for the root, every section, and most leaves. Missing
descriptions are acceptable only for intentionally repetitive fixture children.

The fixture configuration must cover at least:

| Shape or rule | Required example |
|---|---|
| Scalars | string, integer, number, boolean, and explicit null |
| Constraints | enum, const/read-only, min/max, length, pattern |
| Optionality | required, optional absent, nullable, default |
| Environment | string and integer placeholders; one secret |
| Arrays | strings, integers, booleans, objects, nested arrays |
| Fixed objects | multiple levels of declared children |
| Dynamic objects | `additional_children` with `key_pattern` |
| Restricted dynamic objects | `additional_children` with `key_enum` |
| Composite alternatives | union and array `children_options` |
| Application policy | `live`, `reload`, and `restart` fields |
| Paths | a key requiring JSON Pointer escaping |

Fixture-only fields are grouped under a clearly described `fixtures` object and
have no runtime effect. This keeps the real server and AI settings easy to find.

## 6. Application architecture

### 6.1 Backend

`demo2/app.py` will:

1. load `.env` without mutating the tracked examples;
2. construct aiset `Settings`, `Resolver`, and `Service`;
3. register one document ID, `demo2`, using `config.json5` and
   `descriptor.json5`;
4. register the host application callback for `live` and `reload` changes;
5. mount the reusable aiset HTTP application and assets;
6. add host routes for chat and process lifecycle actions;
7. serve the `demo2` frontend.

The host must not parse, validate, edit, or atomically write JSON5 itself.

### 6.2 Frontend

The page has a fixed header and a responsive two-column workspace:

- **Left pane:** aiset tree editor and lifecycle buttons.
- **Right pane:** AI chat history, request input, send/cancel state, tool
  activity, and errors.

At narrow widths the panes stack, with the editor first. Each pane has its own
scroll area so a large configuration does not move the chat input off-screen.

The visual tokens match AIDIR:

```css
--bg: #0f1117;
--panel: #1a1d27;
--border: #2a2d3a;
--accent: #5b8af7;
--text: #d0d4e8;
--muted: #6b7090;
--ok: #4caf86;
--warn: #f0a500;
--err: #e05555;
```

No frontend framework, build step, CDN, or copied AIDIR JavaScript is required.
The host stylesheet may provide layout and theme variables; configuration-tree
behavior and controls come from aiset assets.

## 7. Tree editor requirements

### 7.1 Host integration target

The desired host code is intentionally small:

```python
editor_html = aiset.render_tree_editor("demo2")
```

```js
aiset.mountTree("#settings-tree", {
  document: "demo2",
  apiBase: "/api/settings",
});
```

Equivalent final names are acceptable only if documented in
`SPEC_service.md`. `render_full_editor()` should become the full tree editor or
delegate to the new helper; it must no longer mean a single raw JSON Pointer
textarea while claiming to be a full editor.

### 7.2 Tree behavior

The reusable tree must:

- build its structure from the authorized descriptor;
- read values and revisions from the service, not from embedded page data;
- show object keys and array indexes as collapsible nodes;
- initially expand the root and first level;
- show descriptions, type, constraints, origin, and apply policy;
- use appropriate controls for booleans, enums, numbers, strings, multiline
  strings, nullability, and secrets;
- retain a raw JSON5 editor for composite values and union fallbacks;
- distinguish stored, defaulted, environment-backed, absent, read-only, secret,
  invalid, and dirty values;
- support keyboard navigation and accessible labels;
- preserve user input after validation or revision conflicts;
- render all labels and descriptions with `textContent`, never untrusted HTML.

### 7.3 Structural editing

The editor must expose:

- **Add item** for arrays;
- **Remove item** for removable array entries;
- **Move up/down** for array entries;
- **Add property** for objects with `additional_children`;
- key choices for `key_enum`;
- key validation for `key_pattern`;
- **Remove property** only for dynamic or optional removable properties;
- a type chooser for `children_options` and unions when more than one shape is
  valid.

Required fixed children, `const`, and `read_only` nodes cannot be removed or
edited.

### 7.4 Staged editing

Tree edits are staged in the browser until **Apply** is pressed. The dirty state
shows the old and proposed values and can be reverted per node.

**Apply** submits all staged operations as one optimistic transaction against
one source revision and one descriptor revision. Validation is all-or-nothing:
if one operation fails, nothing is persisted.

This staged transaction is also the bridge for AI changes: agent-proposed
operations appear in the same dirty tree and use the same Apply workflow.

## 8. Required reusable aiset extensions

Current M1 can read or replace one JSON Pointer value, but it has no generated
tree, deletion, array insertion/reordering, or batch transaction. These
features must be added to aiset rather than emulated in `demo2`.

### 8.1 Tree snapshot

Add a service operation that returns one consistent, authorized snapshot:

```python
service.tree(document_id, path="", view="source", principal=principal)
```

The result contains:

- document and root path;
- source and descriptor revisions;
- authorized descriptor nodes;
- stored values or source fragments;
- effective origin metadata without resolved secret values;
- node capabilities such as editable/addable/removable/reorderable.

HTTP:

```http
GET /api/settings/tree?document=demo2&path=&view=source
```

This prevents an N+1 request for every node and guarantees that the rendered
tree uses one revision.

### 8.2 Atomic structural operations

Add one batch operation:

```python
service.apply_operations(
    document_id,
    operations,
    expected_revision=...,
    expected_descriptor_revision=...,
    principal=...,
)
```

Operation shapes:

```json
{"op": "set", "path": "/server/port", "value_text": "8384"}
{"op": "add", "path": "/fixtures/string_list/-", "value_text": "\"new\""}
{"op": "remove", "path": "/fixtures/string_list/1"}
{"op": "move", "from": "/fixtures/object_list/2", "path": "/fixtures/object_list/0"}
```

HTTP:

```http
POST /api/settings/operations/validate
POST /api/settings/operations
```

Rules:

- use JSON Pointer and the array `-` append token;
- authorize and validate every affected path;
- apply operations to one in-memory candidate;
- preserve unaffected source bytes and owned comments;
- reject unsafe comment ownership conflicts;
- persist once under the existing store lock;
- report all changed paths and the most restrictive application policy;
- keep existing revision, backup, audit, callback, and error semantics;
- never partially commit a batch.

Single-value `validate()` and `set()` remain compatible.

### 8.3 UI asset API

Add reusable assets/functions:

| Helper | Responsibility |
|---|---|
| `render_tree_editor(document, options=None)` | Return the complete tree-editor host fragment |
| `mountTree(target, options)` | Load and mount one tree editor |
| `getPendingOperations(instance)` | Return a copy of staged operations |
| `stageOperations(instance, operations, source)` | Stage user or AI operations |
| `validatePending(instance)` | Validate the complete staged batch |
| `applyPending(instance)` | Commit the complete staged batch |
| `reload(instance)` | Re-read and re-render from the server |

Multiple mounted editors must not share document IDs, revisions, pending edits,
or status through module-global mutable state.

### 8.4 Specification and documentation updates

Implementation of these interfaces requires synchronized changes to:

- `SPEC_service.md` for Python, HTTP, result, error, and UI contracts;
- `IMPLEMENTATION_LOG.md` for the new milestone;
- `README.md` for the reusable tree helper and demo2 quick start;
- `TEST.md` and `commands.md`;
- `DOCUMENTS.MD`;
- `memory/context.md` and `memory/history.md`.

`SPEC.md` is read-only. If its M4 statements must be corrected, create
`SPEC_.md` using the protected-document correction format from `AGENTS.md`.

## 9. Button semantics

### Apply

- Validate and commit every staged editor or AI operation atomically.
- Keep the staged values on any error.
- Show `applied`, `reload_required`, `restart_required`, or `apply_failed`.
- Disable while a request is active.

### Reload

- Ask for confirmation when staged changes exist.
- Discard staged browser changes only after confirmation.
- call aiset's explicit `reread()` path;
- adopt valid external changes and re-render the tree;
- surface invalid-on-disk/LKG behavior explicitly.

Reload means re-read configuration; it does not restart the process.

### Restart

- Ask for confirmation.
- Reject the request while an Apply operation is active.
- return an acknowledgment before stopping the server;
- re-execute `demo2/app.py` with the same interpreter and arguments;
- preserve `config.json5`, `.env`, and no chat history;
- show reconnecting state and poll `/api/health` until the application returns.

Restart is a host-owned route and callback, not a generic aiset operation.

## 10. AI configuration agent

### 10.1 Transport

The first implementation uses OpenAI-compatible Chat Completions. The backend
owns provider calls so the API key never reaches the browser. Calls use the
configured base URL, model, timeout, temperature, and bounded tool-round count.
HTTP and protocol failures are shown as errors; there is no success-shaped
fallback response.

### 10.2 Agent context

For every user message, the host supplies:

- a short system instruction defining the agent as a `demo2` configuration
  assistant;
- the authorized descriptor/tree snapshot;
- current source and descriptor revisions;
- bounded conversation history;
- aiset tool definitions.

The context excludes resolved secret values, `.env` contents, arbitrary files,
and process environment data.

### 10.3 Tools

The agent receives only host wrappers over public aiset operations:

| Tool | Behavior |
|---|---|
| `settings_get` | Read one authorized source/effective node |
| `settings_get_tree` | Read a bounded subtree |
| `settings_validate_operations` | Validate proposed staged operations |
| `settings_stage_operations` | Return validated operations to the browser for staging |

The model has no shell, filesystem, HTTP proxy, restart, or direct persistence
tool. `settings_stage_operations` does not write the file. The user sees the
proposed changes in the left pane and commits them with **Apply**.

### 10.4 Chat behavior

- User, assistant, tool activity, validation, and error entries are visually
  distinct.
- Enter sends; Shift+Enter inserts a newline.
- Duplicate sends are blocked while a request is active.
- A cancel action aborts the upstream request where supported.
- History is bounded by both message count and estimated character size.
- History is kept in backend memory under a random browser session ID and is
  lost on restart.
- Assistant text is rendered as text in the first version; no unsafe HTML or
  unsanitized Markdown is inserted.
- Revision conflicts cause a fresh tree read and a request for the model to
  reconsider; they never cause blind overwrite.

## 11. Security and reliability

- Bind defaults to `0.0.0.0` for parity with the existing demo, but the page
  must identify itself as an unauthenticated internal test application.
- `.env`, API keys, resolved secrets, and secret source fragments never enter
  model context, logs, chat history, or frontend payloads.
- All writes go through aiset authorization, validation, revision checks,
  locking, atomic persistence, backups, callbacks, and audit events.
- Request bodies, chat history, tool rounds, subtree depth, and provider
  response size have explicit limits.
- Browser validation remains advisory; the service is authoritative.
- Dynamic property names are treated as data and rendered with `textContent`.
- Restart and chat routes accept only same-origin JSON requests in demo mode.
- Errors retain stable codes and sanitized details.

## 12. Testing and acceptance

### 12.1 Automated tests

Extend the suite with:

1. tree snapshot permissions, secret handling, and revision consistency;
2. source-preserving add/remove/move operations;
3. atomic batch success and all-or-nothing rejection;
4. required/read-only/dynamic-key enforcement;
5. stale source and descriptor revision conflicts;
6. callback and application-state aggregation;
7. `render_tree_editor` and independent multiple mounts;
8. `run_demo2.sh` seeding without overwrite;
9. `.env` port conversion and default `8383`;
10. app startup/bind failure/health/static routes;
11. AI provider success, tool loop, timeout, malformed response, and bounded
    round failure using a local fake provider;
12. prevention of secret disclosure in model and frontend payloads;
13. staging agent operations without persistence;
14. restart acknowledgment and re-execution behavior.

The regular command remains:

```sh
./test.sh
```

No live external model is required by automated tests.

### 12.2 Manual acceptance

1. Delete local `demo2/config.json5` and `demo2/.env`; run
   `./run_demo2.sh`; both are copied from examples.
2. Change either local file and rerun; neither is overwritten.
3. Open `http://127.0.0.1:8383`; the AIDIR-styled split page appears.
4. Expand every fixture section and verify every declared type has a suitable
   editor and description.
5. Add/remove/reorder array entries and add/remove allowed dynamic properties.
6. Stage several edits and Apply; all appear in one persisted revision.
7. Cause one invalid edit in a batch; verify that no operation is persisted.
8. Modify the file externally and Reload; the valid change appears.
9. Stage a change, press Reload, cancel confirmation, and verify it remains.
10. Change a restart-policy field and verify the required state is shown.
11. Restart; verify the page reconnects and configuration persists.
12. Ask the agent to change scalar and collection values; verify proposals are
    staged and highlighted but not saved before Apply.
13. Apply the AI proposal and verify the saved JSON5 retains unrelated comments
    and formatting.
14. Configure an unavailable provider and verify an explicit chat error.
15. Verify no API response or browser content contains the configured AI key.

## 13. Implementation sequence

1. Approve this proposal and close the blocking TBDs.
2. Specify tree snapshots and atomic structural operations in
   `SPEC_service.md`.
3. Implement and test source-preserving batch operations.
4. Implement and test reusable tree assets.
5. Add `demo2` examples, descriptor, and launcher.
6. Add host backend and lifecycle routes.
7. Add AI provider/tool loop and tests.
8. Add the AIDIR-styled frontend and browser acceptance checks.
9. Update all related documentation and project memory.

Each implementation step should be validated before proceeding to the next
file-level change, following `AGENTS.md`.

## 14. TBD

These points need user confirmation before implementation:

1. **Default model:** confirm the model identifier to ship in
   `config.json5.example`; this proposal uses `qwen3:8b` only as a placeholder.
   >>I will add the model into .env when it is created. I will add: url and model name, create the corresponding fields in the .env.example
2. **AI commit policy:** confirm that AI changes should be staged for the user
   to Apply, as proposed, rather than allowing the model to persist changes
   directly.
   >> yes, it is the best option
3. **Restart portability:** confirm that Linux/POSIX process re-execution is
   sufficient for `demo2`; `run_demo2.sh` already makes the launcher
   POSIX-specific.
   >>the app should indicate the states "restart required" / "reload required" and user must be able to initiate the operations (for the restart, maybe, not needed)

