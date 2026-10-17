# Improvements aiset needs for the aidir integration

file version 1.0.0

Written by the aidir side while embedding aiset as the settings subsystem. Every
item below was hit during the implementation, is reproducible against the
current `aiset/` checkout, and is ordered by how much it blocks a complete,
high-quality integration.

**Status: implemented (2026-10-17).** Every item below is done; see the "As
implemented" note under each heading and `IMPLEMENTATION_LOG.md` phase K. None
of them blocked the migration: aidir shipped with workarounds in place and the
workarounds were removed afterwards. The file stays as the record of what was
asked for, why, and what was decided instead.

Reproduce everything with:

```sh
cd aiset && ./test.sh
```

The reproductions below are the state **before** the fix. They are kept because a
regression test derived from them is the only thing that keeps these defects
out, and because the next host will hit something similar.

---

## P1 — A `union` used as an object member type is invisible to the resolver
> **As implemented.** `_object_child_node(node, key, value)` now looks into
> `children_options`: among the alternatives that declare the key it prefers one
> whose declared type fits the stored value, and takes the first otherwise.
> Validation is unchanged and stays authoritative. The array position keeps its
> documented positional behaviour, now identical to `descriptor.node_at`.
> `SPEC_.md` correction 7; regression tests in `tests/test_resolver.py`,
> including the heterogeneous-array fixture this proposal asked for.

**Impact: high. Workaround in place, but the descriptor is worse because of it.**

### What happens

`aidir` declares `workers.items.<id>` as a `union` of the worker families
(agent, LLM worker, search worker, MCP client, ...), which is the natural way to
say "the shape depends on which worker this is".

The environment resolver does not walk union members:

- `aiset/resolver.py:126` `_object_child_node(node, key)` looks only at
  `node.children` and `node.additional_children`. A `union` node has neither:
  its shapes live in `children_options`.
- So for `/workers/items/call_llama_cpp/request_timeout` the resolver receives
  `node is None` and `resolve_value` returns the value un-substituted, while
  `_resolve_template` reports `env_not_allowed`.

The result is not a warning. `build_effective` reports an error-severity issue,
`Service._analyze` (`aiset/service.py:1022`) discards the state, and the whole
document becomes `invalid_on_disk` with an empty effective dict. **The
configuration subsystem stops working** — every read returns the default and
every write is refused.

Reproduction:

```python
from aiset.resolver import Resolver, build_effective
from aiset.descriptor import compile_descriptor
# root -> workers -> items: { type: "union", children_options: [ {type: "string"}, {type:"int"} ] }
# value: {"items": {"w1": {"request_timeout": "${REQUEST_TIMEOUT:-100}"}}}
```

### Inconsistency that makes it a defect rather than a design choice

The array path already handles this: `aiset/resolver.py:137` `_array_item_node`
returns `option_nodes[0]` when the node is a union, and
`aiset/validator.py:316` `_validate_array` validates each item against the
alternative set. An object member of union type is the only position where the
alternatives are silently dropped.

`aiset/tree.py` and `aiset/descriptor.py:1139` `_array_item_node` also resolve
positionally, so the two helpers do not even agree with each other.

### What would fix it

`_object_child_node` should consider the union alternatives, in the same order
`_validate_union` does: return a node only when exactly one alternative can
carry the value, otherwise return `None` and let validation produce the single
authoritative issue.

```python
def _object_child_node(node, key):
    child = node.children.get(key) if node.children else None
    if child is not None:
        return child
    if node.additional_children is not None:
        return node.additional_children
    if node.option_nodes:                      # union: the alternative that fits
        matches = [opt for opt in node.option_nodes
                   if opt.type == "object" and key in (opt.children or {})]
        if len(matches) == 1:
            return matches[0]
    return None
```

If "exactly one" is too strict to be useful, the alternative is to state in
`SPEC_service.md` that a union member is resolved with `options[0]` for every
position, and to make `descriptor.py:1139` agree. Either way, the behaviour has
to be documented, because today a descriptor that looks correct silently
produces an unusable document.

**Acceptance:** the reproduction below loads cleanly; the `env_not_allowed` error
disappears; a union whose members disagree on the type still reports one clear
issue.

