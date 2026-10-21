# Further improvements aiset needs, from the aidir host

file version 1.0.0

Written by the aidir side after `proposal_improvement6.md`. aiset is a separate
project; the changes below were implemented in `aiset/` on 2026-10-21.

This document answers one question: **can a union alternative that is an object
be edited as a structure, not as a raw JSON fragment?** Before the change it
could not. The snapshot already carried everything the editor needed; the
rendering and the shape chooser ignored it.

**Status: implemented 2026-10-21.** A tool entry is `string | object`; the
object form is the normal one in the shipped configuration
(`tools.search.worker`). Before this change it was editable only as a text area.

Implementation: `tree.py` expands the union's active alternative (its object
`children` or array `items`, with the alternative's capabilities), and
`aiset-tree.js` renders those children under the row while keeping the shape
chooser. An alternative the snapshot did not expand gets synthetic children from
the descriptor and the staged value; a field edit composes one `set` on the union
path, because the child path does not exist until the union holds an object. The
chooser writes nothing when the value already matches the chosen alternative and
reports when it replaces the value. Covered by
`test_tree_expands_the_object_alternative_of_a_union`,
`test_tree_expands_the_array_alternative_of_a_union`,
`test_tree_denies_a_secret_inside_a_union_alternative`,
`test_a_union_object_child_is_writable_by_its_path`,
`test_a_union_array_item_can_be_appended`, and the union cases in
`test_tree_editor_public_api`.

---

## 1 — A union object alternative is rendered as raw source

**Impact: high. The common tool entry is edited as text.**

### What happens

`worker_tool` is a union of two alternatives:

```json5
children_options: [
  { type: "string", min_length: 1, description: "Short form: worker id" },
  { type: "object", description: "Long form", children: {
      worker: {...}, name: {...}, description: {...},
      enabled: {...}, inputSchema: {...}, parameters: {...} } },
]
```

The tree snapshot for a stored object already contains the alternative:

```text
/workers/items/call_llama_cpp/tools/search
  type: union
  matched_option: 1
  value_text: {"worker": "web_search"}
  field.children_options[1].children: worker, name, description, enabled,
                                      inputSchema, parameters
```

`matched_option` is correct, so `_unionActive` returns `1`. Then
`_unionControl` builds a synthetic node and calls `_typedControl`:

```javascript
var optNode = Object.assign({}, node, { type: option.type, field: option });
control = this._typedControl(optNode, ...);
```

`_typedControl` handles enum, bool, int/number and a one-line string. Everything
else falls through to:

```javascript
/* Everything else is edited as source text: objects and arrays that cannot be
 * edited member by member, ... */
var area = element("textarea", ...);
```

So the object alternative becomes a JSON text area. The comment states the
limitation; this proposal removes it.

Two related consequences:

- `isComposite(node)` is true only for `type === "object" | "array"`, and a union
  node has `type: "union"`, so the tree never renders the alternative's children.
  A union object is a leaf as far as the editor is concerned.
- The alternative's `children` are already in `field.children_options[active]`,
  with types, descriptions, enums, `ui` hints and nested `children`/`items`. The
  data for a structured editor is present.

### What would fix it

When the active alternative is `object` or `array`, render its children as a
normal tree group under the union row, using the alternative's `children` as the
descriptor and the union path as the parent:

```text
search  union  object  [shape…]
  worker       string  web_search        {..}  .env  ⊖
  name         string  (unset)
  description  string  (unset)
  enabled      bool    (unset)
  inputSchema  any     (unset)
```

- Each child is an ordinary node rendered by `_renderNode`, with its path
  `<union>/<child>`. The server already resolves such a path through the union
  (`descriptor.node_at` descends into alternatives), so `set`/`add`/`remove`
  behave as for any other child.
- The alternative's `children` supply the field types and descriptions. They
  are the template of the shape, so they are shown even when `showAbsent` is
  off; the alternative is a form, not an arbitrary object.
- Adding a child of an object alternative stages an `add` at
  `<union>/<new-key>`; removing uses `remove` at the child path.
