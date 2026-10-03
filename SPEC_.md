# aiset: Shared Settings System Specification

Status: complete working draft for discussion; not an implemented or approved API.
Date: 2026-10-03.
Targets: aidir, aibt, sndbx, colloc, and other projects.
Project name: `aiset`. Initial location: `aidir/aiset/`; other hosts use
`src/aiset/` when they have a `src/` directory, otherwise `aiset/` at the root.

During specification development, this file is the sole editable specification
and contains the complete design, including all incorporated amendments.
After the specification is finalized, freeze it and rename it to `SPEC.md`.

## 1. Goal and initial scope

Build a reusable library for describing, loading, validating, reading, and
editing project configuration. Projects supply a descriptor and a small
integration adapter; configuration mechanics must not be copied between them.

The authoritative editable storage format is JSON5, with comments and source
formatting preserved. Existing `${VAR}` and `${VAR:-default}` templates must
also be supported without writing resolved environment values back to disk.

The first editor is deliberately small:

- Enter a parameter path and read its source value, including objects/arrays.
- Enter a parameter path and a JSON5 value, validate it, and save it.
- Expose the same operations through Python, HTTP, and MCP.
- Supply reusable HTML/JavaScript assets for embedding into Settings.

A generated tree/form editor is a later consumer of the same descriptor and
service, not a prerequisite. This request produces a specification only.

## 2. Findings from existing projects

