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
- 2026-10-15. M2/M4 work deliberately not started: MCP adapter, hook
  dispatcher, generated forms, helper micro-forms, history/restore, and AI
  execution. Recognized hook bindings are refused at write time with
  `UNSUPPORTED_CAPABILITY`.

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