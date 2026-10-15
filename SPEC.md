# aiset: Shared Settings System Specification

Status: complete working specification; the design is settled (the discussion
register in section 16 is empty). Not yet implemented; preparation tasks are in
section 15. The service and transport interface is in SPEC_service.md.
Date: 2026-10-03.
Targets: aidir, aibt, sndbx, colloc, and other projects.
Project name: `aiset`. Initial location: `aidir/aiset/`; other hosts use
`src/aiset/` when they have a `src/` directory, otherwise `aiset/` at the root.

During specification development, this file is the sole editable specification
and contains the complete design, including all incorporated amendments.
After the specification is finalized, freeze it and rename it to `SPEC.md`.

The service and transport interface is specified separately in
[SPEC_service.md](SPEC_service.md). It is normative for the Python, HTTP, and MCP
interfaces, is used for host integration, and must be kept up to date as the
project evolves (its section 19 defines the change-control rule). Semantic rules
— descriptor grammar, storage, resolver, and security — remain in this document.

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

## 3. Library boundaries

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
| UI assets | Framework-independent path/value controls and optional best-effort browser validation. |

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
aiset is currently its own Git repository; a pinned submodule remains a
future delivery option.

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
  a   package built from the pinned revision. No particular Python import name is
  committed here.
- Host descriptors, real project configurations, and host integration state stay
  outside the submodule. Only the standalone demo uses library-local editable
  state by default.
- An unmanaged nested clone is not the recommended default: the parent otherwise
  cannot reliably reproduce which revision its installation uses.

The reusable architecture also permits distribution as a versioned package.
Repository placement must not become part of runtime semantics.

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

The standalone launch entry point is a plain Python script, `demo_app.py` (name
illustrative). It runs with no parameters and also accepts command-line
parameters:

```text
python demo_app.py
python demo_app.py --aiset.port:12345 --aiset.host:0.0.0.0
```

- It serves its bundled frontend/backend over plain HTTP (no TLS). The demo is
  an internal test project, so it performs no special security checks: no
  Host/Origin validation, no CSRF, and no CORS handling.
- It binds to `0.0.0.0` by default (security is not a concern for a test
  project), with an explicit startup override. A bind failure is reported rather
  than silently choosing another port.
- Command-line parameters override values from the demo configuration; the same
  keys (port, host, and others) can also be set in the configuration.
- It uses a shipped demo descriptor and a default editable configuration file at
  `.local/demo/config.json5`, resolved relative to the standalone checkout.
- It seeds that file from the tracked example only when the editable file is
  absent, and never replaces an existing user's edits on restart.
- It accepts explicit config/descriptor/state-directory overrides, so tests can
  use isolated temporary directories and installed packages do not need a
  writable package directory.

Demo startup reports a clear error if initialization is required but the
selected location is not writable; it does not choose a hidden fallback path.
The library repository's own `.gitignore` excludes `.local/`, lock files,
temporary files, and backups in its designated runtime locations. Tracked
examples and test fixtures are never edited by the running backend. Ordinary
hosts use their own registered paths instead of this default.

The demo configuration is just a file. It has no associated project user,
account database, host service, Redis instance, external credentials, or
authentication configuration. Demonstration examples avoid required environment
variables and external dependencies. Local environment/template tests inject
their own resolver mapping. Operations are audited under an explicit local-demo
principal, not a fabricated authenticated user.

Command-line parameter convention. A parameter has the form `--<path>:<value>`,
where `<path>` is a dotted configuration key path and `<value>` is parsed with
the same rules as `value_text` (section 5.3): strings are quoted and bare tokens
are parsed as JSON5 values. Examples: `--aiset.port:12345`,
`--aiset.host:"0.0.0.0"`, `--logging.level:"debug"`. Parameters override the
corresponding configuration values. Any aiset-based standalone entry point may
use this convention.

The frontend initially supplies the read/validate/set controls from section 9,
not a universal editor. Demo writes change only the selected file and the
library's settings snapshot; they do not run commands or apply host services.
Application status follows the same contract as other integrations and must
not imply a host runtime was reconfigured.

### 3.4 Python execution environments

Use two environments with the same aiset package and implementation:

- **Normal embedded operation:** install aiset into the host project's virtual
  environment and run it with that environment's Python interpreter. The host
  controls environment provisioning and dependency resolution.
- **Standalone testing/development:** when needed, explicitly create `.venv/`
  inside the aiset checkout and install aiset there, together with the optional
  standalone web and development/test dependencies. Use it for automated tests
  and the autonomous demo editor on default port 8383.

The local environment is optional and created on demand by a developer or an
explicit setup command/script, not by importing or starting the library.
aiset must not activate, create, switch, or repair environments automatically.
Launch/test commands must select the intended interpreter explicitly rather
than rely on an incidental shell activation or silently fall back to host/system
Python. The chosen environment does not select the application's runtime mode.

The local `.venv/` serves only the standalone test/demo project. It is never
used for host integration, which always runs in the host's own environment.
Selecting the local environment does not enable demo mode, and enabling demo
mode does not require the local environment.

Both environments install the same package through its declared metadata;
no copied modules, environment-specific implementation, or `sys.path` patches.
Editable installation is appropriate for development; hosts may install the
package built from their pinned library revision.

Declare core dependencies separately from optional HTTP/web, MCP, and
development/test tooling. Embedded users need only their selected integrations.
Resolve compatible dependencies in each environment; a conflict with host
dependencies must be reported, not solved by silently upgrading the host or
switching to the local environment. Exact extras, supported Python versions,
and reproducible installation tooling are M1 implementation details (section 17).

The local `.venv/` is a lightweight test/development convenience, not a production
deployment or a security sandbox. It requires no additional account system or
special environment-hardening subsystem. The demo execution model (section 3.3)
does not depend on which virtual environment runs the backend.

Test standalone operation in the local environment and embedded compatibility
in representative host environments. Keep `.venv/` out of version control;
dependency declarations and reproducibility files belong to the project.

### 3.5 Release, versioning, and compatibility

- **Package version.** aiset is a single package versioned `major.minor.patch`.
  `major` changes on incompatible changes, `minor` on backward-compatible
  additions, `patch` on fixes. Descriptor semantics carry their own
  `descriptor_version` (section 4.6.1), independent of the package version.
- **Delivery.** A host adds aiset as a Git submodule in its own directory. A host
  checkout must clone and initialize the submodule (for example with
  `--recursive` when needed). Installs use the package built from the pinned
  commit; no host installer rewrites library source.
- **Compatibility.** aiset aims for backward compatibility. A host declares the
  minimum aiset version it requires and checks at startup that the installed
  version is not lower; a lower or otherwise incompatible version fails with a
  clear compatibility error rather than changing behavior silently.
- **Upgrades.** Upgrading is a deliberate bump of the pinned submodule commit
  followed by the host's compatibility tests. Installs and startups never follow
  a moving upstream branch or update aiset automatically.
- **Migrations.** Descriptor and configuration migrations are explicit,
  multi-step, and non-transactional: each step is an independent `set`, and a
  failure recovers through the Last Known Good configuration (section 14.8).
  Migrations are never applied silently (section 4.5).
- **Field names.** Configuration field names are unrestricted; no field name is
  reserved (section 4.6.3).
- **Project metadata.** Descriptor keywords are reserved as node properties;
  project metadata uses the `x_<project>` namespace and must not override a
  recognized keyword (section 4.5).
- **Compatibility fixtures.** The library owns generic/shared fixtures; each
  host owns its host-specific compatibility tests. One library revision must be
  tested against multiple host adapters without source changes (sections 3.1
  and 12).

### 3.6 aiset's own configuration

Besides the host's project configuration, aiset has its own settings. They live
in a dedicated aiset configuration document (with its own descriptor and file),
separate from the host's project configuration, and cover:

- the AI block (section 14.7);
- the backup-chain depth for Last Known Good (section 14.8.1; default 5);
- conflicted-backup retention (section 10.4; default 5, minimum 1);
- numeric operational limits (section 11) and the symlink option (default
  allowed);
- the external re-read timer (section 10.4; disabled by default);
- the common callback/hook timeout (sections 10.3 and 19; default 30 seconds);
- logging level and sink (section 20);
- demo port and host for the standalone entry point (section 3.3).

These settings use a normal aiset descriptor and can be read and edited through
the same service, HTTP/MCP surface, and UI as any other document. The host
supplies the path to this document when it registers aiset, or relies on the
standalone defaults.

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
| `ui` | Optional presentation overrides for the standard node control; see section 18. |
| `helper` | Optional registered micro-form/wizard for creating or editing a node; see section 18. |
| `hooks` | Optional bindings to the fixed host lifecycle events in section 19. |

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
are rejected in v1 so values stay portable over HTTP and for JavaScript-based
clients.
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
between definitions are errors, not last-writer-wins overrides: two fragments
(or templates, 4.6.10) that define the same field or name incompatibly are a
descriptor (schema) error. Such conflicts are detected when descriptors are
loaded and composed, before any request is served, so they surface during
development or at startup and are never silently resolved in production.
Descriptor composition is local and trusted; clients cannot load remote
descriptors or Python code.

Composition is explicit. A host registers a list of descriptor fragments, each a
descriptor file plus a mount path into the base descriptor, for example:

```json5
{ descriptors: [ { file: "modules/monitoring/descriptor.json5",
                   mount: "/root/children/monitoring" } ] }
```

The same list may be supplied through a documented registration API. There is no
convention-based discovery of host files. During composition each fragment's
`root` node is attached at its mount path. A descriptor mount attaches schema;
this is distinct from a Config's data mount (section 10.2), which attaches
values.

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

Configuration field names are data, not descriptor keywords, and are never
reserved (section 4.6.3): a field named `type`, `id`, `children`, or any other
keyword is expressed through a `children` label or a child `id`. Descriptor
keywords remain reserved only as node properties; project metadata must not use
a recognized keyword as its property name.

Keep a lossless/raw descriptor representation available to trusted host code,
separate from the compiled shared descriptor. Unknown properties are retained,
not stripped from the host's descriptor file or rewritten on load.
The generic browser/HTTP descriptor export contains recognized, authorized
properties only. A host wanting its own metadata in a UI supplies a separate
explicitly authorized export; arbitrary metadata must not leak by default.
The descriptor revision covers the complete source, including project metadata.

Provide a public `validate_descriptor` development operation, plus a CLI
interface so it can run without starting a backend or loading project settings
(the exact command and output are specified in
[SPEC_service.md](SPEC_service.md) section 12).
It is distinct from validating a candidate configuration value:

- Validate syntax, supported descriptor version, and all recognized definitions.
  Unsupported values of known properties, such as `type: "intr"`, remain errors.
- Report every unknown descriptor property with a stable issue code
  `UNKNOWN_DESCRIPTOR_PROPERTY`, severity, JSON Pointer to the property, and
  source line/column when available. Do not include its potentially secret value.
- Traverse the recognized descriptor structure, including every `children`
  node, `children_options` item, and `additional_children` node.
