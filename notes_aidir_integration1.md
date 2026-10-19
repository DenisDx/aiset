# aidir integration notes after `proposal_improvement5.md`

file version 1.0.0

These are issues found while wiring the host (`../`) to the aiset changes for
`proposal_improvement5.md`. They are listed here because the aiset session may
only change files under `aiset/`; each entry names the aidir file that would have
to change. None of them breaks the current aidir test suite.

Baseline: both suites are green with the aiset changes applied -
`aiset`: 428 passed, aidir `test_settings_styles.py`: 15 passed.

## 1 - stale comments in the host stylesheet

**File:** `webui/frontend/settings.css`

The library now paints every `required` class, including the toolbar shell, the
badge wrapper, the status/issues blocks and the staged list. Three comment blocks
still say the library paints none of them:

- lines 112-114 (toolbar shell): "The library names these elements but paints
  none of them: no flex, no gap, no spacing."
- lines 120-124 (badges): "The library paints the badge but **not**
  `aiset-tree-badges`, the wrapper they sit in".
- lines 149-150 (status/issues/staged list): "Also unpainted by the library, and
  `required` in its own inventory."

Reason: the comments describe the state before `proposal_improvement5.md` item 2.
The rules below them still work, but a later reader will trust the comment and
restate structure the library already owns.

Recommended: update each comment to say the library paints the element and the
host rule is now a restyle (padding, a palette choice), not the only rule that
makes the element readable.

## 2 - the host test cannot see an unpainted `required` class

**File:** `test_settings_styles.py`,
`test_every_required_class_is_painted_by_someone` (lines 134-154)

The test passes when a required class is painted by **either** the host or the
library. Before this change that was the only workable rule, but
`proposal_improvement5.md` item 2 makes `required` a promise of the library, and
its acceptance asks the test to "check the first half and stop passing on
`required` alone". As written, a regression that removed a required rule from
`aiset.css` while the host happened to style the same selector would still pass.

Reason: the assertion does not distinguish "the library keeps its promise" from
"this particular host covers the gap".

Recommended: keep the host-or-library coverage check for the whole inventory,
and add a separate assertion that every `required` class has a selector in
`AISET_ASSETS / "aiset.css"` - the same check aiset now enforces in
`tests/test_ui_assets.py::test_every_required_class_carries_a_stylesheet_rule`.

## 3 - the host restates library structure

**File:** `webui/frontend/settings.css`

After item 2 these host rules duplicate rules the library now ships:

- `.aiset-tree-editor .aiset-tree-toolbar` (lines 115-118) restates
  `display: flex; align-items: center; gap; flex-wrap`.
- `.aiset-tree-editor .aiset-tree-badges` (lines 125-127) restates
  `display: inline-flex; align-items: center; gap; flex-wrap`.
- `.aiset-tree-editor .aiset-tree-staged-row` (line 158) restates
  `display: flex; gap; align-items: center`.

Reason: `AGENT_INTEGRATION.md` section 8a.8 says a host does not restate the
structure rules; the existing guard
`test_the_host_does_not_reimplement_the_structure_the_library_owns` only checks
`.aiset-tree-children` and `.aiset-tree-toggle`, so it does not catch these.

Recommended: either drop the structural declarations and keep only the host's
genuine design choices (the toolbar's `padding`, the staged list's font size),
or extend the duplication guard to the classes item 2 moved into the library.

## 4 - the inventory-agreement probe skips two names

**File:** `test_settings_styles.py`,
`test_the_inventory_agrees_with_the_classes_in_the_page` (lines 103-114)

The check skips `aiset-tree` and `aiset-form` while asserting every other
inventory name appears in the assets. `aiset-tree` is emitted by `aiset-tree.js`
(`element("div", { class: "aiset-tree", ... })`), so the skip is no longer
needed for it; `aiset-form` is also emitted by the source. The skips predate the
inventory reaching parity with the source and now only hide a real regression.

Reason: a host reading the inventory is told these names exist, but the test
would not notice if they stopped being emitted.

Recommended: drop both exceptions and let the assertion cover the full inventory.
