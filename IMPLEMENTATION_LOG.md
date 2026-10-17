# aiset Implementation Log

Living plan and work record for implementing [SPEC.md](SPEC.md) and
[SPEC_service.md](SPEC_service.md). Items are checked as they are completed;
notes record decisions and deviations. SPEC.md is read-only: if it needs a
correction, the proposal goes to `SPEC_.md` per AGENTS.md.

Scope of this effort: milestone M1 (SPEC.md section 17, phase 1) - the
standalone editor of aiset's own demo configuration on default port **8383** -
plus the reusable library core it needs (descriptor, source-preserving storage,
resolver, validator, store, service, HTTP adapter, CLI, merge, Config object).
Phases M2-M5 (MCP adapter, lifecycle-hook dispatcher, host integrations,
generated forms/helpers, AI) are out of scope and reported as explicit
`UNSUPPORTED_CAPABILITY` where the spec requires it.

## Plan

### Phase A - foundations

- [x] A1. Study SPEC.md, SPEC_service.md, README/TEST/commands/_AGENT_NOTES,
      memory, `demo_aidir_config.template.json5`, and the aidir/sndbx hosts.
- [x] A2. `pyproject.toml`: package metadata, zero runtime dependencies,
      optional `[dev]` extra (pytest), `aiset` console script.
- [x] A3. `errors.py`: stable error codes from SPEC_service.md section 7,
      `AisetError` hierarchy, HTTP status mapping.
- [x] A4. `pointer.py`: JSON Pointer parse/format/escape, traversal helpers,
      path errors (malformed escape, index range, missing parent).

### Phase B - source-preserving JSON5 template engine (highest risk, SPEC 7.1/7.2)

- [x] B1. Tokenizer + recursive-descent parser producing a CST with byte spans:
      comments (line/block), single/double quotes, trailing commas, unquoted
      keys, numbers, `null`/bools, and template tokens `${VAR}` /
      `${VAR:-default}` both unquoted and inside strings.
- [x] B2. Comment ownership classes: leading, trailing, block-end, document.
- [x] B3. Rejections: duplicate object keys (with location), malformed
      templates, trailing garbage.
- [x] B4. Reads: exact source fragment per JSON Pointer, `format`
      (`json5` / `json5-template`), stored semantic tree (templates kept as
      explicit nodes).
- [x] B5. Edits: scalar value-token replacement, absent-leaf creation with
      local indentation, array element by index, object replacement with
      comment reconciliation, equal-length array element-wise edit,
      `COMMENT_PRESERVATION_CONFLICT` otherwise. Byte-exact guarantee: a read
      with no edit never rewrites the file.
- [x] B6. Fixture corpus + tests comparing exact bytes.

### Phase C - descriptor

- [x] C1. Load JSON5 descriptor, envelope checks, `descriptor_version`.
- [x] C2. `validate_descriptor` in default and strict modes, issue code
      `UNKNOWN_DESCRIPTOR_PROPERTY`, JSON Pointer + line/column, opaque
      metadata values never printed, `children` labels not misreported.
- [x] C3. Grammar checks of 4.6.3 (mutual exclusions, placement, scalar
      constraint/type match, `required`+`default`, `enum`+`const`, `id` rules,
      `key_pattern`/`key_enum`).
- [x] C4. Templates (`typedef`) collection, uniqueness, primitive shadowing,
      cycle detection, expansion with referencing-node override.
- [x] C5. Composition of fragments at mount paths; conflicting definitions are
      hard errors, never last-writer-wins.
- [x] C6. Compilation to an effective node tree with inherited `apply`,
      `secret`, `read_only`; field names from label or `id`.
- [x] C7. CLI `aiset validate-descriptor` (exit codes 0/1/2, json/text).

### Phase D - semantics

- [x] D1. Resolver: one global precedence (host overrides, process env, `.env`,
      inline `:-` default, config default), POSIX `:-`, single pass, no
      structural injection, `env.allowed` gate, conversion, provenance.
- [x] D2. Value validator: exact type rules (`bool` is not `int`), numeric
      bounds/range, string length in code points, portable regex subset with a
      100 ms budget, array constraints, object coverage, dynamic keys,
      unions, required/nullable/default, structured issues.
- [x] D3. Limits: file/body size, depth, collection size, string length,
      pattern length (checked before expensive parsing).