- A key under an object's `children` mapping is a label (the configuration field
  name when the child has no `id`), not a descriptor keyword. A child's `id`,
  when present, is the configuration field name and is a recognized property. Do
  not report labels as unknown properties. Similarly, object keys in literal
  `default`, `enum`, or `const` values are data.
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

### 4.6 Complete descriptor grammar

This is the consolidated descriptor grammar. It restates and formalizes the node
rules from 4.2-4.3 together with the structured `env`/`ui`/`helper`/`hooks`
shapes from sections 6, 18, and 19, and is authoritative for the grammar. The
surrounding subsections remain motivation, examples, and semantics.

#### 4.6.1 Authoring and envelope

A descriptor is authored as JSON5 (a superset of strict JSON) and exported to
the browser as strict JSON. Envelope properties:

| Property | Value type | Required | Meaning |
|---|---|---|---|
| `descriptor_version` | string | yes | Recognized value `"1.0"`; unsupported values fail with a compatibility error. |
| `project` | string | no | Project identifier, informational. |
| `config_version` | string | no | Independent of `descriptor_version`; corresponds to the project config `version`. |
| `root` | object node | yes | The configuration root; always an `object`. |

The descriptor has its own revision, separate from configuration documents.

#### 4.6.2 Node grammar

A node is a JSON object with a required `type` and optional constraint/presentation
properties:

```text
node      := { "type": node_type, <properties>* }
node_type := primitive | template_name
primitive := "string" | "int" | "number" | "bool" | "null"
           | "object" | "array" | "union"
```

`type` is a primitive or the name of a template (4.6.10).

Recognized node properties:

| Property | Value type | Applies to | Meaning |
|---|---|---|---|
| `description` | string | any | Documentation text. |
| `title` | string | any | Future UI label. |
| `required` | bool | any | Presence required; default `false`. Missing and explicit `null` differ. |
| `nullable` | bool | any | Permit `null` in addition to the declared type; default `false`. |
| `default` | any | any | Effective value for an absent optional field; never written to source. |
| `enum` | array | any | Allowed values, compared without implicit type conversion. |
| `const` | any | any | One fixed value, compared without implicit type conversion. |
| `minimum`, `maximum` | number | int/number | Inclusive numeric bounds. |
| `min_length`, `max_length` | int | string | String length bounds. |
| `pattern` | string | string | Portable regex subset. |
| `min_items`, `max_items` | int | array | Array size bounds. |
| `unique_items` | bool | array | Type-aware structural equality. |
| `children` | object or node | object/array | See 4.6.3. |
| `id` | string | children entry | Configuration field name of this child; defaults to the `children` key. See 4.6.3. |
| `children_options` | array of nodes | array/union | See 4.6.3. |
| `additional_children` | node | object | Values of undeclared (dynamic) keys. |
| `key_pattern` | string | object | Portable regex constraint on keys governed by `additional_children`. Mutually exclusive with `key_enum`. |
| `key_enum` | array of strings | object | Explicit list of allowed key names for `additional_children`. Mutually exclusive with `key_pattern`. |
| `env` | object | any | Placeholder policy; see 4.6.4. |
| `secret` | bool | any | Sensitive subtree, inherited by descendants. |
| `read_only` | bool | any | Reject edits, inherited by descendants. |
| `apply` | string | any | `live`, `reload`, or `restart`; inherited from the parent node, root default `restart`. |
| `validators` | array of strings | any | Host-registered server-side validator IDs. |
| `ui` | object | any | Standard-control override; see 4.6.5. |
| `helper` | object | any | Micro-form/wizard binding; see 4.6.5. |
| `hooks` | object | any | Lifecycle hook bindings; see 4.6.5 and 4.6.6. |
| `typedef` | string | any | Declares this node as a named template; usable as a `type` elsewhere. See 4.6.10. |

Any other property is project metadata: ignored at runtime, retained for hosts,
reported by diagnostics (section 4.5). It must not override a recognized name.

#### 4.6.3 Structural rules by type

Object:

- `children` maps a label to a child node. A child's configuration field name is
  its `id` when present, otherwise the label. Labels are internal and are never
  descriptor keywords; any string is allowed as a field name (through the label
  or `id`), so no field name is reserved.
- Effective field names must be unique within one `children` mapping; a
  duplicate (after applying `id`) is a descriptor error. Labels are unique by
  JSON object rules.
- `id` is meaningful only as a direct entry of an object's `children` mapping;
  it is rejected in array items, `children_options` items, `additional_children`
  values, and the root.
- `additional_children` describes values of every key not listed in `children`.
  When absent, undeclared keys are rejected in strict mode.
- `key_pattern` (a portable regex) or `key_enum` (an explicit list of allowed
  key names) constrains keys governed by `additional_children`. The two are
  mutually exclusive: specifying both is an error. With neither, every
  previously undeclared key is allowed in strict mode.
- `key_enum` is meaningful only with `additional_children`; without it, the
  property is rejected.

Example of child naming:

```json5
{
  type: "object",
  children: {
    // Field name is "host" (the label is used as-is).
    host: { type: "string" },
    // Field name is "type"; the label is only an internal name.
    field_type: { id: "type", type: "string", enum: ["text", "image"] },
  },
}
```

Array:

- Exactly one of `children` (one node describing every item) or
  `children_options` (a nonempty array of alternative item nodes) is required.
  Presenting both, or neither, is invalid.
- An item is valid if at least one option validates; matching more than one
  option is not an error.

Union:

- Only `children_options` is used, and it must be nonempty. A value is valid if
  at least one alternative matches; matching more than one is not an error.
  This is not JSON Schema's exclusive `oneOf`.

Mutual-exclusion and placement rules:

- `required` with `default` is invalid: required means explicitly present.
- `enum` with `const` is invalid: one fixed value cannot also list alternatives.
- Scalar constraints must match the node type: `minimum`/`maximum` only for
  `int`/`number`; `min_length`/`max_length`/`pattern` only for `string`;
  `min_items`/`max_items`/`unique_items` only for `array`.
- `children`, `children_options`, `additional_children`, `key_pattern`,
  `key_enum`, and `id` are rejected on scalar types. `id` is accepted only as a
  direct child entry of an object's `children` mapping.

#### 4.6.4 `env` policy

```text
env := { "allowed": bool,              // default false
         "convert"?: "string" | "int" | "number" | "bool" }
```

- `allowed: false` disables placeholder resolution: placeholders inside strings
  stay literal text, and an unquoted placeholder at the node is invalid.
- `allowed: true` enables the resolver policy in section 6.
- `convert` applies only to whole-value placeholders; `"string"` means no coercion.
- Boolean conversion accepts only `true`/`false`; numeric conversion rejects
  empty, nonfinite, and out-of-range values.

#### 4.6.5 `ui`, `helper`, and `hooks` shapes

Sections 18 and 19 remain the detailed contracts; this fixes only the syntactic
shape required to validate a descriptor.

```text
ui := {
  "label"?, "group"?, "order"?, "help"?, "widget"?, "rows"?,
  "placeholder"?   // presentation only
}

Placeholder text is shown inside an empty input field; it does not affect
validation or stored values and is plain text, not HTML.

helper := {
  "tag": string,                       // selects a trusted UI registry entry
  "actions": ["create" | "edit"]+,     // nonempty subset
  "presentation": "modal" | "wizard",
  "settings"?: object                  // tag-specific, JSON-compatible
}

hooks := {
  <event>: [ binding, ... ]            // event is a fixed name, see 4.6.6
}
binding := { "tag": string, "scope"?: "node" | "subtree", "settings"?: object }
```

#### 4.6.6 Fixed hook event names

The only valid `hooks` keys are `before_create`, `before_update`, `after_create`,
and `after_update`. An unknown key is an invalid binding and is rejected, not
treated as project metadata. Semantics are defined in section 19.

#### 4.6.7 Value typing and numeric range

- `bool` is not an integer, including in Python.
- `number` accepts finite integers and finite floating-point values; `int`
  accepts mathematical integers.
- All integer-valued inputs must lie within `[-9007199254740991, 9007199254740991]`;
  larger integers, NaN, and Infinity are rejected so Python, HTTP, and browser
  validation agree.

#### 4.6.8 Reserved descriptor names

Descriptor keywords are reserved as node properties: the property names in
4.6.2, the envelope keys in 4.6.1, and the sub-keys in 4.6.4-4.6.6 must not be
reused as project metadata on a node. Configuration field names are not
descriptor keywords and are never reserved (4.6.3): a field named after any
keyword is written through a `children` label or a child `id`. Custom project
data lives under an `x_<project>` namespace (or its own opaque property).

#### 4.6.9 Grammar validation and diagnostics

`validate_descriptor` checks, in order:

1. JSON5/JSON syntax and the recognized `descriptor_version`.
2. Every recognized property's value type and allowed values (for example,
   `type: "intr"` is an error unless it names a defined template, 4.6.10).
3. The structural rules in 4.6.3, including that a literal `default` itself
   satisfies the node's constraints.
4. The structured shapes in 4.6.4-4.6.6.
5. Unknown-property reporting per section 4.5, traversing every `children` node,
   `children_options` item, and `additional_children` node. A key in a `children`
   mapping is a label or field name (4.6.3), not a keyword.

Default mode returns `valid: true` when recognized definitions are valid and
reports unknown properties as warnings; strict mode treats those diagnostics as
errors and returns `valid: false`. The CLI exit status is zero when `valid` is
true and nonzero otherwise. Resource and depth limits apply to the complete
descriptor, including opaque project metadata.

#### 4.6.10 Templates

A node may declare itself a reusable template by adding `typedef: "<name>"`. The
node keeps working at its own position; in addition, other nodes may reuse its
definition by setting `type: "<name>"`.

```json5
{
  type: "object",
  children: {
    port: {
      typedef: "service_port",
      type: "int", minimum: 1, maximum: 65535,
      description: "TCP port",
    },
    // Reuse the template; override the default only.
    http_port: { type: "service_port", default: 8080 },
    admin_port: { type: "service_port", description: "Admin TCP port" },
  },
}
```

Rules:

- Template names are collected across the whole descriptor, including composed
  fragments (4.3) and any typedef sources supplied when the Config is loaded
  (10.2). A name must be unique across all of them; a duplicate `typedef` name
  is an error (4.3).
- A template name must not be a primitive type name (`string`, `int`, `number`,
  `bool`, `null`, `object`, `array`, `union`); doing so is an error.
- A node with `type: "<name>"` resolves to the template's definition with the
  node's own properties applied on top (the node wins). Object `children` and
  `children_options` merge by key (4.6.3); scalars, arrays, `default`, and
  `const` are replaced by the referencing node when present.
- A template may reference another template; cycles are an error.
- `typedef` is a property of the declaring node only; it is not carried into a
  referencing node.
- Templates are authoring sugar: on compilation a reference is expanded, so the
  runtime descriptor and all validation behave as if the definition were written
  inline.