Reproduction (verified against the current checkout):

| stored value at `/workers/items/w1/request_timeout` | `union` member | plain object |
|---|---|---|
| `${REQUEST_TIMEOUT:-100}` (unquoted) | **invalid** - `env_not_allowed` | valid |
| `"${REQUEST_TIMEOUT:-100}"` (quoted) | **invalid** - `union ... matches none` | valid, see P2 |
| `100` | valid | valid |

---

## P2 — A quoted placeholder can never be converted to a non-string type
> **As implemented.** `_convert` lost the second parameter; both call sites pass
> the resolved text, which is what the function always needed. Covered for int,
> bool and an inline default in `tests/test_resolver.py`.

**Impact: high, and it fails loudly, so it is found immediately.**

### What happens

`aiset/resolver.py:96` resolves a placeholder inside a string and then calls
`_convert(resolved, node, path, issues)` **without** the `raw` argument. Inside
`_convert` (`aiset/resolver.py:185`):

```python
text = (raw if isinstance(raw, str) else str(raw)).strip()
```

`raw` defaults to `None`, so `text` becomes the literal string `"None"` and the
conversion always fails. The unquoted path is unaffected, because
`_resolve_template` passes `raw=value` explicitly.

The minimal reproduction:

```python
node = <"int" node with env: {allowed: true, convert: "int"}>
resolve_value("${REQUEST_TIMEOUT:-100}", node, Resolver(dotenv={}, environ={}), "/rt", issues)
# -> (None, [env_conversion: "Value cannot be converted to int"])
resolve_value(100, node, ...)
# -> (100, [])
```

### Why it matters for aidir

`aidir` declares `convert: "string"` on every quoted placeholder, so it is not
blocked today - but a host that writes `"${PORT:-8080}"` (quoted, as JSON5
normally requires for a numeric-looking value in a string context) gets a
document that will not load, and the message points at the conversion instead of
at the missing argument.

### What would fix it

One line, in the string branch of `resolve_value`:

```python
return _convert(resolved, node, path, issues, raw=resolved)
```

**Acceptance:** the reproduction returns `100`; `tests/test_resolver.py` covers
both the quoted and the unquoted spelling of the same placeholder.

---

## P3 — The descriptor grammar cannot express a free-form JSON region
> **As implemented.** `type: "any"` exists: it accepts every JSON value including
> `null`, rejects composite keys and key constraints like any scalar, keeps the
> operational limits, treats a member placeholder as literal, and is a `leaf` in a
> snapshot and source text in the editor. `SPEC_.md` correction 6;
> `tests/test_descriptor.py` and `tests/test_service.py`.

**Impact: medium. `aidir` ships a bounded workaround that will need raising.**

### What happens

`workers.items.context_add_internal_tools.tools` is typed
`Dict[str, Dict[str, Any]]` by its worker (`core/workers_loader.py`, the worker
docstring is explicit about it). The grammar offers no way to say "any JSON
value here":

- `additional_children` requires a `type` (`aiset/descriptor.py:450`), and
- `validate_value` (`aiset/validator.py:185`) rejects every key of an object
  whose node has neither `children` nor `additional_children`.

So the only options are to under-declare (the first real tool declaration breaks
the entire document) or to spell out a nesting depth.

`aidir` currently ships `json_leaf` / `json_value_1` / `json_value` in
`config.types.json5`: three levels of object and array nesting, ~60 lines,
maintained by hand, with a comment saying it exists only because of this gap.

### What would fix it

A primitive `any` type that accepts every JSON value, including `null`:

```json5
tools: {
  type: "object",
  key_pattern: "^[A-Za-z0-9._-]+$",
  additional_children: { type: "any", description: "Free-form tool declaration" },
}
```

`type_matches("any", value)` returns `True`, `_validate_object` accepts any
member, and the editor renders the node with the raw source control the library
already has. It is a small, well-contained addition: one entry in
`PRIMITIVE_TYPES`, one branch in `type_error`, one in `build_node`, one in the
portable regex/literal checks that inspect the type.

The risk to manage is misuse: `any` must not become the default answer for an
understood node. `validate_descriptor(mode="strict")` is the place to warn.

