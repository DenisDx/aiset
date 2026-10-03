# aiset

Shared, encapsulated JSON5 settings library for aidir, aibt, sndbx, colloc,
and other projects.

## Current status

Documentation bootstrap only. No Python package, server, frontend, descriptor
validator, or test runner has been implemented yet.
The complete working specification is [SPEC_.md](SPEC_.md). It incorporates the
original design and all amendments, including AI skills, preparation tasks,
the discussion register in section 16, and the phase plan in section 17.
Its first milestone is the standalone mixed-type configuration editor with a
web UI on default port **8383**. No server is running or implemented yet.

During specification development, edit only [SPEC_.md](SPEC_.md) as the
specification source. There is no separate original specification to consult.
Once finalized, freeze the document and rename it to `SPEC.md`.

## Intended capabilities

- Read, validate, and edit JSON5 configuration while preserving comments.
- Resolve environment templates without persisting resolved secrets.
- Describe project fields using a shared descriptor.
- Ignore project-owned descriptor metadata at runtime and report unknown
  properties through development validation.
- Provide Python, HTTP, MCP, and reusable UI integration through public APIs.
- Run its own backend/frontend with a local demo file and no host/user accounts.

## Integration boundary

Host projects use aiset unchanged, supplying paths, descriptors, configuration,
and public API hooks. Host-specific adapters remain outside this directory.

Placement:

- aidir: `aiset/` at the project root.
- Other projects with a `src/` directory: `src/aiset/`.
- Other projects without `src/`: `aiset/` at the project root.

This directory is excluded from aidir's Git tracking. The user will register
aiset in version control separately; no nested repository or submodule has been
initialized. A pinned Git submodule is a future delivery recommendation, not
the current installation mechanism.

## Documents

| File | Responsibility |
|---|---|
| [SPEC_.md](SPEC_.md) | Complete editable specification during development; finalized as SPEC.md later. |
| [AGENTS.md](AGENTS.md) | Exact copy of aidir's agent workflow; read-only for agents. |
| [commands.md](commands.md) | Commands applicable to the current documentation bootstrap. |
| [TEST.md](TEST.md) | Bootstrap checks and future implementation acceptance gates. |
| [memory/context.md](memory/context.md) | Initial implementation context and unresolved decisions. |
| [memory/history.md](memory/history.md) | Operations performed in the aiset project. |
| [.gitignore](.gitignore) | Local configuration, credentials, runtime state, dependencies, and build exclusions. |

[AGENTS.md](AGENTS.md) remains unchanged and read-only. Its references to the
protected final specification apply once this working draft is finalized.
The current specification-development workflow is documented above. Do not
implement an unapproved design merely because it appears in the draft.