- [x] D4. `merge(base, update)` per 10.1 plus the Config object model (10.2)
      with documented mount-addressing grammar (`dotted.path` and
      `items.[id=value]`).

### Phase E - storage

- [x] E1. Revisions (opaque sha256), descriptor revision, etag.
- [x] E2. Sidecar lock file, bounded acquisition (default 5 s) -> `LOCK_TIMEOUT`.
- [x] E3. Atomic replace (temp file, fsync file and directory), three
      attempts, commit-state report (`committed` / `uncertain` / `detail`).
- [x] E4. Backup chain `.back...` with once-per-session rotation, bounded
      depth (default 5), source-preserving rotation.
- [x] E5. Conflicted backups `<name>.conflicted.<UTC-ISO>.back` with bounded
      retention, never overwriting the rejected file if the copy fails.
- [x] E6. LKG: newest-valid-backup selection on load and explicit `load_lkg`.

### Phase F - service

- [x] F1. `Service` with the exact Python signatures of SPEC_service.md
      section 3; principals and permission checks; secret enforcement.
- [x] F2. `load` / `get` / `validate` / `set` candidate pipeline, shared by
      every transport; source-preserving re-parse and re-validation of the
      exact candidate under the lock.
- [x] F3. Revisions: `REVISION_REQUIRED` / `REVISION_CONFLICT`, internal
      resolver/layer/hook-registry snapshots verified before commit.
- [x] F4. Callbacks `probe_changes`, `on_application`, `after_save` with the
      fixed order, bounded timeouts, distinct pre/post-commit outcomes;
      subscriptions.
- [x] F5. External edits (10.4): re-read before save, adopt valid edits,
      restore invalid ones after preserving the rejected bytes.
- [x] F6. Application state from the `apply` policy of changed paths.

### Phase G - transports, UI, demo

- [x] G1. HTTP adapter: WSGI app implementing the routes of SPEC_service.md
      section 10 (zero required dependencies; mountable in a host server).
- [x] G2. Shipped UI assets (`include_assets`, `render_node_editor`,
      `render_full_editor`) with Read/Validate/Save, revision conflict
      handling, best-effort browser checks only.
- [x] G3. `demo_app.py`: plain HTTP test app, default bind `0.0.0.0:8383`,
      `--<path>:<value>` overrides, seeding `.local/demo/config.json5` from the
      tracked example only when absent, explicit path overrides, clear errors.
- [x] G4. `examples/`: demo descriptor (full fixture matrix), commented
      mixed-type JSON5 template configuration, aiset's own settings document +
      descriptor, example Markdown editing skill.
- [x] G5. MCP adapter and the hook dispatcher are reported as
      `UNSUPPORTED_CAPABILITY` (phases M2).

### Phase J - demo2 acceptance host (proposal_demo2.md)

- [x] J1. Protected-document correction proposal `SPEC_.md` (structural
      operations, tree snapshots, generated editors, phase 4 list) and the
      interface additions `SPEC_service.md` sections 19-21.
- [x] J2. Source-preserving `apply_add`, `apply_remove`, `apply_move` in
      `jsonsrc.py`: append token, comma and comment ownership, inline and
      multiline arrays, block-end comments, dynamic keys.
- [x] J3. `service.tree()` with authorized snapshots, per-node capabilities,
      secret handling; `GET /api/settings/tree`.
- [x] J4. `service.apply_operations()` atomic staged batches for
      set/add/remove/move; `POST /api/settings/operations[/validate]`.
- [x] J5. Reusable tree editor assets (`aiset-tree.js`): typed controls, add,
      remove, move, add/remove property, staged changes, Apply/Reload, conflict
      handling, independent instances; `render_tree_editor`, `mountTree`.
- [x] J6. `demo2/` host: `.env` reader, config/descriptor examples covering
      every required shape, `app.py` with lifecycle and chat routes,
      `run_demo2.sh` launcher.
- [x] J7. AIDIR-styled two-pane frontend with the assistant pane.
- [x] J8. Configuration assistant: OpenAI-compatible transport, bounded tool
      rounds, read/stage tools only, per-session history, no secret values.
- [x] J9. Tests: 36 demo2 tests (including a local fake provider) and 36 new
      library tests for the tree, operations, and UI assets.

### Phase K - host-integration improvements (aidir, `proposal_improvement_aidir.md`)

Requested by the first real host while embedding the library. Every item was
reproduced against this checkout before a line was written; the proposal file
holds the reproductions and stays the record of what was asked for.

