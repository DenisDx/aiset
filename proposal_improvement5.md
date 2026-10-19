# Further improvements aiset needs, from the aidir host

file version 1.0.0

Written by the aidir side **after** `proposal_improvement4.md` was implemented
(commit `97748c8`). aiset is a separate project: nothing here has been applied to
`aiset/`, and nothing here blocks aidir.

`proposal_improvement4.md` is not reopened. Its eight items were all
implemented, and the host side was rewired to the result the same day: the
stylesheet became a block of `--aiset-*` variables rather than a hundred selector
overrides, the coverage check reads `aiset.classes()` instead of grepping the
asset, and `test_settings_styles.py` now asserts the variable contract.

**These three items are defects in that implementation**, found while wiring it
up, not new requests. They are all about the same theme: the library now makes
promises - an inventory, a palette, a set of `required` classes - and in three
places it does not keep them.

| Item | Severity | Effect |
|---|---|---|
| 1 — `aiset.css` declares four selectors more than once | low | Misleading to review; an edit to the wrong block looks right and does nothing |
| 2 — five classes are `required` and unpainted | medium | The `required` flag promises what the library does not deliver |
| 3 — `aiset.classes()` has no stated stability guarantee | low | A host cannot know whether the names it checks against may be renamed |

Reproduce items 1 and 2 with `test_settings_styles.py` in the aidir repository:
both checks fail against `97748c8` as it stands.

---

## 1 — `aiset.css` declares four selectors more than once

**Impact: low for rendering, real for review.**

### What happens

The variable rewrite of `aiset.css` left earlier declarations behind. Counting
rule blocks in the file:

| Selector | Times declared |
|---|---|
| `.aiset-tree-badge.draft` | 2 |
| `.aiset-tree-env-state` | 3 |
| `.aiset-tree-env-state.on` | 3 |

```css
.aiset-tree-env-state { font-size: 11px; color: var(--aiset-muted); white-space: nowrap; }
.aiset-tree-env-state { font-size: 11px; font-style: italic; color: var(--aiset-muted); white-space: nowrap; cursor: help; }
.aiset-tree-env-state { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; color: var(--aiset-muted); white-space: nowrap; background: transparent; border: 1px solid var(--aiset-border); border-radius: 10px; padding: 1px 8px; cursor: pointer; }
```

Nothing breaks: CSS unions the declarations, and the last block wins on every
property the earlier ones set, so the rendering is correct.

What breaks is review. The first two blocks look like leftovers from the
pre-variable version, and the second contributes a `cursor: help` and an
`font-style: italic` that the third silently overrides. A later fix applied to
the first block - the natural choice, since it is the first match a reader finds
- will pass every test and change nothing on screen.

The same file repeats `.aiset-tree-badge.draft` twice for the same reason, which
is why a reader cannot tell which of the two is the current statement.

### What would fix it

- one declaration per selector: keep the third `.aiset-tree-env-state` block, the
  second `.on` block, and the second `.draft` block; delete the rest;
- add a check to `tests/test_ui_assets.py` that parses `aiset.css` and fails on a
  repeated selector, with the offending selector in the message. The file is
  generated often enough by hand for this to be worth automating.

**Acceptance:** no selector appears twice in `aiset.css`; a test fails when one
does; the rendered editor is unchanged.

---

## 2 — Five classes are marked `required` and the library paints none of them

**Impact: medium. The inventory tells a host the library will not.**

### What happens

`CLASS_INVENTORY` carries a `required` flag, and `AGENT_INTEGRATION.md` section
8a.7 reads it as: a host that styles nothing gets a broken editor. Five classes
are flagged, and `aiset.css` has no rule for any of them:

| Class | `required` | Painted by the library? |
|---|---|---|
| `aiset-tree` | yes | **no** |
| `aiset-tree-toolbar` | yes | **no** |
| `aiset-tree-pending` | yes | **no** |
| `aiset-tree-status` | yes | **no** |
| `aiset-tree-issues` | yes | **no** |

Five of the twelve. The other seven - `editor`, `node`, `row`, `children`,
`toggle`, `name`, `value` - are painted, which is the half that item 5 moved
across.

