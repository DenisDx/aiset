# Tree search and visible-path breadcrumbs

file version 1.1.0

**Status: implemented 2026-10-23. See section 9 for the progress log.**

This is a browser-side change to the tree editor. The server already sends
every searchable key, value and description in the `/tree` snapshot, so no
route, descriptor field, service method, or Python source file needs to change.
The work is limited to `src/aiset/assets/aiset-tree.js`, `aiset.css`, the
reference theme, and documentation of the new editor classes.

Two related features are described:

1. **Search** over keys, values and descriptions, with a result list that
   expands the path to a hit, scrolls it into view and focuses it.
2. **Visible-path breadcrumbs** at the bottom of the editor's top strip, showing
   the path to the topmost tree row that is still visible while the tree is
   scrolled.

Both features are local to one mounted `TreeEditor`; no new server state is
introduced.

---

## 1 — What the editor already has

The tree shell is built in `_renderShell` (`aiset-tree.js`) and currently
contains a toolbar, the tree, the staged-operations list, the status line and
the issue list. `_render` rebuilds `this.treeNode` from the current snapshot and
restores the scroll offsets captured by `_captureScroll`.

Every snapshot node carries what a search index needs:

| Field | Use |
|---|---|
| `path` | unique target and ancestor expansion |
| `label` / last path token | key shown for the node |
| `type`, `kind` | result badge and composite detection |
| `value_text` | stored source of a scalar |
| `field.description` | searchable human description |
| `exists: false` | declared but absent key |
| `access_denied` | secret value is not in the browser at all |
| `children` / `items` | recursion |

Collapsed nodes are not in the DOM, but they are still in the snapshot. That is
why search must walk the tree, not `querySelectorAll`, and why activating a hit
is a render-time operation: set `this.expanded[ancestor]` first, then render.

The existing class inventory is a published host contract
(`aiset.classes()` and `SPEC_service.md` section 21.1). Every new `aiset-*`
class added here must be added to both, or two existing drift tests fail.

---

## 2 — Placement: a sticky top strip

The editor gets one new wrapper between the existing toolbar and the tree:

```text
+-------------------------------------------------------------+
| Apply  Reload  Revert all  Expand all  Collapse all  ...    |  toolbar
+-------------------------------------------------------------+
| [ Search keys, values, descriptions... ]                    |  top strip
| / workers / items / 0 / name                                |
+-------------------------------------------------------------+
| + workers                                                   |  tree
|   + items                                                   |
|       name       string   web_search                        |
+-------------------------------------------------------------+
```

DOM produced by `_renderShell`:

```html
<div class="aiset-tree-editor">
  <div class="aiset-tree-toolbar">…existing buttons…</div>

  <div class="aiset-tree-topbar">
    <div class="aiset-tree-search">
      <input class="aiset-tree-search-input" type="search" …>
      <ul class="aiset-tree-search-results" role="listbox" …></ul>
    </div>
    <div class="aiset-tree-context" role="navigation" aria-label="Visible location">
      <span class="aiset-tree-context-path">/ workers / items / 0 / name</span>
    </div>
  </div>

  <div class="aiset-tree" role="tree"></div>
  …pending, status, issues…
</div>
```

The top strip is `position: sticky; top: 0` inside the nearest scrolling
ancestor. In demo2 that ancestor is `.pane-body`, not the mount point, which is
already handled by the same ancestor-walking logic used by `_captureScroll`.
The search input therefore stays reachable while the tree scrolls, and the
context path is literally the last line of that visible strip.

The existing action toolbar is deliberately left in flow above the strip: it is
already reachable at the top of the document, and making it sticky would cover
more of a tall tree than this feature needs.

---

## 3 — Search

### 3.1 Scope

The index is built from `this._viewTree()`, so staged values, new entries,
renames and deletions are searched as the user sees them, not as the last disk
revision.

For each node, except the document root:

| Search source | Value | Priority |
|---|---|---|
| key | decoded last path token and `node.label` | highest |
| path | decoded full path | high |
| scalar value | `_plainText(node)` (unquoted string, bare number/bool) | medium |
| description | `node.field.description` (and `node.field.title` when present) | low |

Decisions:

- **Leaves only for value search.** An object's `value_text` is the source of
  its whole subtree, so indexing it would return the parent for every child
  value. Container nodes are found by key and description; the matching leaf
  supplies the value hit. Empty objects and arrays are still found by key.
- **Absent keys are searchable.** The snapshot contains declared-but-unwritten
  keys as `exists: false`. A result for such a node is marked `absent`. If the
  editor's `showAbsent` flag is off, activating that result turns it on (and
  emits the normal `viewchange`), because otherwise the tree cannot render the
  target. A short status message says why the view changed.
- **Secrets are not searchable by value.** `access_denied` nodes never reach the
  browser's value text; the index must not invent one. Their key and
  description remain searchable and the normal `secret` badge is shown.
- **Only the active union shape is indexed.** Other alternatives are not in the
  rendered tree and cannot be revealed without changing the shape. Searching
  them would produce dead results.
- **The document root is skipped.** Its path is `/` and its description usually
  matches broad queries; it is always present anyway.

A private `_searchChildren(node)` returns the child list for indexing without
the `showAbsent` filter of `_visibleChildren`, while still using the active
union alternative's children (`_unionVisibleChildren`). This is the only new
traversal rule.

### 3.2 Matching and ranking

- Query is trimmed and lower-cased. Empty query closes the result list.
- Whitespace splits the query into terms; every term must match at least one of
  key, path, value or description (AND across terms).
- A term may be a substring. Case-insensitive substring is enough: no regex,
  no fuzzy scoring, no server round trip.
- Score is summed over terms:

```text
key equals term          100
key starts with term      80
key contains term         60
path contains term        50
value contains term       35
description contains term 25
```

Results are sorted by score descending, then by path. Duplicate nodes are
impossible because each path appears once in the index.

The list is capped at 50 visible results. When more match, a non-clickable
trailing row says `Showing first 50 of N`.

The visual index is built lazily on the first non-empty query and rebuilt on
each query. A 60–80 ms debounce on the input prevents needless work on a very
large document, but the public `search(text)` method stays synchronous so tests
and hosts do not have to wait for a timer.

### 3.3 Result list

Each result is an `li` with role `option`:

```text
name                    value · string
/workers/items/0/name
"…snippet with the matched text…"
```

- The key is the prominent text.
- The full path is the secondary line.
- One or more match-kind labels (`key`, `value`, `description`) and the node
  type are shown as small text.
- A value or description hit shows a short snippet around the first matching
  term, with surrounding whitespace collapsed. The matched substring is wrapped
  in `<mark>`; the rest is a text node, never `innerHTML` from the snapshot.
- An absent node gets the existing `absent` treatment and the same amber colour
  as an absent row.

The list is absolutely positioned below the input, with a maximum height and
its own scrollbar. It overlays the tree instead of reflowing it.

### 3.4 Activating a result

Clicking a result, or pressing Enter on the active one, runs one reveal
operation:

```javascript
TreeEditor.prototype._revealPath = function (path) {
  var node = this._find(path);
  if (!node) { this._setStatus("error", "The search target no longer exists."); return; }

  if (node.exists === false && !this.showAbsent) {
    this.setShowAbsent(true);          // renders and emits viewchange
  }

  var parts = path.split("/").filter(Boolean);
  var prefix = "";
  this.expanded[""] = true;
  for (var i = 0; i < parts.length - 1; i += 1) {
    prefix += "/" + parts[i];
    this.expanded[prefix] = true;      // every ancestor, however deep
  }
  this.expanded[path] = true;          // reveal the target's own children too

  this._pendingReveal = path;
  this._render();

  var row = this._rowByPath[path];
  if (!row) { return; }
  row.classList.add("aiset-tree-search-hit");
  row.focus({ preventScroll: true });
  row.scrollIntoView({
    block: "center",
    inline: "nearest",
    behavior: prefersReducedMotion() ? "auto" : "smooth"
  });
  this._scheduleContextUpdate();
  this._setStatus("info", "Jumped to " + path + ".");
};
```