- [x] K1. `resolver._convert` took the text to convert through a second
      parameter that defaulted to `None` and turned every quoted `"${VAR}"`
      with a non-string `env.convert` into the literal `"None"`. The parameter
      is gone; both call sites pass the resolved text. Regression tests cover
      int, bool and inline-default conversions.
- [x] K2. An object member whose type is a `union` was resolved against no
      descriptor node, because the shapes live in `children_options` and the
      resolver only looked at `children`/`additional_children`. Every `${VAR}`
      below such a node reported `env_not_allowed`, an error-severity issue, so
      the document stopped loading entirely. The resolver now picks the
      alternative that declares the member, preferring one whose declared type
      fits the stored value; validation stays authoritative.
- [x] K3. `aiset.asgi.create_asgi_app`: an ASGI transport over the same
      dispatcher as the WSGI adapter, with `principal_from_scope` for hosts that
      authenticate asynchronously, worker-thread offload under asyncio, and a
      bounded body read. Documented as `SPEC_service.md` section 10a.
- [x] K4. `/assets/*` is served from the installed package with or without
      `static_dir`, so a host that only wants the API still gets the editor.
      Without a host directory nothing else resolves, and nothing is ever
      resolved against the process working directory.
- [x] K5. `type: "any"`: the opaque value type, so a host can declare a region
      it owns (a JSON schema, a tool declaration, an extension map) without
      inventing a schema for it. Limits still apply; a placeholder inside an
      opaque value stays literal; in a snapshot it is a `leaf` and in the editor
      it is source text. Corrected in `SPEC_.md` correction 6.
- [x] K6. Union resolution is now specified as well as implemented: an array
      item resolves with the alternative at its index, an object member with
      the alternative that declares it. `SPEC_.md` correction 7.
- [x] K7. Host callbacks are checked at registration: a callback that cannot
      receive the documented three arguments raises `TypeError` instead of
      failing later as a swallowed `callback_failed` log line while the host
      kept stale values. The `application.state` table and the `event` fields
      are documented in `SPEC_service.md` sections 9 and 16.
- [x] K8. Descriptor diagnostics carry `line` and `column`, read from the same
      CST the editor uses; a path naming a missing property is reported at the
      nearest existing ancestor.
- [x] K9. Cleanups: `CommitReport.to_dict` moved into its class and its
      `document_id` reference corrected (it could not have worked), the dead
      `and False` expression in `tree._origin_of` removed, the positional array
      resolver aligned with `descriptor.node_at`, and the stale test counts in
      README/AGENT_INTEGRATION/commands replaced by a pointer to `./test.sh`.

### Phase H - verification and documents

- [x] H1. `tests/` covering the M1 acceptance matrix with pytest.
- [x] H2. Manual browser/demo protocol in TEST.md, real commands in
      commands.md.
- [x] H3. README.md status/structure/usage update; `SPEC_.md` references fixed.
- [x] H4. `memory/context.md` and `memory/history.md` updated.

## Notes

- 2026-10-15. Phases A and B are done. The parser/editing engine is proven by
  `tests/test_jsonsrc.py` (29 tests) over the SPEC 7.1 classification fixture,
  mixed types, CRLF, BOM, no final newline, Unicode, single-line objects,
  escaped keys, and the composite-edit rules of 5.3.4/5.3.5.
- 2026-10-15. Comment after `{` of a member value belongs to the member
  (trailing), matching the SPEC 7.1 example, so it survives a replacement of
  the member value itself.
- 2026-10-15. All phases A-H are complete. 232 automated tests pass
  (`./test.sh`), the demo serves the real UI and API on 0.0.0.0:8383, and an
  edit made through HTTP changes the file by exactly the edited tokens.
- 2026-10-15. Deviations and decisions taken during implementation:
  - `store.Settings.from_mapping` reads the nested `aiset`/`storage`/`runtime`
    layout of `examples/aiset.json5`; flat keys are also accepted.
  - `Service.register` compiles the descriptor leniently (errors fail, unknown
    project metadata is a warning), because runtime must accept host metadata;
    typo-free checking is `validate_descriptor(mode="strict")` or the CLI.
  - Array item shorthand: `children` on an array is a single item node
    (`is_item_node`), matching the SPEC 4.1 examples; an object `children` map
    is always a label map, so a label `type` is unambiguous.
  - Descriptor regex evaluation uses a bounded worker thread (100 ms default);
    an undetermined outcome becomes a warning issue, never a false pass.
  - `Config` mount grammar is documented in `config_obj.py`: dotted names with
    `\.` escapes and `[field=value]` identity selectors; zero or multiple
    matches raise `DescriptorError`.
  - Backup rotation happens once per editing session (14.8.2); rollback consumes
    the newest `.back` and shifts the remaining chain up one level.
  - External-edit restoration only runs on a re-read, never on the first load,
    so a tracked example can never receive a `.conflicted` file.
