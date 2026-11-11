# Roadmap

Deferred work and directions that are not current assignments. Entries here are
not implementation authorization; concrete work needs a proposal or an explicit
assignment.

## Deferred by specification

- MCP adapter and lifecycle-hook dispatcher (M2). A hook-bound subtree is
  reported in a snapshot as `capabilities.unsupported` and refused at write time
  with `UNSUPPORTED_CAPABILITY`.
- Generated forms, helper micro-forms, history/restore, and the revision diff of
  `proposal_improvement2.md` item 5. Deletion, array append/reorder, and
  dynamic-key removal are implemented.
- Host integrations (aidir, aibt, sndbx, colloc): M3.
- The AI block declared in `examples/aiset_descriptor.json5` is never executed.

## aidir host follow-ups

Found while wiring aidir to `proposal_improvement5.md`. These require changes
in aidir, not in aiset, so they are recorded here rather than as an aiset
proposal. None of them breaks the current aidir test suite.

1. `webui/frontend/settings.css` — three comment blocks say the library paints
   none of the toolbar shell, badge wrapper, and status/issues/staged list;
   the library paints all of them now. Rewrite them as restyles, not as the
   only rule that makes the element readable.
2. `test_settings_styles.py`,
   `test_every_required_class_is_painted_by_someone` — the test passes when a
   required class is painted by either the host or the library. Add a separate
   assertion that every `required` class has a selector in `aiset.css`, mirroring
   `tests/test_ui_assets.py::test_every_required_class_carries_a_stylesheet_rule`.
3. `webui/frontend/settings.css` — the host restates library structure for
   `.aiset-tree-toolbar`, `.aiset-tree-badges`, and `.aiset-tree-staged-row`.
   Keep only genuine design choices, or extend the duplication guard to those
   classes.
4. `test_settings_styles.py`,
   `test_the_inventory_agrees_with_the_classes_in_the_page` — the check skips
   `aiset-tree` and `aiset-form`, which the source does emit. Drop both
   exceptions so the assertion covers the full inventory.
