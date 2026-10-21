# Further improvements aiset needs, from the aidir host

file version 1.0.0

Written by the aidir side after `proposal_improvement5.md`. aiset is a separate
project; the changes below were implemented in `aiset/` on 2026-10-21.

Found while reviewing the generated editor against the reference theme. Two of
the three items are about a union node: the operator cannot switch the shape when
the value is a placeholder, and the chooser cannot tell eight object shapes
apart. The third is the same label problem seen from the other side.

**Status: implemented 2026-10-21.** aidir had worked around item 3 by declaring
`workers.items.<id>` as a plain object; items 1 and 2 still cost the operator the
ability to change `logging.level` between a level name and its numeric form.

Implementation: `aiset-tree.js` checks the union branch before the template
branch, so the shape chooser is always present; `_unionActive` falls back to
`_inferOption`, which classifies the value text (quoted string, object, array,
literal, or a substitution, which takes the string alternative); the template
control is built from the active alternative, so `${LOG_LEVEL:-error}` edits its
variable and its string fallback; the chooser labels come from `title`,
`description`, else `type`, with the type in the tooltip. Covered by
`test_tree_editor_public_api` (template union, chooser labels, inferred shape).

---

## 1 — A union whose value is a placeholder never shows its shape chooser

**Impact: medium. The operator cannot change the type of `logging.level`.**

### What happens

`logging.level` is a union of a named level (`debug`, `info`, …, `emerg`) and the
systemd-journald number `0-7`. In aidir's `config.json5` the stored value is:

```json5
level: ${LOG_LEVEL:-error},
```

so the node carries a template. `TreeEditor._valueControl` checks for that before
it checks for a union:

```javascript
if (this._showsTemplate(node)) { return this._templateControl(node); }

if (node.type === "union" && field.children_options && field.children_options.length) {
  return this._unionControl(node);
}
```

`_templateControl` renders the variable name, a presence badge, a typed control
for `node.type` (which is `"union"`, so a plain text input), and the `⊘` button.
`_unionControl` — the only place that renders `_typeChooser` — is never reached.

The operator therefore sees a text field with `error` and a `.env` badge, and no
`shape…` control. The only way to switch the type is to press `⊘`, which drops
the substitution and replaces `${LOG_LEVEL:-error}` with the literal fallback.
That is the opposite of what the user wants when they only wanted to choose
between a name and a number.

### What would fix it

Let the union own the value, and render the template control for the alternative
that is active:

```javascript
if (node.type === "union" && field.children_options && field.children_options.length) {
  return this._unionControl(node);
}
if (this._showsTemplate(node)) { return this._templateControl(node); }
```

`_unionControl` then needs the template case for its typed control: when the
stored value is `${VAR}` or `${VAR:-fallback}`, the control for the active
alternative should show the fallback and keep the `.env` behaviour, while the
`shape…` chooser stays next to it. The two are independent: one chooses the
alternative, the other chooses how the value of that alternative is stored.

A narrower fix, if the template control is meant to win: append
`_typeChooser` to `_templateControl` when the node is a union, and stage a sample
of the newly chosen alternative as a literal (with the usual "this replaces the
placeholder" consequence made explicit). That still loses the placeholder, so the
first option is preferable.

**Acceptance:** a union node whose source is `${LOG_LEVEL:-error}` renders both
the `.env` control and the `shape…` chooser; choosing `int` stages `0` and
choosing the string alternative stages `"info"` without first dropping the
substitution, or the chooser states that switching replaces the placeholder.

---

## 2 — `matched_option` is absent in the source view

**Impact: medium. A literal union value also loses its typed control.**

### What happens

In the source view, `service.tree(document, path, view="source")` returns
`matched_option: null` for a union even when the stored value is a plain literal
that matches one alternative unambiguously. Reproduced against aidir:

```text
/workers/items/web_search  type: union  matched_option: None
/logging/level             type: union  matched_option: None
```

`_unionActive` therefore returns `-1` unless the user has already chosen a shape
in this browser session:

```javascript
if (typeof chosen === "number" && ...) { return chosen; }
if (typeof node.matched_option === "number" && ...) { return node.matched_option; }
return -1;
```

With `active < 0`, `_unionControl` renders no typed control at all, only
`shape…`. A value the operator can see (`error`, `3`) has no editor until the
shape is picked again, and the pick stages a sample instead of editing the stored
value.

The snapshot already carries `value_text`. An alternative can be inferred without
resolving anything:

| Source text | Alternative |
|---|---|
| a quoted string, or a quoted/unquoted `${…}` | `string` |
| a number | `int` or `number` |
| `true` / `false` | `bool` |
| `{…}` / `[…]` | `object` / `array` |

Either fill `matched_option` in the source snapshot the same way the effective
view does, or infer it in `_unionActive` from `value_text` when `matched_option`
is absent. The descriptor has `children_options`, so the types are known.

**Acceptance:** opening a document with `level: ${LOG_LEVEL:-error}` or
`level: "info"` shows the control for the string alternative; `level: 3` shows
the number control; no shape needs to be picked first.

---

## 3 — Eight object alternatives are indistinguishable in the chooser

**Impact: low for aidir after the host workaround, medium for any host that keeps the union.**

### What happens

`_typeChooser` labels an alternative by its type only:

```javascript
options.forEach(function (option, index) {
  select.appendChild(element("option", { value: String(index), text: option.type }));
});
```

aidir declared `workers.items.<id>` as a union of eight worker families, all of
type `object`. The editor therefore offered a select with eight identical
`object` entries and no way to tell which family a choice meant. The host
workaround was to drop the union and declare one plain object, which is simpler
for the editor but loses the cross-field grouping:

```json5
// before
additional_children: { type: "union", children_options: [
  { type: "worker_agent", description: "…" }, … eight alternatives … ] }

// after
additional_children: { type: "worker_entity", description: "…" }
```

The union was the better model; the chooser was the problem.

### What would fix it

Label an alternative with its `title` when the descriptor has one, else its
`description`, and keep the type as a suffix or tooltip:

```javascript
var label = option.title || option.description || option.type;
if (label !== option.type) { label += " (" + option.type + ")"; }
```

The descriptor grammar does not have a `title` on a union alternative today, but
`description` is already there and is unique in the aidir descriptor. A `title`
property would let a host keep the description long and the label short.

**Acceptance:** a union of eight object alternatives shows eight distinct labels;
a union of `string`/`int` still shows both; the label falls back to `type` when
neither `title` nor `description` is present.

---

## What aidir changed meanwhile

Both are host-side and need nothing from the library:

- `workers.items.<id>` is a plain `worker_entry` object (23 fields, all
  optional), so the editor renders the fields directly instead of an eight-way
  shape chooser. Worker-local descriptors still name their own exact family
  (`worker_llm`, `worker_search`, …), so a local file keeps the strict shape.
- The `+`/`-` toggle is a fixed 20×20 square: the library sets only display and
  font on `.aiset-tree-toggle`, so its width followed the glyph and every name on
  the row shifted by a pixel.