| Project | Inspected sources | Existing behavior | Integration requirement |
|---|---|---|---|
| aidir | [loader/editor](https://github.com/DenisDx/aidir/blob/main/core/config.py), [merge helper](https://github.com/DenisDx/aidir/blob/main/core/config_merger.py), [HTTP handlers](https://github.com/DenisDx/aidir/blob/main/webui/backend/app.py), [Settings UI](https://github.com/DenisDx/aidir/blob/main/webui/frontend/app.js), [configuration example](https://github.com/DenisDx/aidir/blob/main/config.json5.example) | Environment substitution before parsing; cached dictionary and dotted lookup; raw and field editing; field writes regenerate JSON and reapply selected comments/placeholders. Validation checks syntax and configuration version. | Retain existing public access patterns through a facade; replace regeneration with source edits; support arrays, dynamic IDs, secrets, and component configs. |
| aibt | Local checkout: `src/core/config.py`, `config.json5.example`, and `webui/backend/app.py` (aibt repository-relative paths). | `pyjson5` parsing; project and component files; `.env` mapping is consulted before process environment, with empty-value behavior differing from aidir; a memoryd-specific reload route exists. | Explicit resolver compatibility policy; component descriptors and layers; project-controlled reload. |
| sndbx | Local checkout: `src/config.py`, `src/webui_server.py`, and `config.json5.example` (sndbx repository-relative paths). | Process environment takes priority over `.env`; missing variables without defaults raise errors; loader returns separate environment/config dictionaries. Sandbox Auto-start choices are persisted separately in `data/sandbox_startup_overrides.json`. | Preserve adapter return shape and overlay provenance; distinguish sandbox configuration persistence from running VM changes. |
| colloc | Remote [runtime LLM storage](https://github.com/DenisDx/colloc/blob/197b00fb24fec4b196bd9bc976845f495d0a4b5c/services/common/runtime_llm_config.py) and [README](https://github.com/DenisDx/colloc/blob/351928a491e33be7301ec1227f6945f2db80ddec/README.md) | Environment-backed defaults; selected runtime LLM fields persisted as JSON in Redis and applied to process environment; multiple Docker services. | Do not assume an existing JSON5 file or a single process. Introduce JSON5 explicitly, with a host-owned runtime distribution/migration adapter. |

The supplied aidir snapshot was also reviewed. It contains nested objects,
arrays of resource/endpoint/model objects, dynamic provider/worker keys,
quoted and unquoted environment placeholders, line and block comments,
commented-out examples, and integer/string log levels.

These findings are observations, not a claim that every field in every project
has already been inventoried. No private environment files were inspected.
colloc has no local checkout here; its referenced files were read from GitHub.

### 2.1 Consequences

1. A parse-and-dump editor with a comment reconstruction map is insufficient:
   block comments, array-item comments, single quotes, and exact source layout
   must survive.
2. A field tree alone needs extensions for dynamic-key dictionaries, unions,
   cross-field references, placeholders, secrets, and runtime application.
3. Storage, configuration loading, and live application are separate concerns.
   Reloading a dictionary does not restart listeners or reconfigure workers.
4. Existing environment precedence must not change accidentally.
5. Task/envid-specific overrides and runtime state are not automatically
   editable project configuration.

## 3. Proposed library boundaries

The project is named `aiset`. Its Python package layout is not selected yet.
Names below describe responsibilities, not committed source paths.

| Module | Responsibility |
|---|---|
| Descriptor | Load, version, validate, compose, and export field definitions. |
| Source document | Parse JSON5/template source into a concrete syntax tree with token spans and comments. Apply localized edits. |
| Resolver | Resolve environment references, defaults, and explicit configuration layers. |
| Validator | Shared structural rules plus registered project-specific checks. |
| Store | Registered files, revisions, locking, atomic persistence, backups, and reload. |
| Service | One read/validate/set implementation used by every transport. |
| HTTP adapter | Mount authenticated routes in an existing application or serve a minimal standalone endpoint. |
| MCP adapter | Register settings tools in the project's existing MCP server. |
| UI assets | Framework-independent path/value controls and browser validation. |

The core library must not require FastAPI, an MCP SDK, Redis, or a UI framework.
Transport integrations are optional dependencies. No imports may load a project
configuration, mutate environment variables, or start a server implicitly.

Each host registers:

- A project/instance identity and allowlisted configuration document IDs.
- File paths, descriptors, layer order, and environment resolver policy.
- Authentication/authorization and audit/error logging callbacks.
- Optional semantic validators and runtime-application callbacks.

Clients select a document ID, never a filesystem path. There is no aidir,
worker, sandbox, or model knowledge embedded in the shared core.

### 3.1 Encapsulation and host integration

The settings system is an independent library project. Its directory must be
usable unchanged in different hosts, like an ordinary third-party library.
Project-specific behavior is supplied through descriptors, initialization
configuration, and documented public APIs, not edits to library modules.

The integration boundary consists of:

- Explicit configuration/descriptor paths and registered document IDs.
- Resolver/layer policies and transport/server configuration.
- Public Python service methods and HTTP/MCP contracts in section 8.
- Registration APIs for semantic validators, authorization, auditing, and
  runtime-application callbacks.
- UI mounting/transport configuration and authorized descriptor export.

All host-specific Python adapters and callbacks live in the host repository,
outside the library directory. They are needed only for behavior that cannot
be expressed declaratively; ordinary integrations should be config-driven.
The library must not discover host internals, depend on the host's working
directory, import host modules by convention, or require subclassing/monkey
patching private classes.

Paths are supplied explicitly; relative paths resolve against a documented
configuration base directory, not an incidental process working directory.
The standalone demo has its own explicit base directory, described below.
Shared modules and assets are identical whether used standalone or by a host.

Exceptions may be necessary, but are explicit exceptions:

- General improvements are developed, tested, and released in the library's
  own repository, then adopted by hosts as version updates.
- A temporary fork/patch must record its reason, upstream revision, compatibility
  impact, and removal plan. It is not a standard integration mechanism.
- No host installer or startup code may silently rewrite library source.

The public API and descriptor semantics are versioned. Incompatible versions
fail with a clear compatibility error rather than changing behavior silently.
The same library revision must be tested against multiple host adapters without
modifying its source between test runs.

### 3.2 Independent repository and version pinning

Recommended future delivery: a separate `aiset` Git repository included in a
host directory as a Git submodule. In aidir it is located at `aiset/`; other
hosts use `src/aiset/` when `src/` exists, otherwise root-level `aiset/`.
The user will initialize/register version control separately. The initial
directory is not yet a Git repository or submodule.

A submodule has its own repository/history and is pinned by the parent
repository to a specific commit. Its worktree may have a `.git` file pointing
to Git metadata rather than a literal nested `.git` directory; this still
provides the requested independent Git identity.

This is straightforward packaging, not a major architectural complication.
The harder work is maintaining source-preserving editing, stable public
contracts, and compatibility across hosts. Operational requirements are:

- Clone/install workflows initialize the pinned submodule, including recursive
  initialization if required by its dependencies.
- Normal install/startup never follows a moving upstream branch or updates the
  library automatically. Upgrades deliberately change the pinned commit and run
  host compatibility tests.
- The library owns its package metadata, dependencies, backend, frontend,
  fixtures, tests, and release process. Hosts install the package from the pinned
  checkout; they do not use ad hoc `sys.path` hacks.
- Development may use an editable package installation; deployments can install
  a package built from the pinned revision. No particular Python import name is
  committed by this proposal.
- Host descriptors, real project configurations, and host integration state stay
  outside the submodule. Only the standalone demo uses library-local editable
  state by default.
- An unmanaged nested clone is not the recommended default: the parent otherwise
  cannot reliably reproduce which revision its installation uses.

The reusable architecture also permits distribution as a versioned package.
Repository placement must not become part of runtime semantics.
No repository or submodule is created by this specification update.

### 3.3 Self-contained backend, frontend, and demo configuration

The library repository includes its own runnable backend and frontend. It must
be possible to clone it, install its declared dependencies, and exercise config
reading, validation, editing, and automated tests without aidir or any other host.

The backend is the standalone HTTP adapter using the same service/store/resolver
as embedded operation. The frontend uses the same distributable UI assets and
routes. There must not be a second demo-only implementation of validation,
comment handling, or persistence.

Illustrative repository layout, not committed names:

```text
aiset/
  pyproject.toml
  src/
  frontend/
  examples/
    config.json5
    descriptor.json5
  tests/
  .local/
    demo/
      config.json5
```

The standalone launch entry point:

1. Explicitly selects local demo mode and serves its bundled frontend/backend
   on `127.0.0.1:8383` by default, with an explicit startup port override.
   A bind failure is reported rather than silently choosing another port.
2. Uses a shipped demo descriptor and a default editable configuration file at
   `.local/demo/config.json5`, resolved relative to the standalone checkout.
3. Seeds that file from the tracked example only when the editable file is
   absent. It never replaces an existing user's edits on restart.
4. Accepts explicit config/descriptor/state-directory overrides, so tests can
   use isolated temporary directories and installed packages do not need a
   writable package directory.

Demo startup must report a clear error if initialization is required but the
selected location is not writable; it does not choose a hidden fallback path.
The library repository's own `.gitignore` excludes `.local/`, lock files,
temporary files, and backups in its designated runtime locations. Tracked
examples and test fixtures are never edited by the running backend.
Ordinary hosts use their own registered paths instead of this default.

The demo configuration is just a file. It has no associated project user,
account database, host service, Redis instance, external credentials, or
authentication configuration. Demonstration examples avoid required environment
variables and external dependencies. Local environment/template tests inject
their own resolver mapping.

Account-free access is permitted only in explicit local demo mode:

- Bind only to a loopback address; reject non-loopback bind settings in this mode.
- Serve UI and API from the same origin; reject unexpected Host/Origin values,
  cross-origin writes, and unsupported request content types. No permissive CORS.
- Use a server-generated same-origin CSRF capability for write requests without
  requiring a user login or account. Validate and set keep all normal descriptor,
  path, revision, and source-preservation checks.
- Do not make the demo's unauthenticated HTTP backend or MCP writes available
  over a public/proxied interface. Public deployment requires the normal
  authenticated host/standalone integration.
- Audit demo operations as an explicit local-demo principal, not a fabricated
  authenticated user.

The frontend initially supplies the read/validate/set controls from section 9,
not a universal editor. Demo writes change only the selected file and the
library's settings snapshot; they do not run commands or apply host services.
Application status follows the same contract as other integrations and must
not imply a host runtime was reconfigured.

## 4. Descriptor format

### 4.1 General shape

Use a declarative JSON-compatible descriptor, authored as JSON or JSON5 and
exported to the browser as strict JSON. Python supplies optional validators,
not a second independent field definition.

```json5
{
  descriptor_version: "1.0",
  project: "demo",
  config_version: "1.0",
  root: {
    type: "object",
    description: "Project settings",
    children: {
      param1: {
        type: "int",
        required: true,
        description: "Demo parameter",
        minimum: 0,
        maximum: 100,
      },
      param2: {
        type: "array",
        required: false,
        description: "Demo array",
        children: { type: "int", description: "Array item" },
      },
      entries: {
        type: "array",
        description: "Mixed entries",
        children_options: [
          { type: "string", description: "Entry name" },
          {
            type: "object",
            description: "Named entry",
            children: {
              id: { type: "string", required: true, min_length: 1 },
              enabled: { type: "bool", default: true },
            },
          },
        ],
      },
    },
  },
}
```

Every named field is represented by a descriptor node. A child's `required`
applies when its containing object exists; it does not force an optional parent
object into existence.

### 4.2 Node rules

| Property | Meaning |
|---|---|
| `type` | `string`, `int`, `number`, `bool`, `null`, `object`, `array`, or `union`. |
| `description`, `title` | Documentation and future UI labels; rendered as text, not HTML. |
| `required` | Presence required; default `false`. Missing and explicit `null` are different. |
| `nullable` | Permit `null` in addition to the declared type; default `false`. |
| `default` | Effective value for an absent optional field. Not inserted into the source on read/save. |
| `enum`, `const` | Allowed values or one fixed value, compared without implicit type conversion. |
| `minimum`, `maximum` | Inclusive numeric bounds. |
| `min_length`, `max_length`, `pattern` | String constraints; pattern uses an agreed portable regex subset. |
| `min_items`, `max_items`, `unique_items` | Array constraints; uniqueness uses type-aware structural equality. |
| `children` | Object: mapping of field names to nodes. Array: one node describing every item. |
| `children_options` | Array: allowed item alternatives. Union: allowed alternatives for the node's own value. |
| `additional_children` | Node describing values of dynamic object keys. Absent means undeclared keys are rejected in strict mode. |
| `key_pattern` | Optional constraint on keys governed by `additional_children`. |
| `env` | Explicit placeholder policy, described in section 6. |
| `secret` | Sensitive subtree; inherited by descendants. Source and effective read permissions are distinct. |
| `read_only` | Reject edits to this subtree; inherited by descendants. |
| `apply` | `live`, `reload`, or `restart`; default `restart` until a host guarantees otherwise. |
| `validators` | IDs of server-side validators registered by the host. |
| `ui` | Optional group/order/help metadata for future generated editors. |

`required: true` with a `default` is an invalid descriptor combination: required
means explicitly present. Descriptor versions are independent of the existing
project configuration `version` field.

For arrays, `children` and `children_options` are mutually exclusive, and one
is required. Options must be a nonempty array. An item is valid if at least one
option validates; matching more than one option is not an error.

For objects, `children` describes fixed fields and `additional_children`
describes all remaining keys. For a `union`, only `children_options` describes
alternatives, and at least one must match. This extends the requested
`children_options` model to fields such as aidir's string-or-integer log level.
It is not JSON Schema's exclusive `oneOf`.

Booleans are not integers, including in Python. `number` accepts finite integers
and finite floating-point values; `int` accepts mathematical integers.
Integer-valued inputs to either type must be within the portable exact range
`[-9007199254740991, 9007199254740991]`. Larger integers, NaN, and Infinity
are rejected in v1 so HTTP and browser validation agree.
The root is always an object. Descriptor self-validation rejects malformed
recognized definitions, invalid constraints, and invalid defaults before serving
requests. Unknown descriptor properties are ignored during normal operation
and reported by development validation as specified in section 4.5.

### 4.3 Dynamic keys and heterogeneous values

```json5
{
  type: "object",
  children: {
    default: { type: "string" },
  },
  additional_children: {
    type: "object",
    children: {
      enabled: { type: "bool", default: true },
      level: {
        type: "union",
        children_options: [
          { type: "int", minimum: 0, maximum: 7 },
          {
            type: "string",
            enum: ["emergency", "alert", "critical", "error",
                   "warning", "notice", "info", "debug"],
          },
        ],
      },
    },
  },
}
```

Dynamic collections cover providers, workers, agents, sandboxes, and envids
without hard-coding their instance IDs in the descriptor.

Module-specific descriptors may be mounted at a host-selected subtree. Conflicts
between definitions are errors, not last-writer-wins overrides. Descriptor
composition is local and trusted; clients cannot load remote descriptors or
Python code.

### 4.4 Beyond structural validation

Registered validators handle relationships such as:

- A resource's provider ID must exist in the providers collection.
- An endpoint's worker ID must exist.
- Sandbox published ports must not conflict.
- A timing relation or provider-specific model option must be valid.

Validators receive a candidate effective snapshot and changed paths, and return
structured issues. They must be side-effect-free and must not execute configured
shell commands or contact external providers merely to validate a write.

Checks requiring filesystem/network access belong to an explicit optional
diagnostic operation, not routine field validation.

### 4.5 Project metadata and descriptor diagnostics

Projects may add their own properties to the descriptor for their own use.
The shared library ignores unknown properties when interpreting the descriptor;
it does not require source changes or registration of every project's metadata.
This applies to descriptor-envelope properties, field nodes, and recognized
metadata structures such as `env` and `ui`.

Example field node:

```json5
{
  type: "int",
  minimum: 1,
  maximum: 65535,
  description: "Service port",
  x_aidir: {
    subsystem: "http",
    documentation_group: "listeners",
  },
}
```

`x_aidir` is opaque project-owned data. The library does not execute it,
validate its internal schema, or infer settings behavior from it. A namespace
such as `x_<project>` is recommended to reduce future name collisions, but is
not mandatory and does not suppress unknown-property reporting.

Keep a lossless/raw descriptor representation available to trusted host code,
separate from the compiled shared descriptor. Unknown properties are retained,
not stripped from the host's descriptor file or rewritten on load.
The generic browser/HTTP descriptor export contains recognized, authorized
properties only. A host wanting its own metadata in a UI supplies a separate
explicitly authorized export; arbitrary metadata must not leak by default.
The descriptor revision covers the complete source, including project metadata.

Provide a public `validate_descriptor` development operation, plus a CLI
interface so it can run without starting a backend or loading project settings.
It is distinct from validating a candidate configuration value:

- Validate syntax, supported descriptor version, and all recognized definitions.
  Unsupported values of known properties, such as `type: "intr"`, remain errors.
- Report every unknown descriptor property with a stable issue code
  `UNKNOWN_DESCRIPTOR_PROPERTY`, severity, JSON Pointer to the property, and
  source line/column when available. Do not include its potentially secret value.
- Traverse the recognized descriptor structure, including every `children`
  node, `children_options` item, and `additional_children` node.
- A name under an object's `children` mapping is a configuration field name,
  not a descriptor keyword. Do not report such names as unknown properties.
  Similarly, object keys in literal `default`, `enum`, or `const` values are data.
- Report an unknown property's location once and treat its entire value as
  opaque; do not recursively report its internal keys as descriptor properties.
- Always report deliberate custom fields as well as potential spelling mistakes.
  Thus `requried` is visible to developers instead of being silently mistaken
  for `required`. The diagnostic does not reinterpret or autocorrect it.

Default diagnostic mode returns `valid: true` if recognized definitions are
valid and includes unknown properties as warnings. A strict development mode
treats unknown-property diagnostics as errors and returns `valid: false`, useful
for projects wanting typo-free CI checks. CLI exit status is zero when `valid`
is true and nonzero otherwise; output includes warnings even on success.
Choosing strict development mode does not change normal runtime interpretation.

Example default-mode diagnostic:

```json
{
  "valid": true,
  "issues": [
    {
      "code": "UNKNOWN_DESCRIPTOR_PROPERTY",
      "severity": "warning",
      "path": "/root/children/port/x_aidir",
      "message": "Property is not interpreted by the shared settings library"
    }
  ]
}
```

Projects can separately validate their metadata in host-owned tooling. That
does not require modifying the library. Known descriptor names are reserved;
project metadata must not override `type`, `required`, `secret`, or other
recognized semantics. A library upgrade that introduces a colliding name needs
an explicit metadata migration, not an unnoticed behavioral change.

Unknown descriptor metadata is not the same as an undeclared configuration
field: configuration-field coverage and validation remain as strict as section 5
requires. Ignoring metadata must never create an unrestricted settings subtree.
Resource/depth limits apply to the complete descriptor, including opaque data.

## 5. Paths and edit semantics

### 5.1 Canonical paths

Use JSON Pointer for Python, HTTP, MCP, and the shared UI:

```text
/logging/level
/models/providers/ollama_local/models/0/id
/sandboxes/items/sandbox-1/run_at_startup
```

Escape `~` as `~0` and `/` as `~1` in object keys. Dots remain ordinary
characters. A numeric segment addresses an array index only when the current
node is an array; object keys such as `"0"` remain keys.

The empty pointer denotes the root and is read-only in the first editor.
Malformed escapes, negative indexes, out-of-range indexes, and missing parents
produce explicit errors. The array append marker `-` is not supported in v1.

Existing aidir dotted methods remain compatibility facades. They convert only
unambiguous legacy object paths; arrays and literal dots use JSON Pointer.
No shared endpoint guesses between dotted and pointer syntax.

### 5.2 Set one parameter

`set` replaces the addressed value; it does not recursively merge an object.
It may create an absent optional leaf when the parent already exists and the
descriptor permits the field or dynamic key. It does not create missing parents.
Setting an array element requires an existing index.

Input is a `value_text` string containing exactly one JSON5 value or supported
template value. Strings must be quoted. Invalid JSON5 is not silently converted
to a string. A missing value, trailing executable text, or extra document is an
error. Comments in the input are handled as source text, never executed.

Before persistence:

1. Parse the path and check edit permissions and descriptor coverage.
2. Parse the new source value.
3. Resolve its placeholders and the complete candidate configuration.
4. Validate the addressed subtree and the complete effective configuration,
   including semantic rules and layer effects.
5. Construct a source-preserving patch and reparse/revalidate its result.
6. Persist once, publish the new stored snapshot, and report application status.

Existing invalid fields do not become valid simply because they were untouched.
During migration, an explicit inspection-only compatibility mode may retain
unknown fields and report descriptor gaps. Writes remain disabled until the
editable document has complete strict descriptor coverage.

Deletion, array insertion/removal, batch transactions, and full-document editing
are later shared operations. Existing aidir editors must remain available during
the transition; their adapters must not claim the new preservation guarantee
until they use the new store.

## 6. Source, templates, and effective settings

Keep three separate representations:

1. **Source document:** exact file bytes, comments, quotes, and placeholder text.
2. **Stored semantic tree:** parsed literals and explicit placeholder/template
   nodes, before environment resolution.
3. **Effective snapshot:** resolved/defaulted/merged values supplied to the host.

Ordinary JSON5 parses directly. A file containing an unquoted token such as
`${REDIS_PORT:-6379}` is a **JSON5 template**, not valid standalone JSON5.
The source parser must explicitly recognize such tokens outside strings.
Inside strings it records placeholder spans without resolving them in storage.

Example descriptor:

```json5
{
  type: "int",
  minimum: 1,
  maximum: 65535,
  env: { allowed: true, convert: "int" },
}
```

Proposed new-project resolver policy:

- Explicit host overrides, then process environment, then supplied `.env`
  mapping, then a placeholder's default.
- `${VAR}` without a value or default is an error.
- `${VAR:-default}` uses the default only when the variable is absent. An
  explicitly present empty value remains empty; the syntax is not shell evaluation.
- Substitution is single-pass; environment values are data, not nested templates.
- No `eval`, shell interpolation, or textual insertion of environment values
  into reparsed JSON5.
- String interpolation preserves quotes, slashes, Unicode, and newlines safely.
- Whole-value numeric/bool placeholders use explicit descriptor conversions.
  Boolean conversion accepts only `true` and `false`; numeric conversion rejects
  empty/nonfinite/out-of-range values. Quoted whole placeholders can opt into
  conversion, but ordinary strings are not coerced.
- In v1 an environment variable cannot inject an object, array, key, or comment.
- Placeholder resolution is disabled unless the node's `env.allowed` is true.
  Disabled placeholders inside strings remain literal text; unquoted placeholders
  at such a node are invalid.

Existing adapters must record their current precedence, missing/empty-value
behavior, and conversion needs before adopting the new policy. Legacy behaviors
are explicit compatibility profiles, not global defaults. They must not permit
environment values to alter source structure. Configurations depending on raw
structural injection require an explicit migration, not a silent reinterpretation.

The browser must never receive environment values to validate placeholders.
It reports local structural checks as passed/failed and environment/semantic
checks as requiring server validation. Server validation is always authoritative.

Optional field defaults affect only effective snapshots. Reads do not edit the
file. Environment files themselves are not editable through this v1 API.

## 7. Comment-preserving storage contract

### 7.1 Required guarantees

Do not serialize the effective dictionary and reconstruct comments afterward.
Use a concrete syntax tree/token-span editor retaining source trivia.

- A read followed by no edit leaves the file byte-for-byte unchanged.
- Setting an existing scalar replaces only its value tokens; comments before,
  after, and inline remain unchanged.
- Untouched source bytes remain identical: key order, quotes, whitespace,
  trailing commas, comments, and placeholder expressions.
- Preserve UTF-8 text and original newline style, including a final missing
  newline. A source BOM, if accepted by the parser, is preserved.
- Duplicate object keys are rejected with locations; never edit an ambiguous key.
- New leaves use local indentation/newline conventions and adjust only necessary
  surrounding separators. Existing sibling comments remain attached.
- If preservation cannot be guaranteed, fail explicitly and do not modify disk.
  No fallback to parse-and-dump is permitted.

Composite `set` needs structural reconciliation rather than blind span
replacement. Existing named object children and equal-length array elements
retain their comment trivia while their values are edited.
If a replacement deletes/reorders commented children, changes their structural
type, or introduces ambiguous comment ownership, v1 rejects it with
`COMMENT_PRESERVATION_CONFLICT`. Even rejection must leave the document intact.
There is no force-write escape hatch in the first UI/API.

Comment-free portions of a replaced subtree may be reformatted. Internal
comments from submitted `value_text` may be added only when attachment is
unambiguous; otherwise the operation is rejected. Existing comment bytes and
relative attachment must survive accepted edits.

This makes object/array reads and writes useful immediately without promising
lossless arbitrary array reordering. Identity-aware list editing and an explicit
comment relocation workflow can be designed later.

### 7.2 Parser selection gate

The existing `json5`/`pyjson5` decoders produce values, not a sufficient
source-preserving edit model. Select a parser/editor only after a fixture-based
proof demonstrates the guarantees above, including template tokens.

Prefer a maintained implementation with appropriate licensing and Python
integration. A small isolated source-editing subsystem is an alternative only
if no suitable dependency passes the same tests. Dependency choice and any
cross-language runtime requirement need approval before implementation.

### 7.3 Revisions and durable writes

Every source read returns an opaque revision for that document. It changes on
any byte change, including comments/whitespace. The descriptor has a separate
revision. Writes require both revisions; absence is not an unconditional write.

Within a bounded cross-process lock on a stable sidecar lock file:

1. Re-read the file and compare revisions.
2. Build and validate the candidate using a captured resolver/layer snapshot.
3. Verify registered layer/descriptor revisions are still current.
4. Write a uniquely named temporary file in the same directory, retaining
   restrictive file permissions and required ownership.
5. Flush and synchronize it; atomically replace the target and synchronize the
   containing directory.
6. Publish the new stored revision; remove temporary files on failure.

Lock timeouts, conflicts, permissions, parse errors, and persistence failures
have distinct errors. A failure after replacement must report the known committed
state or require an explicit re-read; it must not claim the file was untouched.
The lock file is not the replaced configuration inode.

All library writers must cooperate with the lock. Arbitrary editors that ignore
it can still race filesystem replacement; this limitation must be documented,
and deployments requiring strict guarantees must route writes through the store.
External edits are detected on the next read/reload and never overwritten from
a stale in-memory dictionary.

Backups are optional, private, bounded by an explicit host retention policy, and
outside public/static directories. A backup failure under a required-backup
policy aborts before commit. Backup rotation itself must not lose comments.

## 8. Unified service and transport contract

### 8.1 Library operations

| Operation | Input | Output |
|---|---|---|
| `load` | Registered document ID and host resolver/layer policy | Validated effective snapshot, source revision, descriptor revision, provenance. |
| `get` | Document ID, pointer, authorized view | Source fragment or effective value, revisions, field metadata/provenance. |
| `validate` | Document ID, pointer, `value_text`, expected revisions | Candidate validation issues and whether the proposed edit can preserve source. No writes or live changes. |
| `set` | Same inputs as validate plus principal | Stored revision, validation result, and application status. |
| `descriptor` | Document ID and principal | Authorized strict-JSON descriptor and its revision. |
| `validate_descriptor` | Descriptor source and diagnostic mode, without a host/config file | Validity and descriptor issues, including unknown-property locations. |

Validation and set use the same candidate pipeline. Set repeats it under the
write lock; an earlier successful validation is not permission to skip checks.
Effective snapshots are isolated from caller mutation.

### 8.2 Minimal HTTP routes

The mount prefix is configurable; `/api/settings` is illustrative.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/settings/descriptor?document=main` | Descriptor used by the browser. |
| GET | `/api/settings/value?document=main&path=/logging/level&view=source` | Read one field/subtree. |
| POST | `/api/settings/validate` | Validate one proposed set operation. |
| POST | `/api/settings/value` | Persist one proposed set operation. |

Request example for validate/set:

```json
{
  "document": "main",
  "path": "/logging/level",
  "value_text": "\"warning\"",
  "expected_revision": "opaque-source-revision",
  "expected_descriptor_revision": "opaque-descriptor-revision"
}
```

Source read response:

```json
{
  "document": "main",
  "path": "/logging/level",
  "exists": true,
  "view": "source",
  "value_text": "\"${LOG_LEVEL:-error}\"",
  "format": "json5-template",
  "revision": "opaque-source-revision",
  "descriptor_revision": "opaque-descriptor-revision",
  "origin": {"kind": "file", "document": "main"}
}
```

`format` is `json5-template` when the fragment includes recognized, enabled
placeholder syntax, even inside a quoted string that is itself valid JSON5.
Otherwise it is `json5`.
An ordinary object read returns its exact source fragment, including comments,
as `value_text`, not a regenerated JSON object.

An absent permitted optional leaf returns `exists: false` and no `value_text`.
An undeclared path or missing parent is an error. Explicit `null` is present
and returns `"null"`. An effective default must not masquerade as a stored value.

Successful set response includes:

```json
{
  "ok": true,
  "stored": true,
  "revision": "new-source-revision",
  "descriptor_revision": "opaque-descriptor-revision",
  "application": {
    "state": "restart_required",
    "active_revision": "previous-active-revision"
  }
}
```

Application states are `applied`, `reload_required`, `restart_required`, and
`apply_failed`. A missing host application callback cannot report `applied`.
For a committed write whose callback fails, return `stored: true` and
`apply_failed` with an explicit application error; do not return a generic
write failure that encourages blind retries.

Errors share a transport-neutral envelope:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Candidate configuration is invalid",
    "issues": [
      {
        "path": "/redis/port",
        "rule": "maximum",
        "message": "Must be at most 65535"
      }
    ]
  }
}
```

Issues include source line/column when available, but never secret values.
Invalid syntax/path/envelope: HTTP 400. Unauthorized: 401/403. Unknown document
or undeclared path: 404. Missing revisions: 428. Stale revisions or preservation
conflict: 409. Descriptor/value validation failure: 422. Body too large: 413.
Lock timeout: 503. Unexpected storage failures: 500 with sanitized details.

The standalone server uses the same service and authorization interface. It
binds to loopback by default and must refuse unauthenticated normal startup.
The only account-free exception is explicitly selected local demo mode with the
restrictions in section 3.3. Mounting inside an existing server is the preferred
host integration; autonomous demo operation is also a first-class use case.

### 8.3 MCP

Register `settings_get`, `settings_validate`, and `settings_set`, with the same
document/path/value/revision inputs and result shapes as HTTP. The descriptor
can be an authorized resource or `settings_descriptor` tool.

MCP tool schemas describe request envelopes, not a second project configuration
schema. Application validation failures use MCP's error-result mechanism
(`isError: true`) while retaining the shared error code/issues in structured
content. A committed set with `apply_failed` retains its explicit stored status.

Write tools are independently permissioned and may be disabled. They must not
inherit write permission merely because the caller can invoke an inference
endpoint or another MCP tool.

## 9. First reusable UI

Distribute a small HTML fragment, stylesheet, and JavaScript module. The host
mounts the fragment in Settings and supplies an API base URL or transport
callbacks, authentication/CSRF integration, and a document ID.

Controls:

1. Parameter path input using JSON Pointer, with a visible path example.
2. **Read** button and source-value textarea supporting multiline JSON5.
3. Field description/type/range/required/read-only information.
4. **Validate** and **Save** buttons.
5. Explicit local/server validation, conflict, persistence, and application status.

Workflow:

- Read obtains the source and descriptor revisions.
- Editing performs portable local checks without replacing the user's text.
- Placeholder/server-only checks remain visibly pending until server validation.
- Save repeats authoritative validation and submits the captured revisions.
- A conflict retains the user's input and offers re-read/reconcile, never
  automatic overwrite.
- After saving, re-read the field and display whether reload/restart is required.
- An absent allowed optional field can be created; a read-only field cannot be
  saved. Changing document/path invalidates the previous captured revisions.

Use a real JSON5 parser, not `eval`, in the browser. Template support shares
the lexical/validation contract with the server. Render configuration and
descriptions through text controls, never untrusted HTML.
No framework/global CSS dependency and no CDN dependency are required.
Browser/server validators share fixtures and descriptor version checks.

Full config viewing, generated forms, tree navigation, completion, specialized
secret widgets, deletion, and list-reordering UI are outside the first editor.
Existing aidir raw/logging controls are not removed as part of this proposal.

## 10. Layers, provenance, and live application

The loader can produce one uniform effective object without owning the host's
runtime lifecycle. Every effective value should expose its origin to authorized
diagnostic callers: source file, default, environment reference, or override.
Environment diagnostics expose variable names, not secret values.

Layer order and merge rules are host-defined and versioned. For aidir-style
component configuration, the existing recursive-object merge and whole-array
replacement rule must be preserved. The shared field `set` operation itself is
replacement, not that merge operation.

Editing targets one registered source document. Reading effective configuration
does not grant the ability to write back a flattened layered object.
If an override masks a changed source value, report that the stored value changed
but the effective value remains overridden.

Initial integrations:

- **aidir:** facade for `Config.get`, indexing, load, and raw/source access;
  route/UI adapters; component defaults and overrides remain explicit.
  The current SIGHUP handler reloads the config cache, not all runtime objects.
- **aibt:** preserve dict-returning loader functions and component file loading;
  do not mistake memoryd reload for whole-project application.
- **sndbx:** preserve `{"env": ..., "config": ...}` at its integration boundary;
  retain the existing Auto-start overlay until an explicit migration is approved.
  Never restart a running sandbox as a side effect of saving a field.
- **colloc:** first inventory environment, Redis runtime, and session-scoped
  settings. Select which become file-backed project configuration. Import existing
  Redis values only in an explicit migration. Redis may remain a runtime
  distribution/cache adapter; it is not the JSON5 comment-preserving store.
  Do not move transient session settings into the project file.

Use a host callback for supported live/reload changes. It runs after durable
commit, outside the file lock, and receives immutable old/new snapshots and
changed paths. Store revision and active revision remain distinct.
The most restrictive affected `apply` policy wins. Structural changes include
removed descendants when calculating that policy.
Cross-process distribution, acknowledgements, and rollback are host concerns
until a separate contract is agreed.

## 11. Security and operational requirements

- Explicit permissions for source reads, effective reads, validation, and writes.
- Secret handling applies recursively to parent-object/root reads and diagnostics.
  A source fragment containing inaccessible secrets is denied in v1, not returned
  as a redacted fragment that could accidentally overwrite the real values.
- Never send resolved credentials in descriptors, errors, audit events, or the
  initial editor. Authorized secret editing is a separate capability.
- All changed descendants of an object replacement undergo permission/read-only
  checks; parent edits cannot bypass child protections.
- HTTP cookie-based writes require the host's CSRF/origin protections. CORS is
  opt-in and restricted, not wildcard.
- Allowlisted paths only; no client-selected paths, symlink traversal, arbitrary
  backup downloads, Python expressions, or remote schema fetches.
- Host-configured file/request size, nesting, collection, regex, and validation
  limits; check them before expensive parsing. Effective configuration obeys the
  same limits after resolution.
- Unknown descriptor metadata is inert and retained for host use, but is neither
  executed nor automatically exported. Development diagnostics report property
  locations without logging metadata values.
- Audit actor, document, changed paths, old/new revisions, and result.
  Do not log entire request values or environment payloads.
- Invalid external edits fail reload explicitly and retain the last validated
  active snapshot; reads must disclose invalid-on-disk status rather than pretend
  that the cached data is current.

## 12. Acceptance tests and implementation gates

These are required future tests, not claims of existing implementation.

| Area | Required verification |
|---|---|
| Descriptor | Nested objects/arrays, union alternatives, dynamic keys, missing vs null, defaults, invalid descriptors, composition conflicts. |
| Descriptor metadata | Unknown properties ignored at runtime and retained for hosts; every unknown location reported in diagnostic mode; strict-mode exit status; typo warnings; opaque nested metadata; field/data keys not misreported; safe browser export. |
| Encapsulation | Identical library revision works with multiple host configs/adapters; no host imports, source patches, implicit working-directory assumptions, or writes to shared modules/assets. |
| Standalone demo | Own backend/frontend work without a host/account/Redis; first-run local file seeding, retained edits on restart, explicit path overrides, isolated test state, read-only-location errors, no writes to tracked examples. |
| Demo isolation | Explicit demo selection; non-loopback bind rejected; Host/Origin/content-type and CSRF checks; normal mode still requires authorization; file edits do not launch host commands/services. |
| Type parity | Python bool vs int, fractional values, numeric bounds, finite values, exact integer range, identical browser/server portable outcomes. |
| Paths | Escaped slash/tilde, dotted keys, numeric object keys, arrays, malformed pointers, absent leaves/parents, read-only root. |
| Source preservation | Exact untouched-byte comparison after scalar edits; line/block/array/nested comments; single quotes; trailing commas; UTF-8; CRLF; headers; commented examples; URL strings; templates. |
| Composite editing | Retained child comments; accepted safe replacements; rejected deletion/reordering/type changes with ambiguous comments; original bytes unchanged after rejection. |
| Template resolution | Quoted/unquoted references, defaults, empty/missing variables, resolver profiles, escaped environment values, conversion failures, no structural injection, no secret persistence. |
| Validation | Full candidate and cross-field checks; no partial write on failure; parse the exact persisted candidate, not a separately serialized proxy. |
| Persistence | Stale source/descriptor/layer revisions, concurrent cooperating processes, lock timeout, permissions, external edits, atomic-write fault injection, commit-state reporting, temporary-file cleanup. |
| Transport parity | Python/HTTP/MCP return the same values, issue paths, conflict codes, and stored/application status. |
| Security | Auth/CSRF, source vs effective permissions, recursive secret/read-only enforcement, size/depth limits, sanitized audit/error output. |
| UI | Read/set scalar and object, placeholder validation status, optional field creation, changed path invalidation, retained input after conflict, restart/apply-failure display. |
| Host compatibility | Existing aidir/aibt/sndbx load shapes, precedence and merge rules, no automatic listener/worker/VM restart, explicit colloc migration. |

The authoritative phased implementation plan is in section 17. Its first working
milestone is the autonomous mixed-type configuration editor on default port 8383.
This section remains the overall acceptance matrix.

Every implemented phase must pass its relevant tests before the next integration.
No runtime code or dependency changes are included in this draft.

## 13. Decisions still requiring agreement

User-established requirements now include an encapsulated independent library,
unchanged modules across normal host integrations, project-owned descriptor
metadata ignored at runtime but reported by development validation, and an
autonomous backend/frontend with a default local demo file and no user accounts.
Exceptional patches remain possible but must be explicit.

Remaining questions are collected in section 16, the authoritative discussion
register. Recommendations are not approved merely because they appear in this
draft. Section 15 defines specification readiness; section 17 defines delivery.
The first working milestone and default standalone port 8383 are user requirements,
not open architectural choices.

No unresolved marker is embedded in implementation code. Section 16 is the
authoritative open-decision register for subsequent specification work.

## 14. AI functionality

### 14.1 Purpose and current scope

Plan for connecting AI models to assist with configuration editing inside aiset.
The AI capability is future work: no model/provider integration, agent runtime,
invocation mechanism, or AI UI is implemented or selected at this stage.

The configuration-editing context must include project-specific instructions,
not only field types and constraints. For this purpose, the host project must
provide at least one Markdown file containing a skill/instruction for an agent
responsible for editing that project's configuration.

The skill complements the configuration descriptor; it does not replace
machine-readable validation. Here, editing context means the instructions and
configuration information supplied for this task, not arbitrary host chat
history or unrelated runtime/task context.

### 14.2 Host-provided agent skill

In addition to the configuration descriptor, each host integration must supply
one or more Markdown skill files. The host owns and maintains these files
outside the shared aiset directory; using them must not require modifying
aiset's modules.

A skill should explain:

- The project's purpose and the meaning of its configuration groups.
- Which document(s) and parameter paths the agent may edit.
- Project conventions, valid examples, semantic dependencies, and common
  mistakes not adequately explained by individual field descriptions.
- How to propose a change and use aiset's read/validate/set workflow.
- Comment and environment-placeholder preservation requirements.
- Read-only/sensitive settings and what must not be exposed to a model.
- When a saved change requires reload/restart and how that should be explained.

Plain Markdown instructions are sufficient for this stage. No framework-specific
skill format, front matter, executable code, or provider identity is required.
Examples must not contain real credentials or resolved secret values.

For multiple files, the host must identify which configuration documents each
file applies to and any relevant reading order. The exact registration fields,
composition rules, loading API, and discovery mechanism remain future design
decisions; aiset must not guess files from the host's directory structure.

The descriptor remains authoritative for shared structural constraints. Skills
may explain rules, but cannot override validation, access controls, read-only
fields, or source-preservation guarantees.

### 14.3 Future editing boundary

An eventual AI editor must use aiset's documented configuration APIs rather
than bypassing the store with direct file writes. Candidate changes undergo
the same validation, permission checks, revision handling, and comment-preserving
persistence as manual UI, HTTP, and MCP edits.

Skill content is instruction data, not executable code or authorization.
It must not itself grant tools, file access, or write privileges. Hosts remain
responsible for approving which configuration information may be supplied to
a model; no automatic upload of skills, source documents, or secrets is implied.

The host's skill-file requirement is recorded now for integration planning.
No skill loader, mandatory runtime startup check, new endpoint, or AI dependency
is introduced by this specification addition. Manual configuration editing
does not require an AI model or running agent.

### 14.4 Deferred decisions

AI decisions are collected under Q15 in section 16: providers/credentials,
invocation, execution/tools, skill/context assembly, human approval, and auditing.
They do not block the standalone manual editor.

For now, the deliverable is the host-authored Markdown editing skill and its
documented role. No decision about the agent's lifecycle or execution platform
is implied.

## 15. TODO: Prepare the specification for implementation

1. Resolve Q01-Q10 in section 16, record the decisions in the relevant contracts,
   and approve the milestone M1 scope and acceptance criteria in section 17.
2. Complete a source-preserving parser feasibility check against representative
   fixtures; do not approve a parse-and-dump fallback.
3. Finalize descriptor/envelope examples, the test-data matrix, explicit numeric
   resource limits, and reproducible install/start/test commands.
4. Keep terminology, contracts, and cross-references consistent; remove
   superseded/contradictory statements. Retain one discussion register and one
   authoritative phase plan.

The specification is ready to start M1 when those tasks are complete and every
M1-blocking question has an accepted answer. Later-phase questions may remain
open with an explicit phase gate; resolving AI or every host migration is not
a prerequisite for building the standalone editor.

## 16. TBD: Questions to discuss

The following is the authoritative discussion register. Existing recommendations
are not accepted answers unless explicitly approved. The project name, unchanged
library boundary, host placement convention, standalone first milestone, and
default port 8383 are decided and are not reopened here.

| ID | Question requiring an agreed contract | Must be resolved before |
|---|---|---|
| Q01 | Which Python versions/platforms, package layout, web dependencies, launch/stop commands, and startup-option precedence are supported? How are server startup settings separated from the editable demo file so edits cannot unexpectedly move the listener? | M1 implementation. |
| Q02 | Which concrete syntax parser/editor passes the lossless JSON5/template fixtures? What syntax is supported, and how are unsupported or ambiguous source edits rejected without writing? | M1 implementation. |
| Q03 | What is the complete descriptor grammar, including recognized `env`/`ui` keys, union/dynamic-key rules, defaults, reserved names, version compatibility, and development diagnostic output? JSON or JSON5 authoring, or both? | M1 implementation. |
| Q04 | Approve JSON Pointer and the exact read/set rules: absent optional leaves, numeric object keys, arrays, root access, object replacement, and comment-conflict rejection. Which safe composite edits must M1 accept? | M1 implementation. |
| Q05 | Approve the demo/new-project placeholder resolver: precedence, absent versus empty values, defaults, conversions, escaping, and literal placeholders. How are tests isolated from the developer's environment? | M1 implementation; host compatibility profiles before phase 3. |
| Q06 | Which browser JSON5/template parser and shared fixtures guarantee portable validation parity? Finalize numeric equality/ranges, regex subset and limits, Unicode behavior, and reporting of server-only checks. | M1 implementation. |
| Q07 | Finalize Python/HTTP signatures, authorized descriptor/source/effective views, request/response/error envelopes, revisions, optional-field results, and standalone descriptor-validation CLI output. | M1 implementation. |
| Q08 | What filesystem/locking guarantees apply on the supported platform? Specify timeouts, cancellation/fault behavior, permission retention, invalid external-edit handling, commit-state reporting, and the demo's backup policy. | M1 implementation. |
| Q09 | Specify demo Host/Origin/CSRF protection, explicit path registration and symlink policy, plus numeric file/body/depth/collection/regex/time limits. What are the expected error/status and logging behaviors? | M1 implementation; production authorization before phase 2. |
| Q10 | Approve the fixture corpus, supported test sizes, measurable response-time targets if required, CI commands, and the exact M1 acceptance checklist. How does a clean standalone installation obtain/bundle its UI assets without a CDN or host environment? | M1 implementation. |
| Q11 | Finalize normal-mode authorization, embeddable UI mounting, MCP SDK/transport integration, and host-owned adapter contracts. In which order are aidir, aibt, sndbx, and colloc integrated? | Phase 2 for shared transports; phase 3 for each host. |
| Q12 | How are component descriptors composed, layers/provenance registered, and live application acknowledged across processes? Define stored/active revisions and masking/failure behavior for each host. | Phase 3, before the affected integration. |
| Q13 | Choose release/API versioning, pinned-package/submodule delivery, upgrade checks, descriptor/config migrations, and project-metadata collision handling. Who maintains host compatibility fixtures? | Phase 2 release; migrations before an affected upgrade. |
| Q14 | Prioritize extended operations: batch/remove/append, comment-aware array identity/reordering, backups/restore, diff/approval workflows, generated forms, and change subscriptions. Define transactional semantics before implementing them. | Phase 4, separately for each feature. |
| Q15 | Decide AI model/provider connections and credentials, agent caller/environment/tools, skill registration/composition, context assembly, human approval, and secret-safe audit behavior. No execution platform is selected now. | Phase 5, only after a separate implementation approval. |

## 17. Phased implementation plan

This plan replaces the earlier implementation outline. Section 12 remains the
overall acceptance matrix; each phase selects its relevant tests and adds
observable exit criteria. This is a plan, not an execution record.

### Phase 0: Close the specification and prove feasibility

- Complete section 15 and resolve Q01-Q10.
- Select the parser/editor only after source-preservation fixtures pass.
- Freeze the M1 contracts, example descriptor/config, dependency choices,
  operational limits, and install/start/test instructions.
- Confirm later-phase exclusions so the first milestone is not blocked by host
  migration, production auth, MCP, generated forms, or agent execution.

Exit: approved M1-ready specification and reproducible parser feasibility
evidence. This preparation gate is not the first working-product milestone.

### Phase 1 / M1: Standalone editor of aiset's own demo configuration

**First milestone:** a working configuration editor using aiset's own backend,
frontend, descriptor, and mixed-type test configuration, served on its own
HTTP port. Default address: `http://127.0.0.1:8383`.
The startup port is configurable; 8383 is its fixed default, not a test-data
value or a host project's port.

Deliver vertically integrated behavior:

1. Package the shared descriptor/resolver/validator/source-editor/store/service
   modules and a bundled standalone UI without host-specific imports.
2. Ship a documented test descriptor, commented JSON5/template config, and an
   example Markdown editing skill. The skill is instructional only; no agent
   or skill execution/loading subsystem is needed.
3. Seed `.local/demo/config.json5` only when absent. Support explicit isolated
   config/descriptor/state locations; never modify tracked examples on startup.
4. Implement source field/subtree reads, candidate validation, and revision-checked
   single-field writes through the Python service and shared HTTP routes.
5. Implement the manual path/value UI with Read, Validate, Save, descriptor
   hints, local checks, server-only check status, and actionable errors.
6. Preserve source comments/placeholders with tested localized edits. Safe
   object/array edits follow the approved Q04 contract; ambiguous edits fail.
7. Implement required locking/atomic writes, stale revisions, permission/path
   checks, and explicit disk/validation failures. No success-shaped fallback.
8. Run the account-free explicit demo mode with section 3.3's loopback,
   Host/Origin/CSRF protections. Bind failures, including an occupied port, are
   explicit; do not silently select another port or kill its owning process.

Minimum valid fixture matrix:

| Data/behavior | Demonstration |
|---|---|
| `string` | Empty/nonempty strings, Unicode, quotes, slashes, multiline/escaped text, length/enum constraints. |
| `int` and `number` | Zero, negative values where allowed, fractional numbers, bounds and exact-range checks. |
| `bool` | Both values; `false` remains a present value, not "missing". |
| `null` / nullable | Explicit null, absent optional field, and effective default are distinguishable. |
| `object` | Nested named fields, required/optional children, dynamic keys, literal dots, escaped slash/tilde, and numeric object keys. |
| `array` | Empty arrays when allowed, scalar items, object items, nested arrays, indexed reads/edits, and mixed `children_options`. |
| `union` | A field permitting multiple value types, with accepted and rejected alternatives. |
| Templates | Quoted/unquoted placeholders with self-contained defaults; injected test mappings for missing/empty/conversion checks. No required real credentials. |
| Source/metadata | Line/block/array comments, single quotes, trailing commas, custom descriptor metadata ignored at runtime and reported by diagnostics. |
| Protection/errors | Read-only fields and synthetic sensitive fields; malformed paths/values, invalid ranges/types, rejected comment-conflicting replacements, and stale revisions. |

M1 acceptance, all required:

- From a clean standalone installation, the documented command serves the
  actual UI and API on port 8383 without aidir, Redis, user accounts, a model,
  or any undeclared host dependency.
- The override port works. An occupied 8383 fails clearly. First-run seeding,
  subsequent startup, explicit path overrides, and non-writable paths are tested.
- Browser read/validate/save/re-read cycles cover every data-type row above.
  Server rejection is tested even when client checks are bypassed.
- An accepted edit changes the selected file and survives backend restart.
  Tracked examples remain unchanged; unrelated file bytes/comments/placeholders
  remain identical. Pure validation and failed pre-commit edits leave bytes
  unchanged. Post-commit faults follow the explicit committed-state contract.
- Invalid descriptors, intentional metadata, unknown-property diagnostics,
  and strict development mode are exercised without executing custom data.
- Two browser sessions demonstrate revision conflict handling: the second stale
  save does not overwrite the first, and its unsaved text remains available.
- Automated service/store/HTTP tests and browser integration tests pass, including
  source-preservation fixtures, fault/conflict cases, and demo security checks.
  Test sizes/limits use the explicit Q09/Q10 values, not unmeasured claims.
- UI distinguishes persistence from application state. A demo-file edit does not
  claim to reconfigure a host or change the listening port.
- Tests run in isolated temporary state; runtime files remain ignored. Commands
  and results are documented for reproducible standalone use.

M1 excludes host integrations, MCP, production/public deployment, generated
universal editors, batch/delete/append/list reordering, and AI model/agent
execution. It includes the real shared core and safety guarantees, not a throwaway
mock editor that will be replaced for host use.

### Phase 2 / M2: Reusable distribution and shared integrations

Prerequisite: M1 accepted; resolve the phase-2 portions of Q11/Q13.

- Stabilize the public package/API and versioned descriptor contracts.
- Package the embeddable UI and authenticated normal-mode HTTP adapter.
- Implement MCP tools with the same service semantics, validation, permissions,
  revisions, and error shapes.
- Publish controlled install/upgrade instructions and compatibility tests;
  never initialize or change user-managed Git tracking implicitly.

Exit: standalone and embedded test harnesses use the same library revision
unchanged; Python/HTTP/MCP parity and normal-mode authorization tests pass.
Host-specific integration work is still separate.

### Phase 3 / M3: Integrate host projects

Prerequisite: M2 accepted; resolve Q11/Q12 for each host.

- Integrate aidir first unless another order is explicitly agreed.
- Supply descriptors, host-owned adapters, compatibility resolver/layer policies,
  and at least one Markdown editing skill per host.
- Add aibt and sndbx with preserved loader shapes and override semantics.
- Inventory and explicitly migrate colloc's selected file-backed settings;
  Redis runtime distribution and session settings remain separate decisions.
- Test source/effective provenance, secret boundaries, stored/active state,
  masking, reload/restart, and failed application in each affected host.

Exit: each adopted host edits configuration through unchanged aiset modules,
with host regression tests and documented migration/application behavior.
Integrating one host does not require the others to be migrated simultaneously.

### Phase 4 / M4: Extended editing capabilities

Prerequisite: relevant host/library baseline accepted; resolve Q14 per feature.
Add separately reviewed transactions, removal/append, identity-aware array edits,
preview/restore, generated forms, and subscriptions as prioritized.
Each feature must preserve the core comment/validation/permission guarantees
and have its own acceptance tests. This is not a mandatory all-at-once release.

### Phase 5: AI functionality, separately approved

Prerequisite: resolve Q15 and approve a concrete agent integration design.
Only then implement model connections, skill/context loading, invocation, tools,
approval, and auditing through the established editing APIs.
No AI runtime work is authorized by the current specification-preparation task.
