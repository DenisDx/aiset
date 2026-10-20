# Corrections to the frozen aiset specification

Target document: `SPEC.md` (agent-write-protected, per `AGENTS.md`).
Reason: `proposal_demo2.md` implements milestone M4 capabilities that the frozen
specification currently places out of scope for v1. The implementation follows
the proposal; this file records the exact corrections so `SPEC.md` can be
updated by its owner.

---

## Correction 1: structural editing and batches are no longer "later operations"

### Old text (SPEC.md 5.3.6 "Out of scope for v1")

```text
Deletion, array append/insert/remove, batch edits, and full-document editing are
later operations, not part of this contract. When implemented, they are carried
out as independent sequential operations: v1 provides no multi-operation
transactions, no cross-operation locking, and no all-or-nothing atomicity. A
failed or partially applied sequence is recovered by loading the Last Known Good
configuration (section 14.8), not by rollback. Existing aidir editors remain
available through compatibility facades and must not claim the preservation
guarantee until they use the new store.
```

### Reason for the correction

`proposal_demo2.md` sections 7.3, 7.4 and 8.2 require deletion, array
append/remove, reordering, and a staged batch that is applied atomically. The
frozen text forbids exactly that batch, so the proposal and the specification
contradict each other. The specification already anticipates phase 4 as the
phase that adds removal, array append/insert/remove and reordering (section 17,
phase 4), so the contradiction is about ordering and about the word
"transaction", not about the features themselves.

### Recommended new text

```text
Deletion, array append/insert/remove, reordering, batch edits, and
full-document editing were phase 4 operations and are now implemented as the
structural operation set of section 5.3.7.

A structural operation is still one localized source edit, applied against one
in-memory candidate document. When a client stages several operations, they are
applied to that single candidate and committed as one write under the existing
store lock. This is not a transaction system: there are no partial commits, no
rollback log, and no cross-process locking beyond the store lock that already
exists. An operation that fails aborts the whole staged batch, and the file on
disk is left byte-for-byte unchanged. Recovery of an already stored but
operationally broken configuration still uses the Last Known Good configuration
(section 14.8).

Single-value `validate()` and `set()` remain available and keep their existing
semantics.
```

---

## Correction 2: new sections for the tree snapshot, operations, and UI asset API

### Old text (SPEC.md 17, phase 4)

```text
Add, each separately reviewed: removal, array append/insert/remove and
reordering (moving each item's comments with it), history listing and restore
from the backup chain, revision diff/approval, standard-control overrides,
helper micro-forms/wizards, generated forms, and change subscriptions.
```

### Reason for the correction

Removal, array append/insert/remove, reordering, and generated forms are now
implemented (milestone M2 of `IMPLEMENTATION_LOG.md`), driven by the `demo2`
host. The generated tree editor, the tree snapshot operation, and the atomic
operation batch are not described anywhere in the frozen specification, yet they
are part of the public interface now implemented in the library and used by a
host.

### Recommended new text

Three new sections should be added to the specification, mirroring
`SPEC_service.md` sections 20-22, which are the normative interface:

```text
### 5.3.7 Structural operations

A structural operation is one of `set`, `add`, `remove`, or `move`, addressed by
JSON Pointer. `add` uses the `-` token to append an array item, or names a new
key of an object that permits one; `move` takes one array item to another index.
An operation authorizes and validates every affected path, preserves the source
bytes and owned comments of everything it does not touch, and rejects unsafe
comment ownership with `COMMENT_PRESERVATION_CONFLICT`.

Staged operations are applied to one in-memory candidate and committed as one
write; see Correction 1 for the exact scope of that guarantee.

### 8.4 Tree snapshots

`service.tree()` returns one consistent, authorized snapshot of a subtree:
descriptor nodes, stored source fragments, effective origin metadata without
resolved secrets, and per-node capabilities (edit, add, remove, reorder,
add/remove child, key options, key pattern). The browser renders a whole
configuration from a single revision instead of issuing one request per node.

### 9.1 Generated editors

The shipped UI assets provide `render_tree_editor`, `mountTree`,
`getPendingOperations`, `stageOperations`, `validatePending`, `applyPending`,
and `reload`. A generated editor stages changes and commits them as one
operation batch; it is a presentation of the same service, never a second
validation or persistence implementation. `render_full_editor()` is the
generated tree editor.
```

