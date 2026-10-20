# `doctor`: validate a document and optionally repair it

file version 1.0.0

Proposal for a library API that answers one question in one call: *what is wrong
with this configuration file, and which of those things can be repaired
mechanically?* With `fix`, it repairs the subset that can be repaired without
guessing, through the same atomic operation pipeline as any other write.

Written by the aidir side after a real incident: a host upgraded the library,
and two local configuration files that had been valid for months stopped aidir
at startup, one stale key per run (`endpoints.*.request_timeout`, then
`endpoints.*.context_builder_worker`). The report existed - `LoadResult.issues` -
but it was buried in a startup traceback, and the repair was a human deleting
lines from a mostly-valid file.

Status: implemented in `aiset/` on 2026-10-20. One item changed while building it:
`add_defaults` was dropped, because the descriptor grammar rejects `required`
together with `default` ("required means explicitly present"), so there is no
declared value to add. A missing required key is report-only. `fix=True` is
therefore `clamp` alone. See `IMPLEMENTATION_LOG.md`.

---

## 1. What `doctor` is, and what it must not become

`doctor` is **validation plus a bounded repair pass**, not a configuration
manager:

| It is | It is not |
|---|---|
| A single call that returns every issue with its path and rule | A wizard that decides what the configuration should mean |
| A repair of the classes in section 3 | A general "make it valid" switch |
| Deterministic: same input, same plan, no network, no host callbacks | A migration engine that knows a field was renamed in version N |
| Read-only by default | A startup side effect |

The honest limitation: aiset knows **syntax, shape and the descriptor**. It does
not know that `context_builder_worker` was removed from the host's feature set,
nor whether `8080` in a string was a mistake or intentional. So the repair set is
deliberately small and every change is reported with `before` and `after`.

---

## 2. API

Python, on `Service`, next to `get` / `tree` / `apply_operations`:

```python
def doctor(
    self,
    document_id: str,
    *,
    principal: Principal,
    fix: bool | Iterable[str] = False,
    expected_revision: str | None = None,
    expected_descriptor_revision: str | None = None,
) -> DoctorReport:
    """Validate one document and optionally repair the mechanically fixable issues."""
```

- `fix=False` (default) only reads. It never writes and never changes the
  revision.
- `fix=True` applies the safe class of section 3: `clamp`. This is what a caller
  means by "fix it" in the common case.
- `fix=["clamp", "coerce", "drop_unknown"]` selects explicitly. The lossy
  classes are never implied by `fix=True`.
- `expected_revision` / `expected_descriptor_revision` behave exactly as in a
  write: a stale revision is `428`, not a silent overwrite.

Permissions: the report needs `settings_read_source`, and `settings_read_effective`
when a rule depends on the resolved value (`env_conversion`). Repairing needs
`settings_write`. A doctor with `fix` and no write permission returns the report
and marks every fix as `skipped: forbidden` rather than raising before reporting.

HTTP, next to the other document routes:

```text
POST {base}/document/doctor
{"document": "main", "fix": false,
 "expected_revision": "...", "expected_descriptor_revision": "..."}
```

POST even for the report, because the same route changes behaviour with `fix`;
a GET that silently repairs on a query flag is an accident waiting to happen.

CLI, for operators and for `install.sh`:

```sh
aiset doctor --config config.json5 --descriptor config.descriptor.json5 \
    --typedef config.types.json5 --env .env --format text
aiset doctor --config config.json5 --descriptor config.descriptor.json5 \
    --typedef config.types.json5 --env .env --fix
aiset doctor ... --fix --class clamp,drop_unknown --format json
```

Exit code: `0` when the document is valid, `1` when issues remain, `2` when the
repair was applied but issues remain that need a human. A `--check` alias for the
report form, so `install.sh` can call it without pretending to fix.

---

## 3. Fix classes

Each validator rule maps to exactly one class. The mapping is the contract; a new
rule without a mapping is a new `report_only` entry, never an implicit repair.