- 2026-10-15. Two defects found by live HTTP testing and fixed:
  - A composite replacement re-attached an original trailing comment that the
    submitted text already carried (duplicate comment after the closing brace).
    Original comments are now re-attached only when they are absent from the
    submitted value text, so a read/edit/restore round trip is byte-identical.
  - A read-only descendant blocked every parent edit that carried it unchanged
    (for example editing a resource while keeping its immutable `id`). The
    check now compares source fragments: a read-only child blocks the edit only
    when its bytes actually change.
- 2026-10-15. Interface deviations from SPEC_service.md, all additive and
  documented: two extra stable error codes (`PARSE_ERROR`, HTTP 400, for
  malformed JSON5/template source including duplicate keys, and
  `INVALID_DESCRIPTOR`, HTTP 422, for a rejected descriptor), plus a `/health`
  route. Every code listed in SPEC_service.md section 7 is implemented with the
  documented status mapping, so no correction to SPEC_service.md was required.
  A GET route for the registered document ids (`{base}/documents`) exists so the
  UI can offer a document selector.
- 2026-10-15. Defect found in manual use: the demo2 page loaded but stayed empty
  because `frontend/app.js` touched DOM nodes while the document was still
  parsing. The script now waits for the document, loads with `defer`, and fails
  visibly ("editor assets are not loaded") instead of silently. A headless page
  smoke test (`demo2/tests/test_page.py`) renders the three shipped scripts in
  order and asserts that the editor mounts and the status is fetched.
- 2026-10-15. Chat failures were reported as `INTERNAL_ERROR`; provider and
  protocol errors now map to stable codes and statuses (503 unreachable, 504
  timeout, 502 HTTP/protocol) with the provider's own message, so a wrong model
  name is reported as such instead of looking like an empty answer.
- 2026-10-15. Two assistant findings from manual use, both fixed in the host:
  - A model addresses the configuration root as `/`; the canonical JSON Pointer
    for the root is the empty string, so the tool call failed with NOT_FOUND and
    the assistant told the user the root was undeclared. Tool paths are now
    normalized (`/`, `root`, `server/port`, trailing slashes), the system prompt
    states the convention, and an unknown path returns the declared sections with
    a hint instead of a bare error.
  - A malformed tool-call argument aborted the whole answer. Argument parsing is
    now tolerant (single quotes, code fences, object form) and a still-unparsable
    call becomes a retryable tool result, not a fatal 502.
  - The bounded tree is returned as structured JSON with explicit `truncated`
    markers rather than a flat preview, so a root read is always usable.
- 2026-10-15. Tree view options added on user request: `expandAll()` /
  `collapseAll()` with **Expand all** and **Collapse all** in the editor toolbar
  (the document root stays open on collapse), an opt-in `valuesAsText`
  representation of objects and arrays that shows the stored source fragment as
  a read-only block instead of an editable value, and square icon buttons for the
  structural actions with the purpose in the `title` tooltip. The int fields are
  no longer white: `input[type="number"]` was missing from the demo2 palette.
  320 tests; no server change was needed because the tree snapshot already
  carries `value_text` for every node.
- 2026-10-15. The tree snapshot now carries declared keys that the file does not
  contain (`exists: false`, with `default_applied` in the effective view), and
  the editor hides them unless `showAbsent` is set; demo2 offers the second
  checkbox. Leaves with nothing to show render a coloured type mark instead of
  an empty control (`i`/`n` green, `"` blue, `b` violet, `?` muted, never red).
  Placeholders also work on the multiline control, and the demo descriptor now
  declares six of them, including on an empty and on two absent keys. The tree
  toggles are larger in the demo2 theme. 323 tests; `examples/` stays untouched.