---

## Correction 3: phase 4 list

### Old text (SPEC.md 17, phase 4)

```text
Add, each separately reviewed: removal, array append/insert/remove and
reordering (moving each item's comments with it), history listing and restore
from the backup chain, revision diff/approval, standard-control overrides,
helper micro-forms/wizards, generated forms, and change subscriptions.
```

### Reason for the correction

Removal, array append/insert/remove, reordering, and generated forms are done;
the phase plan must reflect that.

### Recommended new text

```text
Implemented: removal, array append/insert/remove and reordering (each item's
comments move with it), generated tree editors, and the atomic staged batch.

Still phase 4: history listing and restore from the backup chain, revision
diff/approval, standard-control overrides, and helper micro-forms/wizards.
```
---

## Correction 4: environment placeholders and raw source editing in the generated tree editor

### Old text

SPEC.md section 9, "First reusable UI", controls:

```text
1. Parameter path input using JSON Pointer, with a visible path example.
2. **Read** button and source-value textarea supporting multiline JSON5.
3. Field description/type/range/required/read-only information.
4. **Validate** and **Save** buttons.
5. Explicit local/server validation, conflict, persistence, and application status.
```

SPEC.md section 9, closing scope note:

```text
Full config viewing, generated forms, tree navigation, completion, specialized
secret widgets, deletion, and list-reordering UI are outside the first editor.
Existing aidir raw/logging controls are not removed by aiset.
```

SPEC.md section 6, resolver policy (relevant part):

```text
- Placeholder resolution is disabled unless the node's `env.allowed` is true.
  Disabled placeholders inside strings remain literal text; unquoted placeholders
  at such a node are invalid. This is the only literal/escaping mechanism in v1.
```

### Reason for the correction

The tree editor shows the stored source of a node, but it offers only a control
for the declared type. For a node whose stored value is a placeholder
(`${DEMO2_PORT:-8383}`, or `"${DEMO2_HOST:-0.0.0.0}"` inside a string) that
control cannot represent the value:

- an `int` control rejects the token and renders empty, so the field looks unset;
- the inline fallback of the substitution cannot be changed through the UI;
- staging any value overwrites the placeholder and silently removes the
  substitution, which is exactly the information the user must not lose.

Two related gaps: a generated editor cannot show the raw source of a whole
object (comments included) although the first editor has a multiline source
textarea for a single path, and nothing tells the user whether the variable
behind a substitution is actually set.

### Recommended new text

Add to section 9:

```text
Generated editors (SPEC_service.md section 21) edit a node in one of three
modes, all of them staged and validated by the same server:

1. Typed control per declared type, including enum, bool, number and the
   `null` switch for nullable nodes.
2. Raw source mode for any node, including a whole object or array. The raw
   fragment is stored exactly as written: JSON5, comments, quoting and
   placeholders are preserved. While it is open, the children of the node are
   not rendered. Leaving the mode stages one `set` operation with the fragment
   after the server has validated it; a fragment that is not valid JSON5 or
   does not match the declared structure is reported with the server issues and
   nothing is staged.
3. Placeholder mode for a node whose stored value is a placeholder, and for any
   node whose descriptor sets `env.allowed`. The variable name and the inline
   `:-` fallback are two separate controls, the fallback using the control of
   the declared type. Editing either one rewrites the placeholder token instead
   of replacing it with a bare value. An empty variable name stores the inline
   value and returns the node to placeholder-free mode. A node that has no
   placeholder gets a button that switches it into placeholder mode. A
   placeholder cannot be introduced where the descriptor sets
   `env.allowed: false`, or on an object or array in v1.
```

Add to section 6:

```text
- Environment diagnostics may report whether a variable is set, never its value.
  A generated editor shows this next to the placeholder control so the user can
  tell whether the file or the inline fallback decides the effective value. The
  presence query is permissioned like any other read and answers with booleans
  only.
```