- `validate_descriptor` reports an unknown `type` name, a duplicate `typedef`, a
  cyclic reference, and a name that shadows a primitive as errors.

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
6. When configured and supported, run the before hooks from section 19 against
   the validated candidate, then verify its captured revisions before commit.
7. Persist once, publish the new stored snapshot, apply the host policy, run
   configured after hooks, and report persistence/application/hook outcomes
   separately.

Existing invalid fields do not become valid simply because they were untouched.
During migration, an explicit inspection-only compatibility mode may retain
unknown fields and report descriptor gaps. Writes remain disabled until the
editable document has complete strict descriptor coverage.

Deletion, array insertion/removal, batch edits, and full-document editing are
later operations (section 5.3.6). Existing aidir editors must remain available
during the transition; their adapters must not claim the new preservation
guarantee until they use the new store.

### 5.3 Path and edit semantics contract

This is the consolidated path/edit contract. It formalizes the canonical path
and read/set semantics from 5.1-5.2 together with the comment-preservation edit
rules from section 7.1, and enumerates the composite edits M1 accepts. It is
authoritative for the contract.

#### 5.3.1 Canonical path

A path is a JSON Pointer used identically by Python, HTTP, MCP, and the UI.

```text
pointer := "" | "/" segment*
segment := <unquoted characters> where "~" -> "~0" and "/" -> "~1"
```

- `""` denotes the root; in the first editor the root is read-only.
- A numeric segment addresses an array index only when the current node is an
  array; otherwise it is an ordinary object key (for example, object key `"0"`
  remains a key).
- Dots are ordinary characters and need no escaping.

Distinct error conditions:

| Condition | Result |
|---|---|
| Malformed escape (`~` not followed by `0` or `1`) | path error |
| Negative or out-of-range array index | path error |
| Missing parent along the path | error |
| Undeclared path (no descriptor coverage) | not found / validation error |
| Array append marker `-` | unsupported in v1 |

#### 5.3.2 Read (`get`)

- Two authorized views: `source` (exact source fragment, including comments and
  placeholder text) and `effective` (resolved/defaulted/merged value).
- Absent permitted optional leaf: `exists: false`, no `value_text`.
- Explicit `null`: present, returns `"null"`.
- An effective `default` never masquerades as a stored value.
- Root read is allowed; it is the only operation on the empty pointer in v1.

#### 5.3.3 Set one value

`set` replaces the addressed value; it does not recursively merge an object.

- May create an absent optional leaf when its parent already exists and the
  descriptor permits the field or dynamic key.
- Does not create missing parents.
- Setting an array element requires an existing index.
- Input `value_text` contains exactly one JSON5 value (or one whole-value
  template); strings must be quoted; trailing executable text or a second
  document is an error.

#### 5.3.4 Accepted M1 edits

M1 accepts exactly these single-field replacements:

| # | Edit | Requirement |
|---|---|---|
| 1 | Scalar leaf (string/int/number/bool/null or whole-value template) | Replace value tokens only; surrounding/inline comments unchanged. |
| 2 | Create absent optional leaf | Parent exists; new leaf follows local indentation/newline conventions. |
| 3 | Object replacement | See object rule below. |
| 4 | Array element by index | Edit one existing element in place; other elements untouched. |
| 5 | Equal-length array replacement | Element-wise value edit; see array rule below. |

Object replacement rule:

- For every commented named child of the current value, the submitted value must
  contain a child with the same name and the same structural type
  (scalar/object/array); its value may change.
- Comment-free children may be added, removed, or reordered.
- Deleting, reordering, or changing the structural type of a commented child is
  rejected.

Array replacement rule (whole array):

- The submitted array must have the same length; each element keeps its own
  comment trivia (a value-only edit per element).
- Inserting, deleting, or reordering elements that carry comments is rejected.

#### 5.3.5 Comment-conflict rejection

When a composite replacement cannot preserve comment attachment, the operation
fails with `COMMENT_PRESERVATION_CONFLICT` and leaves the document byte-for-byte
unchanged. There is no force-write escape hatch in v1.

- Internal comments inside submitted `value_text` are added only when their
  attachment is unambiguous; otherwise the operation is rejected.
- Comment-free portions of a replaced subtree may be reformatted.

#### 5.3.6 Out of scope for v1

Deletion, array append/insert/remove, batch edits, and full-document editing are
later operations, not part of this contract. When implemented, they are carried
out as independent sequential operations: v1 provides no multi-operation
transactions, no cross-operation locking, and no all-or-nothing atomicity. A
failed or partially applied sequence is recovered by loading the Last Known Good
configuration (section 14.8), not by rollback. Existing aidir editors remain
available through compatibility facades and must not claim the preservation
guarantee until they use the new store.

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

Resolver policy (decided; one global policy for every host):

- **Precedence**, highest first: explicit host overrides, then the process
  environment, then a supplied `.env` mapping, then the placeholder's inline
  default, then the descriptor/config `default`. A value supplied by `.env`
  wins over the config `default`.
- **`:-` uses POSIX shell semantics** (the only supported operator in v1):
  - `${VAR}` substitutes the variable's value; if the variable is unset or
    empty, the result is the empty string.
  - `${VAR:-default}` substitutes the variable's value, or `default` when the
    variable is unset or set to the empty string.
- Substitution is single-pass; environment values are data, not nested templates.
- No `eval`, shell interpolation, or textual insertion of environment values
  into reparsed JSON5.
- String interpolation preserves quotes, slashes, Unicode, and newlines safely.
- Whole-value numeric/bool placeholders use explicit descriptor conversions
  (`env: { allowed: true, convert: "int" }`). Boolean conversion accepts only
  `true` and `false`; numeric conversion rejects empty, nonfinite, and
  out-of-range values. Ordinary strings are not coerced.
- In v1 an environment variable cannot inject an object, array, key, or comment.
- Placeholder resolution is disabled unless the node's `env.allowed` is true.
  Disabled placeholders inside strings remain literal text; unquoted placeholders
  at such a node are invalid. This is the only literal/escaping mechanism in v1.
- Tests supply their own resolver mapping through the `load`/`get` API; results
  must not depend on the developer's process environment.

The policy is global: exactly one resolver order and one `:-` semantics apply
to every host. Hosts whose current behavior differs (for example, aibt consults
`.env` before the process environment; sndbx reverses that) must be brought into
line during integration, following the steps in README.md. Legacy precedence is
not preserved as a runtime profile. Environment values must never alter source
structure; configurations that relied on structural injection require an
explicit migration, not a silent reinterpretation.

The browser must never receive environment values to validate placeholders.
The browser's checks, when implemented, are a best-effort first filter: local
structural results are advisory and environment/semantic checks require server
validation. A host UI may skip local checks entirely. Server validation is
always authoritative and re-runs the full pipeline regardless of what the
client reported.

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

The editable document must be valid JSON5 (or a JSON5 template, section 6).
Comments are part of the document and are preserved, never regenerated. Every
comment has an owner, determined by where it sits relative to the surrounding
elements:

- **Leading (preceding) comment:** begins on its own line and stands before an
  element. It belongs to the element that follows.
- **Trailing (following) comment:** follows an element or its closing brace on
  the same line. It belongs to the element or block it follows.
- **Block-end comment:** begins on its own line before a block's closing brace.
  It belongs to the whole block and keeps its position at the end of that block.
- **Document comment:** a leading comment before the root object belongs to the
  whole document.

A comment is deleted only when the element or block it belongs to is deleted.
An edit that would leave a comment without an unambiguous owner is rejected.
Ownership is positional, so any later operation that moves an element (for
example, array reordering) must move its attached comments with it.

```json5
// Document comment (belongs to the whole document).
{
  // Leading comment for element1.
  element1: 124, // Trailing comment for element1.
  element2: { // Trailing comment for element2.
    // Leading comment for element3.
    element3: 123, // Trailing comment for element3.
    // Leading comment for element4.
    element4: 111 // Trailing comment for element4.
    // Block-end comment for element2 (kept before the closing brace).
  } // Trailing comment for element2's closing brace.
}
```

This example is a required source-preservation fixture: a read with no edit
must return it byte-for-byte unchanged, and scalar edits must not disturb the
surrounding comment classification.

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
cross-language runtime requirement are settled by the parser feasibility check
(section 15).

### 7.3 Revisions and durable writes

Every source read returns an opaque revision for that document. It changes on
any byte change, including comments/whitespace. The descriptor has a separate
revision. Writes require both revisions; absence is not an unconditional write.
Resolver inputs, layers, and hook registrations are server-owned state. The
server captures their internal revisions when preparing each candidate and
verifies the same snapshot before commit; clients do not send those internal
revisions. If any captured state changes, the operation fails with
`REVISION_CONFLICT`.

Configured before hooks run on an immutable prepared candidate before acquiring
the persistence lock. The candidate, descriptor, layers, and hook registrations
have captured revisions; stale snapshots cause a conflict, not a blind retry.
Hooks must never execute while holding the file lock.

Within a bounded cross-process lock on a stable sidecar lock file:

1. Re-read the file and compare revisions.
2. Build and validate the candidate using a captured resolver/layer snapshot.
3. Verify registered layer/descriptor/hook-registry revisions are still current.
4. Write a uniquely named temporary file in the same directory, retaining
   restrictive file permissions and required ownership.
5. Flush and synchronize it; atomically replace the target and synchronize the
   containing directory.
6. Publish the new stored revision; remove temporary files on failure.

Lock acquisition is bounded by a timeout with a comfortable margin over typical
lock hold times: default 5 seconds, configurable. Lock timeouts, conflicts, parse
errors, and persistence failures have distinct error codes. File-permission
retention is not enforced or checked in the first version.

Durable write failures are retried a bounded number of times: three attempts with
a short backoff. After the final failure the library logs an `ERROR` (section 20)
and stops; it does not loop or guess. A failure after the atomic replacement must
report the known committed state rather than claim the file was untouched. The
commit-state report has the form:

```json
{"document": "main", "committed": true,
 "revision": "new-or-previous-revision", "uncertain": false,
 "detail": "atomic replace completed; directory sync failed"}
```

`committed` states whether the new content is known to be on disk; `uncertain`
marks a result that cannot be determined without a re-read (the caller should
re-read); `detail` is a sanitized explanation. The lock file is not the replaced
configuration inode.

All library writers must cooperate with the lock. Arbitrary editors that ignore
it can still race filesystem replacement; this limitation must be documented,
and deployments requiring strict guarantees must route writes through the store.
External edits are detected on the next re-read, on a periodic check, or before
a save (section 10.4): a valid external edit is adopted through the normal
validation and callbacks; an invalid one is restored from the last validated
version rather than replacing it with stale in-memory data.

Backups are optional, private, bounded by an explicit host retention policy, and
outside public/static directories. A backup failure under a required-backup
policy aborts before commit. Backup rotation itself must not lose comments.

## 8. Unified service and transport contract

The authoritative Python/HTTP/MCP interface — signatures, authorized views,
request/response/error envelopes, revision transport, optional-field results,
and the descriptor-validation CLI — is specified in
[SPEC_service.md](SPEC_service.md). That document is normative for the interface
and must be kept in sync with the implementation as the project evolves. This
section describes the shared semantics behind it.

