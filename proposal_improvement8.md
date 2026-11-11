# Python aiset improvements from the aiset-flutter implementation

Status: draft
Approval: F1 is confirmed by the project owner (2026-11-11); A1–A21 are proposed.

## Scope and requirements

The `aiset-flutter` project built a compatible Dart/Flutter product against
baseline `main` @ `cbb74c7` (2026-10-23), Python 3.14.4, imported with
`PYTHONPATH=src` and zero runtime dependencies. Every defect below was
reproduced by executing that baseline. This proposal records the defects in the
Python library and the one cross-project feature request.

Included: mutation round-trip safety (A1–A3, A9), parser and path diagnostics
(A4–A6), packaging and test robustness (A7, A8), descriptor validation and
composition (A10–A21), and localized descriptor text (F1).

Excluded: changes that would reproduce a baseline defect in the Dart product;
F1 direction changes that are still open (see "Open questions"); any change to
the descriptor/configuration format beyond F1.

The items share three failure shapes:

- **Silent source corruption.** A mutation reports success but produces source
  that the same library cannot parse. A single postcondition — "the result must
  re-parse" — plus a full-output round-trip test catches all of them.
- **Interpreter errors escaping the documented hierarchy.** Callers that catch
  `AisetError`/`InvalidDescriptor` crash on ordinary user mistakes.
- **Grammar accepts what it cannot use.** A constraint disappears, a file
  passes validation and then crashes the validator, or a feature is unreachable
  through the validator.

### Defect summary

| ID | Severity | Area / location | Required behaviour |
|---|---|---|---|
| A1 | high | `jsonsrc.Document._array_replacement` | Equal-length array replacement must return only the replaced node's text. `apply_set('/list', '["x","y","z"]')` must re-parse and keep comments. |
| A2 | high | `jsonsrc.Document.apply_move` / `_render_array_body` | Moving an item must not re-emit a document-level comment inside the array. The comment stays where it was; the result re-parses. |
| A3 | high | `jsonsrc.Document.apply_rename` | Reject a new key containing control characters or line breaks; otherwise quote it. An accepted rename always re-parses. |
| A4 | medium | `jsonsrc.Parser.parse_key` (and truncated-input paths) | `Document('{')` and `Document('{a: 1')` raise a positioned `ParseError`, not `IndexError`. |
| A5 | medium | `jsonsrc.Parser.parse_escape` | A malformed `\x` escape is a positioned `ParseError` with `PARSE_ERROR`, not a Python `ValueError` that echoes file content. |
| A6 | low | `jsonsrc.Document.apply_add` | Distinguish "parent is not an array" from "array index out of range"; include the pointer and the real reason. |
| A7 | low | packaging | Add a `LICENSE` file with MIT text and the intended copyright holder; it currently exists only as metadata in `pyproject.toml`. |
| A8 | low | `demo2/tests/test_app.py::run_launcher` | The launcher test must not depend on a hardcoded 30-second process timeout. Separate seeding from serving or poll for seeded files. |
| A9 | high | `jsonsrc.Document._create_member` | Creating a member in an inline object must emit `{ a: 1, b: 2 }`, not `{ a: 1 , b: 2}`; the result re-parses. |
| A10 | high | `descriptor.validate_descriptor` | Check that the document root is an object before `_check_envelope` calls `.get`. A non-object descriptor produces the documented diagnostic; `compile_descriptor` raises `InvalidDescriptor`, not `AttributeError`. |
| A11 | high | `descriptor._check_node` / `PROPERTY_TYPES` | `minimum` and `maximum` are numbers and `enum` is a list. A bad one is `INVALID_PROPERTY_TYPE`; it must not crash the validator or silently disappear. |
| A12 | medium | `errors.DescriptorError` | Composition failures carry a stable code (`INVALID_DESCRIPTOR`) and the documented error hierarchy, not a bare `ValueError`. |
| A13 | medium | `descriptor._mount` | Check free space at the final mount position only. Walking through an existing node is not a collision; a missing intermediate reports "does not exist". |
| A14 | medium | `descriptor._check_envelope` | Unknown envelope keys emit `UNKNOWN_DESCRIPTOR_PROPERTY`: warning by default, error in strict mode. |
| A15 | medium | `descriptor._check_node` | Compile-check `key_pattern` like `pattern` and report `INVALID_PATTERN` at `<node>/key_pattern`. |
| A16 | medium | `descriptor._check_default` | Check a default after template expansion, so a template-typed node gets the same `INVALID_DEFAULT` result as its expanded form. |
| A17 | medium | `descriptor._check_node` | Resolve a template reference to the type it defines before applying type-applicability rules. Composite keys on a template-typed node are valid and reach the existing merge logic. |
| A18 | medium | `descriptor._merge_template` | Merge two array item nodes as nodes. The array item template must carry both the template constraints and the reference overrides. |
| A19 | low | `descriptor._check_scalar_constraints` | Report one diagnostic per misplaced constraint; `type: "any", minimum: 1` must not be reported twice. |
| A20 | low | `descriptor.compile_descriptor` | Post-composition issues must not carry positions inside a generated `json.dumps` string. Validate the composed structure directly or map positions to the origin file. |
| A21 | low | `descriptor.compile_descriptor` | Label each typedef source and fragment by its argument kind. The second typedef source must not be reported as `<fragment>`. |