- 2026-10-15. Four defects found by hand in the demo2 tree:
  - Icons never appeared on array items: `kind` was derived from the node type,
    so a string inside an array was a `leaf`, and `remove`/`reorder` were granted
    to the array instead of to its items. `kind` now follows the parent, item
    capabilities come from the item path, a `read_only` array freezes its items,
    and an array no longer offers a misleading "remove this item".
  - Static assets were served without cache headers, so a browser could keep an
    old script or stylesheet and look exactly like a broken one: `no-cache` plus
    `Last-Modified` are sent now.
  - The key input flew to the right edge because of `margin-left: auto`.
  - A nullable field mixed the string "null" with a stored null: an explicit
    `null` switch now stages a real null, locks the text control and shows it as
    disabled; unticking reverts to the stored value.
  Placeholders were verified on host, port, an empty string, a multiline string
  and two absent keys; 326 tests.
- 2026-10-15. Two readability additions on request: the tree snapshot now carries
  `comments` (the comments of the source file that introduce a node, decorative
  section rules dropped) and the editor shows them in the tooltip of the node
  name together with the descriptor description, flags, apply policy, default,
  constraints and the stored value. A node with a declared default also gets a
  small icon button that stages it; it is disabled while the stored value
  already is the default. 328 tests.
- 2026-10-15. Environment placeholders and raw source editing (SPEC_.md
  correction 4). A node with a stored `${VAR:-default}` used to render empty in
  a typed control, and staging a value destroyed the substitution. The tree
  snapshot now carries `template: {name, default}`, and the editor renders the
  variable name and the inline fallback as two controls, the fallback with the
  control of the declared type. An empty name stores the inline value; every
  node with `env.allowed` gets a button that switches it into that mode; every
  editable node gets a raw source mode that hides the subtree and stages one
  validated `set`. `POST <base>/env` reports whether a variable is set, never
  its value. 332 tests.
- 2026-10-15. Raw editor refinements: the window grows when the fragment does
  not fit, never past the pane width or the screen height minus their padding,
  and a size the user dragged is never taken away. The button that opens it no
  longer looks like a text field: it is a bold, centred `{..}` text label
  instead of a braced icon. 332 tests.
- 2026-10-15. Added `AGENT_INTEGRATION.md`: a task-oriented integration guide
  written for agents rather than for a human reader. Dense tables, exact
  identifiers, a reading-order table, hard rules first, then Python/HTTP/editor
  contracts, descriptor grammar, paths and views, operations, the tree
  snapshot, permissions, an error table with causes, extension and testing
  checklists, and the do-not list. It points at `SPEC_service.md` for normative
  detail instead of duplicating it, and is listed in `DOCUMENTS.MD`.
- 2026-10-15. Square action buttons were squeezed to 4px of content: the generic
  `.aiset-tree-actions button` rule (specificity 0,1,1) came after
  `.aiset-tree-action` (0,1,0) and applied its 10px padding, so with
  `box-sizing: border-box` the caption had nowhere to sit. The generic rule now
  excludes `.aiset-tree-action`. Both text captions are 9px bold and centred
  (`{..}` for raw source, `↺` for restoring a default), and the default button
  switched from an SVG to the same text treatment so the font rules reach it.
- 2026-10-15. The `.env` affordance was backwards. It is a button on a plain
  value that switches the node into substitution mode; a node that already uses
  a placeholder shows no button, only its name, its typed fallback and a plain
  note about whether the variable is set. The button is offered on every
  editable scalar and is disabled with an explanation where the descriptor
  forbids substitution, instead of being hidden. It is a small pill rather than
  a 24px square, because a four-character caption does not fit one.
- 2026-10-15. Two defects in the `.env` button, both found by dumping what the
  editor renders for every node of demo2:
  - `_button()` dropped its `kind` argument, so the `env` class never reached the
    element: the pill styling never applied and a four-character caption
    overflowed the 24px square.
  - The button was disabled wherever the descriptor has no `env.allowed`, and in
    the demo no plain field declares it, so it was never usable anywhere. It now
    works on every editable scalar; the tooltip warns that the server will
    refuse where the descriptor forbids substitution, and the server keeps
    refusing at store time.
- 2026-10-15. The presence indicator was on the wrong rows and was not a button.
  A node that already stores `${VAR:-...}` shows the variable in its own name
  field, so the note there was noise; it is gone. The check now belongs to the
  mode opened from a plain value: after a name is typed the row grows a real
  button "set in .env" / "not set" that asks the server again, and it stays
  disabled until there is a name to check.