| Rule (as `ValueIssue.rule`) | Class | Action | Safe? |
|---|---|---|---|
| `required` | — | report only: **a required node cannot carry a default** | — |
| `minimum`, `maximum`, `exact_range` | `clamp` | `set` to the bound | yes-ish |
| `type` where the source is an unambiguous literal | `coerce` | `set` the typed form | no |
| `undeclared_field`, `undeclared_path` | `drop_unknown` | `remove` the key | **no** |
| `const`, `enum`, `pattern`, `min_length`, `max_length` | — | report only | — |
| `min_items`, `max_items`, `unique_items`, `max_depth` | — | report only | — |
| `max_collection_size`, `max_string_length` | — | report only | — |
| `key_pattern`, `key_enum` | — | report only | — |
| `union` | — | report only | — |
| `nullable` | — | report only | — |
| `env_conversion`, `env_not_allowed`, `unresolved_template` | — | report only | — |
| `read_only` | — | report only | — |
| `comment_preservation`, `parse`, `path`, `value_text` | — | report only | — |

Why each safe class is safe, and each unsafe class is not:

- **A missing required key cannot be repaired.** The descriptor grammar rejects
  `required` together with `default` ("required means explicitly present"), so
  there is no declared value to add. The doctor reports the path and stops.
  Materialising an *optional* default would be semantically neutral but would
  rewrite a large part of the file for no error, so it is not a repair class.
- **`clamp` is deterministic but not intent-preserving.** A port of `70000`
  becomes `65535`; a timeout of `0` under `minimum: 1` becomes `1`. Both are
  plausible, neither is certain. Kept in `fix=True` because a bound is a fact the
  descriptor states, but reported with `before` and `after` so the operator sees
  a value change rather than a silent normalisation.
- **`coerce` is opt-in** because a quoted number is sometimes deliberate (a
  version string, a port kept as text for a template). Never applied to a value
  containing `${` - a placeholder is not a literal.
- **`drop_unknown` is opt-in and lossy.** `context_builder_worker` was genuinely
  dead, but an undeclared key can also be a typo of a declared one. The report
  therefore includes a `suggestion` when a declared sibling is within a small edit
  distance, and `drop_unknown` deletes only what the operator explicitly asked
  for. Deleting is never the default.

---

## 4. Report

```json
{
  "ok": true,
  "document": "main",
  "revision": "sha256:…",
  "descriptor_revision": "sha256:…",
  "valid": false,
  "issues": [
    {
      "path": "/endpoints/0/context_builder_worker",
      "rule": "undeclared_field",
      "message": "Field 'context_builder_worker' is not declared",
      "severity": "error",
      "line": 164,
      "column": 33,
      "fix": "drop_unknown",
      "suggestion": "remove this key; no declared sibling is close to it"
    },
    {
      "path": "/endpoints/0/port",
      "rule": "maximum",
      "message": "Must be at most 65535",
      "severity": "error",
      "fix": "clamp",
      "before": "70000",
      "after": "65535"
    },
    {
      "path": "/tasks/queue_timeout",
      "rule": "required",
      "message": "Required key is missing",
      "severity": "error",
      "fix": null,
      "suggestion": "required with no default; a value must be chosen"
    },
    {
      "path": "/webui/port",
      "rule": "required",
      "message": "Required key is missing and the descriptor has no default",
      "severity": "error",
      "fix": null
    }
  ],
  "fixes": [],
  "skipped": [],
  "applied": false,
  "new_revision": null
}
```

- `fix` per issue is `null` for report-only, otherwise the class that would
  handle it. A host can render "3 fixable, 1 needs a human" from this alone.
- With `fix`, `fixes` lists what was applied, each with `path`, `action`
  (`set` / `add` / `remove`), `before`, `after`, and the originating `rule`.
  `skipped` explains why something fixable was not fixed (permission, a
  conflicting fix on the same path, a lossy class not requested).
- `applied` is false for a dry run; `new_revision` is the revision after a
  successful write, so a caller can chain without re-reading.
- The report is the same shape in Python, HTTP and CLI (`--format json`), and
  the CLI text form is one line per issue, path first, so it can be piped.

---

## 5. Safety invariants

1. **No write without `fix`.** A report-only call leaves the file byte-identical
   and the revision unchanged.
2. **Repairs are operations**, applied through `apply_operations`: one atomic
   batch, revision-checked, comment- and placeholder-preserving. The doctor does
   not get a private write path.