### F1 — localized `description` and `title`

Status: accepted for implementation in the Python version (project owner,
2026-11-11). Both implementations must follow one rule set so that a descriptor
written for one renders the same in the other.

`description` and `title` accept exactly two forms:

```json5
// form 1 — string (unchanged and still the compatible default)
{ retries: { type: int, description: 'Number of retry attempts' } }

// form 2 — language-tagged object
{
  retries: {
    type: int,
    description: {
      default: 'en',
      text: { en: 'Number of retry attempts', ru: 'Число попыток повтора' },
    },
  },
}
```

The object has `text` (required: map of normalized language tag to non-empty
string) and `default` (optional: language tag used when the active locale has no
entry; when absent, the descriptor document's default language is used). A bare
map without the wrapper (`{ en: '…', ru: '…' }`) must not be accepted: it is
ambiguous with an object-valued setting and cannot name a default.

Normative rules:

- **R1 — the string form is unchanged.** Existing descriptors parse and render
  exactly as before; no migration.
- **R2 — a string is also a translation key.** A locale-aware reader looks up the
  string in the active locale's resources; when no translation exists, it
  displays the string itself. Untranslated content is never empty, a key, or an
  error.
- **R3 — the object must resolve to a string.** It must contain an entry for its
  `default`, or for the document default language when `default` is omitted. An
  object that cannot resolve is a descriptor error, not a silent fallback.
- **R4 — locale-unaware readers still get a string.** A CLI, a health endpoint, a
  log line, or a legacy export resolves the object to its default-language text.
- **R5 — resolution order.** Active-locale entry → host-supplied translation for
  the string key → default-language entry → the string itself. A value obtained
  at any step is not passed through a later step again.
- **R6 — comments are never translated.** A source comment may still supply a
  description as today and is treated as default-language text. Where both a
  field and a comment exist, the field wins.
- **R7 — `title` behaves identically.**
- **R8 — tags are BCP-47**, compared case-insensitively after normalization
  (`RU` → `ru`, `zh-hans` → `zh-Hans`). A malformed tag is a descriptor error at
  the field; a well-formed tag no reader uses is ignored.
- **R9 — unknown keys inside the object are a descriptor error.** A typo such as
  `defualt` must not disable the default-language rule.

Errors: empty object; missing `text`; non-string entry in `text`; `default`
naming a tag absent from `text`; no `default` and no document default; malformed
language tag; unknown key inside the object.

Legacy export: when a descriptor is exported for a string-only consumer, each
localized `description` and `title` is flattened to its default-language text in
the exported copy. The original file is never modified.

## Implementation plan

- [ ] **A1** — Return only the replaced node's text from
  `_array_replacement`; keep the `_replace_node` splice contract. Add a
  full-output assertion and a re-parse assertion.
- [ ] **A2** — In `apply_move`, keep document-level/opening comments outside the
  replaced array span (or do not re-emit them into the body). Add a round-trip
  test for the document-comment case.
- [ ] **A3** — Validate the new key as one identifier (`fullmatch`, not `match`)
  or a quoted string; reject control characters and line breaks with
  `PathError`. Add a re-parse assertion.
- [ ] **A4** — Guard every `self.text[self.pos]` access in `parse_key` and the
  parser entry points; truncated input raises a positioned `ParseError`. Add
  tests for `{`, `[`, `{a: 1`, and a truncated string.
- [ ] **A5** — Validate all `\x` digits as hexadecimal before conversion, as the
  `\u` branch already does.
- [ ] **A6** — In `apply_add`, if the parent is an `ArrayNode`, report "index out
  of range" (or "use the `-` append token"); reserve "does not address an
  object" for a genuinely non-container/non-object parent.
- [ ] **A7** — Add `LICENSE` with the MIT text and the copyright holder confirmed
  by the project owner. Keep `pyproject.toml` metadata consistent with it.
- [ ] **A8** — Give `run_demo2.sh` a seed-only mode, or make the test poll for
  the seeded files and terminate the launcher. Remove the hardcoded 30-second
  expectation from the success path.
- [ ] **A9** — In `_create_member`, insert the separator directly after the
  previous value, preserving the closing brace's leading whitespace. Add a
  full-output and re-parse test for inline objects.
- [ ] **A10** — Move the `isinstance(data, dict)` guard before
  `_check_envelope` in `validate_descriptor`; ensure `compile_descriptor` and
  `_collect_typedefs` raise `InvalidDescriptor` for a non-object descriptor.
- [ ] **A11** — Remove `enum`, `minimum`, and `maximum` from the property-type
  skip in `_check_node`; keep `type`, `const`, and `default` skipped. Report
  `INVALID_PROPERTY_TYPE` with the property path.
- [ ] **A12** — Make `DescriptorError` part of the documented hierarchy (subclass
  `InvalidDescriptor`/`AisetError` with code `INVALID_DESCRIPTOR`) while keeping
  its `path` and `as_issue`. Check every composition failure path.
- [ ] **A13** — In `_mount`, apply the free-space check to the final token only;
  a missing intermediate token reports "does not exist".
- [ ] **A14** — Define the allowed envelope keys and report each unknown key as
  `UNKNOWN_DESCRIPTOR_PROPERTY`, promoted to an error in strict mode.
- [ ] **A15** — Mirror the `pattern` compile-check for `key_pattern`, reporting
  `INVALID_PATTERN` at `<path>/key_pattern`.
- [ ] **A16** — Pass the collected templates to `_check_default` (or check
  defaults after `expand_templates`) so the type and constraints being checked
  are the resolved ones.
- [ ] **A17** — Before the object/array/union/scalar applicability checks in
  `_check_node`, resolve a `type` that names a template to the type defined by
  that template. Keep the existing recursion and cycle checks.
- [ ] **A18** — In `_merge_template`, when both `children` values are item nodes
  (`is_item_node`), merge the two node dictionaries instead of passing their
  `type` strings to `_merge_template`.
- [ ] **A19** — Iterate constraints once, not once per declaring type, or
  deduplicate the emitted issues.
- [ ] **A20** — Validate the composed structure with `_check_*` directly instead
  of `validate_descriptor(_dump(data))`; otherwise map generated positions back
  to the descriptor/fragment source.
- [ ] **A21** — Build the origin labels as
  `["typedef source"] * len(typedef_sources) + ["fragment"] * len(fragments)`
  instead of alternating labels by position.
- [ ] **F1** — In `descriptor.py`, accept both forms and validate R3, R8, R9;
  keep the compiled node's `description`/`title` resolved to the
  default-language string. In `tree.py`, carry the full localized value plus the
  active-locale string. Leave `validator.py` unaffected. Add a doctor check for
  localized fields and implement legacy export as a copy-only flattening.
- [ ] Add cross-cutting regression tests: every mutation operation asserts full
  output and re-parses; every descriptor failure asserts the stable code; F1
  covers the shared matrix below.
- [ ] Update `SPEC_service.md` where the interface or diagnostics change, and
  `SPEC_.md` only for approved product requirements, following `AGENTS.md`.
- [ ] Record implementation decisions and verification in
  `IMPLEMENTATION_LOG.md`.

## Acceptance and verification

Observable criteria:

- A1, A2, A3, A9: the exact output is asserted, and feeding it back to
  `Document(...)` succeeds; comments that are not part of the edited node are
  preserved.
- A4, A5: each malformed input raises `ParseError` with `code == "PARSE_ERROR"`
  and a line/column.
- A6, A10–A21: each case returns the documented issue code/path or raises the
  documented error type; no `AttributeError`, `IndexError`, `TypeError`, or bare
  `ValueError` escapes.
- A7: `LICENSE` exists and matches the declared MIT license.
- A8: the launcher test passes in a constrained container without relying on the
  process exit within 30 seconds.
- F1: the shared matrix passes: (1) string form unchanged; (2) object with
  `default`, active locale and fallback; (3) object without `default`, document
  default present; (4) unresolvable object is a descriptor error with the field
  path; (5) `title` mirrors all four; (6) comment-only description unchanged and
  never translated; (7) field wins over comment; (8) legacy export flattening
  leaves the original byte-identical; (9) tag normalization and malformed-tag
  rejection; (10) string-form descriptors remain readable by older readers.
- Valid inputs keep their current byte-for-byte source-preserving behaviour.

Verification commands: `./test.sh` (the single source of truth for the test
count), then the focused suites affected by each group. Test results are recorded
in `IMPLEMENTATION_LOG.md`, not here.

### Open questions for F1

Do not implement either direction until decided:

- Can a host translation override an entry inside the object? Current
  `aiset-flutter` default: no — an inline object is final; the host translator
  applies only to the string form.
- Is the string form's key the literal text or a stable identifier? Current
  default: the literal text. Editing the source text then orphans translations;
  a stable key avoids that at the cost of harder authoring.

Compatibility window: the object form is not mutually readable until the Python
implementation lands. Descriptors shared with the current Python release should
stay in the string form; the compatibility corpus is re-baselined after the
implementation, not before.
