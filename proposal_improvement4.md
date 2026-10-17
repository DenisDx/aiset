# Further improvements aiset needs, from the aidir host

file version 1.0.0

Written by the aidir side **after** `proposal_improvement2.md` and
`proposal_improvement3.md` were implemented. aiset is a separate project: nothing
here has been applied to `aiset/`, and nothing here blocks aidir.

Neither earlier document is reopened by this one. What follows was found on
2026-10-17 while giving the generated editor the design of the host project. The
editor mounted, every request succeeded, every test passed - and it rendered as
unstyled text, because the host had no stylesheet and nothing warned it.

The underlying question is where the design of a generated UI belongs. The
answer used here is the one the library already implies: **the library owns the
markup and the behaviour, the host owns the design.** aiset cannot guess whether
a host is dark or light, dense or airy, so it must not pretend to. What it must
do is make that division cheap to honour.

Section 8a of `AGENT_INTEGRATION.md` now carries the class inventory, the traps
and a reference stylesheet, so a host no longer has to read 2000 lines of
JavaScript. That removes the *discovery* cost but not the *drift* cost, and the
items below are the rest.

**Status: nothing here blocks aidir.** `webui/frontend/settings.css` is the
working answer to items 1-4 and is in this repository; items 5-8 are the
follow-ups it exposed.

**Priority.** Items 5 and 6 are the ones that change the integration contract;
do those first. Items 1 and 3 are mechanical. Items 7 and 8 are quality.

---

## 1 — The class inventory is prose, so it drifts

**Impact: medium. Solved for the reader, not for the machine.**

> **Partly addressed (2026-10-17).** `AGENT_INTEGRATION.md` section 8a.2 now
> lists all 47 emitted classes with their element and meaning, and 8a.7 tells a
> host how to check its own coverage. The discovery cost is gone; the drift cost
> is not, and that is what the rest of this item is about.

### What happens

`aiset-tree.js` emits 47 distinct class names across `aiset-tree-*` and
`aiset-form-*`. They appear in no specification: `SPEC.md`, `SPEC_service.md` and
`AGENT_INTEGRATION.md` never name `aiset-tree-row`, `aiset-tree-badge` or
`aiset-tree-children`.

The only place a host can learn them is `demo2/frontend/styles.css`, which lives
in the demo, not in the package, and which is one host's answer rather than a
contract. The first aidir attempt had to extract the list from the JavaScript
source with a regular expression; `test_settings_styles.py` still does that on
every run, and its docstring explains why.

The cost is not only the initial discovery. A class that is not part of a
documented contract will be renamed without breaking a test, and a host stylesheet
will quietly lose a rule. `aiset-tree-staged-op` and `aiset-tree-badges` are
exactly the kind of name that reads as internal.

### What would fix it

A table of the classes, their element, and whether they are structural:

```text
| Class | Element | Meaning |
|---|---|---|
| aiset-tree-node | div | one node; state in data-absent/is-staged/is-deleted |
| aiset-tree-row | div | the clickable line: toggle, name, badges, value, controls |
| aiset-tree-children | div | the nested group; the host draws indentation here |
| aiset-tree-desc | div | the descriptor description of the node above it |
| aiset-tree-badges | span | wrapper around the badges of one node |
| aiset-tree-badge <kind> | span | kind: type, apply, origin, env, draft, absent, default, lock, unsupported, req, dirty, new, deleted |
| ... | | |
```

- put it in `SPEC_service.md` next to the tree description, and
- state which classes a host **must** style for the editor to be usable
  (`-row`, `-children`, `-badge`, the value controls, the toolbar) and which are
  optional polish.

Optionally, ship the demo theme as `src/aiset/assets/aiset-host-theme.css`: a
reference a host can adopt unchanged instead of writing one from scratch. It
stays a host file by being outside the library's own contract.

The documentation half is done. The remaining half is mechanical:

- export the inventory from the code, so it cannot disagree with the code:
  `aiset.classes()` returning `{name, element, role, required}` as data, and
  `include_assets()` unchanged;
- a library test that parses `aiset-tree.js` and fails when the emitted set and
  the exported set differ - then the doc, the export and the source are three
  views of one list, and the test keeps them equal;