3. **Dry run first, inside the call.** `doctor(fix=…)` builds the batch, applies
   it with `dry_run=True`, and only then writes. A fix that does not validate is
   not attempted.
4. **No secret, no read-only, no const.** A node with `secret: true` is never
   read for a fix and never modified; `read_only` and `const` violations are
   report-only. A hook-bound node is report-only, like any write.
5. **No template surgery.** A value containing `${` is never clamped, coerced or
   reformatted. A key whose value is a placeholder may still be dropped by
   `drop_unknown`, but the report says so explicitly.
6. **Parent before child, child before parent** where it matters: `add`
   operations are ordered outermost-first, `remove` operations innermost-first,
   all operations on one path are collapsed into one, and array indices are
   handled from the highest to the lowest so a removal does not shift a later
   path.
7. **Idempotent.** A second `doctor(fix=…)` on the result returns `valid: true`
   (or only report-only issues) and `fixes: []`.
8. **A parse error ends the run.** No fixes are attempted on a file that does not
   parse; the issue is returned with its line and column.
9. **The file is backed up by the normal write path.** The doctor does not
   invent a second backup scheme; the store's existing `.back` chain applies.

---

## 6. What "obsolete" cannot mean

The request was "delete it if it is no longer relevant". aiset has no signal for
relevance:

- an undeclared key may be a **removed feature** (delete is right),
- a **typo** of a declared key (rename is right),
- a **future field** written by a newer host version (delete is wrong),
- a **host-private key** the descriptor deliberately does not cover (delete is
  wrong, and the descriptor is incomplete).

So the doctor does not classify relevance. It reports the key as undeclared,
optionally suggests a rename, and deletes it only when the operator selects
`drop_unknown`. If a future version wants automatic removal, the descriptor needs
an explicit declaration for removed keys, for example:

```json5
retired_endpoint_option: { type: "any", retired: true, since: "1.2" }
```

That is a descriptor-grammar change and a separate proposal; it is out of scope
here. Mentioned because it is the only honest way to make "delete if obsolete"
automatic.

---

## 7. Host responsibilities (aidir and other hosts)

The library reports and repairs a file. The host owns everything around it:

| Step | Host |
|---|---|
| Run the report at startup | Log a one-line summary (`3 issues, 2 fixable`) and continue if the document still loads; do not auto-fix. |
| Offer the repair | A deliberate action: `aiset doctor --fix` from `install.sh`, or a WebUI "Fix" button that shows the plan first. |
| Reload/restart | Derive from the `apply` policy of the touched paths, exactly as after a manual edit. The doctor returns `new_revision`; it never restarts anything. |
| Secrets | Use a principal without `settings_read_secret`. The doctor must work, and report, without seeing a secret value. |
| Local drift | Keep a copy of the plan in the host log. `drop_unknown` is lossy; the operator's record is the plan, not the doctor's silence. |

### 7.1 A host diagnostic command

The library call is only half of what an operator needs. The other half is the
host's own state: are the containers up, does the port the document names
actually answer, is the virtual environment intact. Each host should expose one
command that answers both, because that is the moment the operator has already
decided something is wrong.

For aidir the command is:

```sh
venv/bin/python core/app.py doctor                 # report: documents + host checks
venv/bin/python core/app.py doctor --config-only   # library doctor only, nothing else
venv/bin/python core/app.py doctor --quick         # one-line summary, used at startup
venv/bin/python core/app.py doctor --fix           # safe repairs
venv/bin/python core/app.py doctor --fix-all       # plus visible and lossy repairs
venv/bin/python core/app.py doctor --root          # allow privileged repairs
venv/bin/python core/app.py doctor --json          # machine-readable
```

This is deliberately the same entry point as the service, so nobody has to
remember a second script, and the exit code can be used by `install.sh` and by
monitoring.

The command must also be discoverable: `-h` / `--help` (and `doctor --help`) in
the same early dispatch, and a two-line hint on every normal start. Both must
work when the configuration does not load, which is when an operator needs them.