`aiset-tree-badges` is the related case and is **not** flagged: the library
paints neither the badge wrapper nor anything about it, and it is
`required: false`. It is listed here because it is the same defect with a
weaker flag, and because it is the one that was actually observed.

`aiset-tree-badges` is the one that was actually observed, and it sits just
outside the flag. The library styles the badge and never the wrapper, so without
a host rule the badges of one node render as a single run of text -
`type apply secret dirty` instead of four separated pills. That is the exact
problem `proposal_improvement4.md` item 1 was written about, and this repository
already solves it in `webui/frontend/settings.css`. `required: false` is
arguably the right flag for a wrapper - a host may reasonably not want badges at
all - but then the rule belongs in the library for the same reason the row layout
does: a host that does nothing should still get separated badges.

The same is true of the toolbar: `aiset-tree-toolbar` has no display, no gap and
no spacing, so Apply / Reload / Revert render as bare inline text.

Item 5 of the previous document moved the *structural* half of the tree into the
library - row layout, the indent of `.aiset-tree-children`, the guide line - and
that worked. These five are the other half of what `required` is claiming: not
structure, but the containers and the shell. Either the flag means the library
paints them, or it means the host must.

### What would fix it

Decide which, and make the flag mean it.

- **Paint them in the library.** Six rules, no design opinion in any of them:
  `aiset-tree` and `aiset-tree-pending` are spacing; `aiset-tree-toolbar` is
  `display: flex` with a gap and padding; `aiset-tree-badges` and
  `aiset-tree-staged-row` are `display: inline-flex` with a gap;
  `aiset-tree-status` and `aiset-tree-issues` are a font size and spacing.
  Colours stay on `--aiset-*`, so this is structure again and not design.
- **Or stop flagging them.** A host that trusts `required` and skips them gets
  what the flag promised.

Painting them is the better half of the answer, because it also removes the last
way the editor renders unreadable by default. Whichever is chosen, state it in
the section 8a.2 table, which currently lists them among the classes a host
**must** style without saying that the library does not.

**Acceptance:** every class with `required: true` either has a rule in
`aiset.css` or is documented as host-owned; `test_settings_styles.py` checks the
first half and stops passing on `required` alone.

---

## 3 — `aiset.classes()` has no stated stability guarantee

**Impact: low, but it decides whether the interface is usable.**

### What happens

`aiset.classes()` is the right interface and it works: it is what let this
repository delete a regular expression over 2000 lines of JavaScript and check
its stylesheet against a published list instead. The host test now reads it
directly, and 54 entries with a `required` flag is exactly the contract a host
wants.

What is missing is a sentence saying the names are stable. `AGENT_INTEGRATION.md`
section 14 lists what counts as an interface change - a service method, a
transport or route, a resolver behaviour, a descriptor property, an operation, a
snapshot field, editor behaviour - and a class name is not among them, though a
host styles it exactly as hard as it styles a route.

The risk is silent in both directions. A host may write
`.aiset-tree-name { … }`, assert on it in a test, and be broken by a rename that
looked like internal tidying. A maintainer may avoid renaming a published name
because nothing says it is safe, which is a cost too.

### What would fix it

One sentence in `SPEC_service.md`, next to the tree section, and one row in the
section 14 table:

| Change | Files that must move together |
|---|---|
| Renamed or removed emitted class | `aiset-tree.js` `CLASS_INVENTORY`, `aiset.css`, `SPEC_service.md` section 8a.2, `AGENT_INTEGRATION.md` section 8a.2, `aiset-host-theme.css`, host stylesheets |

A class name in `CLASS_INVENTORY` is a styling contract. Renaming one is an
interface change, handled like a snapshot field: the old name goes through a
deprecation, or is documented as breaking and the version moves.

A test that keeps the inventory honest already exists somewhere in spirit - item
1 asked for one and `test_ui_assets.py` should have it - so the remaining work is
the promise, not the check.

**Acceptance:** `SPEC_service.md` states the stability of the inventory; the
section 14 table lists a class rename as an interface change; a test fails when a
class is added to the sources without a matching entry in `CLASS_INVENTORY`.