- 2026-10-16. Four editor fixes from a screenshot: the caption buttons `.env`,
  `{..}` and `↺` share one pill style; `{..}` and `↺` are offered on every row and
  disabled with their reason where they cannot act (read-only field, no declared
  default); the presence control no longer renders as an empty dot before a
  variable name is typed, it appears only once there is something to check; and
  the green `env VARIABLE` badge is gone, because it repeated the name the field
  next to it already shows.
- 2026-10-16. Staging a `set` whose `value_text` equals what the snapshot already
  stores is now a no-op: nothing is staged, the row keeps no dirty badge and the
  staged list stays empty. Entering the environment mode and leaving it again
  therefore returns the row to the state it was in. Caught in `stageOperations`,
  so it also covers the assistant proposing a value that is already stored.
- 2026-10-16. The "drop the substitution" and "restore the default value" buttons
  shared one glyph and were confused with each other: they are now `⊘` and `↺`.
- 2026-10-16. The "drop the substitution" button did the opposite of its name in
  one of its two situations: after a substitution had been typed and staged, it
  staged the literal value, that operation was skipped as a no-op, and the
  substitution stayed pending. It now forgets everything staged for the path
  first, so the node goes back to what the file holds, in both cases.
- 2026-10-16. The drop-substitution button now behaves as the user described: it
  appears only while a variable name is filled, clears the name, hides the name
  field, gives way to the `.env` button and leaves the row showing the plain
  value. A node with a staged change also carries its own `↺` revert button, so
  a single staged operation can be undone where it was made; the default-value
  button moved to `⌂` to keep the two apart.
- 2026-10-16. Two follow-up states of the drop button: pressing `.env` after a
  drop brings the name field back and gives way to the drop button again, and
  `revert` restores the substitution view together with the clean row. Both
  fell out of the same cause: the view flags outlived the action that set them.
  `_dropTemplate` sets `hiddenTemplate` after it reverts, which `revert` clears.
- 2026-10-16. Component documents in demo2. `demo2/conf2/descriptor.json5`
  describes the override file and declares the `typedefvalue1` and
  `typedefvalue2` templates; the main descriptor uses them through
  `typedef_sources`, so the base section and the update cannot drift apart. The
  host registers the component as a second document, merges it onto
  `includes.conf2` (SPEC.md 10.1), and reports every changed path in
  `/api/demo2/status`; the page gets a document switcher. The base section
  deliberately contains the overlap cases: replaced scalars, an array replaced
  as a whole, a flipped flag, a field only in the base that survives, and a
  nested object where one inner field is replaced while the other is kept.
- 2026-10-16. Helpers (SPEC.md 18.2): `aiset.registerHelper(tag, factory)` plus
  `instance.runHelper(node)`. The tree editor renders a form button for a node
  whose descriptor carries a `helper` binding, and the shipped `node_form`
  helper opens a modal over the visible children and stages the fragment it
  builds through the same validate-then-stage path as the raw editor.
- 2026-10-16. `aiset validate-descriptor` accepts repeatable `--typedef`
  sources, so a descriptor that uses templates owned by a component descriptor
  is validated exactly as the host compiles it.
- 2026-10-16. The type mark was rendered in the wrong place, so it never showed
  up: a leaf whose value is empty is rare, and a typed control exists otherwise.
  The column that shows + and - for objects now carries a coloured type mark for
  every leaf instead: `i` and `n` green, `"` blue, `b` violet, `[`/`{` muted for
  an empty array or object, `?` for anything else. Red is still not used, and
  the value column no longer repeats the mark.
- 2026-10-16. A network-level failure while loading a document now says "the
  host did not answer. Is demo2 still running?" instead of "Failed to fetch",
  which named a symptom the user cannot act on. The reported case turned out to
  be a stopped host: the component document, the typedef wiring and the tree
  route were all answering once the process was up again.
- 2026-10-16. Merge precedence became a parameter and the base wins by default
  (SPEC_.md correction 5). `aiset.merge(base, update, *, prefer="base")` keeps
  the base on every conflict, merges objects recursively, adds what only the
  update has and never deletes; `prefer="update"` restores the former rule.
  `POST /merge` takes and echoes the parameter, `Config.update` forwards it, and
  demo2 merges its component document with the default, so the main file keeps
  its values and the component only fills the gaps. Editing the merged section
  still writes the base document, which the default precedence makes visible.
  340 tests.