### 8.1 Library operations

| Operation | Input | Output |
|---|---|---|
| `load` | Registered document ID and host resolver/layer policy | Validated effective snapshot, source revision, descriptor revision, provenance. |
| `get` | Document ID, pointer, authorized view | Source fragment or effective value, revisions, field metadata/provenance. |
| `validate` | Document ID, pointer, `value_text`, expected revisions | Candidate validation issues and whether the proposed edit can preserve source. No writes or live changes. |
| `set` | Same inputs as validate plus principal | Stored revision, validation result, and application status. |
| `descriptor` | Document ID and principal | Authorized strict-JSON descriptor and its revision. |
| `validate_descriptor` | Descriptor source and diagnostic mode, without a host/config file | Validity and descriptor issues, including unknown-property locations. |

Validation and set use the same candidate pipeline. Set prepares and validates
its own candidate, including configured before hooks, even after an earlier
successful validation. Under the write lock it verifies captured revisions and
reparses/revalidates the exact candidate without invoking hooks again. A changed
snapshot fails with a conflict rather than reusing an obsolete hook decision.
Effective snapshots are isolated from caller mutation. Hook-capable async/sync
dispatch and result reporting are defined in section 19.

### 8.2 Minimal HTTP routes

The mount prefix is configurable; `/api/settings` is illustrative.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/settings/descriptor?document=main` | Descriptor used by the browser. |
| GET | `/api/settings/value?document=main&path=/logging/level&view=source` | Read one field/subtree. |
| POST | `/api/settings/validate` | Validate one proposed set operation. |
| POST | `/api/settings/value` | Persist one proposed set operation. |
| POST | `/api/settings/load/lkg` | Load the newest valid LKG without replacing the current file. |

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
`apply_failed`. The required level comes from the `apply` policy of the changed
paths (most restrictive affected wins, including removed descendants): a change
that affects only `live` elements requires neither reload nor restart and never
reports `reload_required` or `restart_required`, regardless of whether a host
callback is registered. `reload_required` and `restart_required` therefore come
from the policy, not from the presence of a callback; `applied` means the change
was applied live by a host callback or needed no live application. For a
committed write whose callback fails, return `stored: true` and `apply_failed`
with an explicit application error; do not return a generic write failure that
encourages blind retries.

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

The standalone server uses the same service interface. In normal mode the host
supplies authorization; aiset does not define it (section 11). The account-free
exception is explicitly selected demo mode (section 3.3): a plain internal test
app over HTTP with no security checks. Mounting inside an existing server is the
preferred host integration; autonomous demo operation is also a first-class use
case.

### 8.3 MCP

Register `settings_get`, `settings_validate`, `settings_set`,
`settings_descriptor`, and `settings_load_lkg`, with the same
document/path/value/revision inputs and result shapes as HTTP
(SPEC_service.md section 11). The descriptor can also be an authorized resource.

MCP tool schemas describe request envelopes, not a second project configuration
schema. Application validation failures use MCP's error-result mechanism
(`isError: true`) while retaining the shared error code/issues in structured
content. A committed set with `apply_failed` retains its explicit stored status.

Write tools are independently permissioned and may be disabled. They must not
inherit write permission merely because the caller can invoke an inference
endpoint or another MCP tool.

## 9. First reusable UI

Distribute ready-to-include JavaScript assets plus helper functions that return
HTML fragments. The goal is the most compact possible host integration: the host
includes the shipped JS files (or obtains the include string from a helper) and
calls a function such as `render_node_editor(document, path)` or
`render_full_editor(document)` where the editor should appear; the function
returns an HTML fragment to insert. The host supplies the API base URL (or
transport callbacks) and the document ID. No framework, build step, or CDN is
required, and the host may supply its own authentication wrapper around the API
calls.

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

Use a real JSON5 parser, not `eval`, in the browser. Render configuration and
descriptions through text controls, never untrusted HTML. No framework/global
CSS dependency and no CDN dependency are required. If the browser parses source
at all, it must accept template tokens (`${VAR}`, `${VAR:-default}`) as opaque
text and must not resolve them.

Browser-side validation is optional and minimal, a best-effort first filter that
only avoids needless round-trips. It may perform a few rough checks (for example,
obvious syntax errors or a missing required field) or none at all. It is never
authoritative. aiset can also be driven through another UI over its HTTP API,
so correctness must not depend on any browser check. The server always
re-validates every candidate with the full descriptor, resolver, and semantic
rules, and its result is the only one that counts. Browser checks are advisory:
they must not block a submission that the server would accept.

Full config viewing, generated forms, tree navigation, completion, specialized
secret widgets, deletion, and list-reordering UI are outside the first editor.
Existing aidir raw/logging controls are not removed by aiset.

## 10. Layers, provenance, and live application

The loader can produce one uniform effective object without owning the host's
runtime lifecycle. Every effective value should expose its origin to authorized
diagnostic callers: source file, default, environment reference, or override.
Environment diagnostics expose variable names, not secret values.

Layer order is host-defined and versioned. aiset provides a merge operation
(section 10.1) implementing recursive-object merge with whole-array replacement;
this matches the existing aidir-style component rule and is the recommended way
to assemble layers and component configuration. The shared field `set` operation
itself is replacement, not that merge operation.

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
changed paths. Store revision and active revision remain distinct: `stored_revision`
is what aiset wrote, and the host owns the active revision; aiset reports what the
application callback returns and does not persist it by default.
The most restrictive affected `apply` policy wins. Structural changes include
removed descendants when calculating that policy.
Cross-process distribution, acknowledgements, and rollback are host concerns
until a separate contract is agreed.

After hooks observe the committed change and its application outcome; they do
not replace or invoke the application callback a second time. Hook completion
does not imply that a setting requiring reload/restart has become active.

Change subscriptions. A host can register callbacks subscribed to specific
document paths; when a committed change touches a covered path, the library
calls the callback with immutable old/new snapshots and the changed paths so the
host can re-read and reapply. Subscriptions are in-process and after-commit,
like the application callback; cross-process delivery, acknowledgements, and
durability remain host concerns. The web UI uses polling in the first version;
server-push is not provided initially. Registration and delivery are specified in
[SPEC_service.md](SPEC_service.md).

### 10.1 Merge contract

aiset provides a pure merge operation for assembling configuration from a base
and an update. A host may merge on its own; aiset supplies the tool. Merge
operates on parsed configuration values, not on source text: it does not touch
comments, revisions, or the store, and it is independent of `set` (which is
replacement, not merge).

```python
merge(base, update) -> merged
```

Rules:

- Exactly two inputs: a base and an update. The update has priority.
- The update may be a partial configuration and may target any node or section
  of the base.
- The algorithm is recursive. For each field present in both values:
  - if both values are objects, merge them recursively by these rules;
  - otherwise (scalars, arrays, `null`, or a type mismatch) the update replaces
    the base value; arrays are replaced in full, not element by element.
  Then fields present only in the update are added, and fields present only in
  the base are kept unchanged.
- Consequently, in this version an update cannot delete a base field; it can
  only overwrite it (for example, replacing an object with `null` or another
  scalar).
- Merge is deterministic and returns a new value; it does not mutate its inputs.
- Merging several updates requires a single base; the host applies the updates
  in sequence (`merge(merge(base, u1), u2)`). Chaining is the host's
  responsibility; aiset provides only the update-onto-base operation.

Merge is independent of layers and provenance: it produces values, and the host
decides which value is the base and which is the update. The optional HTTP/MCP
form is specified in [SPEC_service.md](SPEC_service.md).

### 10.2 Config object model

Hosts work mostly with Config objects rather than raw dictionaries. A Config
object carries both data and the metadata needed to combine, track, and apply
it.

- **Creation.** The host asks aiset to build a Config from a file, optionally
  targeting a place in a base and optionally supplying additional typedef
  sources (below). The object records its origin: the file, the load time, and
  its intended mount path.
- **Update.** `config.update(other)` produces a new Config by merging the update
  onto the base (10.1). The base is unchanged; the result carries the combined
  origin. Updates can be applied repeatedly, so changes are picked up while the
  host runs.
- **Host-managed layers.** The host decides which Config is the base and which
  are updates, and in what order. aiset provides creation, merge, and metadata,
  not a fixed layer policy.
- **Mount addressing.** A Config may target a place in the base, given as a
  path. Object paths use dotted names, for example `workers.myworker`. Array
  elements are addressed by an identity field, for example
  `workers.items.[id=myworker]`, selecting the element whose `id` equals
  `myworker`. Mount addressing is not a JSON Pointer: it is used only to place a
  Config when loading or merging (edits use JSON Pointer, section 5.3). It is
  also distinct from a descriptor mount (section 4.3), which attaches schema
  rather than values. The exact mount-string grammar and escaping are an
  implementation decision. Before publishing the Config API, the implementation
  must document one canonical grammar and test literal separators, zero
  matches, and duplicate identity matches; it must not guess ambiguous mounts.
- **Typedef sources.** Creation accepts an optional list of files whose
  `typedef` definitions (4.6.10) are added to the template registry together
  with the main descriptor. This keeps a component's template next to the
  component. Template names must be unique across the main descriptor and all
  sources; a collision is a descriptor error (4.3), reported before serving.
- **Metadata.** Subscriptions (SPEC_service.md section 13) and origin live in
  the Config metadata, so a Config can be handed around and re-applied when a
  change arrives. The serialized representation of origin/provenance is not
  fixed in the first version.

Example: when a new worker is added to aidir, its `typedef` stays in the
worker's own folder (encapsulation). The core collects the list of such
fragments and passes it when loading the main file, so the main descriptor can
use the worker's `type`:

```python
worker_sources = discover_worker_descriptors()   # e.g. workers/*/descriptor.json5
main = Config.load("config.json5", typedef_sources=worker_sources)
# main may now use `type: "worker"`, defined in a worker fragment:
#   workers: { items: { additional_children: { type: "worker" } } }
```

The Config object is the recommended host-facing surface; `merge`, `get`, `set`,
and `load` remain available. The constructor and methods are specified in
[SPEC_service.md](SPEC_service.md).

### 10.3 Save callbacks and rollback

A host may register callbacks that run around saving. The first version defines
two. Each receives the **full configuration**, before and after, not a branch:

- **`probe_changes`** runs before a candidate is persisted and may also be used
  for intermediate validation, so a save need not follow it. It receives copies
  of the configuration before and after the change and returns either `ok` or a
  rejection: the fields it did not accept together with a text explanation (the
  shared issue format, 7). On rejection aiset aborts the save and shows the
  error. It is the host's hook for validation beyond the descriptor and
  complements the `before_*` hooks (section 19) and the semantic validators
  (4.4).
- **`after_save`** runs after a durable commit, so the host knows the
  configuration changed and can re-read and reapply it.

Each callback may be registered as synchronous or asynchronous. For an
asynchronous `probe_changes`, aiset calls it with `await` and waits for the
decision before proceeding (section 19.4). Callbacks run after the file lock is
released. The common callback/hook timeout is 30 seconds by default and is
configurable in aiset's own settings. A host may register a shorter timeout for
an individual callback or hook, but not an unbounded one.

Order during a save:

```text
probe_changes -> descriptor before_* hooks -> validators/commit
              -> application callback -> descriptor after_* hooks -> after_save