- `inputSchema` and `parameters` stay raw text because their type is `any`; that
  is intentional, not the union's fault.

Implementation sketch, inside `_unionControl`:

```javascript
if (active >= 0 && (option.type === "object" || option.type === "array")) {
  wrap.appendChild(this._renderAlternative(optNode, option));
} else if (active >= 0) {
  wrap.appendChild(this._typedControl(optNode, ...));
}
```

`_renderAlternative` builds a synthetic node with `type: option.type`,
`field: option`, `path: node.path`, `children`/`items` from the alternative and
the current stored values, then reuses `_renderNode` for the children. The row
still carries `_typeChooser`.

**Acceptance:** a tool entry stored as `{"worker": "web_search"}` renders the six
declared fields as an editable structure, not a text area; editing `worker`
stages `set /…/tools/search/worker`; a tool entry stored as `"web_search"`
renders a text input; switching between the two shapes keeps working.

---

## 2 — Choosing a shape always replaces the value

**Impact: medium. A correct object is erased by re-selecting `object`.**

### What happens

`_typeChooser` does not look at the current value:

```javascript
select.addEventListener("change", function () {
  self.unionShape[node.path] = index;
  self._stage(node, self._sampleForOption(option));
  select.value = "";
});
```

Every change stages a fresh sample: `"emerg"` for the first enum value, `0` for
`int`, `{}` for `object`. If the stored value already matches the chosen
alternative, the file is still rewritten with the sample. The user reported this
as "при выборе любого типа значение стирается".

It also makes the chooser feel unsafe: the only way to see the object structure
(once item 1 is fixed) would be to select `object`, which replaces the object
with `{}`.

### What would fix it

Stage a sample only when the current value does **not** match the chosen
alternative:

```javascript
self.unionShape[node.path] = index;
if (!valueMatchesAlternative(node, option)) {
  self._stage(node, self._sampleForOption(option));
}
```

`valueMatchesAlternative` can be a cheap client-side check (the snapshot already
carries `value_text` and the option `type`): a quoted string or `${…}` matches
`string`, a number matches `int`/`number`, `true`/`false` matches `bool`, `{…}`
matches `object`, `[…]` matches `array`, and `matched_option === index` is a
direct yes.

When a sample is staged because the value cannot be reused, say so next to the
control ("the stored value is replaced") rather than doing it silently.

**Acceptance:** selecting the alternative that already matches changes no bytes
in the file; selecting a different one stages a sample and the UI says the old
value is replaced.

---

## 3 — `matched_option` is missing when the value is a template

**Impact: medium. `logging.level` cannot switch shape (from improvement6).**

Already described in `proposal_improvement6.md` items 1 and 2. Repeated here
because the same inference fixes both: the union should infer its active
alternative from `value_text` when `matched_option` is absent. For a tool entry
the value is usually a literal object, so `matched_option` is present; for
`logging.level` it is `${LOG_LEVEL:-error}`, so it is not.

The single change is:

- fill `matched_option` in the source snapshot from `value_text`, or
- infer it in `_unionActive` from `value_text` and the option types.

Then a union object is auto-selected (the user's "если там не строка — объект
должен быть выбран автоматически"), and a placeholder union shows the control of
the alternative it would take.

**Acceptance:** a stored object selects the object alternative without any shape
click; `${LOG_LEVEL:-error}` selects the string alternative; `3` selects the
integer alternative.

---

## What is already correct

These are not problems and should not be changed:

| Thing | State |
|---|---|
| `worker_tool` as a union of `string | object` | correct; both forms occur in real files |
| `matched_option` for a literal object | correct in the source view (`1` in the reproduction) |
| The shape option list | correct: `string`, `object` |
| The short string form | renders as a text input, as it should |

The host-side alternatives were considered and rejected:

- `type: "any"` — no validation and still a text area;
- a plain object — the short `"web_search"` form would stop validating;
- two separate keys (`tool` and `tool_ref`) — an incompatible file change.

The union is the right model; only its rendering and its value-preserving
selection are missing.