The modes are a host concern, but one of them constrains the library directly:
**`--config-only` must be served entirely by `Service.doctor`.** It is the mode
an operator uses to validate a new configuration while a healthy aidir keeps
running, so it must not need Docker, a network call, or a host check. If the
library report cannot stand alone, that mode cannot exist.

Four requirements follow from the library design, and they are the reason this
section is in the library proposal and not only in the host's:

1. **The command must run when the document is invalid.** The whole point is to
   diagnose a broken configuration. If importing the host's configuration module
   raises first, the doctor can never run. The host must dispatch the subcommand
   *before* any eager configuration import - in aidir that means above
   `from core.config import ...`, which builds the process-wide object at module
   import.
2. **The report must not require a valid document.** `Service.doctor` returns
   issues for an invalid document rather than raising, and `Service.load` exposes
   `invalid_on_disk` plus every `ValueIssue`. A host can therefore diagnose a
   broken file with the same service it uses for a healthy one.
3. **Repairs are opt-in and explicit.** `--fix` selects the safe class
   (`clamp`). A lossy class (`drop_unknown`, `coerce`) needs its name, and a host
   that exposes them behind a single button must show the plan first.
4. **The host reports its own checks with the same status vocabulary.** One
   table with `ok` / `warn` / `fail`, a fix and an action per row, so a report
   from the library and a report from the host read as one document.

What the host must not do: fix the library's job in the host (rewrite the file
itself), fix what the library called report-only (guess an enum, invent a
required value), or hide a change. The host adds checks the library cannot make -
process state, containers, ports, permissions - and calls the library for
everything about the file.

The concrete aidir design, including Redis and the container checks, is in
`../proposal_doctor.md` of the aidir repository. It also carries the open
questions; they are host questions, not library questions.

---

## 8. Acceptance

- A document with one out-of-range integer and one undeclared key:
  `doctor(fix=True)` clamps the first, reports the second as `drop_unknown` but
  does not delete it, and **writes nothing** because the document would remain
  invalid.
- `doctor(fix=False)` leaves the revision unchanged and writes nothing.
- `doctor(fix=["drop_unknown"])` removes the key, keeps every comment and every
  `${VAR}` outside it, and the next call reports `valid: true`.
- A second `doctor(fix=…)` is a no-op.
- A required key **without** a default is reported and never invented.
- A `secret` node is never read for a fix and never modified; a principal without
  write permission gets a report with `skipped: forbidden`, not an exception.
- A file that does not parse returns the parse issue and applies nothing.
- A value containing `${` is never coerced or clamped.
- A stale `expected_revision` returns `428` and writes nothing.
- The text report prints one line per issue, path first, in a stable order.

Tests belong in `tests/test_service.py` (report and permissions),
`tests/test_tree_and_operations.py` (the batch and its ordering),
`tests/test_http.py` and `tests/test_asgi.py` (the route on both transports),
and `tests/test_cli_and_demo.py` (exit codes and `--format json`).

---

## 9. Non-goals

- Guessing a value for `enum`, `pattern`, `const` or a missing key without a
  default.
- Rewriting a document to a canonical style, reordering keys, or reformatting.
- Renaming keys automatically, even when a typo is obvious; a suggestion is
  enough.
- Touching any document other than the one named.
- Running automatically at startup, or from a GET.
- Changing the descriptor, or reporting descriptor problems as document issues.
  Descriptor diagnostics already have a surface (`validate-descriptor`,
  `POST /descriptor/validate`).

---

## 10. Open questions

1. **Should `fix=True` include `clamp`?** It changes values. The alternative is
   an empty `fix=True`, with clamping always explicit. Current proposal: include
   it, because a stated bound is a fact, and report the change.
2. **Rename suggestions**: a small edit-distance helper in the library (no
   dependency, ~20 lines) or leave suggestions to the host? Current proposal:
   in the library, because the report is otherwise less useful for the most
   common typo case.
3. **Report-only as a separate method?** `validate_document` already exists for a
   *candidate* source; `doctor` is about the file on disk and adds fixability.
   Keeping one method with `fix` is simpler. Confirmation wanted.
4. **Exit code `2`** for "fixed but issues remain" is a CLI convention; the HTTP
   route returns `200` with `valid: false`, like `load`. Confirm that asymmetry is
   acceptable.