```

Rollback is host-initiated: aiset never rolls back autonomously. If the host
decides, after applying, that a configuration must be reverted, it asks aiset to
do so and supplies a reason. Rollback shifts the backup chain down by one level:
it restores the newest valid `.back` as the current file and discards the
previously current file, so the last change is undone as if it had never
happened. aiset records an audit entry `rollback, reason = <reason>` and reports
`restart_required`. The host owns the decision, the reason, and the restart.

Cross-process notification is the host's responsibility, as with subscriptions
and the application callback; aiset provides in-process callbacks and revision
tokens only. A `probe_changes` timeout rejects the operation before persistence.
An application-callback timeout occurs after persistence and reports
`stored: true` with `apply_failed`. An `after_save` timeout also retains
`stored: true` and is reported as a callback failure; it never changes the
application result or rolls back automatically. Unknown late outcomes are
reported explicitly and are not retried blindly.

### 10.4 External edits and re-read

A configuration file may be changed outside aiset, so the stored revision and
the version in memory can drift. aiset therefore:

- exposes an operation to re-read a document and its layers on demand;
- may re-read periodically on a configurable timer (disabled by default; the
  host sets the interval in aiset's own settings);
- re-reads before any save.

On re-read, if the on-disk content differs from the in-memory version, aiset
treats it like a change made through the interface:

1. Each file must be valid JSON5 (or a JSON5 template) and pass its template's
   structural checks, even when a higher layer later overrides it.
2. The assembled result is validated (probe callbacks and validators run on the
   final configuration).
3. If validation succeeds, the new revision becomes current and the `after`
   callbacks are notified that the configuration changed.
4. If validation fails (a file is malformed or fails template checks), aiset
   does not adopt it. Before restoring the last validated version, aiset saves
   the rejected bytes without modification beside the document as
   `<filename>.conflicted.<datetime>.back`, where `<datetime>` is a UTC ISO 8601
   basic timestamp such as `20261015T085344.742000Z`. It then restores the last
   validated version as a normal write and reports the document as recovered.
   The conflicted copy is independent of the once-per-session `.back` rotation,
   is audit-logged with its revision and path, and uses bounded retention
   (default 5, configurable, minimum 1). If the conflicted copy cannot be
   durably created, automatic restoration stops and returns `STORAGE_ERROR`
   without overwriting the rejected file. While the invalid state is present,
   reads disclose the invalid-on-disk status (section 11).

Load-time fallback (14.8.3) and this run-time restore are separate recovery
paths: LKG picks the newest valid backup when a document is loaded, while the
run-time restore writes back the last validated version already in memory.

The host learns the outcome through the same application state as a normal save
(`applied`, `reload_required`, `restart_required`, `apply_failed`) and can use
`restart_required` to tell the user that a restart is needed.

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
- Allowlisted paths only; no client-selected paths, arbitrary backup downloads,
  Python expressions, or remote schema fetches. Symlink traversal is controlled
  by a configuration option and is allowed by default; when disabled, a
  registered path must not resolve through a symlink.
- Limits are checked before expensive parsing and apply to the resolved effective
  configuration too. Defaults (all overridable in aiset's configuration): maximum
  file size 8 MiB, maximum HTTP request body 8 MiB, maximum nesting depth 64,
  maximum collection size 100000 items, maximum string length 1 MiB, maximum
  regex pattern length 512 characters, and a regex evaluation timeout of 100 ms.
- Authorization policy is the host's responsibility. aiset does not define roles
  or user models; it enforces the capabilities the host supplies through its
  authentication/authorization callbacks (section 3). Normal-mode authorization
  is out of aiset's scope; the demo runs without authorization.
- Unknown descriptor metadata is inert and retained for host use, but is neither
  executed nor automatically exported. Development diagnostics report property
  locations without logging metadata values.
- Audit actor, document, changed paths, old/new revisions, and result.
  Do not log entire request values or environment payloads.
- Invalid external edits are not adopted: aiset restores the last validated
  version over the malformed on-disk content (10.4) and audit-logs it; while the
  invalid state is present, reads disclose the invalid-on-disk status rather than
  pretend cached data is current. Valid external edits are adopted through the
  normal before-save validation and callbacks.

## 12. Acceptance tests and implementation gates

These are required future tests, not claims of existing implementation.

| Area | Required verification |
|---|---|
| Descriptor | Nested objects/arrays, union alternatives, dynamic keys, missing vs null, defaults, invalid descriptors, composition conflicts. |
| Descriptor metadata | Unknown properties ignored at runtime and retained for hosts; every unknown location reported in diagnostic mode; strict-mode exit status; typo warnings; opaque nested metadata; field/data keys not misreported; safe browser export. |
| Encapsulation | Identical library revision works with multiple host configs/adapters; no host imports, source patches, implicit working-directory assumptions, or writes to shared modules/assets. |
| Standalone demo | Own backend/frontend work without a host/account/Redis; first-run local file seeding, retained edits on restart, explicit path overrides, isolated test state, read-only-location errors, no writes to tracked examples. |
| Demo behavior | Explicit demo selection; plain HTTP, no security checks, default bind 0.0.0.0; CLI parameters override config; file edits do not launch host commands/services; normal mode uses host authorization. |
| Type rules | Server-side rules are exact and authoritative: Python bool vs int, fractional values, numeric bounds, finite values, exact integer range. Browser checks, when present, are best-effort and never required for correctness. |
| Paths | Escaped slash/tilde, dotted keys, numeric object keys, arrays, malformed pointers, absent leaves/parents, read-only root. |
| Source preservation | Exact untouched-byte comparison after scalar edits; line/block/array/nested comments; single quotes; trailing commas; UTF-8; CRLF; headers; commented examples; URL strings; templates. |
| Composite editing | Retained child comments; accepted safe replacements; rejected deletion/reordering/type changes with ambiguous comments; original bytes unchanged after rejection. |
| Template resolution | Quoted/unquoted references, defaults, empty/missing variables, resolver profiles, escaped environment values, conversion failures, no structural injection, no secret persistence. |
| Validation | Full candidate and cross-field checks; no partial write on failure; parse the exact persisted candidate, not a separately serialized proxy. |
| Persistence | Stale source/descriptor/layer revisions, concurrent cooperating processes, lock timeout, permissions, external edits, atomic-write fault injection, commit-state reporting, temporary-file cleanup. |
| Transport parity | Python/HTTP/MCP return the same values, issue paths, conflict codes, and stored/application status. |
| Security | Host-supplied authorization; source vs effective permissions; recursive secret/read-only enforcement; size/depth limits; sanitized audit/error output. |
| UI | Read/set scalar and object, placeholder validation status, optional field creation, changed path invalidation, retained input after conflict, restart/apply-failure display. |
| Host compatibility | Existing aidir/aibt/sndbx load shapes, precedence and merge rules, no automatic listener/worker/VM restart, explicit colloc migration. |
| UI helpers | Inline overrides versus separate forms; cancel/no-write behavior; permitted creation paths; proposed JSON5 through the same APIs; visible unavailable-helper errors; no secret or permission bypass. |
| Hooks | Fixed events, registered tags/settings, create versus update, dry runs, changed descendants and scope, deterministic order, sync/async parity, timeout/late outcomes, stale snapshots, no callbacks under the file lock, explicit post-commit failures. |

The authoritative phased implementation plan is in section 17. Its first working
milestone is the autonomous mixed-type configuration editor on default port 8383.
This section remains the overall acceptance matrix.

Every implemented phase must pass its relevant tests before the next integration.
No runtime code or dependency changes are included in this draft.

## 13. Decisions and open questions

The specification's decisions are recorded in the relevant sections (the
descriptor grammar in 4.6, the path/edit contract in 5.3, the service and
transport interface in [SPEC_service.md](SPEC_service.md), and so on). Section 16
is the authoritative discussion register for any still-open question; as of this
revision it is empty. Section 15 defines specification readiness; section 17
defines delivery.

User-established requirements remain: an encapsulated independent library,
unchanged modules across normal host integrations, project-owned descriptor
metadata ignored at runtime but reported by development validation, and an
autonomous backend/frontend with a default local demo file and no user accounts.
Exceptional patches remain possible but must be explicit. The first working
milestone and the default standalone port 8383 are fixed requirements, not open
architectural choices.

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

The AI configuration block in section 14.7 covers providers, models, fallback,
tool allowlisting, approval, and audit. The remaining AI decisions (agent
invocation, execution platform and tools, skill loading, context assembly, and
auditing) are deferred to phase 5 and require a separate implementation
approval. They do not block the standalone manual editor.

For now, the deliverable is the host-authored Markdown editing skill and its
documented role. No decision about the agent's lifecycle or execution platform
is implied.

### 14.5 Expected AI scenarios

The agent (or any future LLM-backed tool) is expected to assist with
configuration work in at least two distinct roles. Both are advisory: the
agent never bypasses the descriptor, validator, or store.

1. **Configuration validation (advisory).** Given a current candidate, the
   agent explains how good the configuration is for the stated goal, calls out
   values that are technically allowed but operationally risky, and suggests
   improvements with reasoning. Examples:

   - "Redis `port` is 65535 — that is the maximum legal TCP port, but no
     standard Redis build uses it. Most likely a typo; intended value was
     6379."
   - "Worker `tools_max_turns` is 1; an agent worker that needs a search
     step will not be able to retry on failure."
   - "Provider `ollama_local` is referenced from `resources[0].provider`
     but is not defined in `models.providers`."

   The agent's output is a structured list of issues (severity, path, message,
   suggested change) which the user can apply through the same `set` path the
   manual UI uses. The agent does not relax or override validation.

2. **Configuration auto-fill (interactive).** When the user wants to add a new
   provider, model, monitoring section, envid, or other common construct, the
   agent proposes a complete JSON5 fragment for the new node — analogous to
   the "create file" experience in openclaw / Claude Code. The proposal is
   delivered as `value_text` together with a target path, and is committed
   through the same `validate` + `set` pipeline as a manual edit. The agent
   never writes to the file directly.

   The proposal may draw on:
   - the descriptor (allowed types, enums, ranges, required fields);
   - the current configuration (existing provider ids, naming conventions,
     values already in use, comment hints);
   - the host's Markdown skill (project conventions, valid examples);
   - the user's free-text request.

Both scenarios must respect source preservation, secret handling, and read-only
fields. Secret and read-only sections are visible to the agent only when the
principal permits; the user must approve any change that touches them.

### 14.6 The `AGENT:` comment convention

Comments are a natural carrier of intent that the parser keeps anyway (see
section 7.1). To let configuration authors speak directly to the agent without
producing side effects on runtime parsing, aiset recommends a simple
convention: any JSON5 comment that starts with the literal token `AGENT:`
(after the comment opener and optional whitespace) is an **agent hint**. It
is plain prose for the agent; the aiset parser treats it as an ordinary
comment and preserves it byte-for-byte.

```json5
{
  //AGENT: keep redis.port at the default unless there is a documented reason;
  //       non-default values typically indicate a misconfigured deployment.
  redis: {
    host: "${REDIS_HOST:-127.0.0.1}",
    //AGENT: this port must not exceed 65535; values >10000 usually mean a
    //       test setup was promoted to production by accident.
    port: ${REDIS_PORT:-6379},
  },
  //AGENT: workers.items is the only place to register a new worker. Adding
  //       it under endpoints instead is a recurring mistake — the worker
  //       will be loaded but never scheduled.
  workers: {
    items: {
      //AGENT: provider id must exist in models.providers. Use existing
      //       "ollama_local" or "ollama_remote" unless intentionally
      //       introducing a new one.
      call_ollama: {
        provider: "ollama_local",
        request_timeout: ${REQUEST_TIMEOUT:-100},
      },
    },
  },
}
```

Conventions:

- **Token.** A comment is an agent hint when the first non-whitespace characters
  after `//` (or inside `/* ... */`) spell `AGENT:`. The colon and a single
  space are part of the token. Comments that mention "agent" without the
  token are normal comments.