- a host then writes its coverage check in five lines against `aiset.classes()`
  instead of a regular expression over 2000 lines of JavaScript, which is what
  `test_settings_styles.py` in this repository has to do.

**Acceptance:** the exported inventory equals the emitted classes, a test fails on
any drift, and a host coverage check needs no knowledge of the source layout.

---

## 2 — Apply, Reload and Revert all carry no class

**Impact: medium. A host cannot make its primary action look primary.**

### What happens

`_renderToolbar` builds the first three buttons like this:

```javascript
this.applyButton = element("button", { type: "button", text: "Apply", onclick: ... });
this.reloadButton = element("button", { type: "button", text: "Reload", onclick: ... });
this.revertButton = element("button", { type: "button", text: "Revert all", onclick: ... });
```

No class, while `_viewButton` does give its buttons `aiset-tree-view` and the
lifecycle buttons carry `aiset-tree-lifecycle`. The only hook a host has is
`.aiset-tree-toolbar button`, which matches all of them at once.

So Apply cannot be styled differently from Reload, which is the one thing every
host wants: the button that commits a staged batch should be the visually primary
control. In aidir this forced a positional selector:

```css
.aiset-tree-toolbar button:first-child { background: var(--accent); color: #fff; }
```

That breaks the moment the toolbar gains a button before Apply, and it reads a
button as primary by position rather than by meaning.

The same applies to the "new item: `<type>`" chooser in `_showItemChooser`: its
buttons are bare elements inside the toolbar.

### What would fix it

Give each one the class its role already implies:

```javascript
class: "aiset-tree-button apply"     // and .reload, .revert
```

so a host writes `.aiset-tree-apply { ... }` instead of `:first-child`, and the
chooser buttons become `.aiset-tree-chooser .aiset-tree-button`.

This is additive and breaks no existing host: selectors that match the toolbar as
a whole keep matching.

**Acceptance:** every button in the toolbar carries a class naming its role; the
demodulator host stylesheet uses no positional selector for Apply.

---

## 3 — The bundled CSS hard-codes every colour

**Impact: medium. A host theme is an exercise in specificity.**

### What happens

`src/aiset/assets/aiset.css` contains **zero** uses of `var(--…)`. Colours are
literal: `#f6f8fa`, `#0969da`, `#1a7f37`, `#6b7280`, and so on, across roughly
twenty rules covering action buttons, badges, type marks, the raw editor and the
source view.

Every one of those has to be beaten by a host rule. In aidir that worked, but
only because the host stylesheet loads after the library one, and only because
each override happens to repeat the same selector. Both conditions are invisible
in review: load order is a property of the page, not of either stylesheet, and a
selector that gains one attribute later silently wins.

`test_settings_styles.py` compares specificity for every painting rule the library
ships and fails if one survives the host. A test like that is a symptom: it exists
because the contract makes the normal case hard.

### What would fix it

Route the palette through custom properties, with the current light values as
the defaults:

```css
.aiset-tree-editor {
  --aiset-surface: #f6f8fa;
  --aiset-border:   #c6ccd4;
  --aiset-text:     #1c1f24;
  --aiset-muted:    #6b7280;
  --aiset-accent:   #0969da;
  --aiset-ok:       #1a7f37;
  --aiset-err:      #b42318;
}
```

Rules then reference `var(--aiset-…)`, and a dark host overrides five variables
instead of twenty selectors - no load-order dependency, no specificity contest.

The type-mark palette should be variables too, since it is a choice, not a fact:

```css
--aiset-type-int: #1a7f37;  --aiset-type-string: #0969da;  --aiset-type-bool: #7c3aed;
```

Structural rules (flex, gap, padding, the indent of `-children`) stay as they
are: those are the host's, per item 1.

**Acceptance:** `aiset.css` contains no literal colour outside the `:root` block
that declares the defaults; a host theme is expressible as a variable block; the
existing light rendering is unchanged.

---

## 4 — A generated editor that ships no design has no failure mode

**Impact: low for behaviour, high for trust.**

### What happens

Nothing in the library warns a host that the editor will render unstyled. It
mounts, it renders every node, it saves. From the outside - HTTP status, DOM
content, server logs - an editor with no stylesheet is indistinguishable from a
styled one.

