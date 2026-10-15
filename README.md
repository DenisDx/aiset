# aiset

Shared, encapsulated JSON5 settings library for aidir, aibt, sndbx, colloc,
and other projects.

- Reads, validates, and edits JSON5 configuration while preserving comments and
  untouched source bytes.
- Resolves `${VAR}` / `${VAR:-default}` templates with one global policy and
  never persists resolved secrets.
- Describes project fields with a shared descriptor and a JSON Pointer edit
  contract.
- Ignores project-owned descriptor metadata at runtime and reports it through
  development validation.
- Exposes one service over Python, HTTP, and MCP-shaped envelopes, with
  reusable UI assets for embedding into any host settings page.
- Ships its own backend, frontend, and a standalone demo on default port
  **8383** with no host, accounts, Redis, or model.

The complete design is [SPEC.md](SPEC.md); the normative service and transport
interface is [SPEC_service.md](SPEC_service.md). The interface is versioned:
incompatible versions fail with a clear compatibility error.

## Status

Milestone M1 is implemented and tested: the shared core (source-preserving JSON5
template engine, descriptor compiler, resolver, validator, store, service) and
the standalone demo editor. See [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md)
for the plan and for what belongs to later milestones.

Not implemented yet, by specification: the MCP adapter and the lifecycle-hook
dispatcher (M2). A descriptor that binds hooks is accepted by the descriptor
compiler, but any change touching a hook-bound node is refused with
`UNSUPPORTED_CAPABILITY` rather than silently ignored.

## Quick start

Everything runs from a local virtual environment inside this directory. The
system Python is not used, and the library never creates or switches an
environment itself.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest              # 230 automated tests
.venv/bin/python demo_app.py            # http://127.0.0.1:8383
```

`demo_app.py` binds `0.0.0.0` by default, serves the bundled UI and API, and
seeds `.local/demo/config.json5` and `.local/demo/aiset.json5` from
[examples/](examples/) only when those files are absent. Port and host can be
overridden with the `--<dotted.path>:<value>` convention:

```sh
.venv/bin/python demo_app.py --aiset.port:12345 --aiset.host:"127.0.0.1"
```

Descriptor diagnostics run without starting anything:

```sh
.venv/bin/aiset validate-descriptor examples/descriptor.json5
.venv/bin/aiset validate-descriptor examples/descriptor.json5 --strict --format text
```

## Using the library

```python
from aiset import merge
from aiset.resolver import Resolver
from aiset.service import Principal, Service

service = Service()
service.register(
    "main",
    "config.json5",
    open("examples/descriptor.json5").read(),
    resolver=Resolver(dotenv={"REDIS_HOST": "cache.internal"}),
)
principal = Principal.demo()          # hosts supply their own authorization

loaded = service.load("main", principal=principal)
value = service.get("main", "/log_level", principal=principal)
check = service.validate("main", "/log_level", '"critical"',
                         expected_revision=loaded.revision,
                         expected_descriptor_revision=loaded.descriptor_revision,
                         principal=principal)
result = service.set("main", "/log_level", '"critical"',
                     expected_revision=loaded.revision,
                     expected_descriptor_revision=loaded.descriptor_revision,
                     principal=principal)
assert result.stored and result.application_state == "applied"
merged = merge({"a": {"b": 1}}, {"a": {"c": 2}})
```

The HTTP adapter is a dependency-free WSGI application, so a host can mount it
inside its own authenticated server, and the demo serves the same app:

```python
from aiset.httpd import create_app

app = create_app(service, base="/api/settings")
```

The shipped UI assets (`include_assets`, `render_node_editor`,
`render_full_editor`) are plain JavaScript in
[src/aiset/assets/aiset.js](src/aiset/assets/aiset.js); the host includes them
and inserts the returned HTML fragment.

## Repository layout

```text
aiset/
  pyproject.toml            package metadata, console script, no runtime deps
  demo_app.py               standalone entry point (plain HTTP, port 8383)
  src/aiset/
    errors.py               stable error codes and HTTP status mapping
    pointer.py              JSON Pointer parsing and traversal
    jsonsrc.py              source-preserving JSON5 template engine (parse/edit)
    descriptor.py           descriptor load, validate, compose, compile
    validator.py            value validation and operational limits
    resolver.py             environment resolution and effective snapshots
    store.py                revisions, lock, atomic write, backups, LKG
    service.py              the shared read/validate/set pipeline
    config_obj.py           Config object model and mount grammar
    merge.py                pure merge(base, update)
    httpd.py                WSGI HTTP adapter
    cli.py                  `aiset validate-descriptor`
    assets/                 reusable UI assets (JS + CSS)
  frontend/index.html       demo page using the shipped assets
  examples/                 demo and aiset descriptors/configurations, editing skill
  tests/                    automated suite
  .local/demo/              editable demo state (seeded, never tracked)
```

## Integration boundary

Host projects use aiset unchanged, supplying paths, descriptors, configuration,
and public API hooks. Host-specific adapters remain outside this directory.
Placement: aidir keeps `aiset/` at the project root; other projects use
`src/aiset/` when a `src/` directory exists, otherwise `aiset/` at the root.

Python environments: normal embedded operation installs aiset into the host
project's venv. Standalone development, tests, and the demo use the local
`.venv/` inside this directory. Both environments install the same package; the
library never activates, creates, or repairs an environment.

## Environment resolver policy

One resolver policy for every host, highest priority first:

1. explicit host overrides;
2. the process environment;
3. a supplied `.env` mapping;
4. the placeholder's inline default;
5. the descriptor/config `default`.

A value from `.env` wins over the config `default`. `:-` uses POSIX shell
semantics and is the only supported operator: `${VAR}` yields the empty string
when the variable is unset or empty, `${VAR:-default}` yields `default` then.
Resolution is single-pass, environment values are data, and `env.allowed` gates
resolution. The browser never receives environment values; server validation is
authoritative.

Hosts that currently behave differently are brought into line during
integration: aidir substitutes before parsing and adopts source-preserving
editing; aibt consults `.env` before the process environment and reverses it;
sndbx already matches the order but adopts the same `:-` semantics; colloc
introduces a JSON5 file through its migration adapter. No host-specific
precedence profile exists in the library.

## Documents

| File | Responsibility |
|---|---|
| [DOCUMENTS.MD](DOCUMENTS.MD) | Document map for the whole project. |
| [SPEC.md](SPEC.md) | Complete specification (read-only for agents). |
| [SPEC_service.md](SPEC_service.md) | Normative Python/HTTP/MCP interface. |
| [IMPLEMENTATION_LOG.md](IMPLEMENTATION_LOG.md) | Implementation plan and work log. |
| [_AGENT_NOTES.md](_AGENT_NOTES.md) | Implementation guidance and pitfalls. |
| [TEST.md](TEST.md) | Test protocol and acceptance mapping. |
| [commands.md](commands.md) | Setup, run, and test commands. |
| [AGENTS.md](AGENTS.md) | Agent workflow (read-only for agents). |
| [memory/context.md](memory/context.md), [memory/history.md](memory/history.md) | Agent working context and change log. |

[AGENTS.md](AGENTS.md) is unchanged and read-only. Corrections to protected
documents are written to a `FILENAME_.md` file as described there.