`_rowByPath` is built during `_renderNode` alongside `_renderedRows` and cleared
at the start of `_render`. Both the node container and its row carry a
`data-path` attribute (the row copy is what hit-testing reads). Looking a row
up by the map avoids a CSS selector that would have to escape `/`, `~0`, `~1`,
quotes and spaces in path tokens.

The row receives `tabindex="-1"` on every render. That does not add a tab stop
but makes programmatic focus legal. Focus goes to the **row**, not to its input
control: focusing a text field would let the next keystroke edit the document
by accident, while a focused row keeps the tree context and the next Tab reaches
the control. The target row gets `aiset-tree-search-hit` as a temporary visual
landmark. The highlight is removed on the next search, on Escape, or on the next
render that is not a reveal.

After activation the result list closes but the query remains in the input, so
the user can reopen the same list with ArrowDown or by focusing the input again.

### 3.5 Keyboard and accessibility

The input is a combobox over a listbox:

- `role="combobox"`, `aria-autocomplete="list"`, `aria-expanded`,
  `aria-controls` pointing at the result list, and `aria-activedescendant`
  pointing at the active option.
- Every editor instance gets a small unique suffix for element ids, so two
  editors on one page cannot collide.
- `ArrowDown` / `ArrowUp` move the active result and keep it scrolled into view
  inside the result list.
- `Enter` activates the active result, or the first result when none is active.
- `Escape` closes the list, clears the active descendant and removes the search
  highlight; it does not clear the text.
- `Tab` leaves the search normally and closes the list.
- Clicking outside the search container closes the list. A document-level
  `pointerdown` listener is added at mount and removed in `destroy`.
- `:focus-visible` already gives the focused row the library focus ring.
- Result rows are real buttons? No: a `li role="option"` with a click handler is
  enough, and it keeps arrow-key semantics under the combobox. `mousedown`
  calls `preventDefault` so the input keeps focus and the list does not close
  before `click`.

The search container is `aria-label="Search keys, values and descriptions"`.
A no-match state is a plain non-option `li role="status"` with the text
`No matches`.

### 3.6 Lifecycle

- Search state belongs to the instance: query, results, active index and the
  pending reveal target.
- `reload()` clears the reveal target and reruns the current query after the
  new tree arrives; results whose path disappeared are dropped.
- `destroy()` closes the list, removes the document `scroll` and `pointerdown`
  listeners, and cancels a pending animation frame.
- Search never stages or writes anything. Applying, reverting or collapsing
  still goes through the existing public methods.

---

## 4 — Visible-path breadcrumbs

### 4.1 Meaning

The context line shows the full path to the topmost tree row that is still
visible in the scroll container. When `/workers/items/0/name` is the first row
below the sticky top strip, the line reads:

```text
/ workers / items / 0 / name
```

At the top of the tree it reads `/`. If the viewport starts in the middle of a
deep group because the parent rows have scrolled away, the line still contains
the whole ancestor chain. That is the information the topmost row alone cannot
show.

Segments are display text for now, not links. Making an ancestor segment
scroll to its own path is a natural later extension, but it is not needed to
solve the reported problem and would add another focus target to the tree.

### 4.2 Finding the top row

The top strip changes the visible top edge: the first row may be partly hidden
behind the sticky search/context block. The update routine therefore uses the
bottom of the top strip as the effective viewport top:

```javascript
TreeEditor.prototype._updateContext = function () {
  var scroller = this._scrollAncestor();       // nearest overflow: auto/scroll
  var box = scroller.getBoundingClientRect ? scroller.getBoundingClientRect()
                                           : { top: 0, left: 0 };
  var bar = this.topbar.getBoundingClientRect();
  var top = Math.max(box.top, bar.bottom);

  var row = null;
  if (document.elementFromPoint) {
    var hit = document.elementFromPoint(box.left + 8, top + 1);
    row = hit && hit.closest ? hit.closest(".aiset-tree-row") : null;
    /* A result popup or the top strip itself may be under the probe point;
     * fall back to the rendered rows in document order. */
    if (!row || !this.treeNode.contains(row)) { row = this._firstVisibleRow(top); }
  } else {
    row = this._firstVisibleRow(top);
  }

  var path = row ? (row.dataset.path || "") : "";
  if (path !== this._contextPath) {
    this._contextPath = path;
    this.contextPathNode.textContent = formatContextPath(path);
    this._emit("contextchange", { path: path });
  }
};
```

`_firstVisibleRow(top)` walks `_renderedRows` (populated in `_renderNode` in
document order) and returns the first row whose `getBoundingClientRect().bottom`
is greater than `top`. It is the fallback for browsers or hit-test results that
do not expose the row.

`_scrollAncestor()` walks `parentElement` like `_captureScroll` does and returns
the nearest ancestor whose computed `overflow-y` is `auto`, `scroll` or
`overlay` and whose `scrollHeight` exceeds its `clientHeight`. If there is none,
it returns `document.scrollingElement || document.documentElement`. Recomputing
it per update is cheap and survives a host changing its layout.

### 4.3 When it updates

- On `scroll` events. The event does not bubble, so the listener is registered
  on `document` with `capture: true`.
- After every `_render`, `_applyViewChange`, `expandAll` / `collapseAll`, and
  after a search reveal.
- On window resize; the existing `_onResize` handler is extended to schedule a
  context update.
- Updates are coalesced through `requestAnimationFrame`; the path text is
  written only when the path actually changes, so the breadcrumb itself cannot
  cause a scroll feedback loop.
- The listener and the animation-frame handle are removed in `destroy`.

### 4.4 Styling and host integration

`aiset.css` provides:

- `.aiset-tree-topbar`: sticky strip, background from `--aiset-surface`, border
  from `--aiset-border`, `z-index` above the tree.
- `.aiset-tree-context`: one line, monospace, muted, truncating with ellipsis or
  scrolling horizontally when a path is wider than the pane; it never wraps and
  never changes height.
- `.aiset-tree-search`, `.aiset-tree-search-input` and
  `.aiset-tree-search-results`: the search field and its overlay panel.

The reference theme (`aiset-host-theme.css`) gets matching colour overrides.

A host that wants the breadcrumb in its own header instead of inside the editor
can listen to `contextchange` and render `payload.path` there, or call
`instance.getContextPath()`. Such a host is responsible for hiding or restyling
the editor's own line; the default stays inside the editor, so demo2 and any
host that mounts the tree editor get the feature without extra glue. (The
standalone `frontend/index.html` uses the older single-value editor, not the
tree editor.)

---

## 5 — Public API additions

```javascript
instance.search(text)          // set the query, return the current result array
instance.focusSearch()         // focus the input and select its text
instance.revealPath(path)      // expand ancestors, scroll and focus a path
instance.getContextPath()      // path currently shown by the breadcrumb
instance.on("contextchange", handler)  // {path} whenever the path changes
```

`search(text)` is the programmatic form of typing into the field. It reuses the
same index and result rendering. It returns plain result objects
(`{path, score, kinds, snippet}`), not DOM nodes, so a host can build its own
result UI if it wants.

The `contextchange` event is emitted only when the resolved path changes. It is
not emitted on every scroll frame.

---

## 6 — Files touched

| File | Change |
|---|---|
| `src/aiset/assets/aiset-tree.js` | search index, result list, reveal/focus, top strip, context computation, new public methods, class inventory entries |
| `src/aiset/assets/aiset.css` | structural styles for the top strip, search results, context line, search hit; all colours via `--aiset-*` |
| `src/aiset/assets/aiset-host-theme.css` | reference-theme overrides for the same classes |
| `SPEC_service.md` | add the new class rows to the section 21.1 table (documentation only) |
| `tests/test_ui_assets.py` | new DOM-stub checks; this is the existing JS test harness, not server code |
| `demo2/frontend/app.js` | re-sync the view-option checkboxes when search enables show-absent |
| `README.md` | name the search, reveal and context API in the tree-editor section |
| `AGENT_INTEGRATION.md` | add the new classes to the host inventory |
| `TEST.md` | manual browser protocol for search, focus and breadcrumb scrolling |
| `DOCUMENTS.MD` | link this proposal |
| `memory/context.md`, `memory/history.md` | session notes |