---

## Correction 5: merge precedence is a parameter, and the base wins by default

### Old text

SPEC.md section 10.1, Merge contract:

```text
- Exactly two inputs: a base and an update. The update has priority.
- The update may be a partial configuration and may target any node or section
  of the base.
- The algorithm is recursive. For each field present in both values:
  - if both values are objects, merge them recursively by these rules;
  - otherwise (scalars, arrays, `null`, or a type mismatch) the update replaces
    the base value; arrays are replaced in full, not element by element.
  Then fields present only in the update are added, and fields present only in
  the base are kept unchanged.
```

SPEC_service.md section 14, Merge API:

```text
- `base`, `update`: JSON-compatible values (in practice, objects).
- `merged`: a new value; the inputs are not mutated.
- The update has priority; recursion and replacement rules are in SPEC_.md
  10.1.
```

### Reason for the correction

"the update always replaces the base" made a component document destructive:
loading one could silently rewrite values the operator had set on purpose in
the main file, and a partial update could not express "use this only where the
main file says nothing". The precedence is a policy decision of the host, not a
property of the merge function, so it belongs in the interface rather than being
fixed by the library.

### Recommended new text

Replace the SPEC.md 10.1 bullets above with:

```text
- Exactly two inputs: a base and an update, plus one precedence parameter.
- The default precedence is `base`: on a conflict the base value survives.
  Fields present only in the update are added, and fields present only in the
  base are kept unchanged.
- The algorithm is recursive in both precedences. For each field present in both
  values:
  - if both values are objects, merge them recursively by these rules;
  - otherwise (scalars, arrays, `null`, or a type mismatch) the winner takes the
    field: the base with the default precedence, the update with `update`.
- `prefer: "update"` restores the former rule, where the update replaces the base
  on every conflict. It is never implicit: a host that wants an override layer
  asks for it explicitly.
- An update cannot delete a base field in either precedence.
- Merge is deterministic and returns a new value; it does not mutate its inputs.
```

And in SPEC_service.md section 14:

```text
aiset.merge(base, update, *, prefer="base") -> merged

| prefer | Conflict winner | Meaning |
|---|---|---|
| `base` (default) | the base | The update fills gaps and merges objects. |
| `update` | the update | The former behaviour: an overriding layer. |

`POST {base}/merge` accepts the same `prefer` value in the request body and
echoes it in the response; an unknown value is a `BAD_REQUEST`.
`Config.update(other, *, prefer="base")` forwards the parameter unchanged.
```

Add to SPEC.md 10.2, next to the update rule:

```text
- **Editing the base with a loaded layer.** A component document never receives a
  write. Any change made through the service, whatever value the editor was
  showing, is stored in the base document at its own path and revision. The base
  keeps owning its own values; the default precedence makes an edit visible
  immediately, and the next reload of the layer cannot take it back.
```

---

## Correction 6: the value-type list gains `any`, and `apply` gains no new value

Requested by the aidir integration (`proposal_improvement_aidir.md` P3).

### Old text (SPEC.md 4.6.1, value types)

```text
Value types: string, int, number, bool, null, object, array, union.
```

### Reason for the correction

A host frequently owns a region of its configuration whose shape the shared
library cannot and should not know: a JSON schema, a plugin declaration, a tool
description, an arbitrary extension map. Before this correction the grammar had
no way to say "this value is opaque", and every alternative was a loss:

- omitting the key produced `undeclared_field`, an error, so the first real value
  made the whole document unloadable;
- declaring it as an object produced an error for every key of that object,
  because an object node without `children` or `additional_children` accepts
  nothing;
- spelling out a nesting depth worked but had to be maintained by hand and was
  silently too shallow for a deeper document.

### Recommended new text