- 2026-10-16. The expand/collapse buttons of the tree read better: `+` and `-`
  are bold at 19px (three pixels larger) instead of 16px regular, in the normal
  text colour instead of the muted one, with a panel background on hover. The
  library stylesheet carries the same typographic defaults for other hosts.
- 2026-10-16. The tree editor draws the staged operations, not the snapshot it
  loaded. A staged value is the value the control shows, a staged entry appears
  in its array or object, a staged move reorders the visible list, and a staged
  removal keeps the row with a red `deleted` mark until the change is applied or
  reverted. The store, the raw editor and every service call still see the file
  as it is, so the projection is a preview and nothing else.
- 2026-10-16. A node is dirty exactly when it carries a staged operation that
  the file does not already describe; the flag itself is never stored. A value
  that comes back to what the file holds therefore drops its staged operation,
  so a checkbox toggled twice ends clean instead of stuck, and the same holds
  for every other control. Editing a value also cancels a staged removal of
  that node, so the batch can still apply.
- 2026-10-16. Values behind a `${VAR}` substitution compare by their variable
  and their default, never by spelling: the quotes belong to the JSON5 literal
  around the substitution, and `${VAR}` says what `${VAR:-}` says. A substitution
  is now also written in the form the file uses — a string field keeps its
  quotes, a field the descriptor converts stays a bare token — so changing a
  default and returning it clears dirty, an enum behind a placeholder clears too,
  and applying a change no longer drifts the source form of the file.
- 2026-10-16. Adding an entry to an array uses the shape the descriptor
  declares. `describe()` now returns the item node of an array under
  `children`, which is how a descriptor writes it, so the tree and the node
  route finally tell a client what a new entry must look like. The editor reads
  that shape once, in `_itemShape`, for both the `+` button and the new row, so
  `value2` (an array of ints) offers a number field with 0 instead of a free text
  field holding `[]`. A value typed into a new row updates the staged `add`
  itself: the service accepts the append token on an add only, so the two must
  never become two operations.
- 2026-10-16. A template now also resolves in the position SPEC.md 4.6.10
  already allows but the compiler skipped: the single node that describes every
  item of an array. `expand_templates` walks that node like any other, so
  `children: { type: "typedefvalue1" }` yields real objects carrying the
  template's children, its constraints and its helper binding. The conf2
  templates grew accordingly: the edit form of `typedefvalue1` is described
  (helper binding plus `ui` label, help and placeholder per field), and two
  structures use the template as a type — `testobjarray`, an array whose items
  are such objects, and `testobjobj`, an object whose every value is one by key.
  The main descriptor declares the same two keys through the imported template,
  and both demo2 configurations carry matching values: the base array wins as a
  whole, while of `testobjobj` the base keeps its own values and takes the added
  key and the inner field the base lacks.
- 2026-10-16. Creating a child of a collection builds the tree the descriptor
  declares instead of one empty value. A new object starts as its required
  children (`const`, then `default`, then the empty value of the type), the rest
  stays unwritten but visible with the show-absent option, and everything under a
  new entry is addressed by the index or key it will have — the service accepts
  the append token on an `add` only, so a child of a new array entry is a `set`
  on its resolved index. An object the user names by itself shows the key where
  the name stood, in front of the value: it renames the entry, and `+` opens a
  row that waits for its name. The old free-standing "key" field is gone; it
  appeared on objects that had nothing to name and always wrote `null`.
- 2026-10-15. M2/M4 work deliberately not started: MCP adapter, hook
  dispatcher, helper micro-forms, history/restore, and a general agent
  framework. Recognized hook bindings are refused at write time with
  `UNSUPPORTED_CAPABILITY`. The demo2 assistant is host code limited to aiset's
  public service, exactly as the proposal requires.
- 2026-10-15. `demo2` answers to the proposal's three open questions: the model
  identifier lives in `demo2/.env` (`DEMO2_AI_MODEL`), agent changes are staged
  for the user to apply, and the application reports `reload_required` /
  `restart_required` states with user-initiated Reload and Restart actions
  (Restart re-executes the process with the same interpreter and arguments).
- 2026-10-15. Findings from the demo2 work that changed the library:
  - A staged batch is a user-visible transaction over one candidate, not a
    rollback system; `SPEC_.md` records the correction to the frozen text.
  - A read-only descendant blocks a parent edit only when its bytes change.
  - A container whose subtree contains an inaccessible secret is denied in the
    tree snapshot as well, otherwise the parent `value_text` would leak it.
  - The assistant principal has no secret permissions, so no tool result can
    carry a secret value.
  - Tool results are bounded by a character budget and are never truncated
    mid-JSON.
  - Restart must acknowledge before re-executing; the re-execution is scheduled
    so the response reaches the browser first.
  - `create_app` gained `static_map` so a host can ship its own script and
    stylesheet next to the bundled assets.