Not touched: `src/aiset/*.py`, `src/aiset/assets/__init__.py`, the service,
HTTP/ASGI adapters, descriptor grammar, tree snapshot builder, permissions, and
everything else on the Python side. The server-rendered skeleton stays a
placeholder that `_renderShell` replaces on mount.

### New class inventory entries

| Class | Element | Role | Required |
|---|---|---|---|
| `aiset-tree-topbar` | div | structure | true |
| `aiset-tree-search` | div | structure | true |
| `aiset-tree-search-input` | input | control | false |
| `aiset-tree-search-results` | ul | structure | true |
| `aiset-tree-search-result` | li | action | true |
| `aiset-tree-search-path` | span | text | false |
| `aiset-tree-search-snippet` | span | text | false |
| `aiset-tree-search-hit` | div | structure | false |
| `aiset-tree-context` | nav | structure | true |
| `aiset-tree-context-path` | span | text | false |

---

## 7 — Test plan

### 7.1 Automated (existing DOM stub)

1. `search("...")` finds a key, a scalar value and a description, each with the
   correct `kind`.
2. Search is case-insensitive; multi-term queries require all terms; ranking is
   key before value before description; the 50-result cap is enforced.
3. Container `value_text` is not matched by a child value; the leaf is the only
   result.
4. An absent declared key is found, marked `absent`, and `revealPath` turns on
   `showAbsent` before rendering.
5. A secret node exposes no value text to the index; its key is still found and
   the result carries the `secret` marker.
6. Staged values and new entries are found through `_viewTree`; reverting them
   removes them from the next query.
7. `revealPath("/a/b/c")` expands `""`, `/a`, `/a/b` and `/a/b/c`, and calls
   `focus()` and `scrollIntoView()` on the row found through `_rowByPath`.
8. Rows carry `tabindex="-1"`; an activated result has
   `aiset-tree-search-hit`.
9. Keyboard handling: ArrowDown/ArrowUp change `aria-activedescendant`; Enter
   reveals; Escape closes; Tab closes.
10. Breadcrumb computation: with injected geometry, the first row whose bottom
    crosses the top-strip bottom gives its path; a fully hidden parent is
    included in the path; no visible row yields `/`.
11. `contextchange` fires once per changed path, not once per scroll frame.
12. `destroy()` removes the document listeners and cancels the pending frame.
13. The class inventory, the source literals and the `SPEC_service.md` table
    stay in sync (the existing drift tests cover this automatically once the
    new entries are added).

### 7.2 Manual browser protocol

1. Open demo2, or any host page that mounts the tree editor.
2. Type a key fragment: the list shows matching keys, values and descriptions;
   the first result is active.
3. Click a deep collapsed result: every ancestor opens, the row is centred,
   focused and highlighted; the breadcrumb shows its full path.
4. Repeat with the keyboard only: ArrowDown, Enter, then Tab into the row's
   control.
5. Search for a value and a description, not just a key.
6. Search an absent key with "show absent" off: the view switches on, the key
   appears, the status explains why.
7. Search a known secret value: no result; the key is still found.
8. Scroll a long tree: the breadcrumb names the topmost visible row, including
   ancestors that have left the viewport.
9. Collapse all, expand all, stage an edit, apply it: the breadcrumb and search
   stay consistent and the viewport is not thrown to the top.
10. Resize the pane and the window: the sticky strip and the breadcrumb keep
    working; the search results stay anchored to the input.
11. Repeat in a host whose scroller is an ancestor of the mount (demo2's
    `.pane-body`), not the mount itself.

---