**Acceptance:** `type: "any"` validates any JSON value; `examples/descriptor.json5`
grows a fixture for it; `aidir`'s `json_value` typedef collapses to one line.

---

## P4 — The library is WSGI-only, and Starlette's WSGI bridge is deprecated
> **As implemented.** `aiset.asgi.create_asgi_app` is a plain ASGI application over
> the dispatcher that the WSGI adapter already uses, so the transports cannot
> drift. It offloads to a worker thread under asyncio, bounds the body read, and
> takes `principal_from_scope(scope)` for asynchronous authentication - the case
> the old bridge could not express. `PATH_INFO` deliberately keeps the full path.
> `SPEC_service.md` section 10a; `tests/test_asgi.py` compares it route by route
> against the WSGI adapter.

**Impact: medium. `aidir` ships a 90-line bridge it would rather not own.**

### What happens

`aiset.httpd.create_app` returns a WSGI application. Every ASGI host therefore
needs an adapter. The obvious one is gone:

```python
from starlette.middleware.wsgi import WSGIMiddleware   # FastAPI dependency
# .../starlette/middleware/wsgi.py:11: warnings.warn("starlette.middleware.wsgi
#     is deprecated and will be removed in a future release.")
```

`aidir` runs FastAPI 0.115 / starlette 0.46, where the module still works but
warns, and it cannot carry a host-provided `Principal`: `build_environ`
constructs a fixed key set and never reads `scope["extensions"]`, so the
authenticated principal cannot be injected without patching the environ after
the fact.

`aidir` therefore has `core/settings/asgi.py`: environ construction, body
reading, thread offload, response assembly. It is transport plumbing, not
library behaviour, but it is code the library is better placed to own.

### What would fix it

Either of:

- **`create_asgi_app(service, base=...)`** next to `create_app`, returning a pure
  ASGI callable. ~80 lines in `httpd.py`, no new dependency, works under uvicorn
  and hypercorn directly. The WSGI app can then be defined in terms of it.
- or document an officially supported bridge (`a2wsgi`) in `SPEC_service.md`
  and in `AGENT_INTEGRATION.md` section 6, with the environ-injection caveat and
  the recommended pattern for authenticated hosts.

The first is clearly better for a library whose stated goal is "embed aiset in a
Python host", since most modern Python hosts are ASGI.

**Acceptance:** an ASGI app mounts under a path prefix, receives a host-provided
`principal_resolver`, and is covered by `tests/test_http.py`.

---

## P5 — The assets are only served when `static_dir` is set
> **As implemented.** `/assets/*` is served from the installed package regardless
> of `static_dir`, and without a host directory no other path resolves at all -
> nothing is ever looked up against the process working directory. Covered in
> `tests/test_asgi.py`.

**Impact: low to medium. Costs the host a second mount.**

### What happens

`aiset/httpd.py:57` only reaches `_static` when `static_dir` is not `None`:

```python
if static_root is not None:
    return _static(start_response, static_root, path, asset_root, static_map or {})
```

A host that only wants the API (`create_app(service, base="/api/settings")`,
which is the shape recommended in `AGENT_INTEGRATION.md` section 3) therefore
cannot serve `aiset.css`, `aiset.js` or `aiset-tree.js` at all, and a request to
`{base}/assets/...` is answered `NOT_FOUND` by `_handle_api` before `_static`
is ever consulted.

`aidir` works around it with two mounts: the WSGI app under `/api/settings` with
`static_dir=None`, and a plain `StaticFiles` mount of
`aiset.assets.ASSETS_DIR` at `/assets`. The host then owns the
`Cache-Control: no-cache` rule that `httpd.py:293` states is mandatory.

### What would fix it

Serve `/assets/*` from `asset_root` regardless of `static_dir`:

```python
if static_root is not None or path.startswith("/assets/"):
    return _static(start_response, static_root or Path(), path, asset_root, static_map or {})
```

`_static` already guards every entry with `is_file()` and rejects `/` and `..` in
the name, so an empty `static_root` cannot escape the package directory.

**Acceptance:** `create_app(service, base="/api/settings")` alone serves
`/assets/aiset.css` with `Cache-Control: no-cache, must-revalidate`;
`tests/test_http.py` covers it.