- **Scope.** Hints attached to a node apply to that node and, by inheritance,
  its descendants unless a more specific hint is present. A hint placed inside
  an array item applies only to that item.
- **Form.** Hints are free prose. Authors are encouraged to state the rule, the
  reason, and (when relevant) the symptom of a misconfiguration. Lists of
  valid values, references to other paths, and concrete bad/good examples are
  all welcome.
- **Lifecycle.** Hints are loaded into the agent context as part of the
  configuration document. They are never written to the descriptor, never
  validated as schema, and never executed. They are removed only by the human
  who wrote them, or when the value they describe is removed.
- **Conflict resolution.** If a hint disagrees with the descriptor, the
  descriptor wins (it is machine-checked). If two hints disagree, the more
  specific one (closer to the node) wins. The agent surfaces the conflict to
  the user rather than guessing.
- **Privacy.** Hints are part of the configuration document. The host decides
  whether to include the document in the agent context, redacted or in full;
  resolved secret values must never appear in hints.
- **Tooling.** The editor UI and the descriptor-aware tools MAY highlight
  `AGENT:` hints as such (for example with a different gutter mark) so authors
  can find and audit them. The parser itself does not require this.

The agent skill (14.2) should describe when and how to use `AGENT:` hints in
the host project, and may impose additional conventions (naming, structure,
language).

### 14.7 aiset AI configuration block