## 8 — Acceptance criteria

- A user can find a key, a scalar value, or a description without knowing where
  it is in the document.
- Activating a result expands the complete ancestor chain, scrolls the target
  into view and leaves keyboard focus on the target row.
- Searching never writes to the document and never reveals a secret value.
- The context line always names the topmost visible row's full path while the
  tree is scrolled, and stays visible because the top strip is sticky.
- The feature works identically in demo2 and in any host that mounts the tree
  editor, without new routes or Python changes.
- All new classes are in `aiset.classes()` and in the `SPEC_service.md` table;
  the existing UI drift tests stay green.

---

## 9 — Implementation progress

**2026-10-23 — implemented.** The feature is browser-only; no Python source,
route, descriptor, snapshot field or service method changed.

### 9.1 What was done

- `src/aiset/assets/aiset-tree.js`
  - Added the sticky `.aiset-tree-topbar` to the shell with the search input,
    result listbox and the context path line.
  - Added the search index over the current view tree (so staged edits are
    searched as rendered), matching keys, decoded paths, scalar values and
    `field.title` / `field.description`.
  - Absent declared keys are indexed and activating one enables `showAbsent`
    before rendering; secret values never enter the index.
  - Composite source text is not indexed, so a child value returns the leaf,
    not every ancestor that repeats it in `value_text`.
  - Added ranking, the 50-result cap, snippets with `<mark>`, a no-match state,
    combobox/listbox ARIA wiring, arrow/Enter/Escape/Tab handling, outside-click
    closing and instance-scoped ids.
  - `revealPath` expands every ancestor and the target, re-renders, scrolls the
    row to the centre, focuses the row (`tabindex="-1"`) and marks it with
    `aiset-tree-search-hit`.
  - Added the context breadcrumb: the top row is found below the sticky strip
    with `elementFromPoint` and a `_firstVisibleRow` fallback; updates are
    throttled with `requestAnimationFrame` and emitted as `contextchange`.
  - Added public `search`, `focusSearch`, `revealPath` and `getContextPath`.
  - Added the ten class-inventory entries; rows now carry `data-path` and are
    programmatically focusable.
- `src/aiset/assets/aiset.css`: structural and visual rules for the top strip,
  search field/results, highlighted hit and context line; colours stay on
  `--aiset-*` variables.
- `src/aiset/assets/aiset-host-theme.css`: reference-theme coverage for every
  new class.
- `SPEC_service.md` 21.1: the new class rows.
- `demo2/frontend/app.js`: the host's view-option checkboxes now follow a
  `viewchange`, so an absent-key search that enables show-absent stays in sync.
- `tests/test_ui_assets.py`: the existing DOM smoke test now covers key, value
  and description search, case folding, multi-term matching, absent-key reveal,
  deep-path expansion, focus, highlighting and the breadcrumb's top-row
  resolution; the stub records `focus` and `scrollIntoView` calls.
- `README.md`, `AGENT_INTEGRATION.md` and `TEST.md`: the public API, the class
  inventory and the demo2 manual steps now include the new UI.

### 9.2 Verification

`./test.sh` passes: **463 passed**, same test count because the new assertions
live in the existing `test_tree_editor_public_api` smoke test. The descriptor
diagnostics and the tracked-example checks are green as well.

No live browser was available in this environment, so the manual protocol in
section 7.2 remains the recommended visual check (especially sticky positioning,
smooth scrolling and the demo2 `.pane-body` scroller).

### 9.3 Notes and deviations

- The context line uses JSON Pointer paths with decoded tokens; the root is `/`
  and `getContextPath()` returns the empty root pointer `""`.
- Search results are plain objects (`path`, `keyLabel`, `type`, `exists`,
  `score`, `kinds`, `snippet`); the DOM list is an implementation detail.
- The row highlight is cleared by a new search or Escape, and disappears with
  the next full render unless the render is the reveal that created it.
- A pending debounced query is cancelled before a synchronous search or a close,
  so Enter/Escape cannot be followed by a late result list reopening.