---

## P6 — `apply` has no way to say "the host handles this itself"
> **As implemented by documentation.** No fourth state was added: `live` already
> means "the next read sees the value", which is the no-action case, and a node
> that leaves `apply` unset asks for `restart` rather than pretending to be live.
> `SPEC_service.md` section 4 now carries the four states as a table with the host
> action each one implies, and `service._apply_change` says the same next to the
> code that produces it.

**Impact: low. A reporting gap, not a failure.**

### What happens

`aiset/service.py:67` `APPLY_ORDER = {"live": 0, "reload": 1, "restart": 2}` and
`_apply_change` return one of `applied`, `reload_required`, `restart_required`,
`apply_failed`. A host whose configuration mixes live log levels with
restart-required ports has to guess which of the three buttons to show, and the
editor's `lifecycle` option only renders host-declared buttons.

`aidir` shows both "Reload settings" and "Restart aidir" unconditionally and
lets the user choose, which is correct but imprecise.

### What would fix it

Nothing structural is needed: document that `application.state` is the contract
and that `changed_paths` together with the descriptor `apply` values is what the
host should use to decide which action to offer. If a fourth state is wanted,
`"host"` (the value is applied by a host callback, nothing else required) would
cover exactly this case and needs no new machinery - only a new name in
`APPLY_ORDER` handling.

---

## P7 — `on_after_save` has an unwritten callback contract
> **As implemented, with a guard rather than only text.** The three callback
> signatures are written down in `service.py` next to the registration methods and
> in `SPEC_service.md` section 16, including the `ChangeEvent` fields. Because the
> commit-time boundary swallows every exception, a callback that cannot receive
> the documented arguments now raises `TypeError` **at registration** - the exact
> silent-stale-cache bug this item describes cannot happen again.

**Impact: low, but it cost a real bug.**

### What happens

`Service.on_after_save` (`aiset/service.py:381`) registers a callback that
`_notify` invokes as `callback(previous_stored, new_stored, event.to_dict())`.
The signature appears only in `SPEC_service.md` prose. `aidir` first guessed
`(document_id)` positionally, stored a dict where a `str` was expected, and
swallowed the resulting exception inside aiset's `_safe_call` - so the effective
cache silently stopped refreshing after every write made through the HTTP API.

The failure was invisible: writes reported success, the file changed, the API
returned the new value, and only the running process kept the old one.

### What would fix it

- Name the contract in `AGENT_INTEGRATION.md` section 4 next to the other
  callbacks, with the exact argument list.
- Consider raising (not swallowing) a callback whose signature does not match, or
  at least logging the argument count at registration time.

A cheaper alternative that removes the footgun entirely: let a host pass the
document id, for example `service.on_after_save(callback, document=...)`.

---

## P8 — Minor items
> **As implemented.** Descriptor issues carry `line` and `column`, read from the
> same CST the editor uses, with a missing property reported at its nearest
> existing ancestor. `CommitReport.to_dict` moved into its class and its
> `document_id` reference was corrected - it could never have worked. The dead
> `and False` expression in `tree._origin_of` is gone. `examples/` is frozen, so
> the missing union fixture became tests instead of an example. The stale counts
> in README, AGENT_INTEGRATION and commands were replaced by a pointer to
> `./test.sh`, which is how the next reader gets a true number.

| Item | Note |
|---|---|
| Descriptor diagnostics have no line or column | `descriptor.py` reports `path` only, while value issues carry `line`/`column`. A `descriptor.json5` typo in a 1200-line file is found by reading, not by jumping. `Issue` already has the fields. |
| `examples/descriptor.json5` is missing a `union` array fixture with per-item types | The union resolution defect of P1 would have been caught by a fixture. |
| `README.md:48` says 230 tests, `AGENT_INTEGRATION.md` says 332 | Stale counts in several places; harmless but they mislead. |
| `store.py:107-115` | `CommitReport.to_dict` is defined at module indentation level, so it is a module function, not a method. It works; it reads as a bug. |
| `tree.py:297` | `out.pop("variable", None) if ... and False else None` is dead code. |
