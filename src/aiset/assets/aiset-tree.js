/* aiset tree editor (SPEC_service.md section 21).
 *
 * Reusable, framework-free editor for one configuration document: it builds
 * its structure from the authorized tree snapshot, stages every change until
 * the user presses Apply, and commits the whole batch through aiset's atomic
 * operations endpoint. The server is always authoritative.
 *
 * Public API (per mounted instance, never through module-global state):
 *   aiset.renderTreeEditor(document, options)  -> HTML fragment for a host
 *   aiset.mountTree(target, options)           -> instance
 *   instance.getPendingOperations()
 *   instance.stageOperations(operations, source)
 *   instance.validatePending()
 *   instance.applyPending()
 *   instance.reload()
 *   instance.revert(path)
 *   instance.expandAll() / instance.collapseAll()
 *   instance.setValuesAsText(flag) / instance.getValuesAsText()
 *   instance.setShowAbsent(flag) / instance.getShowAbsent()
 *
 * Every node also offers raw source editing and, where the descriptor allows
 * it, an environment variable: the name and the inline fallback are edited
 * separately, so a substitution is never lost by changing the value.
 *   instance.on(event, handler) / instance.destroy()
 */

(function (global) {
  "use strict";

  var api = global.aiset || (global.aiset = {});

  /* The class inventory, as data (SPEC_service.md section 21, AGENT_INTEGRATION
   * section 8a.2). A host styles against these names; a library test compares
   * this list with the classes the source actually emits, so the two cannot
   * drift. `required` marks the classes a host must style for the tree to be
   * readable (structure), as opposed to optional polish. */
  var CLASS_INVENTORY = [
    { name: "aiset-tree-editor", element: "div", role: "root", required: true },
    { name: "aiset-tree-toolbar", element: "div", role: "toolbar", required: true },
    { name: "aiset-tree", element: "div", role: "tree", required: true },
    { name: "aiset-tree-node", element: "div", role: "structure", required: true },
    { name: "aiset-tree-row", element: "div", role: "structure", required: true },
    { name: "aiset-tree-children", element: "div", role: "structure", required: true },
    { name: "aiset-tree-desc", element: "div", role: "structure", required: false },
    { name: "aiset-tree-toggle", element: "button", role: "control", required: true },
    { name: "aiset-tree-toggle-type", element: "span", role: "control", required: false },
    { name: "aiset-tree-type", element: "span", role: "badge", required: false },
    { name: "aiset-tree-name", element: "span", role: "text", required: true },
    { name: "aiset-tree-badges", element: "span", role: "badge", required: false },
    { name: "aiset-tree-badge", element: "span", role: "badge", required: false },
    { name: "aiset-tree-value", element: "span", role: "control", required: true },
    { name: "aiset-tree-value-readonly", element: "span", role: "control", required: false },
    { name: "aiset-tree-key", element: "input", role: "control", required: false },
    { name: "aiset-tree-null", element: "input", role: "control", required: false },
    { name: "aiset-tree-actions", element: "span", role: "action", required: false },
    { name: "aiset-tree-action", element: "button", role: "action", required: false },
    { name: "aiset-tree-env", element: "input", role: "control", required: false },
    { name: "aiset-tree-env-state", element: "button", role: "action", required: false },
    { name: "aiset-tree-template", element: "span", role: "control", required: false },
    { name: "aiset-tree-secret", element: "span", role: "text", required: false },
    { name: "aiset-tree-source", element: "div", role: "control", required: false },
    { name: "aiset-tree-raw", element: "div", role: "control", required: false },
    { name: "aiset-tree-raw-title", element: "div", role: "text", required: false },
    { name: "aiset-tree-raw-text", element: "textarea", role: "control", required: false },
    { name: "aiset-tree-raw-actions", element: "div", role: "action", required: false },
    { name: "aiset-tree-shape", element: "select", role: "control", required: false },
    { name: "aiset-tree-union", element: "span", role: "control", required: false },
    { name: "aiset-tree-chooser", element: "span", role: "action", required: false },
    { name: "aiset-tree-pending", element: "div", role: "structure", required: true },
    { name: "aiset-tree-staged", element: "ul", role: "structure", required: false },
    { name: "aiset-tree-staged-row", element: "li", role: "structure", required: false },
    { name: "aiset-tree-staged-op", element: "span", role: "text", required: false },
    { name: "aiset-tree-staged-path", element: "span", role: "text", required: false },
    { name: "aiset-tree-staged-source", element: "span", role: "text", required: false },
    { name: "aiset-tree-status", element: "div", role: "status", required: true },
    { name: "aiset-tree-issues", element: "ul", role: "status", required: true },
    { name: "aiset-tree-view", element: "button", role: "action", required: false },
    { name: "aiset-tree-lifecycle", element: "button", role: "action", required: false },
    { name: "aiset-tree-button", element: "button", role: "action", required: false },
    { name: "aiset-tree-apply", element: "button", role: "action", required: false },
    { name: "aiset-tree-reload", element: "button", role: "action", required: false },
    { name: "aiset-tree-revert", element: "button", role: "action", required: false },
    { name: "aiset-tree-icon", element: "svg", role: "icon", required: false },
    { name: "aiset-tree-icon-text", element: "span", role: "icon", required: false },
    { name: "aiset-form", element: "div", role: "form", required: false },
    { name: "aiset-form-title", element: "div", role: "form", required: false },
    { name: "aiset-form-row", element: "div", role: "form", required: false },
    { name: "aiset-form-label", element: "label", role: "form", required: false },
    { name: "aiset-form-field", element: "span", role: "form", required: false },
    { name: "aiset-form-control", element: "input", role: "form", required: false },
    { name: "aiset-form-actions", element: "div", role: "form", required: false },
  ];

  function request(base, method, path, body) {
    var options = { method: method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(base + path, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || payload.ok === false) {
          var error = new Error((payload.error && payload.error.message) || response.statusText);
          error.code = (payload.error && payload.error.code) || "HTTP_" + response.status;
          error.issues = (payload.error && payload.error.issues) || [];
          error.status = response.status;
          throw error;
        }
        return payload;
      });
    });
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || payload.ok === false) {
          var error = new Error((payload.error && payload.error.message) || response.statusText);
          error.code = (payload.error && payload.error.code) || "HTTP_" + response.status;
          error.status = response.status;
          error.issues = (payload.error && payload.error.issues) || [];
          throw error;
        }
        return payload;
      });
    });
  }

  function element(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") { node.textContent = attrs[key]; }
      else if (key === "class") { node.className = attrs[key]; }
      else if (key.indexOf("on") === 0) { node.addEventListener(key.slice(2), attrs[key]); }
      else if (key === "dataset") { Object.keys(attrs.dataset).forEach(function (d) { node.dataset[d] = attrs.dataset[d]; }); }
      /* Boolean attributes are disabled by their presence: set them as
       * properties, because setAttribute("disabled", false) still disables. */
      else if (key === "disabled" || key === "checked" || key === "readonly" || key === "required") {
        node[key] = attrs[key] === true || attrs[key] === "true";
      }
      else if (attrs[key] !== null && attrs[key] !== undefined) { node.setAttribute(key, attrs[key]); }
    });
    (children || []).forEach(function (child) { if (child) { node.appendChild(child); } });
    return node;
  }

  function label(text) { return document.createTextNode(text); }

  function TreeEditor(host, options) {
    this.host = host;
    this.document = options.document;
    this.apiBase = options.apiBase || "/api/settings";
    this.view = options.view || "source";
    this.lifecycle = options.lifecycle || [];
    this.hostRoutes = options.hostRoutes || {};
    this.agents = options.agents || null;
    this.viewButtons = options.viewButtons !== false;
    this.valuesAsText = options.valuesAsText === true;
    this.showAbsent = options.showAbsent === true;
    this.pending = [];
    this.revision = null;
    this.descriptorRevision = null;
    this.tree = null;
    this.expanded = {};
    this.rawMode = {};
    this.envDraft = {};
    this.hiddenTemplate = {};
    this.keyDrafts = {};
    this._addSeq = 0;
    this.unionShape = {};
    this._envNames = {};
    this.handlers = {};
    this.busy = false;
    this._renderShell();
    var self = this;
    this._onResize = function () { self._fitAllRaw(); };
    if (global.addEventListener) { global.addEventListener("resize", this._onResize); }
    this.ready = this.reload();
  }

  TreeEditor.prototype._renderShell = function () {
    this.host.innerHTML = "";
    this.toolbar = element("div", { class: "aiset-tree-toolbar" });
    this.statusNode = element("div", { class: "aiset-tree-status", role: "status", "aria-live": "polite" });
    this.issuesNode = element("ul", { class: "aiset-tree-issues" });
    this.treeNode = element("div", { class: "aiset-tree", role: "tree" });
    this.pendingNode = element("div", { class: "aiset-tree-pending" });
    this.host.appendChild(this.toolbar);
    this.host.appendChild(this.treeNode);
    this.host.appendChild(this.pendingNode);
    this.host.appendChild(this.statusNode);
    this.host.appendChild(this.issuesNode);
    this._renderToolbar();
  };

  TreeEditor.prototype._renderToolbar = function () {
    var self = this;
    this.toolbar.innerHTML = "";
    this.applyButton = element("button", { type: "button", class: "aiset-tree-button aiset-tree-apply", text: "Apply", onclick: function () { self.applyPending(); } });
    this.reloadButton = element("button", { type: "button", class: "aiset-tree-button aiset-tree-reload", text: "Reload", onclick: function () { self.reload(true); } });
    this.revertButton = element("button", { type: "button", class: "aiset-tree-button aiset-tree-revert", text: "Revert all", onclick: function () { self.stageOperations([], "user"); } });
    this.toolbar.appendChild(this.applyButton);
    this.toolbar.appendChild(this.reloadButton);
    this.toolbar.appendChild(this.revertButton);
    if (this.viewButtons) {
      this.expandButton = this._viewButton("Expand all", "Expand every section of the tree", function () { self.expandAll(); });
      this.collapseButton = this._viewButton("Collapse all", "Collapse every section; the document root stays open", function () { self.collapseAll(); });
      this.toolbar.appendChild(this.expandButton);
      this.toolbar.appendChild(this.collapseButton);
    }
    this.lifecycle.forEach(function (action) {
      var button = element("button", { type: "button", text: action.label, class: "aiset-tree-lifecycle" });
      button.addEventListener("click", function () { self.runLifecycle(action); });
      self.toolbar.appendChild(button);
    });
  };

  TreeEditor.prototype._viewButton = function (text, title, handler) {
    var button = element("button", { type: "button", class: "aiset-tree-view", title: title, "aria-label": title });
    button.textContent = text;
    button.addEventListener("click", handler);
    return button;
  };

  /* Expand or collapse every composite node at once. The document root stays
   * open on collapse: a fully closed tree would hide the top-level sections. */
  TreeEditor.prototype.expandAll = function () {
    var self = this;
    var root = this._rootNode();
    this.expanded = {};
    if (root) {
      this.expanded[root.path || ""] = true;
      (function walk(node) {
        self._visibleChildren(node).forEach(function (child) {
          if (self._visibleChildren(child).length) { self.expanded[child.path] = true; }
          walk(child);
        });
      })(root);
    }
    this._applyViewChange();
  };

  TreeEditor.prototype.collapseAll = function () {
    this.expanded = {};
    var root = this._rootNode();
    if (root) { this.expanded[root.path || ""] = true; }
    this._applyViewChange();
  };

  TreeEditor.prototype.isExpanded = function (path) {
    return !!this.expanded[path];
  };

  /* Composite nodes show their stored source text only when the host asks for
   * it; otherwise they are edited through their children. */
  TreeEditor.prototype.setValuesAsText = function (flag) {
    this.valuesAsText = flag === true;
    this._applyViewChange();
    return this.valuesAsText;
  };

  TreeEditor.prototype.getValuesAsText = function () {
    return this.valuesAsText;
  };

  /* Declared keys that are not written in the file: shown only on request. */
  TreeEditor.prototype.setShowAbsent = function (flag) {
    this.showAbsent = flag === true;
    this._applyViewChange();
    return this.showAbsent;
  };

  TreeEditor.prototype.getShowAbsent = function () {
    return this.showAbsent;
  };

  TreeEditor.prototype._applyViewChange = function () {
    this._render();
    this._emit("viewchange", {
      valuesAsText: this.valuesAsText,
      showAbsent: this.showAbsent,
      expanded: Object.keys(this.expanded).length
    });
  };

  TreeEditor.prototype._rootNode = function () {
    return (this.tree && this.tree.node) || null;
  };

  TreeEditor.prototype.on = function (event, handler) {
    (this.handlers[event] = this.handlers[event] || []).push(handler);
    return this;
  };

  TreeEditor.prototype._emit = function (event, payload) {
    (this.handlers[event] || []).forEach(function (handler) { handler(payload); });
  };

  TreeEditor.prototype._setStatus = function (state, message) {
    this.statusNode.textContent = message;
    this.statusNode.setAttribute("data-state", state || "info");
    this._emit("status", { state: state, message: message });
  };

  TreeEditor.prototype._setIssues = function (issues) {
    this.issuesNode.innerHTML = "";
    (issues || []).forEach(function (issue) {
      var path = issue.path || "/";
      if (issue.line) { path += " (line " + issue.line + ", column " + issue.column + ")"; }
      this.issuesNode.appendChild(element("li", { text: "[" + issue.severity + "] " + path + ": " + issue.message }));
    }, this);
  };

  // -- data ------------------------------------------------------------
  TreeEditor.prototype.reload = function (confirmFirst) {
    var self = this;
    if (confirmFirst && this.pending.length) {
      if (!global.confirm("Discard " + this.pending.length + " staged change(s)?")) { return this.ready; }
      this.stageOperations([], "user");
    }
    this._setStatus("pending", "Loading configuration...");
    return request(this.apiBase, "GET", "/tree?document=" + encodeURIComponent(this.document) +
                   "&view=" + encodeURIComponent(this.view))
      .then(function (tree) {
        self.tree = tree;
        self.revision = tree.revision;
        self.descriptorRevision = tree.descriptor_revision;
        self._expandDefault();
        self.hiddenTemplate = {};
        self.unionShape = {};
        self._render();
        self._setStatus("ok", "Loaded revision " + String(tree.revision).slice(0, 12) +
          (tree.invalid_on_disk ? " — invalid on disk, showing the last valid state" : ""));
        self._emit("loaded", tree);
        return tree;
      })
      .catch(function (error) {
        /* A network-level failure says nothing about the document, so name the
         * cause a user can act on: the host is not answering. */
        self._setStatus("error", /failed to fetch|networkerror/i.test(error.message)
          ? "Load failed: the host did not answer. Is demo2 still running?"
          : "Load failed: " + error.message);
        self._setIssues(error.issues);
        throw error;
      });
  };

  TreeEditor.prototype._expandDefault = function () {
    if (!this.tree || !this.tree.node) { return; }
    var self = this;
    this.expanded = {};
    this.expanded[this.tree.path || ""] = true;
    var visible = this._visibleChildren;
    (function walk(node, depth) {
      if (depth > 1) { return; }
      visible.call(self, node).forEach(function (child) {
        self.expanded[child.path] = true;
        walk(child, depth + 1);
      });
    })(this.tree.node, 0);
  };

  TreeEditor.prototype._find = function (path) {
    if (!this.tree || !this.tree.node) { return null; }
    var found = null;
    (function walk(node) {
      if (node.path === path) { found = node; return; }
      (node.children || []).concat(node.items || []).forEach(walk);
    })(this.tree.node);
    return found;
  };

  // -- staging ---------------------------------------------------------
  TreeEditor.prototype.getPendingOperations = function () {
    return this.pending.map(function (item) { return Object.assign({}, item.operation); });
  };

  /* Writing what the file already holds is not a change: it must not stage an
   * operation, must not mark the row dirty, and must leave the staged list
   * empty. Entering the environment mode and leaving it again untouched is the
   * common case. */
  /* Whether a value says what the file already says. */
  TreeEditor.prototype._matchesStore = function (operation) {
    if (!operation || operation.op !== "set") { return false; }
    var node = this._find(operation.path || "");
    if (!node || node.exists === false) { return false; }
    return this._sameValue(node, operation.value_text);
  };

  /* What the file holds and what a control proposes are written on two
   * different layers: the quotes belong to the JSON5 literal around a
   * substitution, and "${VAR}" says exactly what "${VAR:-}" says. So a value
   * behind a substitution is compared by its variable and its default, and
   * everything else is compared without the quotes. */
  TreeEditor.prototype._sameValue = function (node, text) {
    var storedText = this._valueText(node);
    var stagedText = text === null || text === undefined ? "" : String(text);
    if (storedText === stagedText) { return true; }
    var stored = this._templateInfo(node);
    var staged = this._templateInfo({ value_text: stagedText });
    if (stored && staged) {
      var storedDefault = stored.fallback === null || stored.fallback === undefined ? "" : stored.fallback;
      var stagedDefault = staged.fallback === null || staged.fallback === undefined ? "" : staged.fallback;
      return stored.name === staged.name && storedDefault === stagedDefault;
    }
    return unquote(String(storedText)) === unquote(stagedText);
  };

  /* Nothing about "dirty" is stored per node. A node is dirty exactly when it
   * carries a staged operation that the file does not already describe, so a
   * value that comes back to what the file holds takes its operation with it
   * and the node turns clean again — the same rule for every control, and the
   * reason toggling a checkbox twice ends where it started. */
  TreeEditor.prototype._reconcile = function (operation) {
    var self = this;
    var path = operation.path || operation.from || "";
    if (operation.op === "set") {
      /* A value of an entry that the same batch adds belongs to that add: the
       * service accepts the append token on an add only, and one operation
       * says the intended result better than two. */
      var adds = this.pending.filter(function (item) {
        return item.operation.op === "add" &&
          (item.operation.path === path || self._resolvedAddPath(item) === path);
      });
      if (adds.length) {
        for (var i = 0; i < adds.length; i += 1) {
          adds[i].operation.value_text = operation.value_text;
        }
        return false;
      }
      var token = path.slice(path.lastIndexOf("/") + 1);
      if (token === "-" || token === "*") {
        /* An append token names an entry, and nothing has added it yet. */
        return false;
      }
      /* Editing a value means the node stays, so a staged removal of the same
       * node is dropped instead of leaving a batch that could not apply. */
      this.pending = this.pending.filter(function (item) {
        return !(item.operation.op === "remove" && item.operation.path === path);
      });
      if (this._matchesStore(operation)) {
        this.pending = this.pending.filter(function (item) {
          return !(item.operation.op === "set" && item.operation.path === path);
        });
        return false;
      }
    }
    return true;
  };

  TreeEditor.prototype.stageOperations = function (operations, source) {
    var self = this;
    (operations || []).forEach(function (operation) {
      if (!operation) { return; }
      if (!self._reconcile(operation)) { return; }
      /* Every append is its own entry: two appends to the same array share the
       * path "-" but must not replace each other. Other operations still
       * deduplicate by path. */
      var key = operation.op === "add"
        ? "add|" + (operation.path || "") + "|" + (self._addSeq++)
        : operation.op + "|" + (operation.path || "") + "|" + (operation.from || "");
      var existing = -1;
      self.pending.forEach(function (item, index) {
        if (item.key === key) { existing = index; }
      });
      if (existing >= 0) { self.pending.splice(existing, 1); }
      var entry = { key: key, operation: Object.assign({}, operation), source: source || "user" };
      self.pending.push(entry);
      if (operation.op === "add") {
        /* What was just created opens: the point of adding it is to fill it. */
        self.expanded[self._resolvedAddPath(entry)] = true;
        var parentPath = (operation.path || "").slice(0, (operation.path || "").lastIndexOf("/"));
        if (parentPath) { self.expanded[parentPath] = true; }
      }
    });
    if (!operations || !operations.length) { this.pending = []; this.unionShape = {}; }
    this._renderPending();
    this._render();
    this._emit("staged", this.getPendingOperations());
    return this.getPendingOperations();
  };

  /* Dropping a staged operation also restores the view: the row goes back to
   * the substitution the file holds, with its name and its drop button. */
  TreeEditor.prototype.revert = function (path) {
    var self = this;
    this.pending = this.pending.filter(function (item) {
      return item.operation.path !== path && item.operation.from !== path &&
        !(item.operation.op === "add" && self._resolvedAddPath(item) === path);
    });
    delete this.hiddenTemplate[path];
    delete this.envDraft[path];
    /* A union the user re-shaped goes back to the alternative its stored value
     * matched; otherwise the row would keep the abandoned shape. */
    delete this.unionShape[path];
    this._renderPending();
    this._render();
  };

  TreeEditor.prototype.validatePending = function () {
    var self = this;
    if (!this.pending.length) { return Promise.resolve({ valid: true, issues: [] }); }
    this._setStatus("pending", "Validating " + this.pending.length + " staged change(s)...");
    return request(this.apiBase, "POST", "/operations/validate", this._envelope()).then(function (result) {
      self._setIssues(result.issues);
      self._setStatus(result.valid ? "ok" : "error",
        result.valid ? "All staged changes are valid." : "Staged changes are invalid; nothing was written.");
      self._emit("validated", result);
      return result;
    }).catch(function (error) {
      self._setIssues(error.issues);
      self._setStatus("error", "Validation failed: " + error.message);
      throw error;
    });
  };

  TreeEditor.prototype.applyPending = function () {
    var self = this;
    if (this.busy) { return Promise.resolve(null); }
    if (!this.pending.length) { this._setStatus("info", "Nothing staged."); return Promise.resolve(null); }
    return this.validatePending().then(function (result) {
      if (!result.valid) { return null; }
      self.busy = true;
      self._setControlsDisabled(true);
      self._setStatus("pending", "Applying...");
      return request(self.apiBase, "POST", "/operations", self._envelope()).then(function (applied) {
        self.busy = false;
        self._setControlsDisabled(false);
        self.revision = applied.revision;
        self.stageOperations([], "user");
        var state = (applied.application && applied.application.state) || "unknown";
        self._setStatus("ok", "Stored in one revision. Application: " + state + ".");
        self._emit("applied", applied);
        return self.reload().then(function () { return applied; });
      }).catch(function (error) {
        self.busy = false;
        self._setControlsDisabled(false);
        self._setIssues(error.issues);
        if (error.code === "REVISION_CONFLICT" || error.status === 409) {
          self._setStatus("error", "Conflict: the file changed on disk. Your staged changes are kept — press Reload to reconcile.");
        } else {
          self._setStatus("error", "Nothing was stored: " + error.message);
        }
        throw error;
      });
    });
  };

  TreeEditor.prototype._envelope = function () {
    return {
      document: this.document,
      operations: this.getPendingOperations(),
      expected_revision: this.revision,
      expected_descriptor_revision: this.descriptorRevision
    };
  };

  TreeEditor.prototype._setControlsDisabled = function (disabled) {
    [this.applyButton, this.reloadButton, this.revertButton].forEach(function (button) {
      if (button) { button.disabled = disabled; }
    });
    Array.prototype.forEach.call(this.toolbar.querySelectorAll(".aiset-tree-lifecycle"), function (button) {
      button.disabled = disabled;
    });
  };

  TreeEditor.prototype.runLifecycle = function (action) {
    var self = this;
    if (this.busy) { return Promise.resolve(null); }
    if (action.confirm && !global.confirm(action.confirm)) { return Promise.resolve(null); }
    this.busy = true;
    this._setControlsDisabled(true);
    this._setStatus("pending", action.label + "...");
    return postJson(action.url, action.body || { document: this.document })
      .then(function (result) {
        self.busy = false;
        self._setControlsDisabled(false);
        self._setStatus("ok", (result && result.message) || action.label + " acknowledged.");
        self._emit("lifecycle", { action: action.id, result: result });
        if (action.reloadAfter !== false) { return self.reload().then(function () { return result; }); }
        return result;
      })
      .catch(function (error) {
        self.busy = false;
        self._setControlsDisabled(false);
        self._setIssues(error.issues);
        self._setStatus("error", action.label + " failed: " + error.message);
        throw error;
      });
  };

  TreeEditor.prototype.destroy = function () {
    if (this._onResize && global.removeEventListener) { global.removeEventListener("resize", this._onResize); }
    this.host.innerHTML = "";
    this.handlers = {};
  };

  // -- rendering -------------------------------------------------------
  TreeEditor.prototype._render = function () {
    this._envNames = {};
    this.treeNode.innerHTML = "";
    var view = this._viewTree();
    if (!view || !view.node) {
      this.treeNode.appendChild(element("p", { text: "This path does not exist yet. Apply a change to create it." }));
      this._renderPending();
      return;
    }
    this.treeNode.appendChild(this._renderNode(view.node, true));
    this._renderPending();
    this._loadEnvPresence();
  };

  /* -- the staged view -------------------------------------------------
   * The snapshot on disk never moves while the user works, so the editor draws
   * the tree the user currently expects: a staged value is shown in its control,
   * a staged addition appears, a staged removal stays visible but is marked as
   * deleted, and a staged move reorders. Nothing here touches the store. */
  TreeEditor.prototype._viewTree = function () {
    /* An open key row is part of the view too, and it is not an operation yet. */
    var hasDrafts = Object.keys(this.keyDrafts).length > 0;
    if ((!this.pending.length && !hasDrafts) || !this.tree || !this.tree.node) { return this.tree; }
    var index = this._pendingIndex();
    var node = this._projectNode(this.tree.node, "", index);
    return node ? Object.assign({}, this.tree, { node: node }) : this.tree;
  };

  TreeEditor.prototype._pendingIndex = function () {
    var sets = {}, removes = {}, adds = {}, moves = {};
    this.pending.forEach(function (item) {
      var op = item.operation;
      var path = op.path || op.from || "";
      if (op.op === "set") { sets[path] = op; }
      else if (op.op === "remove") { removes[path] = true; }
      else if (op.op === "add") {
        var parent = path.slice(0, path.lastIndexOf("/"));
        (adds[parent] = adds[parent] || []).push(item);
      } else if (op.op === "move") {
        /* The target index lives in the destination path, the entry to move in
         * `from`; both sides matter, so both are kept. */
        var target = path.slice(0, path.lastIndexOf("/"));
        (moves[target] = moves[target] || []).push({ from: op.from || op.path, to: path.slice(path.lastIndexOf("/") + 1), operation: op });
      }
    });
    return { sets: sets, removes: removes, adds: adds, moves: moves };
  };

  /* Returns the same node object when nothing below it changed, so an untouched
   * subtree is not copied on every render. */
  TreeEditor.prototype._projectNode = function (node, path, index) {
    if (!node) { return null; }
    var ownSet = index.sets[path];
    var ownRemove = index.removes[path];
    var ownAdds = index.adds[path] || [];
    var ownMoves = index.moves[path] || [];
    var base = node.children || [];
    var items = node.items || [];
    var touched = ownSet || ownRemove || ownAdds.length || ownMoves.length;
    var children = null;
    var projectedItems = null;

    if (base.length) {
      var copy = [];
      var changedChild = false;
      for (var i = 0; i < base.length; i += 1) {
        var childPath = path + "/" + escapeToken(base[i].path.split("/").pop());
        var projected = this._projectNode(base[i], childPath, index);
        if (projected !== base[i]) { changedChild = true; }
        copy.push(projected);
      }
      if (changedChild || ownAdds.length || ownMoves.length) { children = copy; }
    }
    if (items.length) {
      var itemCopy = [];
      var itemChanged = false;
      for (var j = 0; j < items.length; j += 1) {
        var itemPath = path + "/" + items[j].path.split("/").pop();
        var projectedItem = this._projectNode(items[j], itemPath, index);
        if (projectedItem !== items[j]) { itemChanged = true; }
        itemCopy.push(projectedItem);
      }
      if (itemChanged || ownAdds.length || ownMoves.length) { projectedItems = itemCopy; }
    }

    /* Order of the preview: what the container holds now, then the staged
     * additions, then the staged reorder. This is a preview of the batch the
     * user assembled, not a simulation of index shifts. */
    var additions = [];
    for (var k = 0; k < ownAdds.length; k += 1) {
      /* A new entry is built from its shape and then projected like any other
       * node. Each append gets its own concrete index, so several entries
       * staged in one batch stay distinct. */
      var addPath = this._resolvedAddPath(ownAdds[k]);
      var fresh = this._newNode(addPath, ownAdds[k].operation.value_text, node, true);
      additions.push(this._projectNode(fresh, fresh.path, index));
    }
    if (this.keyDrafts[path] && this._keyedObject(node)) {
      var draft = this._newNode(path + "/", "", node, false);
      draft.draft = true;
      draft.exists = true;
      draft.origin = { kind: "draft" };
      draft.value_text = "";
      children = (children || base).concat([draft]);
      touched = true;
    }
    if (additions.length) {
      var intoArray = node.type === "array";
      for (var a = 0; a < additions.length; a += 1) { additions[a].label = this._addLabel(node, additions[a]); }
      if (intoArray) {
        projectedItems = (projectedItems || items).concat(additions);
      } else {
        children = (children || base).concat(additions);
      }
    }
    if (ownMoves.length) {
      if (projectedItems || items.length) { projectedItems = this._applyMoves(projectedItems || items, ownMoves); }
      if (children || base.length) { children = this._applyMoves(children || base, ownMoves); }
    }

    if (!touched && !children && !projectedItems) { return node; }
    var view = Object.assign({}, node);
    if (children) { view.children = children; }
    if (projectedItems) { view.items = projectedItems; }
    if (ownSet) {
      /* Only the displayed value changes: the view modes stay as the user left
       * them, so a dropped substitution does not come back on its own. An edited
       * value is not a new entry, so the row stays "dirty" only. A value written
       * where there was none is the exception: that creates the node. */
      view.value_text = ownSet.value_text;
      if (view.exists === false) { view.exists = true; view.staged = true; }
    }
    if (ownRemove) { view.pending_delete = true; }
    return view;
  };

  TreeEditor.prototype._applyMoves = function (list, moves) {
    var out = list.slice();
    moves.forEach(function (move) {
      var token = move.from.split("/").pop();
      var at = -1;
      for (var i = 0; i < out.length; i += 1) {
        if (out[i].path.split("/").pop() === token) { at = i; break; }
      }
      if (at < 0) { return; }
      var moved = out.splice(at, 1)[0];
      var to = Number(move.to);
      if (isNaN(to)) { return; }
      /* "-"/"*" and out-of-range indexes mean the end, as in the service. */
      if (move.to === "-" || move.to === "*") { to = out.length; }
      out.splice(Math.max(0, Math.min(out.length, to)), 0, moved);
    });
    return out;
  };

  /* A staged addition has no snapshot node yet: build one from the descriptor
   * shape of the parent, so the control renders the value that will be written. */
  /* "-"/"*" is the request form of an append; the row needs a real index. */
  TreeEditor.prototype._addLabel = function (parent, node) {
    if (parent.type === "array") { return node.path.slice(node.path.lastIndexOf("/") + 1); }
    return node.path.slice(node.path.lastIndexOf("/") + 1);
  };

  /* The declared definition of something that does not exist yet: an array
   * describes its items once, an object describes each of its own keys, and any
   * other key takes the shape of `additional_children`. */
  TreeEditor.prototype._shapeFor = function (parent, token) {
    if (!parent) { return null; }
    if (parent.type === "array") { return this._itemShape(parent); }
    var field = parent.field || {};
    if (token && token !== "-" && token !== "*" && field.children && field.children[token]) {
      return field.children[token];
    }
    return field.additional_children || this._childNode(field.children);
  };

  TreeEditor.prototype._newNode = function (path, valueText, parent, required, shape) {
    var token = path.slice(path.lastIndexOf("/") + 1);
    var declared = shape === undefined ? this._shapeFor(parent, token) : shape;
    var field = (parent && parent.field) || null;
    /* A new entry is addressed by the index it will have, because everything
     * under it is written by that path; the append token stays in the add. */
    var written = required !== false;
    var node = {
      path: written ? this._resolveAddPath(path) : path,
      exists: written,
      staged: written,
      access_denied: false,
      origin: written ? { kind: "staged" } : { kind: "absent" },
      value_text: written ? (valueText === undefined || valueText === null ? "" : valueText) : null,
      /* An absent child of a new entry can be filled in: its parent is created
       * by the same batch, so writing it is a plain set on an existing path. */
      capabilities: {
        edit: true,
        /* An array that is not written yet still accepts an item: the append
         * creates the list itself. */
        add: !!(declared && declared.type === "array"),
        remove: written, reorder: false,
        add_child: !!(declared && declared.type === "object" && (declared.additional_children ||
          (declared.children && Object.keys(declared.children).length) || declared.key_pattern)),
        remove_child: !!(declared && declared.type === "object" && written),
      },
      comments: [],
      children: [],
      items: [],
      type: (declared && declared.type) || "undeclared",
      kind: parent && parent.type === "array" ? "array_item"
        : declared && declared.type === "object" ? "object"
        : declared && declared.type === "array" ? "array" : "leaf",
      field: declared || null,
      apply: (declared && declared.apply) || (parent && parent.apply) || null,
    };
    if (declared && declared.type === "object") {
      var children = declared.children || {};
      Object.keys(children).forEach(function (key) {
        /* A new entry is written empty, so every declared child starts absent
         * and is shown only because its parent is new. Filling one stages a
         * normal set by that child's path. */
        node.children.push(this._newNode(node.path + "/" + escapeToken(key), null, declared,
          false, children[key]));
      }, this);
    }
    if (declared && declared.type === "array") {
      node.kind = "array";
      node.value_text = written ? node.value_text : null;
      node.capabilities.remove = true;
    }
    return node;
  };

  TreeEditor.prototype._renderPending = function () {
    this.pendingNode.innerHTML = "";
    if (!this.pending.length) { return; }
    this.pendingNode.appendChild(element("h4", { text: "Staged changes (" + this.pending.length + ")" }));
    var list = element("ul", { class: "aiset-tree-staged" });
    var self = this;
    this.pending.forEach(function (item) {
      var row = element("li", { class: "aiset-tree-staged-row", dataset: { path: item.operation.path || item.operation.from || "" } });
      row.appendChild(element("span", { class: "aiset-tree-staged-op", text: item.operation.op }));
      row.appendChild(element("span", { class: "aiset-tree-staged-path", text: item.operation.path || item.operation.from }));
      row.appendChild(element("span", { class: "aiset-tree-staged-source", text: "from " + (item.source || "user") }));
      var revert = element("button", { type: "button", text: "Revert" });
      revert.addEventListener("click", function () { self.revert(item.operation.path || item.operation.from); });
      row.appendChild(revert);
      list.appendChild(row);
    });
    this.pendingNode.appendChild(list);
  };

  /* Children of one node as they are rendered right now. A new object shows
   * every declared fixed child, even unwritten ones, regardless of the
   * show-absent setting: the point of adding it is to fill in the fields.
   * Dynamic keys (`items`) stay hidden until they exist: those are open
   * collections, not a fixed shape. */
  TreeEditor.prototype._visibleChildren = function (node) {
    var children = (node.children || []).concat(node.items || []);
    if (this.showAbsent) { return children; }
    var fixed = node.children || [];
    var isNewObject = !!node.staged && node.type === "object";
    return children.filter(function (child) {
      if (child.exists !== false) { return true; }
      return isNewObject && fixed.indexOf(child) >= 0;
    });
  };

  TreeEditor.prototype._renderNode = function (node, isRoot, parent) {
    var self = this;
    var container = element("div", {
      class: "aiset-tree-node" + (node.pending_delete ? " is-deleted" : "") + (node.staged ? " is-staged" : ""),
      role: "treeitem",
      dataset: {
        path: node.path,
        absent: String(node.exists === false),
        deleted: String(!!node.pending_delete),
        staged: String(!!node.staged)
      }
    });
    var row = element("div", { class: "aiset-tree-row" });
    var children = this._visibleChildren(node);
    var composite = children.length;
    var isOpen = !!this.expanded[node.path];

    /* An expandable node gets + and -; a leaf gets a coloured mark of its type
     * in the very same place, so the column always says what the node is. */
    var toggle = composite
      ? element("button", {
        type: "button",
        class: "aiset-tree-toggle",
        text: isOpen ? "-" : "+",
        "aria-expanded": String(isOpen),
        "aria-label": (isOpen ? "Collapse " : "Expand ") + (node.path || "root")
      })
      : element("span", {
        class: "aiset-tree-toggle aiset-tree-toggle-type",
        "aria-hidden": "true",
        title: (node.type || "?") + ": nothing to expand"
      });
    if (composite) {
      toggle.addEventListener("click", function () {
        self.expanded[node.path] = !self.expanded[node.path];
        self._render();
      });
    } else {
      toggle.appendChild(this._typeGlyph(node));
    }
    row.appendChild(toggle);

    var name = isRoot ? (node.path || "/") : node.path.split("/").pop();
    /* The key of a child the user names itself is that name, so it stands where
     * the name stood, in front of the value, and can be corrected in place. */
    if (!isRoot && this._keyedObject(parent)) {
      row.appendChild(this._keyControl(node, parent));
    } else {
      var labelNode = element("span", { class: "aiset-tree-name", text: node.label || name });
      labelNode.setAttribute("title", this._tooltip(node));
      row.appendChild(labelNode);
    }
    row.appendChild(this._badges(node));
    var value = this._valueControl(node);
    if (value) { row.appendChild(value); }
    row.appendChild(this._structuralControls(node));
    container.appendChild(row);

    if (node.field && node.field.description) {
      container.appendChild(element("div", { class: "aiset-tree-desc", text: node.field.description }));
    }
    var source = this._compositeValue(node);
    if (source) { container.appendChild(source); }
    if (this.rawMode[node.path]) {
      /* The raw fragment stands in for the node and everything under it. */
      container.appendChild(this._rawEditor(node));
      return container;
    }
    if (composite && isOpen) {
      var group = element("div", { class: "aiset-tree-children", role: "group" });
      children.forEach(function (child) {
        group.appendChild(self._renderNode(child, false, node));
      });
      container.appendChild(group);
    }
    return container;
  };

  TreeEditor.prototype._badges = function (node) {
    var wrap = element("span", { class: "aiset-tree-badges" });
    function badge(text, kind) {
      return element("span", { class: "aiset-tree-badge " + (kind || ""), text: text });
    }
    wrap.appendChild(badge(node.type || "?", "type"));
    if (node.apply) { wrap.appendChild(badge(node.apply, "apply")); }
    if (node.origin && node.origin.kind && node.origin.kind !== "file") {
      wrap.appendChild(badge(node.origin.kind, node.origin.kind === "draft" ? "draft" : "origin"));
    }
    if (node.exists === false) { wrap.appendChild(badge(node.default_applied ? "default" : "absent", "absent")); }
    if (node.field && node.field.read_only) { wrap.appendChild(badge("read-only", "lock")); }
    if (node.access_denied) { wrap.appendChild(badge("secret", "lock")); }
    if ((node.capabilities || {}).unsupported) {
      wrap.appendChild(element("span", {
        class: "aiset-tree-badge unsupported",
        text: "unsupported",
        title: "Descriptor lifecycle hooks are recognized but not executed by this build; writes here are refused."
      }));
    }
    if (node.field && node.field.required) { wrap.appendChild(badge("required", "req")); }
    if (node.field && node.field.nullable) { wrap.appendChild(badge("nullable", "req")); }
    if (this._pendingFor(node.path)) { wrap.appendChild(badge("dirty", "dirty")); }
    if (node.staged) { wrap.appendChild(badge("new", "new")); }
    if (node.pending_delete) { wrap.appendChild(badge("deleted", "deleted")); }
    return wrap;
  };

  /* A node is pending when a staged operation names it; a new entry of an array
   * is named by the append token in the add but by its index in the view. */
  TreeEditor.prototype._pendingFor = function (path) {
    var self = this;
    return this.pending.some(function (item) {
      var operation = item.operation;
      return operation.path === path || operation.from === path ||
        (operation.op === "add" && self._resolvedAddPath(item) === path);
    });
  };

  /* ${VAR} / ${VAR:-default}: as a standalone token or inside a string. */
  TreeEditor.prototype._templateInfo = function (node) {
    if (node.template) {
      return { name: node.template.name, fallback: node.template.default };
    }
    var text = node.value_text;
    if (typeof text !== "string") { return null; }
    var body = text;
    if (text.length > 1 && text[0] === '"' && text[text.length - 1] === '"') { body = text.slice(1, -1); }
    var match = body.match(/^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([\s\S]*))?\}$/);
    if (!match) { return null; }
    return { name: match[1], fallback: match[2] === undefined ? null : match[2] };
  };

  TreeEditor.prototype._envAllowed = function (node) {
    return !!(node.field && node.field.env && node.field.env.allowed);
  };

  /* The value as plain text, without the quotes a string carries in source. */
  TreeEditor.prototype._plainText = function (node) {
    var text = node.value_text;
    if (text === null || text === undefined) { return ""; }
    return node.type === "string" ? unquote(text) : text;
  };

  TreeEditor.prototype._valueControl = function (node) {
    var self = this;
    var caps = node.capabilities || {};
    var field = node.field || {};
    if (node.access_denied) {
      return element("span", { class: "aiset-tree-secret", text: "hidden (secret)" });
    }
    /* An object or array is edited through its children, or as raw source. */
    if (isComposite(node)) { return null; }
    if (!caps.edit) {
      return element("span", { class: "aiset-tree-value aiset-tree-value-readonly", text: this._valueText(node) });
    }
    /* Raw mode shows the stored fragment below the row instead. */
    if (this.rawMode[node.path]) { return null; }
    if (this._showsTemplate(node)) { return this._templateControl(node); }

    if (node.type === "union" && field.children_options && field.children_options.length) {
      return this._unionControl(node);
    }
    var wrap = element("span", { class: "aiset-tree-value" });
    var current = this._plainValueText(node);
    /* An unchecked box cannot say whether a bool is stored or false. */
    if (node.type === "bool" && node.exists === false) { wrap.appendChild(this._typeGlyph(node)); }
    var control = this._typedControl(node, current, function (staged) { self._stage(node, staged); });
    wrap.appendChild(control);
    if (field.nullable && node.type !== "object") {
      wrap.appendChild(this._nullToggle(node, control));
    }
    return wrap;
  };

  /* A union is edited through the control of the alternative the value matches:
   * an enum string becomes a select, an int a number field, an object stays the
   * raw source. The shape chooser switches the alternative. */
  TreeEditor.prototype._unionControl = function (node) {
    var self = this;
    var options = (node.field && node.field.children_options) || [];
    var wrap = element("span", { class: "aiset-tree-value aiset-tree-union" });
    var active = this._unionActive(node, options);
    var control = null;
    if (active >= 0) {
      var option = options[active];
      var optNode = Object.assign({}, node, { type: option.type, field: option });
      control = this._typedControl(optNode, this._plainValueText(node),
        function (staged) { self._stage(node, staged); });
      wrap.appendChild(control);
    }
    if ((node.field || {}).nullable) { wrap.appendChild(this._nullToggle(node, control || wrap)); }
    wrap.appendChild(this._typeChooser(node, options));
    return wrap;
  };

  /* The alternative a union node is currently shown as: the shape the user
   * picked, else the alternative the stored value matched (snapshot field). */
  TreeEditor.prototype._unionActive = function (node, options) {
    var chosen = this.unionShape[node.path];
    if (typeof chosen === "number" && chosen >= 0 && chosen < options.length) { return chosen; }
    if (typeof node.matched_option === "number" &&
        node.matched_option >= 0 && node.matched_option < options.length) {
      return node.matched_option;
    }
    return -1;
  };

  TreeEditor.prototype._sampleForOption = function (option) {
    if (option.enum && option.enum.length) { return JSON.stringify(option.enum[0]); }
    if (option.const !== undefined) { return JSON.stringify(option.const); }
    var samples = { string: '""', int: "0", number: "0", bool: "false", null: "null",
                    array: "[]", object: "{}" };
    return samples[option.type] || "null";
  };

  /* One control per declared type. The callback receives the text to stage and
   * the same value as plain text, which is what a ${VAR:-default} needs. */
  TreeEditor.prototype._typedControl = function (node, current, onChange) {
    var self = this;
    var field = node.field || {};
    if (field.enum && field.enum.length) {
      var select = element("select", { "aria-label": "Value for " + node.path });
      if (node.exists === false) { select.appendChild(element("option", { value: "", text: "(unset)" })); }
      field.enum.forEach(function (option) {
        select.appendChild(element("option", { value: JSON.stringify(option), text: String(option) }));
      });
      /* A fallback default arrives as plain text, a stored value as source. */
      var wanted = current;
      if (!field.enum.some(function (option) { return JSON.stringify(option) === current; })) {
        wanted = JSON.stringify(unquote(current));
      }
      select.value = wanted;
      select.addEventListener("change", function () {
        if (!select.value) { self.revert(node.path); return; }
        onChange(select.value, unquote(select.value));
      });
      return select;
    }
    if (node.type === "bool") {
      var toggle = element("input", { type: "checkbox", "aria-label": "Value for " + node.path });
      toggle.checked = current === "true";
      toggle.addEventListener("change", function () {
        var text = toggle.checked ? "true" : "false";
        onChange(text, text);
      });
      return toggle;
    }
    if (node.type === "int" || node.type === "number") {
      var number = element("input", {
        type: "number", value: current.replace(/^["']|["']$/g, ""),
        "aria-label": "Value for " + node.path
      });
      if (field.minimum !== undefined) { number.min = field.minimum; }
      if (field.maximum !== undefined) { number.max = field.maximum; }
      if (field.ui && field.ui.placeholder) { number.placeholder = field.ui.placeholder; }
      number.addEventListener("change", function () { onChange(number.value, number.value); });
      return number;
    }
    if (node.type === "string" && !current.includes("\n") && !(field.ui && field.ui.rows > 2)) {
      var input = element("input", { type: "text", value: unquote(current), "aria-label": "Value for " + node.path });
      if (field.ui && field.ui.placeholder) { input.placeholder = field.ui.placeholder; }
      if (field.max_length) { input.maxLength = field.max_length; }
      input.addEventListener("change", function () { onChange(JSON.stringify(input.value), input.value); });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { input.blur(); }
        if (event.key === "Escape") { self.revert(node.path); }
      });
      return input;
    }
    /* Everything else is edited as source text: objects and arrays that cannot
     * be edited member by member, `null`, and the opaque `any` type, whose value
     * the library deliberately does not inspect. */
    var area = element("textarea", { rows: (field.ui && field.ui.rows) || 3, "aria-label": "Value for " + node.path });
    area.value = current;
    if (field.ui && field.ui.placeholder) { area.placeholder = field.ui.placeholder; }
    area.addEventListener("change", function () { onChange(area.value, area.value); });
    return area;
  };

  /* ${VAR:-fallback}: the variable name and the fallback are edited apart, so a
   * substitution is never lost by changing the value it falls back to. */
  /* A node shows the two template controls while its substitution is visible;
   * after the user dropped it, the row reads as the plain value it became. */
  TreeEditor.prototype._showsTemplate = function (node) {
    if (this.hiddenTemplate[node.path]) { return false; }
    return !!(this._templateInfo(node) || this.envDraft[node.path]);
  };

  /* The value the plain control shows: what is stored, or the inline fallback of
   * a substitution the user just dropped. */
  TreeEditor.prototype._plainValueText = function (node) {
    if (!this.hiddenTemplate[node.path]) {
      return node.value_text === null || node.value_text === undefined ? "" : node.value_text;
    }
    var info = this._templateInfo(node) || { fallback: null };
    if (info.fallback === null || info.fallback === undefined) {
      return node.type === "string" ? '""' : "null";
    }
    return node.type === "string" ? JSON.stringify(info.fallback) : info.fallback;
  };

  /* What the row shows: the staged draft when there is one, the stored
   * substitution otherwise. */
  TreeEditor.prototype._currentTemplate = function (node) {
    var draft = this.envDraft[node.path];
    if (draft && draft.name) { return { name: draft.name, fallback: draft.fallback }; }
    var stored = this._templateInfo(node);
    if (stored) { return stored; }
    return this.envDraft[node.path] ? { name: "", fallback: this._plainText(node) } : null;
  };

  TreeEditor.prototype._templateControl = function (node) {
    var self = this;
    var info = this._currentTemplate(node);
    var wrap = element("span", { class: "aiset-tree-value aiset-tree-template" });

    var name = element("input", {
      type: "text", class: "aiset-tree-env", placeholder: "VARNAME",
      "aria-label": "Environment variable for " + node.path,
      title: "Environment variable; an empty name stores the inline value instead"
    });
    name.value = info.name || "";
    name.addEventListener("change", function () {
      var written = name.value.trim();
      if (!written) { self._dropTemplate(node); return; }
      var fallback = info.fallback === null || info.fallback === undefined ? "" : info.fallback;
      self.envDraft[node.path] = { name: written, fallback: fallback };
      self._stageTemplate(node, written, fallback);
    });
    wrap.appendChild(name);
    /* A node that already stores ${VAR} shows its variable in the field above;
     * the presence check belongs to the mode opened from a plain value. */
    var presence = this._templateInfo(node) ? null : this._envBadge(node, info.name);
    if (presence) { wrap.appendChild(presence); }

    var fallback = info.fallback === null || info.fallback === undefined ? "" : info.fallback;
    wrap.appendChild(this._typedControl(node, fallback, function (staged, plain) {
      var written = self._currentTemplate(node);
      /* Without a variable name there is nothing to substitute. */
      if (!written || !written.name) { return; }
      self.envDraft[node.path] = { name: written.name, fallback: plain };
      self._stageTemplate(node, written.name, plain);
    }));
    if (info.name) {
      /* Nothing to drop while the name field is still empty. */
      wrap.appendChild(this._button("env-off", "Drop the substitution and keep the inline value", "text:\u2298",
        function () { self._dropTemplate(node); }));
    }
    return wrap;
  };

  /* A substitution sits inside a literal of the declared type: a string field
   * keeps its quotes, a field the descriptor converts (int, bool) stays a bare
   * token, which is how the file writes them. Keeping the form of the file is
   * also what lets an untouched substitution compare equal again. */
  TreeEditor.prototype._stageTemplate = function (node, name, fallback) {
    if (fallback === null || fallback === undefined) { fallback = ""; }
    var text = "${" + name + ":-" + fallback + "}";
    if (node.type === "string") { text = JSON.stringify(text); }
    this.stageOperations([{ op: "set", path: node.path, value_text: text }], "user");
  };

  /* Drop the substitution: this node goes back to the value the file holds.
   * A substitution staged a moment ago must be forgotten first, otherwise
   * pressing this button would leave exactly what it claims to remove. */
  TreeEditor.prototype._dropTemplate = function (node) {
    var info = this._currentTemplate(node) || { fallback: this._plainText(node) };
    var fallback = info.fallback;
    if (fallback === null || fallback === undefined) { fallback = ""; }
    if (fallback === "" && node.type !== "string") {
      var declared = node.field && node.field.default !== undefined ? node.field.default : null;
      fallback = declared === null ? (node.type === "bool" ? "false" : "0") : JSON.stringify(declared);
    }
    delete this.envDraft[node.path];
    this.revert(node.path);
    /* After the revert: reverting clears the view, and the dropped row must
     * stay dropped. */
    this.hiddenTemplate[node.path] = true;
    var text = node.type === "string" ? JSON.stringify(fallback) : fallback;
    if (node.exists !== false && node.value_text === text) { this._render(); return; }
    this.stageOperations([{ op: "set", path: node.path, value_text: text }], "user");
  };

  /* The .env button: it switches a plain value into substitution mode. It works
   * on every editable scalar. A descriptor without env.allowed cannot resolve a
   * placeholder, and the server says so when the change is stored; the tooltip
   * warns beforehand so the button is never a silent no-op. */
  TreeEditor.prototype._envButton = function (node) {
    var self = this;
    var title = "Read this value from an environment variable";
    var editable = !!(node.capabilities || {}).edit;
    if (!editable) { title = "This field is read-only"; }
    else if (!this._envAllowed(node)) {
      title += " (the descriptor allows no substitution here: the server will refuse it)";
    }
    var button = this._button("env", title, "text:.env", function () {
      delete self.hiddenTemplate[node.path];
      self.envDraft[node.path] = true;
      self._render();
    });
    button.disabled = !editable;
    return button;
  };

  /* Presence only, and only while a plain value is being turned into a
   * substitution. The button asks the server again; the server answers whether a
   * variable is set, never its value. */
  TreeEditor.prototype._envBadge = function (node, name) {
    var self = this;
    if (!name) { return null; }
    var badge = element("button", {
      type: "button", class: "aiset-tree-env-state", text: "",
      title: "Is " + name + " set? Press to check again. Its value never reaches the browser.",
      dataset: { envFor: node.path }
    });
    if (!name) { return null; }
    this._envNames[node.path] = name;
    badge.addEventListener("click", function () {
      self._envQueried = "";
      self._loadEnvPresence();
    });
    return badge;
  };

  TreeEditor.prototype._loadEnvPresence = function () {
    var self = this;
    var names = {};
    Object.keys(this._envNames || {}).forEach(function (path) { names[self._envNames[path]] = true; });
    var list = Object.keys(names).sort();
    /* One request per render, and none at all while the set is unchanged. */
    if (!list.length || list.join(",") === this._envQueried) { return Promise.resolve(null); }
    this._envQueried = list.join(",");
    return request(this.apiBase, "POST", "/env", { document: this.document, names: list })
      .then(function (result) {
        var present = result.present || {};
        Array.prototype.forEach.call(self.host.querySelectorAll("[data-env-for]"), function (node) {
          var path = node.getAttribute("data-env-for");
          var isSet = !!present[self._envNames[path]];
          node.textContent = isSet ? "set in .env" : "not set in .env";
          node.className = "aiset-tree-env-state " + (isSet ? "on" : "off");
        });
        self._emit("env", present);
        return present;
      })
      .catch(function (error) {
        self._emit("env", { error: error.message });
        return null;
      });
  };

  /* Raw source editing: any node, including a whole object. The server parses
   * and validates the fragment; nothing is staged while it is wrong. */
  TreeEditor.prototype._rawEditor = function (node) {
    var self = this;
    var stored = this._find(node.path) || node;
    var wrap = element("div", { class: "aiset-tree-raw" });
    wrap.appendChild(element("div", {
      class: "aiset-tree-raw-title",
      text: "Raw source of " + (node.path || "root") + " — JSON5, comments and ${VARIABLES} kept"
    }));
    var area = element("textarea", {
      rows: 8, class: "aiset-tree-raw-text", "aria-label": "Raw source of " + node.path
    });
    area.value = stored.value_text === null || stored.value_text === undefined ? "" : stored.value_text;
    area.addEventListener("input", function () { self._fitRaw(area); });
    wrap.appendChild(area);
    this._fitRaw(area);
    var actions = element("div", { class: "aiset-tree-raw-actions" });
    var check = element("button", { type: "button", text: "Check and stage", title: "Validate the fragment, then stage it" });
    check.addEventListener("click", function () { self._stageRaw(node, area.value); });
    var cancel = element("button", { type: "button", text: "Cancel", title: "Close the raw editor without staging" });
    cancel.addEventListener("click", function () { delete self.rawMode[node.path]; self._render(); });
    actions.appendChild(check);
    actions.appendChild(cancel);
    wrap.appendChild(actions);
    return wrap;
  };

  /* Grow the raw window to its content, never past the screen or the pane, and
   * never smaller than what the user dragged it to. */
  TreeEditor.prototype._fitRaw = function (area) {
    var pane = this.treeNode.clientWidth || 0;
    var screen = global.innerWidth || 1024;
    var maxWidth = Math.max(Math.min(pane - RAW_PADDING, screen - RAW_PADDING), 200);
    if (area.scrollWidth > area.clientWidth) {
      area.style.width = "0px";
      var wanted = Math.max(area.scrollWidth + 4, RAW_MIN_WIDTH);
      area.style.width = Math.min(wanted, maxWidth) + "px";
    }
    var maxHeight = Math.max((global.innerHeight || 768) - RAW_CHROME, RAW_MIN_HEIGHT);
    if (area.scrollHeight > area.clientHeight) {
      area.style.height = "0px";
      var rows = Math.max(area.scrollHeight + 4, RAW_MIN_HEIGHT);
      area.style.height = Math.min(rows, maxHeight) + "px";
    }
  };

  TreeEditor.prototype._fitAllRaw = function () {
    var self = this;
    Array.prototype.forEach.call(this.host.querySelectorAll(".aiset-tree-raw-text"), function (area) {
      self._fitRaw(area);
    });
  };

  TreeEditor.prototype._stageRaw = function (node, text) {
    var self = this;
    var operation = { op: "set", path: node.path, value_text: text };
    this._setStatus("pending", "Checking the raw source of " + (node.path || "root") + "...");
    return request(this.apiBase, "POST", "/operations/validate", {
      document: this.document,
      operations: [operation],
      expected_revision: this.revision,
      expected_descriptor_revision: this.descriptorRevision
    }).then(function (result) {
      self._setIssues(result.issues);
      if (!result.valid) {
        self._setStatus("error", "Nothing was staged: the fragment is not a valid value for " +
          (node.path || "the document") + ". Fix it or cancel.");
        return null;
      }
      self.stageOperations([operation], "user");
      delete self.rawMode[node.path];
      self._setStatus("ok", "Raw source staged; review it and press Apply.");
      self._render();
      return result;
    }).catch(function (error) {
      self._setIssues(error.issues);
      self._setStatus("error", "Nothing was staged: " + error.message);
      throw error;
    });
  };

  /* Read-only stored text of an object or array; shown only on demand. */
  TreeEditor.prototype._compositeValue = function (node) {
    if (!this.valuesAsText || !isComposite(node) || node.access_denied) { return null; }
    var text = node.value_text;
    if (text === null || text === undefined) {
      if (node.exists === false) { return null; }
      text = "";
    }
    return element("pre", {
      class: "aiset-tree-source",
      "aria-label": "Stored text of " + (node.path || "root"),
      text: text
    });
  };

  /* An explicit null is its own control: ticking the box makes the node null
   * and locks the text control, so "null" can never be mistaken for the string. */
  TreeEditor.prototype._nullToggle = function (node, control) {
    var self = this;
    var isNull = this._isNull(node);
    var box = element("input", {
      type: "checkbox", class: "aiset-tree-null", title: "Store an explicit null",
      "aria-label": "Store an explicit null instead of text"
    });
    box.checked = isNull;
    box.addEventListener("change", function () {
      if (box.checked) { self._stage(node, "null"); } else { self.revert(node.path); }
    });
    this._lockForNull(control, isNull);
    return box;
  };

  TreeEditor.prototype._isNull = function (node) {
    var staged = this.pending.filter(function (item) {
      return item.operation.op === "set" && item.operation.path === node.path;
    });
    if (staged.length) { return String(staged[staged.length - 1].operation.value_text).trim() === "null"; }
    return String(node.value_text).trim() === "null";
  };

  TreeEditor.prototype._lockForNull = function (control, isNull) {
    if (!control) { return; }
    control.disabled = isNull;
    control.setAttribute("aria-disabled", String(isNull));
    if (isNull) { control.value = "null"; control.title = "Stored as an explicit null"; }
  };

  /* Short coloured mark of the declared type; red is never used. */
  TreeEditor.prototype._typeGlyph = function (node) {
    var entry = TYPE_GLYPHS[node.type] || TYPE_GLYPHS.other;
    var reason = node.exists === false ? "not stored yet" : "a stored value";
    return element("span", {
      class: "aiset-tree-type " + entry.kind,
      title: node.type + ": " + reason,
      text: entry.glyph
    });
  };

  TreeEditor.prototype._typeChooser = function (node, options) {
    var self = this;
    options = options || (node.field && node.field.children_options) || [];
    var select = element("select", { "aria-label": "Value shape for " + node.path, class: "aiset-tree-shape" });
    select.appendChild(element("option", { value: "", text: "shape…" }));
    options.forEach(function (option, index) {
      select.appendChild(element("option", { value: String(index), text: option.type }));
    });
    select.addEventListener("change", function () {
      if (select.value === "") { return; }
      var index = Number(select.value);
      var option = options[index];
      if (!option) { return; }
      self.unionShape[node.path] = index;
      self._stage(node, self._sampleForOption(option));
      select.value = "";
    });
    return select;
  };

  /* Everything the host knows about one node: source comments, description,
   * default, flags, constraints and the value as written. */
  TreeEditor.prototype._tooltip = function (node) {
    var field = node.field || {};
    var lines = [(node.path || "root") + "  (" + (node.type || "?") + ")"];
    if (node.access_denied) {
      lines.push("hidden: this node contains a secret");
      return lines.join("\n");
    }
    (node.comments || []).forEach(function (text) { lines.push(text); });
    if (field.description) { lines.push("description: " + field.description); }

    var flags = [];
    ["required", "nullable", "read_only", "secret"].forEach(function (flag) {
      if (field[flag]) { flags.push(flag); }
    });
    if (node.apply) { flags.push("apply: " + node.apply); }
    if (field.env) { flags.push("env" + (field.env.convert ? ": " + field.env.convert : "")); }
    if (flags.length) { lines.push(flags.join(" · ")); }

    var details = [];
    if (field.default !== undefined) { details.push("default: " + JSON.stringify(field.default)); }
    if (field.const !== undefined) { details.push("const: " + JSON.stringify(field.const)); }
    if (field.enum) { details.push("one of: " + JSON.stringify(field.enum)); }
    var range = [];
    if (field.minimum !== undefined) { range.push("min " + field.minimum); }
    if (field.maximum !== undefined) { range.push("max " + field.maximum); }
    if (field.min_length !== undefined) { range.push("min length " + field.min_length); }
    if (field.max_length !== undefined) { range.push("max length " + field.max_length); }
    if (field.pattern) { range.push("pattern " + field.pattern); }
    if (range.length) { details.push(range.join(", ")); }
    if (details.length) { lines.push(details.join(" · ")); }

    var stored = node.value_text;
    lines.push("value: " + (stored === null || stored === undefined ? "not stored" : _clip(stored)));
    return lines.join("\n");
  };

  /* One small button that puts the declared default back. */
  /* The helper binding of a node gets its own button; without a registered
   * helper the button says so instead of pretending to work. */
  TreeEditor.prototype._helperControl = function (node) {
    var self = this;
    var found = helperFor(node);
    var title = found
      ? "Edit this node with the " + found.tag + " helper"
      : "This node declares a helper that is not registered";
    var button = this._button("form", title, "form", function () { self.runHelper(node); });
    button.disabled = !found || !(node.capabilities || {}).edit;
    return button;
  };

  /* Always offered, so the row looks the same everywhere; without a declared
   * default, or without write permission, the button says why it is inert. */
  TreeEditor.prototype._defaultControl = function (node) {
    var self = this;
    var field = node.field || {};
    var declared = field.default !== undefined;
    var valueText = declared ? JSON.stringify(field.default) : "";
    var already = declared && node.value_text === valueText;
    var title = "Restore the default value: " + _clip(valueText);
    if (already) { title = "Already the default value"; }
    else if (!declared) { title = "This field declares no default value"; }
    else if (!(node.capabilities || {}).edit) { title = "This field is read-only"; }
    var button = this._button("default", title, "text:\u2302", function () {
      self._stage(node, valueText);
    });
    button.disabled = already || !declared || !(node.capabilities || {}).edit;
    return button;
  };

  TreeEditor.prototype._structuralControls = function (node) {
    var self = this;
    var wrap = element("span", { class: "aiset-tree-actions" });
    var caps = node.capabilities || {};

    if (!node.access_denied) {
      var raw = this._button("raw", "Edit the raw source of this node", "text:{..}", function () {
        self.rawMode[node.path] = true;
        self._render();
      });
      raw.disabled = !caps.edit;
      wrap.appendChild(raw);
      /* A plain value can be turned into a substitution; a node that already
       * has one shows its name and fallback instead, so no button there. */
      if (!isComposite(node) && !this._showsTemplate(node) && !this.envDraft[node.path]) {
        wrap.appendChild(this._envButton(node));
      }
    }
    if ((node.field || {}).helper) { wrap.appendChild(this._helperControl(node)); }
    if (this._pendingFor(node.path)) {
      wrap.appendChild(this._button("revert", "Revert the staged change(s) of this node", "text:\u21ba",
        function () { self.revert(node.path); }));
    }
    var reset = this._defaultControl(node);
    if (reset) { wrap.appendChild(reset); }
    if (node.exists === false && isComposite(node)) {
      wrap.appendChild(this._button("add", "Create this " + node.type,
        "plus", function () { self.stageOperations([{ op: "set", path: node.path, value_text: self._newEntryText(node.field, 0) }], "user"); }));
    } else if (caps.add) {
      wrap.appendChild(this._addItemControl(node));
    }
    if (caps.remove) {
      var removeTitle = node.type === "array" ? "Remove this list"
        : node.kind === "array_item" ? "Remove this item" : "Remove this entry";
      wrap.appendChild(this._button("remove", removeTitle, "trash", function () {
        self.stageOperations([{ op: "remove", path: node.path }], "user");
      }));
      if (caps.reorder) {
        wrap.appendChild(this._button("up", "Move up", "arrow-up", function () { self._move(node, -1); }));
        wrap.appendChild(this._button("down", "Move down", "arrow-down", function () { self._move(node, 1); }));
      }
    }
    if (caps.add_child && node.type === "object") {
      var addProperty = this._addPropertyControl(node);
      if (addProperty) { wrap.appendChild(addProperty); }
    }
    return wrap;
  };

  TreeEditor.prototype._addItemControl = function (node) {
    var self = this;
    var options = (node.field && node.field.children_options) || [];
    var shape = this._itemShape(node);
    var button = this._button("add", "Add an item", "plus", function () {
      if (options.length > 1) { self._showItemChooser(node); return; }
      /* The shape of the item decides the control the new row gets, and a new
       * object starts as its required children rather than as an empty one. */
      self._appendItem(node, self._newEntryText(shape, 0));
    });
    return button;
  };

  /* What a new entry of this container must look like. An array declares the
   * shape of its items either as a list of options or as a single node under
   * `children`; an object declares a new property under `additional_children`
   * or, for a declared key, under its own entry in `children`. */
  TreeEditor.prototype._itemShape = function (node) {
    var field = (node && node.field) || null;
    if (!field) { return null; }
    if (node.type === "array") {
      if (field.children_options && field.children_options.length) { return field.children_options[0]; }
      return this._childNode(field.children);
    }
    if (field.additional_children) { return field.additional_children; }
    return this._childNode(field.children);
  };

  /* The same rule for a raw declaration, which is what a descriptor file and a
   * field description both end up as. */
  TreeEditor.prototype._shapeOfField = function (field, token) {
    if (!field) { return null; }
    if (token && field.children && field.children[token]) { return field.children[token]; }
    return field.additional_children || this._childNode(field.children);
  };

  /* `children` of an array is one node, of an object a map of nodes; a node
   * always names its own type. */
  TreeEditor.prototype._childNode = function (children) {
    if (!children || typeof children !== "object" || Array.isArray(children)) { return null; }
    return children.type ? children : null;
  };

  TreeEditor.prototype._showItemChooser = function (node) {
    var self = this;
    var existing = this.toolbar.querySelector(".aiset-tree-chooser");
    if (existing) { existing.remove(); }
    var chooser = element("span", { class: "aiset-tree-chooser" });
    chooser.appendChild(label(" new item: "));
    (node.field.children_options || []).forEach(function (option) {
      var button = element("button", { type: "button", class: "aiset-tree-button", text: option.type });
      button.addEventListener("click", function () {
        self.stageOperations([{ op: "add", path: node.path + "/-", value_text: self._newEntryText(option, 0) }], "user");
        chooser.remove();
      });
      chooser.appendChild(button);
    });
    this.toolbar.appendChild(chooser);
  };

  /* The append token names no index, but a child of the new entry is written by
   * its own path, so the view needs the index the entry will have: the length of
   * the array in the file, minus what this batch removes, plus what it adds. */
  TreeEditor.prototype._nextIndex = function (arrayPath) {
    var node = this._find(arrayPath);
    var stored = node && node.items ? node.items.length : 0;
    var added = 0;
    var removed = 0;
    this.pending.forEach(function (item) {
      var op = item.operation;
      if (!op.path) { return; }
      var parent = op.path.slice(0, op.path.lastIndexOf("/"));
      if (parent !== arrayPath) { return; }
      if (op.op === "add") { added += 1; }
      if (op.op === "remove") { removed += 1; }
    });
    return Math.max(0, stored - removed) + added - 1;
  };

  TreeEditor.prototype._resolveAddPath = function (path) {
    if (!path) { return path; }
    var token = path.slice(path.lastIndexOf("/") + 1);
    if (token !== "-" && token !== "*") { return path; }
    return path.slice(0, path.lastIndexOf("/")) + "/" + this._nextIndex(path.slice(0, path.lastIndexOf("/")));
  };

  /* The concrete index of one staged append: the array length in the file,
   * minus staged removals, plus its position among the staged appends. Several
   * appends to the same array must each get a distinct index. */
  TreeEditor.prototype._addIndex = function (parentPath, target) {
    var node = this._find(parentPath);
    var stored = node && node.items ? node.items.length : 0;
    var removed = 0;
    var ordinal = -1;
    var seen = 0;
    this.pending.forEach(function (item) {
      var op = item.operation;
      if (!op.path) { return; }
      var parent = op.path.slice(0, op.path.lastIndexOf("/"));
      if (parent !== parentPath) { return; }
      if (op.op === "remove") { removed += 1; }
      if (op.op === "add") {
        if (item === target) { ordinal = seen; }
        seen += 1;
      }
    });
    if (ordinal < 0) { return null; }
    return Math.max(0, stored - removed) + ordinal;
  };

  TreeEditor.prototype._resolvedAddPath = function (item) {
    var op = item && item.operation;
    if (!op || !op.path) { return op ? op.path : ""; }
    var token = op.path.slice(op.path.lastIndexOf("/") + 1);
    if (token !== "-" && token !== "*") { return op.path; }
    var parentPath = op.path.slice(0, op.path.lastIndexOf("/"));
    var index = this._addIndex(parentPath, item);
    return index === null ? op.path : parentPath + "/" + index;
  };

  /* The value a new object entry starts with: empty. A new entry shows every
   * declared fixed child (see _visibleChildren), and only the fields the user
   * fills in are written, each by its own path. Required fields are not
   * pre-filled: the candidate stays invalid until the user supplies them. */
  TreeEditor.prototype._newEntryText = function (shape, indent) {
    if (!shape || shape.type !== "object") { return defaultValueFor(shape); }
    return "{}";
  };

  TreeEditor.prototype._appendItem = function (node, valueText) {
    this.stageOperations([{ op: "add", path: node.path + "/-", value_text: valueText }], "user");
  };

  /* An object the user names by itself: it declares what a value looks like
   * (`additional_children`), a pattern or a closed list of keys. An object with
   * declared children needs no key field, so it gets no "add property" control
   * at all. */
  TreeEditor.prototype._keyedObject = function (node) {
    if (!node || node.type !== "object") { return false; }
    var field = node.field || {};
    var caps = node.capabilities || {};
    return !!(field.additional_children || field.key_pattern || field.key_enum ||
      (caps.key_options && caps.key_options.length));
  };

  /* Rename or name a child. A name is a path segment, so changing it writes the
   * new entry and drops the old one; an empty name drops both again. */
  TreeEditor.prototype._keyControl = function (node, parent) {
    var self = this;
    var parentPath = parent.path;
    var current = node.path.slice(node.path.lastIndexOf("/") + 1);
    var options = (parent.capabilities || {}).key_options || [];
    /* Enter and the following blur/change can both fire; a name must be
     * committed once, otherwise the same entry is staged twice. */
    var committed = false;
    var commit = function (next) {
      if (committed) { return; }
      committed = true;
      next = String(next === undefined || next === null ? "" : next).trim();
      if (node.draft) {
        delete self.keyDrafts[parentPath];
        self._render();
        if (!next) { self._render(); return; }
        self.stageOperations([{ op: "add", path: parentPath + "/" + escapeToken(next),
          value_text: self._newEntryText(self._itemShape(parent), 0) }], "user");
        return;
      }
      if (!next || next === current) { return; }
      var text = node.exists === false ? self._newEntryText(node.field, 0) : node.value_text;
      self.stageOperations([
        { op: "remove", path: parentPath + "/" + escapeToken(current) },
        { op: "add", path: parentPath + "/" + escapeToken(next), value_text: text },
      ], "user");
    };
    var title = node.draft ? "Name this entry; an empty name closes the row"
      : "Key of " + node.path + "; changing it renames the entry";
    if (options.length) {
      var select = element("select", { class: "aiset-tree-key", "aria-label": title, title: title });
      if (node.draft) { select.appendChild(element("option", { value: "", text: "…" })); }
      options.forEach(function (key) { select.appendChild(element("option", { value: key, text: key })); });
      if (current && options.indexOf(current) < 0) {
        select.appendChild(element("option", { value: current, text: current }));
      }
      select.value = current;
      select.addEventListener("change", function () { commit(select.value); });
      return select;
    }
    var input = element("input", { type: "text", class: "aiset-tree-key", value: current || "",
      "aria-label": title, title: title, placeholder: node.draft ? "name it" : "key",
      disabled: !!node.pending_delete });
    if (node.pending_delete) { input.title = "This entry is marked for removal; revert it to rename it"; }
    input.addEventListener("change", function () { commit(input.value); });
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { commit(input.value); }
      if (event.key === "Escape") { input.value = current; }
    });
    return input;
  };

  /* Only an object the user names by itself offers to add an entry: without a
   * declared value shape there is nothing a new key could hold. */
  TreeEditor.prototype._addPropertyControl = function (node) {
    var self = this;
    if (!this._keyedObject(node)) { return null; }
    return this._button("add", "Add a new entry with its own key", "plus", function () {
      if (self.keyDrafts[node.path]) { delete self.keyDrafts[node.path]; } else { self.keyDrafts[node.path] = true; }
      self._render();
    });
  };

  TreeEditor.prototype._move = function (node, direction) {
    var index = Number(node.path.split("/").pop());
    var parent = node.path.split("/").slice(0, -1).join("/");
    var target = index + direction;
    if (target < 0) { return; }
    this.stageOperations([{ op: "move", from: node.path, path: parent + "/" + target }], "user");
  };

  /* Square icon button: the picture carries no text, so the meaning is in the
   * title, which browsers also show on a long press. */
  TreeEditor.prototype._button = function (kind, title, iconName, handler) {
    /* A text caption needs a pill: a two- or four-character label does not fit
     * a 24px square. */
    var pill = iconName.indexOf("text:") === 0 ? " pill" : "";
    var button = element("button", {
      type: "button", class: "aiset-tree-action " + kind + pill, title: title, "aria-label": title
    });
    button.appendChild(icon(iconName));
    button.addEventListener("click", handler);
    return button;
  };

  TreeEditor.prototype._stage = function (node, valueText) {
    this.stageOperations([{ op: "set", path: node.path, value_text: valueText }], "user");
  };

  TreeEditor.prototype._valueText = function (node) {
    if (node.access_denied) { return "hidden"; }
    if (node.value_text !== null && node.value_text !== undefined) { return node.value_text; }
    if (node.effective !== null && node.effective !== undefined) {
      return JSON.stringify(node.effective);
    }
    return "";
  };

  /* Room to keep between the raw window and the edge of what contains it. */
  var RAW_PADDING = 48;
  var RAW_CHROME = 240;
  var RAW_MIN_WIDTH = 320;
  var RAW_MIN_HEIGHT = 120;

  var TYPE_GLYPHS = {
    int: { glyph: "i", kind: "int" },
    number: { glyph: "n", kind: "number" },
    string: { glyph: '"', kind: "string" },
    bool: { glyph: "b", kind: "bool" },
    array: { glyph: "[", kind: "container" },
    object: { glyph: "{", kind: "container" },
    other: { glyph: "?", kind: "other" }
  };

  var SVG_NS = "http://www.w3.org/2000/svg";
  var ICON_PATHS = {
    plus: ["M8 3.2v9.6", "M3.2 8h9.6"],
    trash: ["M2.8 4.4h10.4", "M6.4 4.4V2.9h3.2v1.5", "M4.4 4.4l.7 8.7h5.8l.7-8.7"],
    "arrow-up": ["M8 12.8V3.2", "M4.4 6.8L8 3.2l3.6 3.6"],
    "arrow-down": ["M8 3.2v9.6", "M4.4 9.2L8 12.8l3.6-3.6"],
    code: ["M6.2 2.8C4.8 2.8 4.8 4.2 4.8 5.6v1.2c0 1-.6 1.6-1.6 1.6 1 0 1.6.6 1.6 1.6v1.2c0 1.4 0 2.8 1.4 2.8",
           "M9.8 2.8c1.4 0 1.4 1.4 1.4 2.8v1.2c0 1 .6 1.6 1.6 1.6-1 0-1.6.6-1.6 1.6v1.2c0 1.4 0 2.8-1.4 2.8"],
    env: ["M8 1.9a3.1 3.1 0 0 1 1.6 5.9c-.5.4-.6.8-.6 1.3v.4H7v-.4c0-.5-.1-.9-.6-1.3A3.1 3.1 0 0 1 8 1.9z",
          "M7 11.2h2v1.2H7z", "M7 13.4h2v.8H7z"],
    form: ["M3 2.6h10v10.8H3z", "M5.4 5.2h5.2M5.4 7.8h5.2M5.4 10.4h3"]
  };

  function icon(name) {
    /* A text label renders as text: it needs a font, not a path. */
    if (name.indexOf("text:") === 0) {
      var label = document.createElement("span");
      label.setAttribute("class", "aiset-tree-icon-text");
      label.textContent = name.slice(5);
      return label;
    }
    var paths = ICON_PATHS[name] || ICON_PATHS.plus;
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "16");
    svg.setAttribute("height", "16");
    svg.setAttribute("class", "aiset-tree-icon");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    paths.forEach(function (d) {
      var path = document.createElementNS(SVG_NS, "path");
      path.setAttribute("d", d);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.4");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      svg.appendChild(path);
    });
    return svg;
  }

  function _clip(text, limit) {
    var max = limit || 160;
    var value = String(text);
    return value.length > max ? value.slice(0, max - 1) + "…" : value;
  }

  function isComposite(node) {
    return node.type === "object" || node.type === "array";
  }

  function unquote(text) {
    if (text.length > 1 && text[0] === text[text.length - 1] && /['"]/.test(text[0])) {
      try { return JSON.parse(text.replace(/^'/, '"').replace(/'$/, '"')); } catch (error) { return text.slice(1, -1); }
    }
    return text;
  }

  function defaultValueFor(field) {
    if (!field) { return "null"; }
    if (field.default !== undefined) { return JSON.stringify(field.default); }
    switch (field.type) {
      case "int": return "0";
      case "number": return "0";
      case "bool": return "false";
      case "array": return "[]";
      case "object": return "{}";
      case "null": return "null";
      default: return '""';
    }
  }

  function escapeHtml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function escapeToken(token) {
    return String(token).replace(/~/g, "~0").replace(/\//g, "~1");
  }

  // -- public API ------------------------------------------------------
  function renderTreeEditor(documentId, options) {
    var settings = options || {};
    var id = escapeHtml(documentId || "");
    return api.includeAssets() +
      '<div class="aiset-tree-editor" data-aiset-tree="' + id + '">' +
      '<div class="aiset-tree-toolbar" data-role="toolbar"></div>' +
      '<div class="aiset-tree" data-role="tree"></div>' +
      '<div class="aiset-tree-pending" data-role="pending"></div>' +
      '<div class="aiset-tree-status" data-role="status" role="status" aria-live="polite"></div>' +
      '<ul class="aiset-tree-issues" data-role="issues"></ul>' +
      '</div>';
  }

  function mountTree(target, options) {
    var host = typeof target === "string" ? document.querySelector(target) : target;
    if (!host) { throw new Error("aiset.mountTree: target not found"); }
    var instance = new TreeEditor(host, options || {});
    warnIfUnstyled(host);
    return instance;
  }

  /* Development aid (proposal item 4): a page with no rule matching the editor
   * root renders unstyled, and nothing else says so. A styled toolbar is
   * `display: flex`; the browser default for a div is `block`, so a `block`
   * result means neither the library stylesheet nor a host rule matched. */
  function warnIfUnstyled(host) {
    if (typeof global.getComputedStyle !== "function") { return; }
    if (typeof console === "undefined" || typeof console.warn !== "function") { return; }
    var toolbar = host.querySelector && host.querySelector(".aiset-tree-toolbar");
    if (!toolbar) { return; }
    var display = global.getComputedStyle(toolbar).display;
    if (display && display !== "block") { return; }
    console.warn("aiset: the tree editor mounted without styling - no rule matches " +
      ".aiset-tree-toolbar. Load aiset.css (or a host theme) or the tree renders unstyled.");
  }

  /* -- helpers (SPEC.md 18.2) ----------------------------------------
   * A descriptor binds a node to a helper by `tag`; the tag selects an
   * implementation from this registry. Nothing is loaded by guessing a file
   * name or by executing descriptor text. */
  var helpers = {};

  function registerHelper(tag, factory) {
    helpers[tag] = factory;
    return api;
  }

  function helperFor(node) {
    var binding = node && node.field && node.field.helper;
    if (!binding || !binding.tag || !helpers[binding.tag]) { return null; }
    return { tag: binding.tag, factory: helpers[binding.tag], binding: binding };
  }

  /* Opens the bound helper. It resolves with `{value_text}` once the user
   * submits, or with null on cancel; the result is staged through the same
   * validate-then-stage path the raw editor uses. */
  TreeEditor.prototype.runHelper = function (node) {
    var self = this;
    var found = helperFor(node);
    if (!found) {
      this._setStatus("error", "No helper is registered for this node.");
      return Promise.resolve(null);
    }
    return Promise.resolve(found.factory(this, node, found.binding)).then(function (result) {
      if (!result || typeof result.value_text !== "string") { return null; }
      return self._stageRaw(node, result.value_text);
    });
  };

  /* The shipped default: a modal form over the visible children of the node,
   * which is what an element typed through a `typedef` needs. */
  registerHelper("node_form", function (editor, node, binding) {
    var children = editor._visibleChildren(node);
    if (!children.length) { return null; }
    return new Promise(function (resolve) {
      var dialog = element("div", { class: "aiset-form", role: "dialog", "aria-modal": "true" });
      var heading = (binding && binding.settings && binding.settings.note) || node.path || "node";
      dialog.appendChild(element("h4", { class: "aiset-form-title", text: heading }));
      var rows = [];
      children.forEach(function (child) {
        var key = (child.path || "").split("/").pop();
        var current = child.value_text === null || child.value_text === undefined ? "" : child.value_text;
        var row = element("div", { class: "aiset-form-row" });
        row.appendChild(element("label", { class: "aiset-form-label", text: key + " · " + (child.type || "?") }));
        var field = element("span", { class: "aiset-form-field" });
        var control = editor._typedControl(child, current, function (staged) { row.dataset.staged = staged; });
        row.dataset.staged = current;
        control.className = (control.className || "") + " aiset-form-control";
        field.appendChild(control);
        row.appendChild(field);
        rows.push({ key: key, row: row });
        dialog.appendChild(row);
      });
      var actions = element("div", { class: "aiset-form-actions" });
      var cancel = element("button", { type: "button", text: "Cancel", title: "Close without staging" });
      cancel.addEventListener("click", function () { dialog.remove(); resolve(null); });
      var submit = element("button", { type: "button", text: "Stage", title: "Validate and stage this node" });
      submit.addEventListener("click", function () {
        var body = rows.map(function (item) {
          var key = /^[A-Za-z_$][\w$]*$/.test(item.key) ? item.key : JSON.stringify(item.key);
          return "  " + key + ": " + (item.row.dataset.staged || "");
        }).join(",\n");
        dialog.remove();
        resolve({ value_text: "{\n" + body + "\n}\n" });
      });
      actions.appendChild(cancel);
      actions.appendChild(submit);
      dialog.appendChild(actions);
      document.body.appendChild(dialog);
      var first = dialog.querySelector("input, textarea, select");
      if (first && first.focus) { first.focus(); }
    });
  });

  api.classes = function () {
    return CLASS_INVENTORY.map(function (entry) { return Object.assign({}, entry); });
  };
  api.registerHelper = registerHelper;
  api.helpers = helpers;
  api.renderTreeEditor = renderTreeEditor;
  api.mountTree = mountTree;
  api.TreeEditor = TreeEditor;
  api.request = request;
})(window);