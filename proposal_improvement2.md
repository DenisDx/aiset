# Further improvements aiset needs, from the aidir host

file version 1.0.0

Written by the aidir side **after** the first round
(`proposal_improvement_aidir.md`) was implemented. aiset is a separate project:
nothing here has been applied to `aiset/`, and nothing here blocks aidir.

Every item was hit while wiring the WebUI and while making the descriptor
coverage gate runnable. They are ranked by how much host code or host risk each
one removes.

**Status: none of these block the migration.** The two that cost the most
(1 and 2) are both already worked around inside aidir, with tests.

**As implemented (2026-10-17).** Items 1-4 are done in `aiset/`; each heading
carries an "As implemented" note. In item 5, the hook-bound greying and the
`commit_report` pass-through are done; the revision diff remains open.

Reproduce with `cd aiset && ./test.sh`.

---

## 1 — The asset path is the application root, so a host must mount twice
> **As implemented.** The dispatcher serves `{base}/assets/<name>` as well as
> `/assets/<name>`, on both transports, so a host that mounts only the API at
> `base` still gets the editor. `AGENT_INTEGRATION.md` section 3 and
> `SPEC_service.md` section 10 state it. Covered in `tests/test_http.py` and
> `tests/test_asgi.py`.

**Impact: medium. Cost the host a second mount and one blank editor.**

### What happens

`create_app` / `create_asgi_app` serve the bundled editor files from
`/assets/<name>` at the **application root**, outside `base`. A host that
follows the documented API-only shape:

```python
app = create_asgi_app(service, base="/api/settings")
```

and mounts that one application gets a fully working API. The browser then asks
for `/assets/aiset.css`, which is *below no mount prefix the host installed*, so
the request falls through to the host's own static handler and 404s. Every route
answers 200, the health check is green, and the settings page renders empty.

This is what happened in aidir. It survived the first round of tests because the
test exercised the bare library application rather than the mounted FastAPI one
(`WebUIMountTests` now covers it).

The related documentation is not wrong - `AGENT_INTEGRATION.md` section 8 says
the assets are included with `include_assets()`, which defaults to `/assets` -
but neither it nor `SPEC_service.md` section 10 says that a host mounting under
a prefix has to mount the same application a second time.

### What would fix it

Either of:

- **Serve the assets under `base` as well.** A request for `{base}/assets/<name>`
  would be answered from the same package directory. Existing hosts that mount
  twice keep working, because the application root path is still accepted.
- **Or make it explicit.** A named argument, for example
  `static_base="/assets"` (default) or `serve_assets_at_base=True`, plus one
  sentence in `SPEC_service.md` section 10 and in `AGENT_INTEGRATION.md` section
  8 saying plainly what a host must mount.

The second is the smaller change and the one that removes the surprise. The first
removes the footgun entirely.

**Acceptance:** an application mounted only at `{base}` serves
`{base}/assets/aiset.css` with the documented `Cache-Control`, or the contract
states the second mount and a host-shaped test in `tests/test_asgi.py` fails when
it is forgotten.

---

## 2 — No CLI check for "does this configuration file match this descriptor"
> **As implemented.** `aiset validate-document --config F --descriptor D
> [--typedef F ...] [--env F] [--strict] [--format json|text]` validates a whole
> configuration file against its descriptor, using explicit resolution inputs
> with `--env`. Covered in `tests/test_cli_and_demo.py` (clean file, undeclared
> key, missing file, `.env`).

**Impact: medium. Every host writes this check itself.**

### What happens

The single most valuable thing aiset offers a host is the guarantee that an
undeclared key makes a document unloadable. The most valuable *check* - "does my
shipped configuration file load cleanly against my descriptor" - exists only as a
library API:

```python
result = service.load("main", principal=Principal.demo())
assert not result.invalid_on_disk, result.reason
```

`aiset validate-descriptor` checks the grammar of the descriptor. Nothing checks
the descriptor against a real file. So every host writes its own gate; aidir's is
`test_config_descriptor.py`, about 60 lines including a fixture `.env` mapping,
a path inventory, and the "which file is loaded under which id" table.

This matters because the failure mode is invisible: a descriptor that misses one
key does not fail the grammar check, does not fail any host test that does not
load that file, and disables the whole settings subsystem at runtime.

### What would fix it

A subcommand next to `validate-descriptor`:

```sh
aiset validate-document \
    --config config.json5 \
    --descriptor config.descriptor.json5 \
    --typedef config.types.json5 \
    [--env .env] [--strict]
```