- 2026-10-15. The specification was frozen and renamed to `SPEC.md`; the stale
  `SPEC_.md` references in README/TEST/commands/_AGENT_NOTES were corrected as
  part of H3. `SPEC.md` itself was not modified.
- 2026-10-15. No maintained Python JSON5 library exposes a token-span CST, and
  SPEC 7.2 allows a small isolated source-editing subsystem when no dependency
  passes the fixtures. Decision: own parser/editing subsystem with zero runtime
  dependencies. Proof is the fixture corpus in phase B.
- 2026-10-15. Standalone backend uses `wsgiref`/`http.server` from the standard
  library; the HTTP adapter is a WSGI application so a host can mount it. This
  keeps the core free of FastAPI/MCP-SDK imports (SPEC section 3).
- 2026-10-15. **User rule: the system Python must not be used.** All runs
  (tests, demo, CLI) use `/home/denis/aidir/aiset/.venv`. The environment was
  created explicitly: `python3 -m venv .venv` plus
  `.venv/bin/python -m pip install -e ".[dev]"`. aiset never creates or
  switches it itself (SPEC 3.4).

- 2026-10-17. Phase K is complete and `./test.sh` is green. Two defects were
  found only because a host ran the library against a real 42 KB
  configuration with 44 environment placeholders: the union resolution gap (K2)
  and the quoted-placeholder conversion (K1). Both were silent in the library
  test suite because no fixture combined a union with a placeholder. The lesson
  for the suite: a host-shaped fixture is worth more than a grammar fixture, and
  `proposal_improvement_aidir.md` is now the standing checklist for the next
  host.

- 2026-10-17. Dynamic object entries are deletable. `tree.py` now reports a
  `kind: "dynamic_key"` and `capabilities.remove: true` for an entry of an open
  object collection (`additional_children`), for any value type; the container
  itself stays non-removable. The editor keys its remove control off
  `capabilities.remove` (label "Remove this entry") and gates the add-property
  control with `capabilities.add_child` instead of `remove_child`. The service
  already accepted `remove` on an object key; the gap was capability reporting
  and the editor. Regression tests cover scalar and object dynamic entries,
  escaped keys, and the editor button. `AGENT_INTEGRATION.md` documents the
  callback contracts, the `application.state` contract, and dynamic-key removal;
  the section references in `DOCUMENTS.MD`, `AGENT_INTEGRATION.md`, and the test
  count in `TEST.md` were corrected.

- 2026-10-17. Implemented `proposal_improvement2.md` items 1-4 and two of the
  minor items.
  - P1: the dispatcher serves `{base}/assets/<name>` as well as `/assets/<name>`
    on both transports, so a host that mounts only the API still gets the editor.
  - P2: `aiset validate-document --config --descriptor [--typedef] [--env]
    [--strict]` loads a real configuration against its descriptor; explicit
    resolution inputs with `--env`.
  - P3: `POST {base}/document/validate` and `Service.validate_document` validate
    a whole candidate document read-only.
  - P4: a union snapshot node carries `matched_option`, the index of the
    alternative the stored value validated against.
  - P5: a node in a hook-bound subtree reports `capabilities.unsupported` and no
    actions, and the editor badges it; `SetResult`/`OperationsResult` carry
    `commit_report`. The revision diff remains open.
  - Tests added in `tests/test_http.py`, `tests/test_asgi.py`,
    `tests/test_cli_and_demo.py`, `tests/test_tree_and_operations.py`,
    `tests/test_service.py`. Docs updated in `SPEC_service.md`,
    `AGENT_INTEGRATION.md`, `commands.md`, and `proposal_improvement2.md`.

- 2026-10-17. Union nodes are edited through the control of the alternative the
  value matched (`matched_option` from the snapshot): an enum string becomes a
  `<select>` of its values, `int`/`number` a number field, `bool` a checkbox, a
  string a text field, and an object/array stays the raw source. The `shape…`
  chooser now selects by alternative index and remembers the chosen shape per
  node (`unionShape`), which is cleared on reload. Covered in
  `tests/test_ui_assets.py`.