```text
Value types: string, int, number, bool, null, object, array, union, any.

`any` is the opaque type. A node of type `any` accepts every JSON value,
including null, and is not inspected further: no type rule, no constraint, no
null rule and no recursion into its members. It exists so that a host can
declare a region it owns without inventing a schema for it.

Rules for `any`:

- `any` accepts only the `description`, `title`, `ui`, `env`, `secret`,
  `read_only`, `apply`, `validators`, `hooks` and `helper` properties, plus
  `required`. A composite key (`children`, `children_options`,
  `additional_children`) or a key constraint (`key_pattern`, `key_enum`) on an
  `any` node is a descriptor error, exactly as on any other scalar type.
- The operational limits of section 11 still apply to an opaque value: maximum
  depth, collection size, string length and file size are checked structurally
  before the value is handed over.
- A `${VAR}` placeholder inside an opaque value stays literal. `env.allowed` on
  the `any` node governs the node itself, not its members, because resolving the
  members would require understanding their shape.
- In a snapshot (section 8.4 / SPEC_service.md 19) an `any` node is a `leaf`:
  one source fragment, editable, never expanded into members.
- In the generated editor (SPEC_service.md 21) an `any` node is edited as source
  text, like any other node the library does not decompose.

No new `apply` value is introduced. `live` already means "the next read sees the
value", which is what a host that needs no action wants; a node that leaves
`apply` unset keeps asking for `restart`.
```

---

## Correction 7: an object member whose type is a `union` is resolved through the union

Requested by the aidir integration (`proposal_improvement_aidir.md` P1).

### Old text (SPEC.md 4.6.10, templates and alternatives)

```text
children_options declares the alternatives of a union. A union is validated
against every alternative and a value that matches none of them is an error.
```

### Reason for the correction

The text describes validation only, and the implementation of the environment
resolver disagreed with it in exactly one position. `resolve_value` obtained the
descriptor node of an object member from `children` and `additional_children`
only, so a member whose type is a `union` - where the shapes live in
`children_options` - was resolved against no node at all. The consequences were
not cosmetic:

- an unquoted `${VAR}` below such a node reported `env_not_allowed`, an
  error-severity issue, so `analyze` discarded the whole document state and the
  configuration became unreadable;
- a quoted `"${VAR}"` below such a node stayed unresolved and then failed the
  union validation with a message that pointed at the wrong thing.

The array position never had this defect: `_array_item_node` already returned
`option_nodes[0]`. The specification therefore described one behaviour for both
positions and the code implemented two different ones.

### Recommended new text

```text
children_options declares the alternatives of a union. A union is validated
against every alternative and a value that matches none of them is an error.

Resolution of an alternative is a hint, never a rule:

- an array item is resolved with the alternative at its own index, and with the
  last alternative when the array is longer than the alternative list;
- a member of an object whose type is a union is resolved with the alternative
  that declares that member, preferring one whose declared type fits the stored
  value, and taking the first declared one when several declare it or the value
  carries no type yet (an unquoted placeholder).

Validation remains authoritative in both positions: the value is checked against
every alternative and a single issue is reported when none fits. A resolution
choice can therefore never make an invalid value valid.
```

---

## Correction 8: the operation list gains `rename` and `drop`

### Old text

`SPEC_.md` section 5.3.7:

```text
A structural operation is one of `set`, `add`, `remove`, or `move`, addressed by
JSON Pointer.
```

### Why

`rename` shipped with the tree editor and never updated this sentence: one key is
renamed in place, keeping its value and comments, rather than being removed and
added again.

`drop` is new and belongs to the doctor. It removes one key the descriptor does
**not** declare, which `remove` cannot do: `remove` resolves the node first and
answers `NOT_FOUND` for exactly the keys a drifted file carries. `drop` refuses a
declared path, a read-only parent and a secret subtree without
`settings_edit_secret`, and it requires `settings_write`.

### Recommended new text

```text
A structural operation is one of `set`, `add`, `remove`, `move`, `rename` or
`drop`, addressed by JSON Pointer. `add` uses the `-` token to append an array
item, or names a new key of an object that permits one; `move` takes one array
item to another index; `rename` changes one object key in place, keeping its
value and comments; `drop` removes one key the descriptor does not declare and is
used by the doctor to clean a drifted file.

An operation authorizes and validates every affected path, preserves the source
bytes and owned comments of everything it does not touch, and rejects unsafe
comment ownership with `COMMENT_PRESERVATION_CONFLICT`.
```
