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
- Server-side validation is always authoritative. Browser-side checks are
  optional and best-effort (a first filter to avoid round-trips); a UI may
  perform none at all, since aiset can be driven through any UI over its API.
- Proposed extensions: standard-control `ui` overrides, `helper` micro-forms/
  wizards, and registered synchronous/asynchronous host lifecycle hooks.
  These are discussion drafts in specification sections 18-19, not implemented.

## Integration boundary

Host projects use aiset unchanged, supplying paths, descriptors, configuration,
and public API hooks. Host-specific adapters remain outside this directory.

Placement:

- aidir: `aiset/` at the project root.
- Other projects with a `src/` directory: `src/aiset/`.
- Other projects without `src/`: `aiset/` at the project root.

This directory is excluded from aidir's Git tracking and is its own Git
repository. A pinned Git submodule remains a future delivery recommendation,
not the current installation mechanism.

## Python environments

Normal embedded use installs aiset into the host project's venv. Standalone
development, automated tests, and the local demo use an on-demand `.venv/`
inside aiset, with the same package plus required optional/test dependencies.
Setup is explicit; the library never creates or switches environments itself.

The local environment is a lightweight testing convenience. It requires no
separate account system or special security subsystem; the demo execution model
(specification section 3.3) is independent of environment selection.
No environment or installation tooling has been created yet.

## Environment resolver policy

There is exactly one resolver policy for every host (specification section 6).
Placeholders such as `${VAR}` and `${VAR:-default}` are resolved with this order,
highest priority first:

1. explicit host overrides;
2. the process environment;
3. a supplied `.env` mapping;
4. the placeholder's inline default;
5. the descriptor/config `default`.

Additional rules:

- A value supplied by `.env` wins over the config `default`.
- `:-` uses POSIX shell semantics and is the only supported operator:
  - `${VAR}` yields the variable value, or the empty string when it is unset
    or empty;
  - `${VAR:-default}` yields the variable value, or `default` when it is unset
    or empty.
- Resolution is single-pass; environment values are data and are never
  re-parsed as JSON5. They cannot inject objects, arrays, keys, or comments.
- The browser never receives environment values; server validation is
  authoritative.

Hosts that currently behave differently must be brought into line during
integration. In particular:

- **aidir** substitutes before parsing and must adopt source-preserving editing.
- **aibt** currently consults `.env` before the process environment and must
  reverse that order to match the policy above.
- **sndbx** currently gives the process environment priority; it already matches
  the environment order but must adopt the same `:-` semantics.
- **colloc** has no JSON5 file today and must introduce one via its migration
  adapter.

Do not implement a host-specific precedence profile: integrations conform to
this single policy. See specification section 6 for the authoritative contract.

## Documents

| File | Responsibility |
|---|---|
| [SPEC_.md](SPEC_.md) | Complete editable specification during development; finalized as SPEC.md later. |
| [SPEC_service.md](SPEC_service.md) | Authoritative service and transport interface specification (Python/HTTP/MCP); normative for the interface and kept in sync with the project. |
| [AGENT_NOTES.md](AGENT_NOTES.md) | Implementation guidance for the agent: working preferences, decisions and rationale, pitfalls, open white spots. |
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