When aiset itself drives the agent, it needs its own configuration. The host
project (or the standalone demo, or the test host inside aiset) declares this
under a top-level `ai` key in its own `config.json5` (or in whatever file the
host uses for aiset's settings). The block tells aiset which providers and
models to use, in what order to try them, and how to authenticate.

```json5
{
  ai: {
    enabled: true,
    timeout_seconds: 30,

    // Ordered list of providers to try. The first reachable one wins per
    // call; on a transport-level failure the next one is consulted.
    providers: [
      {
        id: "ollama_local",
        type: "openai",             // or "openaix"
        base_url: "http://127.0.0.1:11434/v1",
        api_key: "${OLLAMA_API_KEY:-}",
        // Per-provider overrides for generation defaults.
        generation_defaults: {
          temperature: 0.2,
          max_tokens: 1024,
        },
      },
      {
        id: "openai_remote",
        type: "openai",
        base_url: "https://api.openai.com/v1",
        api_key: "${OPENAI_API_KEY}",
        generation_defaults: {
          temperature: 0.2,
          max_tokens: 2048,
        },
      },
      {
        id: "remote_aidir",
        type: "openaix",
        base_url: "https://remote-aidir.example:21434/v1",
        api_key: "${REMOTE_AIDIR_API_KEY}",
      },
    ],

    // Per-task model selection. Falls back to providers[0] when absent.
    models: {
      chat:      { provider: "ollama_local",  model: "qwen3.5:9b" },
      validate:  { provider: "ollama_local",  model: "qwen3.5:4b" },
      autogen:   { provider: "remote_aidir",  model: "qwen3.5:9b" },
    },

    // Hard limit on fallback hops per single user request. The whole chain
    // fails once this is exhausted; aiset does not retry transparently.
    fallback_max_hops: 2,

    // Tools the agent is allowed to invoke. Each tool is implemented by
    // aiset and runs against the local store/validator; no filesystem
    // access is granted to the model itself.
    tools_allowed: [
      "settings_get", "settings_validate", "settings_set",
      "settings_descriptor", "settings_history",
    ],

    // Safety: the agent never writes without an explicit, recorded approval
    // (or, for scripted host requests, an authenticated principal with the
    // right permission). See section 11.
    require_explicit_approval: true,

    // Audit: every tool call and every model turn is recorded with the
    // principal, the request id, the prompt hash, and the resulting edit.
    audit: { enabled: true, redact_secrets: true },
  },
}
```

Field-level contract:

- `enabled` — master switch. When false, aiset refuses to instantiate the
  agent; the manual UI and the HTTP/MCP surface still work.
- `providers[]` — ordered. `type` is `openai` (chat-completions style) or
  `openaix` (aidir's own dialect). `api_key` may be a `${VAR}` placeholder.
- `models.<task>` — picks a `provider` + `model` for a logical task. Tasks
  include `chat` (interactive dialog), `validate` (advisory review of a
  candidate), `autogen` (auto-fill of a new node). The agent refuses a task
  whose `provider` is not listed in `providers[]`.
- `fallback_max_hops` — bounded by host policy; default 2.
- `tools_allowed` — allowlist of tool ids the agent can call. Anything not
  listed is denied, even if the model requests it.
- `require_explicit_approval` — when true, every `set` produced by the agent
  goes through the normal validate+preview+confirm flow the manual UI uses;
  a single prompt means "show me the diff and wait for me to click Save".

The two AI scenarios from 14.5 reuse this block:

1. **Interactive dialog with the user.** The user types a free-form request
   ("increase HTTP timeouts", "add an ollama provider at port 11435"). aiset
   passes the active descriptor, the current source, the user's Markdown
   skill, and the `AGENT:` hints together with the request to the model.
   The model replies with a plan and one or more proposed `set` operations.
   aiset validates each proposal, shows the diff, and waits for approval
   (unless `require_explicit_approval` is false and the principal permits).
2. **Host-driven natural-language request.** The host process can submit the
   same kind of request programmatically, with its own principal. The
   approval flow still applies, but the confirmation is delivered to the
   host (return the proposed edits without writing) or skipped (the host
   already trusts its own request and supplies `approve: true` with a
   recorded audit entry).

aiset registers the following tools to the agent (the names correspond to
`tools_allowed` above):

| Tool | Purpose |
|---|---|
| `settings_get` | Read a path or subtree (source or effective view). |
| `settings_validate` | Run validate on a proposed `set`, return issues. |
| `settings_set` | Persist a proposed `set` through the full pipeline. |
| `settings_descriptor` | Read the authorized descriptor for a document. |
| `settings_history` | List recent revisions and LKG entries for a document. |

The tools are implemented by aiset, not by the host and not by the model.
A tool call is one read/validate/write through the existing service, so
all guarantees (revisions, source preservation, permission checks, hooks)
apply unchanged. The model can never see resolved secret values; secret
fragments are filtered before being placed in any tool result.

`ai` itself is a normal aiset-managed subtree: it can be edited through the
manual UI, the HTTP/MCP surface, or the agent. The agent, however, is not
permitted to edit its own `ai` block without an out-of-band principal —
a model must not reconfigure the keys that decide which model is in use.

### 14.8 Last known good configuration

Configuration drift after a "valid on paper" edit is one of the most common
causes of a host that refuses to start. aiset therefore maintains a chain
of backups and an explicit Last Known Good (LKG) reference, so a host that
is told to "load LKG" can recover even when the on-disk file is
semantically valid but operationally broken.

#### 14.8.1 Backup chain

aiset manages a small, bounded chain of backup files in the same directory
as the editable document:

```text
config.json5              // current file
config.json5.back         // previous good
config.json5.back.back    // one before that
config.json5.back.back.back
...
```

- The chain is rotated by appending `.back`; existing `.back` files shift
  one level deeper. The depth is host-controlled, default `5`, and is
  part of aiset's own configuration (not the host application config).
- Files beyond the depth are discarded. Depth 0 disables backups.
- Backups are created by aiset only; the host application is asked never to
  touch them directly.
- Backup rotation is itself source-preserving: the rotation only renames
  files; it does not rewrite their contents.

#### 14.8.2 When a backup is created

A new backup is created at most **once per editing session** — that is,
once between (re)loads of the configuration by the host. Concretely:

- The first successful `set` in a session creates `*.back` from the file
  that was current at session start, then writes the new value.
- Subsequent `set` operations in the same session do **not** create new
  backups; the chain stays at the same depth.
- The session is renewed when the host explicitly reloads the
  configuration (or the host process restarts).
- The "one per session" rule applies even if the file on disk has changed
  in the meantime, as long as aiset was not reloaded — a stale in-memory
  dictionary is not silently extended by external edits, and aiset does
  not invent a new backup to "catch up".

This keeps the chain short and predictable, and matches the recovery
contract: after one reload/restart you always see at most one fresh
`.back` from the previous-good file.

#### 14.8.3 Auto-fallback to LKG on load

When aiset loads a document, the steps are:

1. Read the file.
2. Parse, resolve placeholders, build the candidate.
3. Run structural validation against the descriptor.
4. Run semantic validators (registered per document).
5. If everything passes, the document is the current config; the most
   recent valid entry in the backup chain (if any) becomes the LKG.

If step 3 or 4 fails, aiset does not raise. Instead, it:

- Logs the failure (without the resolved secret values).
- Walks the backup chain newest-first and picks the first entry that
  passes the same structural and semantic checks. That entry is the LKG.
- Reports the load result to the host as
  `loaded = "lkg"` with the path or revision of the chosen backup, and a
  reason explaining why the current file was rejected.
- The on-disk file is left untouched. Repairing it is a separate,
  explicit operation (see 14.8.5).

The host decides what to do with an `loaded = "lkg"` result: surface it
to the user, log a warning, refuse to start, or continue. aiset does not
silently re-save the LKG over the current file.

If no backup passes validation, loading fails with `NO_VALID_BACKUP`; it does
not return `loaded = "lkg"` and does not modify the current file.

#### 14.8.4 Explicit "load LKG" API

Sometimes a configuration is semantically valid but the host cannot start
with it (a worker misconfigured, a port that conflicts with something
running, a credential that the host rejects at runtime). aiset therefore
exposes an explicit "load LKG" operation distinct from auto-fallback:

- It is invoked by the host, not by aiset. The host calls it when its own
  startup probe (or a follow-up health check) fails after aiset reported
  a successful load.
- The operation re-runs the load with `force = "lkg"`. It picks the
  newest valid entry in the backup chain regardless of the on-disk
  state. The on-disk file is still left untouched.
- The host receives `loaded = "lkg"` and the chosen revision/path, as in
  14.8.3. The host can then choose to make that revision the new current
  file by an explicit `set` (which will, being a new editing session,
  create a fresh `.back` from whatever is on disk at that moment).
- The operation requires an authenticated principal with the
  `settings_load_lkg` permission. It is audit-logged.

For the standalone demo and for first-time setups, the operation is
exposed through the same Python/HTTP/MCP surface as the other
operations. There is no separate "panic" path; the same revisions,
permissions, and audit guarantees apply.

History and restore are phase 4 operations. Their future contract lists backup
entries with revisions and validity and applies a selected valid entry through
an explicit, revision-checked restore. Automatic recovery only ever uses the
newest valid entry (14.8.3); restoring an older entry is explicit and
audit-logged. Until phase 4 defines their service envelopes, they are not part
of Python, HTTP, or MCP transport parity. Revision diff and an approval workflow
are also phase 4 capabilities (section 17).

Rollback (section 10.3) is a special restore that shifts the chain down by one
level: the newest valid `.back` becomes the current file and the previously
current file is discarded, so the last change is undone as if it never happened.
The host requests it with a reason; aiset audit-logs `rollback, reason = ...`
and reports `restart_required`.

#### 14.8.5 Repairing the on-disk file

The auto-fallback and the explicit "load LKG" path both leave the
on-disk file untouched. Repair is a deliberate `set` against a known
revision; the rotation rule (14.8.2) means the new edit will create one
fresh `.back` from the rejected current state, preserving the option to
inspect it later. aiset never overwrites a file that the host has not
approved for replacement, even when that file is known-bad.

#### 14.8.6 Recommendations for host applications

- The host should always go through aiset to read or modify its own
  configuration. Direct file edits to `config.json5` (or the host's
  aiset-managed equivalent) bypass the rotation, the descriptor, the
  hooks, and the audit log. aiset documents this as a strong
  recommendation; it does not enforce it.
- Hosts that keep an in-memory cache should treat any `loaded = "lkg"`
  result as a signal to reinitialize that cache from the LKG revision
  rather than from the on-disk file.
- Hosts that want to test a new configuration before committing it
  should use validate + diff + explicit set; aiset does not currently
  ship a "staging" file, but the audit and revision chain give a
  sufficient record for rollback.

## 15. TODO: Prepare the specification for implementation

1. Confirm that the discussion register (section 16) is empty and record any new
   decisions in the relevant contracts; approve the milestone M1 scope and
   acceptance criteria in section 17.
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

The following is the authoritative discussion register. As of this revision every
previously open question is resolved and recorded in the relevant sections, so
the register is currently empty. New questions are added here when they arise,
each with a `Must be resolved before` gate: a plan is not blocked by a question
until that gate is reached.

Decided and not reopened here: the project name, the unchanged library boundary,
the host placement convention, the execution-environment policy (section 3.4),
the standalone first milestone and its port, the resolver policy (section 6),
browser-validation scope (section 9), the descriptor grammar including templates
and `typedef_sources` (sections 4.6, 10.2), the path/edit contract (section 5.3),
the merge and Config model (10.1, 10.2), save callbacks and external-edit
handling (10.3, 10.4), the service and transport interface
([SPEC_service.md](SPEC_service.md)), the AI configuration block (14.7), Last
Known Good (14.8), the demo execution model and CLI convention (3.3), and logging
(section 20).

## 17. Phased implementation plan

This plan replaces the earlier implementation outline. Section 12 remains the
overall acceptance matrix; each phase selects its relevant tests and adds
observable exit criteria. This is a plan, not an execution record.

### Phase 0: Close the specification and prove feasibility

- Complete section 15.
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
HTTP port. Default port 8383 with default bind `0.0.0.0` (access via
`http://127.0.0.1:8383`). The startup port is configurable; 8383 is its fixed
default, not a test-data value or a host project's port.

Deliver vertically integrated behavior:

1. Package the shared descriptor/resolver/validator/source-editor/store/service
   modules and a bundled standalone UI without host-specific imports.
   Provide explicit local `.venv/` setup/install/test instructions using that
   same package; library startup must not provision the environment.
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
   object/array edits follow the approved composite-edit contract (section 5.3);
   ambiguous edits fail.
7. Implement required locking/atomic writes, stale revisions, permission/path
   checks, and explicit disk/validation failures. No success-shaped fallback.
8. Run the explicit demo mode as a plain HTTP test app (section 3.3): no
   security checks, default bind `0.0.0.0`. Bind failures, including an occupied
   port, are explicit; do not silently select another port or kill its owning
   process.

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

- From a clean standalone installation in aiset's local `.venv/`, the documented command serves the
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
  source-preservation fixtures, fault/conflict cases, and demo behavior checks.
  Test sizes/limits use the explicit limits in section 11, not unmeasured claims.
- UI distinguishes persistence from application state. A demo-file edit does not
  claim to reconfigure a host or change the listening port.
- Tests run in isolated temporary state; runtime files remain ignored. Commands
  and results are documented for reproducible standalone use.

M1 excludes host integrations, MCP, production/public deployment, lifecycle hook
execution, specialized helpers/generated universal editors, batch/delete/append/
list reordering, and AI model/agent execution. It includes the real shared core
and safety guarantees, not a throwaway
mock editor that will be replaced for host use.

Descriptors without helpers/hooks remain fully usable. Before those capabilities
are implemented, recognized hook bindings must not be silently ignored: reject
their use with an explicit unsupported-capability error. An unavailable helper
is reported in the UI; ordinary editing remains available when otherwise allowed.

### Phase 2 / M2: Reusable distribution and shared integrations

Prerequisite: M1 accepted.

- Stabilize the public package/API and versioned descriptor contracts.
- Package the embeddable UI and authenticated normal-mode HTTP adapter.
- Implement MCP tools with the same service semantics, validation, permissions,
  revisions, and error shapes.
- Implement the fixed lifecycle-hook dispatcher and host registration API with
  synchronous/asynchronous callback coverage and explicit failure outcomes.
- Publish controlled install/upgrade instructions and compatibility tests;
  never initialize or change user-managed Git tracking implicitly.

Exit: standalone and embedded test harnesses use the same library revision
unchanged; Python/HTTP/MCP parity and normal-mode authorization tests pass.
Test standalone operation in aiset's local environment and embedded operation
in host-style environments. Host-specific integration work is still separate.

### Phase 3 / M3: Integrate host projects

Prerequisite: M2 accepted.

- Integrate aidir and sndbx first; they are the primary analysis targets. aibt
  and colloc are lower priority and may be treated as reference material until
  chosen.
- Supply descriptors, host-owned adapters, compatibility resolver/layer policies,
  and at least one Markdown editing skill per host.
- Preserve loader shapes and override semantics for each adopted host.
- Inventory and explicitly migrate colloc's selected file-backed settings;
  Redis runtime distribution and session settings remain separate decisions.
- Test source/effective provenance, secret boundaries, stored/active state,
  masking, reload/restart, and failed application in each affected host.

Exit: each adopted host edits configuration through unchanged aiset modules,
with host regression tests and documented migration/application behavior.
Integrating one host does not require the others to be migrated simultaneously.

### Phase 4 / M4: Extended editing capabilities

Prerequisite: relevant host/library baseline accepted; specialized editors
follow section 18.

Add, each separately reviewed: removal, array append/insert/remove and
reordering (moving each item's comments with it), history listing and restore
from the backup chain, revision diff/approval, standard-control overrides,
helper micro-forms/wizards, generated forms, and change subscriptions.

Operations are sequential: v1 provides no multi-operation transactions or
all-or-nothing atomicity (section 5.3.6); recovery uses the Last Known Good
configuration. Each feature must preserve the core comment/validation/permission
guarantees and have its own acceptance tests. This is not a mandatory
all-at-once release.

### Phase 5: AI functionality, separately approved

Prerequisite: resolve the deferred AI decisions (section 14.4) and approve a concrete agent integration design.
Only then implement model connections, skill/context loading, invocation, tools,
approval, and auditing through the established editing APIs.
No AI runtime work is authorized by the current specification-preparation task.

## 18. UI customization and helpers

The `ui`/`helper` split is part of the descriptor grammar; its exact schemas and
supported form capabilities may grow over time. Both fields are optional on any
descriptor node, including scalars, objects, array items, union alternatives, and
dynamic-key value definitions.

### 18.1 Standard-control overrides: `ui`

`ui` customizes the node's ordinary editor rather than opening another workflow.
Its properties are `label`, `group`, `order`, `help`, `widget`, `rows`, and
`placeholder`.
Examples include a multiline text area, a compact enum selector, ordering,
or additional help text. Presentation choices remain compatible with the node's
type and raw placeholder editing; they cannot redefine validation or stored types.
Unsupported/incompatible widgets produce visible descriptor/UI diagnostics.

```json5
{
  type: "string",
  description: "Monitoring command",
  ui: {
    label: "Command",
    widget: "textarea",
    rows: 4,
    placeholder: "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits",
    help: "Enter the command text; editing does not execute it.",
  },
}
```

Display labels and placeholder text are plain text, not arbitrary HTML. A
placeholder is shown inside an empty input field as a hint; it does not affect
validation or stored values. Hiding/disabling a UI control is not an
access-control mechanism. Standard source editing remains available where
permissions allow, including when a specialized widget cannot represent the
source template safely.

### 18.2 Separate micro-forms: `helper`

A helper is a dedicated form, modal, or multi-step wizard that builds a proposed
node value for creation or editing. Typical tasks are adding a provider or model,
or creating a monitoring section. It is a UI convenience, not another persistence
or validation implementation.

Binding shape:

```json5
{
  type: "object",
  description: "Provider configuration",
  children: {
    enabled: { type: "bool", default: true },
    base_url: { type: "string", required: true },
  },
  helper: {
    tag: "provider_form",
    actions: ["create", "edit"],
    presentation: "modal",
    settings: { offer_presets: true },
  },
}
```

`tag` selects an implementation from a trusted UI registry, not a function
import path or remote script URL. `actions` is a nonempty subset of `create`
and `edit`; `presentation` proposes `modal` or `wizard`. `settings` contains
JSON-compatible tag-specific data validated by the helper's registered schema.
The shared library treats those setting values as data, never executable code.

aiset may ship reusable helpers. A host may register additional helper assets
through a documented UI API while keeping those assets outside aiset's directory.
Exact asset packaging and registry interfaces remain open design decisions.
No helper is loaded by guessing host files or executing descriptor strings.

Workflow:

1. Resolve a permitted node path and load authorized source/descriptor data.
2. Open the helper with its initial value, metadata, and captured revisions.
3. Build a draft; cancel closes it without a write.
4. Produce `value_text` and a target path, not direct filesystem changes.
5. Validate and submit through the same service used by manual edits.
6. Preserve input on errors/conflicts and show stored/application/hook status.

A creation helper cannot bypass current operation limits. Creating an optional
object or dynamic-key entry may use `set` when its parent exists. Appending a
model to an array requires the later append capability; the helper must disable
that action explicitly until supported. A multi-node wizard is a sequence of
independent writes, not an atomic operation: each write is validated and
committed on its own, and a failure leaves earlier committed writes in place
(recovery uses the Last Known Good configuration, section 14.8).

Missing helper tags/capabilities are reported; never pretend the dedicated form
ran successfully. Helper availability cannot grant edit permissions, override
read-only/secret protections, bypass hooks, or replace source-preserving edits.
The server does not trust the browser to enforce any of these rules.

### 18.3 Descriptor interpretation and exports

`ui`, `helper`, and `hooks` are recognized shared descriptor properties, not
arbitrary project metadata. Development validation checks their binding shapes
and reports unknown properties as in section 4.5.
Tag-specific `settings` objects are opaque to generic keyword diagnostics and
validated by a registered declarative settings schema when the tag is available.
The keys of `hooks` are event IDs, not arbitrary project metadata; an unknown
event is an invalid binding and must be rejected. Projects put custom metadata
on descriptor nodes or inside tag-specific settings, not in the event map.

Browser export contains only authorized UI/helper data. It must not expose
server hook callables, private hook settings, or resolved secrets. A host can
expose a safe hook-capability summary if needed for the UI.
Neither UI nor helper options change Python/HTTP/MCP validation semantics.

### 18.4 Generated forms (later)

A fully generated tree/form editor is a later capability (section 17, phase 4).
The first version provides descriptor-driven standard controls plus registered
helpers. Generated forms are implemented in the simplest useful form, and their
schemas include extension points so additional widgets and layouts can be added
without breaking hosts. Like helpers, generated forms only produce `value_text`
and a target path and submit through the same service; they never bypass
validation, permissions, hooks, or source preservation.

## 19. Hooks

Hooks call host-core functions through registration APIs, without modifying
aiset. Prefer tags plus settings over Python function names in configuration.

### 19.1 Fixed lifecycle events

Initially support exactly four events; event names are not freely extensible:

| Event | Moment | Purpose/result |
|---|---|---|
| `before_create` | A permitted source node is absent and a candidate would create it, before persistence. | Pure check: permit or reject with structured issues. |
| `before_update` | An existing source node would change, before persistence. | Same pure checking interface. |
| `after_create` | The node was durably created and the host application outcome is known. | Host notification; report completion/failure separately from storage. |
| `after_update` | The changed node was durably stored and the host application outcome is known. | Same notification interface. |

Read, helper-open, and cancel do not invoke lifecycle hooks. A byte-identical
no-op set does not invoke hooks or create a new revision.
Candidate validation may run before hooks with `dry_run: true`, but never after
hooks. Set runs before checks again with `dry_run: false`; a prior validation
does not authorize saving a changed candidate.

Removal has no event in this initial set. A composite replacement that removes
a hook-bound node must fail explicitly until removal semantics are approved;
it cannot silently bypass that node's hooks.

### 19.2 Node binding and host registration

```json5
{
  type: "string",
  hooks: {
    before_create: [
      { tag: "check_model_id", scope: "node", settings: {} },
    ],
    before_update: [
      { tag: "check_model_id", scope: "node", settings: {} },
    ],
    after_update: [
      { tag: "notify_model_change", scope: "node", settings: { topic: "models" } },
    ],
  },
}
```

Each event holds an ordered list of bindings. A binding contains `tag`, optional
`settings` (default `{}`), and `scope` (`node` by default, or `subtree`).
The host registers the callable, permitted events, settings schema, execution
style, and bounded timeout policy for each tag.
The descriptor never imports Python, looks up arbitrary function names, or
chooses an event loop/executor. Missing tags, invalid settings, unsupported events,
or unsupported hook capability are explicit errors, not skipped callbacks.

Plan events from the proposed source-tree difference, not just the requested
pointer. A parent replacement must include changed/new hook-bound descendants;
dynamic entries use their resolved descriptors. `node` bindings observe that
node's own edits, including replacement through a parent. `subtree` bindings
also observe descendant edits and run once per binding/event/operation with the
aggregated changed paths.

Determine create/update from stored presence, not defaults or effective values.
An absent source node with an effective default is still a creation.
Array paths are positional, not stable model/provider identities; identity-aware
reordering requires the later array contract.
Order: parent before child, then canonical path, then binding-list order,
with sequential invocation. Do not depend on parallel callback races.
Finalize difference/scope/order details before implementation.

### 19.3 Common interface and results

Each callable receives one immutable `HookContext`, containing:

- Event, operation ID, document ID, node path, and aggregated changed paths.
- Principal and `dry_run` status.
- Old/new presence, authorized source values and effective snapshots.
- Validated binding settings and captured source/descriptor/layer/registry revisions.
- For after events: committed revision and explicit host application outcome.

Data is scoped to the registered hook's authorized needs. Hook context/settings
are server-side and are not returned verbatim to the browser, MCP caller, or logs.
Do not supply missing data as fake defaults or expose resolved secret values
merely to dispatch a notification.

Before hooks return a `HookDecision` with `allow: bool` and an `issues` list:
allow or reject plus structured issues
using canonical paths, rule codes, and sanitized messages. They cannot mutate
the candidate, perform writes, or normalize values silently.
Existing semantic `validators` still validate all relevant loads/candidates;
hooks add lifecycle-specific checks and notifications, not a second field schema.
Registered validation logic may be shared by both interfaces.

After hooks return a `HookReceipt` confirming notification completion. Exceptions
or timeout are reported by the dispatcher, not converted to a success receipt.
They may
perform approved host side effects, but cannot change the already committed
document or silently roll it back. Reject recursive writes to the same store
from a hook; a later independent edit must be a new revision-checked operation.

Before rejection/exception/timeout prevents persistence and is returned explicitly.
After failure does not turn a committed write into an uncommitted one:
retain `stored: true`, the new revision, and application status, and include
sanitized per-hook failure information. Run remaining after notifications and
collect their outcomes rather than silently dropping them.

Propose a separate `hook_results` response list with event/tag/path and status
`completed`, `failed`, or `outcome_unknown`, plus sanitized error details where
needed. An after-hook error preserves the normal persistence/application result
and adds an explicit notification error; it must not invite blind re-saving.
Before-hook rejection uses validation issues; missing tags/capabilities,
execution failures, and timeouts have distinct error codes. Finalize their
HTTP/MCP mappings and receipt fields before implementation.

### 19.4 Synchronous and asynchronous variants

Both callable styles are supported for every event:

- Synchronous: `HookContext -> HookDecision` or `HookReceipt`.
- Asynchronous: `HookContext -> Awaitable[HookDecision]` or
  `Awaitable[HookReceipt]`.

Both use identical event names, context, and results. Execution style belongs
to trusted registration metadata; do not create separate descriptor event names.
Use an asynchronous dispatcher for async HTTP/MCP integration. A synchronous
facade may support sync-only bindings; if async execution is required but the
chosen facade cannot provide it, fail explicitly. Do not start/nest an event
loop implicitly inside a running host loop.

Potentially blocking synchronous callbacks need a bounded execution strategy
that does not block the host event loop. The common timeout is 30 seconds by
default and configurable; individual registrations may shorten it but may not
disable it. Decide executor/thread ownership and supported sync facade behavior
before implementation.
Cancellation/timeout does not necessarily stop an already-running thread or
undo an async callback's external side effect; expose an unknown delivery
outcome when necessary, not a false guarantee that nothing happened.

Before hooks must be side-effect-free and use immutable captured inputs. Run
them outside the file lock, then verify the same snapshot under the lock.
If revisions changed, return a conflict without automatic replay.
No after hook runs before a durable commit or for a rejected candidate.

Use operation IDs for host idempotency. Normal dispatch is in-process notification,
not a durable queue: exactly-once delivery or delivery after a process crash is
not promised. Durable delivery/retries require a separately agreed outbox
contract. Do not blindly retry a hook whose outcome is unknown.

### 19.5 Relationship to helpers and rollout

Helpers, generic UI controls, Python, HTTP, and MCP all use the same hook-aware
service pipeline. A helper does not invoke host lifecycle callbacks directly.
Server validation and permissions remain authoritative even if no UI is used.

The existing application callback owns runtime reload/application and runs once;
after hooks observe its result rather than apply the setting a second time.
Notification completion and active-revision/application success are different
outcomes. The save-time ordering of these events relative to the host callbacks
(`probe_changes`, `after_save`) is defined in section 10.3.

Hook runtime support is planned for phase 2; specialized UI/helpers for phase 4.
The first standalone-editor milestone remains focused on unbound ordinary
settings. Sections 18 and 19 are part of the specification.

## 20. Logging

Logging is a first-class operational requirement, not an afterthought.

- **Errors.** Every error the library detects is logged at `ERROR` with enough
  detail to diagnose it: the operation, the document ID, the path, the error
  code, and a sanitized message. Unexpected internal failures are logged with a
  stack trace.
- **Write failures.** A failed durable write is retried a bounded number of
  times (three attempts, with a short backoff). After the final failure the
  library logs an `ERROR` and stops; it does not loop or guess. The commit-state
  report (section 7.3) is included.
- **Warnings.** Recoverable anomalies (an invalid external edit that was
  restored, a masked override, an ignored unknown descriptor property in default
  mode) are logged at `WARNING`.
- **Never log secrets.** Resolved secret values, environment payloads, and whole
  request bodies are never written to logs; environment diagnostics log variable
  names only (section 10).
- **Destination and level** are host-controlled. The standalone demo logs to the
  console. The host supplies the logging/sink configuration; aiset does not
  open files or start services on its own.

Log statements are stable and greppable: each carries a short stable event name
(for example `write_retry`, `external_edit_restored`, `lock_timeout`).

## 21. Review resolutions

The 2026-10-15 consistency review against aidir, sndbx, and
`SPEC_service.md` is resolved as follows:

1. Clients continue to send only source and descriptor revisions. Resolver,
   layer, and hook-registry revisions are internal server snapshots verified
   before commit (sections 7.3 and `SPEC_service.md` section 4).
2. Automatic restoration preserves rejected bytes as
   `<filename>.conflicted.<UTC-ISO-datetime>.back` before replacing the current
   file (section 10.4).
3. Explicit LKG loading is part of the shared Python/HTTP/MCP contract.
   History and restore remain phase 4 operations and are not advertised before
   their envelopes are specified (sections 14.8 and 17).
4. Config mount grammar and escaping are selected and documented by the
   implementer before publishing that API; ambiguous mounts must fail
   explicitly (section 10.2).
5. Hooks and all save callbacks use the same bounded timeout policy. The default
   is 30 seconds; pre-commit and post-commit timeout outcomes remain distinct
   (sections 3.6, 10.3, and 19.4).

No questions from this review remain open.