This is how it reached a user in aidir: 391 tests green, every route answering,
the document selector working, and the page unreadable in the sense that mattered
- no indentation, no badges, bare buttons. Only a screenshot showed it.

The gap is a consequence of the division itself. If the design is the host's,
then "the host has not designed it" is a host-side bug, and the host has no
signal.

### What would fix it

A development aid rather than a runtime check, since a runtime check would fire
on a deliberately unstyled host:

- a console warning from `mountTree` when no rule from the library or the host
  matches the editor root, which happens to be cheap to detect with
  `getComputedStyle` on the toolbar and is enough to catch "the stylesheet did
  not load" without guessing about design;
- or simply the reference theme of item 1, adopted by a host, which removes the
  failure by making the styled case the path of least resistance.

The first is honest about the cause and cheap; the second removes it. They are
not exclusive.

**Acceptance:** mounting into a page with no stylesheet produces one console
warning naming the missing design, and no warning on a page that has the
reference theme.
---

## 5 — Structure belongs to the library, only appearance belongs to the host

**Impact: high. This is the item that removes the failure mode instead of documenting it.**

### What happens

`demo2/frontend/styles.css` puts **everything** in the host sheet, including the
part that is not a matter of taste:

```css
.aiset-tree-row       { display: flex; align-items: center; gap: 8px; ... }
.aiset-tree-children { padding-left: 22px; border-left: 1px solid var(--border); margin-left: 10px; }
```

Those two rules are the difference between a tree and a wall of text. But they
are treated as host decisions, so a host that does not write them gets a flat,
unreadable tree - and no warning, because nothing failed.

The current contract says "the host owns the design". Read strictly, that
includes readability. It should not.

### What would fix it

Split the ownership, using `AGENT_INTEGRATION.md` section 8a.8, which states it:

| Property | Owner now | Should be |
|---|---|---|
| `.aiset-tree-row` layout: flex, gap, wrap | host | **library** |
| `.aiset-tree-children` indent and guide line | host | **library** |
| `.aiset-tree-desc` placement under its node | host | **library** |
| Colours, spacing values, radius, font | host | host |
| Every state treatment (hover, focus, staged, absent) | host | host |
| Focus ring, `color-scheme`, host chrome, proxy paths | host | host |

Concretely: move the structural rules into `aiset.css` and express the parts a
host will want to tune as variables with the current values as defaults:

```css
.aiset-tree-editor {
  --aiset-indent: 14px;      /* .aiset-tree-children padding-left */
  --aiset-guide: 1px;        /* the guide line width            */
  --aiset-row-gap: 8px;
  --aiset-row-pad: 3px 6px;
}
.aiset-tree-row { display: flex; align-items: center; gap: var(--aiset-row-gap);
                  padding: var(--aiset-row-pad); flex-wrap: wrap; }
.aiset-tree-children { margin-left: calc(var(--aiset-indent) - 1px);
                       padding-left: var(--aiset-indent);
                       border-left: var(--aiset-guide) solid currentColor; }
```

Everything visual stays the host's, so this costs the host nothing it wanted.
What it buys: a host that loads one stylesheet and writes no rules gets a tree
that is readable, and the "no design" case degrades to "plain" instead of
"unreadable".

A host that prefers the full sheet still gets it - its rules simply win over the
library defaults by load order, which is already the case.

**Acceptance:** with `aiset.css` alone and no host sheet, a document renders as a
nested tree rather than a flat list; `tests/test_ui_assets.py` asserts the
computed indent of a nested node is greater than zero; a host can still override
the indent without touching the library.

---

## 6 — The reference theme lives in the demo, where no host will find it

**Impact: high. Every host writes the same 300 lines.**

### What happens

After `AGENT_INTEGRATION.md` section 8a.4 there is a reference stylesheet, but it
lives inside a guide as a fenced code block. That is better than nothing and still
not reusable:

- a host has to copy it out of markdown by hand, and cannot tell which parts are
  theme and which are demo layout;
- it cannot be imported, tested, or kept in step with the markup.

The real cause is that `demo2/frontend/styles.css` is **two files in one**:

| Part | Rules | Reusable? |
|---|---|---|
| The editor theme | 86 of 120 | Yes, as a starting point for any host |
| Demo layout: `.app-header`, `.workspace`, `.pane`, `.pane-head`, `.pane-body`, `.chat-*`, `.override-note`, `#document-select` | 34 of 120 | No; a host copy-pasting it inherits a two-pane chat layout it never asked for |

(Counted from the selectors: 120 rule blocks in the file, 86 of which reference
`.aiset-`.)

The theme half is good, and it is the part that should ship. The layout half is
the demo's business.

### What would fix it

- split `demo2/frontend/styles.css` into the two halves;
- ship the theme half as `src/aiset/assets/aiset-host-theme.css`, loadable but
  **not loaded** by `include_assets()`: it is a starting point, not a contract,
  and a host that adopts it should be able to see and edit every line;
- drive it from the same variables as item 3, so adopting it means overriding
  about ten values rather than rewriting the sheet;
- a library test asserts the theme covers every class the editor emits, so the
  theme cannot rot the moment a class is added - which is precisely how the
  wrapper `aiset-tree-badges` went unstyled for as long as it existed.

The theme file is deliberately **not** in the "library owns this" list of item 5:
it is optional, and a host that ignores it must still get a readable tree from
the structural defaults of item 5.

**Acceptance:** `aiset-host-theme.css` is in the package, is not loaded
automatically, covers every emitted class, and `demo2` uses it instead of its own
copy, so there is one theme to maintain rather than two.

---

## 7 — One emitted class has no prefix, and the rest are unverifiable

**Impact: low in practice, high as a precedent.**

### What happens

`.aiset-tree-value` carries a second class, `readonly`, written without the
`aiset-` prefix:

```javascript
return element("span", { class: "aiset-tree-value readonly", text: this._valueText(node) });
```

It is the only one of 47. In a host with a broad reset or a utility framework,
`readonly` is exactly the kind of word that collides - and because the rest of
the editor is safely namespaced, the collision would look like a bug in the host.

This also answers the question of whether the library needs a configurable class
prefix. It does not: the `aiset-` prefix already removes the realistic collisions
for a plain host, and a prefix option would multiply the number of selectors a
host has to keep in step for no gain. Renaming this one class is the whole fix.
Worth stating because "let the host configure the prefix" sounds like the general
answer and is not.

### What would fix it

- rename to `aiset-tree-value-readonly` (additive; a host with an old rule keeps
  matching `.aiset-tree-value` and loses only the state colour);
- have `aiset.classes()` (item 1) flag any emitted class that does not start with
  `aiset-`, so the next one fails a test.

**Acceptance:** every emitted class starts with `aiset-`, and a test enforces it.

---

## 8 — The editor ships no focus ring, and no `color-scheme`

**Impact: low for sighted mouse users, high for keyboard and native widgets.**

### What happens

`aiset.css` contains **no focus rule at all** - no `:focus-visible`, and not one
`:focus` selector either (verified: `grep -n "focus\|outline" aiset.css` returns
nothing). The demo theme does add `:focus` rules, and those remove the outline
and substitute a border change:

```css
/* demo2/frontend/styles.css, not the library */
.aiset-tree-value input[type="text"]:focus, ... {
  outline: none; border-color: var(--accent); background: #1f2331;
}
```

That border change is the only focus affordance, it exists on inputs only, and
the toggles, the action buttons and the badges get nothing. A keyboard user
moving through the tree cannot tell where they are.

Separately, `color-scheme` is a property of the document, not of a widget, so a
dark host still gets a light `<select>` popup, light scrollbars and a
light checkbox tick unless the host sets it. Section 8a.3 tells the host to do
that; it cannot be done from the editor.

### What would fix it

- a focus ring in the library, since removing an outline is the library's act and
  restoring one belongs with it:

```css
.aiset-tree-editor :focus-visible { outline: 2px solid var(--aiset-accent, #0969da); outline-offset: 1px; }
```

- the host sets `color-scheme` on `:root`, which is already documented in 8a.3;
  `mountTree` could warn once when `getComputedStyle(document.documentElement)
  .colorScheme` is `normal` and the editor is dark, but a console note is enough
  and item 4 covers the mechanism.

**Acceptance:** tabbing through a mounted tree shows a visible ring on every
interactive element; a light host renders the same ring in its accent colour.