Exit `0` clean, `1` invalid, `2` usage error, like the existing command. Output
in both `--format text` and `--format json`, the text one naming the exact
configuration path and the descriptor rule that rejected it, which is precisely
the diagnostic a host needs in CI.

With `--env` the resolution inputs are supplied explicitly rather than read from
the process environment, which is what the existing tests already do and what
`AGENT_INTEGRATION.md` section 3 requires.

A `--all` form that walks a descriptor plus a directory of documents would cover
the multi-document case (aidir has seven: the root and six workers).

**Acceptance:** the command loads the document and prints every error-severity
issue; `tests/test_cli_and_demo.py` covers a clean file, a file with an
undeclared key, and a missing file.

---

## 3 — `POST /descriptor/validate` cannot validate against a real document
> **As implemented.** `POST {base}/document/validate` takes `{"document",
> "source"}` and returns `{ok, valid, issues[]}` for a whole candidate document
> without writing or reading the live file (`Service.validate_document`).
> Covered in `tests/test_http.py` and `tests/test_asgi.py`.

**Impact: low to medium. The HTTP twin of item 2 is missing.**

### What happens

The service exposes `POST {base}/descriptor/validate`, which answers "is this
descriptor well-formed". A host that wants "is my *configuration* valid against
my descriptor" over HTTP has no route, so it either keeps an endpoint of its own
(aidir has none, it re-reads and validates in the browser through
`POST {base}/load`) or asks every browser session to discover the problem.

`POST {base}/load` does return the issues, including `invalid_on_disk` and the
reason. That is enough for a person looking at the page and useless for CI: it
is a write-shaped route against the live document, it needs the write
permission, and it returns the whole load result rather than a verdict.

### What would fix it

One read-only route:

| Method | Route | Operation |
|---|---|---|
| POST | `{base}/document/validate` | `document`, `path`, `source`, both revisions; `dry_run` over the candidate |

It validates a candidate document the way `apply_operations(dry_run=True)`
validates an operation batch, without touching the file: same issue shape, same
permissions, same error envelope. A host can then offer a "paste my whole file
and see what is wrong" path in CI or in the editor without a write permission.

**Acceptance:** the route accepts a document and returns
`{ok, valid, issues[]}`; an invalid candidate lists the offending path and rule;
`tests/test_http.py` and `tests/test_asgi.py` cover both transports.

---

## 4 — A snapshot does not say which union alternative matched
> **As implemented.** A snapshot node typed as a `union` carries
> `matched_option`, the index into `children_options` of the alternative the
> stored value validated against. Covered in `tests/test_tree_and_operations.py`.

**Impact: low. Makes the tree editor less explanatory.**

### What happens

After the union resolution fix, `workers.items.<id>` is a union of eight worker
families and every shipped configuration loads. A node in a snapshot reports its
declared `type`, but for a union member it reports `"union"`, so neither the
tree snapshot nor the editor says *which* family the stored value was validated
as.

The consequence is visible exactly where it matters: a worker entry that matches
three alternatives looks identical to one that matches exactly one, and a future
typo inside a `first_available` model entry could be absorbed by a wider
alternative without anybody noticing which rule accepted it.

### What would fix it

One extra field on a snapshot node, for example:

```json
"alternatives": [{"type": "object", "matched": true}, {"type": "object", "matched": false}]
```

or the simpler `"matched_option": 3`. Validation already computes the set
(`_validate_union` tries every alternative); the snapshot only has to report it.

A host can then render "validated as: agent worker" next to the node, which is
the kind of self-documentation the descriptor grammar is meant to produce.

**Acceptance:** a node typed as a union reports which alternative fitted;
`tests/test_tree_and_operations.py` covers a value that matches one alternative
and one that matches none (the latter stays an error).

---

## 5 — Minor items still open

| Item | Note |
|---|---|
| Descriptor `helpers` and `hooks` compile but any write touching a hook-bound node is refused with `UNSUPPORTED_CAPABILITY` | **As implemented.** A node in a hook-bound subtree reports `capabilities.unsupported = "hooks"` with every action false, and the editor shows an "unsupported" badge with the reason; the server still refuses the write. |
| No diff between two revisions | **Still open (deferred).** A host that wants to show "what this Apply will change" must diff the text itself; the staged operations cover most of the need. |
| `CommitReport` is returned by the store but no host-facing result carries it | **As implemented.** `SetResult` and `OperationsResult` carry `commit_report` (including the `uncertain` flag). |
| `env_status` caps at 64 names | documented, but a host with more variables silently gets a partial answer shape; a host may want the total and the count returned. |