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
    this.applyButton = element("button", { type: "button", text: "Apply", onclick: function () { self.applyPending(); } });
    this.reloadButton = element("button", { type: "button", text: "Reload", onclick: function () { self.reload(true); } });
    this.revertButton = element("button", { type: "button", text: "Revert all", onclick: function () { self.stageOperations([], "user"); } });
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
        self._render();
        self._setStatus("ok", "Loaded revision " + String(tree.revision).slice(0, 12) +
          (tree.invalid_on_disk ? " — invalid on disk, showing the last valid state" : ""));
        self._emit("loaded", tree);
        return tree;
      })
      .catch(function (error) {
        self._setStatus("error", "Load failed: " + error.message);
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

  TreeEditor.prototype.stageOperations = function (operations, source) {
    var self = this;
    (operations || []).forEach(function (operation) {
      var key = operation.op + "|" + (operation.path || "") + "|" + (operation.from || "");
      var existing = -1;
      self.pending.forEach(function (item, index) {
        if (item.key === key) { existing = index; }
      });
      if (existing >= 0) { self.pending.splice(existing, 1); }
      self.pending.push({ key: key, operation: Object.assign({}, operation), source: source || "user" });
    });
    if (!operations || !operations.length) { this.pending = []; }
    this._renderPending();
    this._render();
    this._emit("staged", this.getPendingOperations());
    return this.getPendingOperations();
  };

  TreeEditor.prototype.revert = function (path) {
    this.pending = this.pending.filter(function (item) {
      return item.operation.path !== path && item.operation.from !== path;
    });
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
    if (!this.tree || !this.tree.node) {
      this.treeNode.appendChild(element("p", { text: "This path does not exist yet. Apply a change to create it." }));
      this._renderPending();
      return;
    }
    this.treeNode.appendChild(this._renderNode(this.tree.node, true));
    this._renderPending();
    this._loadEnvPresence();
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

  /* Children of one node as they are rendered right now. */
  TreeEditor.prototype._visibleChildren = function (node) {
    var children = (node.children || []).concat(node.items || []);
    if (this.showAbsent) { return children; }
    return children.filter(function (child) { return child.exists !== false; });
  };

  TreeEditor.prototype._renderNode = function (node, isRoot) {
    var self = this;
    var container = element("div", {
      class: "aiset-tree-node", role: "treeitem",
      dataset: { path: node.path, absent: String(node.exists === false) }
    });
    var row = element("div", { class: "aiset-tree-row" });
    var children = this._visibleChildren(node);
    var composite = children.length;
    var isOpen = !!this.expanded[node.path];

    var toggle = element("button", {
      type: "button",
      class: "aiset-tree-toggle",
      text: composite ? (isOpen ? "-" : "+") : "",
      "aria-expanded": composite ? String(isOpen) : null,
      "aria-label": (isOpen ? "Collapse " : "Expand ") + (node.path || "root")
    });
    if (composite) {
      toggle.addEventListener("click", function () {
        self.expanded[node.path] = !self.expanded[node.path];
        self._render();
      });
    }
    row.appendChild(toggle);

    var name = isRoot ? (node.path || "/") : node.path.split("/").pop();
    var labelNode = element("span", { class: "aiset-tree-name", text: name });
    labelNode.setAttribute("title", this._tooltip(node));
    row.appendChild(labelNode);
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
        group.appendChild(self._renderNode(child, false));
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
      wrap.appendChild(badge(node.origin.kind, "origin"));
    }
    if (node.exists === false) { wrap.appendChild(badge(node.default_applied ? "default" : "absent", "absent")); }
    if (node.field && node.field.read_only) { wrap.appendChild(badge("read-only", "lock")); }
    if (node.access_denied) { wrap.appendChild(badge("secret", "lock")); }
    if (node.field && node.field.required) { wrap.appendChild(badge("required", "req")); }
    if (node.field && node.field.nullable) { wrap.appendChild(badge("nullable", "req")); }
    if (this._pendingFor(node.path)) { wrap.appendChild(badge("dirty", "dirty")); }
    return wrap;
  };

  TreeEditor.prototype._pendingFor = function (path) {
    return this.pending.some(function (item) {
      return item.operation.path === path || item.operation.from === path;
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
      var stored = this._valueText(node);
      /* Nothing to show: name the type instead of an empty control. */
      if (!stored) { return this._typeGlyph(node); }
      return element("span", { class: "aiset-tree-value readonly", text: stored });
    }
    /* Raw mode shows the stored fragment below the row instead. */
    if (this.rawMode[node.path]) { return null; }
    if (this._templateInfo(node) || this.envDraft[node.path]) {
      return this._templateControl(node);
    }

    var wrap = element("span", { class: "aiset-tree-value" });
    var current = node.value_text === null || node.value_text === undefined ? "" : node.value_text;
    /* An unchecked box cannot say whether a bool is stored or false. */
    if (node.type === "bool" && node.exists === false) { wrap.appendChild(this._typeGlyph(node)); }
    var control = this._typedControl(node, current, function (staged) { self._stage(node, staged); });
    wrap.appendChild(control);
    if (field.nullable && node.type !== "object") {
      wrap.appendChild(this._nullToggle(node, control));
    }
    if (node.type === "union" && field.children_options) {
      wrap.appendChild(this._typeChooser(node));
    }
    return wrap;
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
    var area = element("textarea", { rows: (field.ui && field.ui.rows) || 3, "aria-label": "Value for " + node.path });
    area.value = current;
    if (field.ui && field.ui.placeholder) { area.placeholder = field.ui.placeholder; }
    area.addEventListener("change", function () { onChange(area.value, area.value); });
    return area;
  };

  /* ${VAR:-fallback}: the variable name and the fallback are edited apart, so a
   * substitution is never lost by changing the value it falls back to. */
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
    wrap.appendChild(this._button("env-off", "Drop the substitution and keep the inline value", "text:\u21ba",
      function () { self._dropTemplate(node); }));
    return wrap;
  };

  TreeEditor.prototype._stageTemplate = function (node, name, fallback) {
    this.stageOperations([{ op: "set", path: node.path, value_text: "${" + name + ":-" + fallback + "}" }], "user");
  };

  /* An empty variable name means a plain value again. */
  TreeEditor.prototype._dropTemplate = function (node) {
    var info = this._currentTemplate(node) || { fallback: this._plainText(node) };
    var fallback = info.fallback;
    if (fallback === null || fallback === undefined) { fallback = ""; }
    if (fallback === "" && node.type !== "string") {
      var declared = node.field && node.field.default !== undefined ? node.field.default : null;
      fallback = declared === null ? "" : JSON.stringify(declared);
      if (declared === null) { fallback = node.type === "bool" ? "false" : "0"; }
    }
    delete this.envDraft[node.path];
    this.stageOperations([
      { op: "set", path: node.path, value_text: node.type === "string" ? JSON.stringify(fallback) : fallback }
    ], "user");
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
    var wrap = element("div", { class: "aiset-tree-raw" });
    wrap.appendChild(element("div", {
      class: "aiset-tree-raw-title",
      text: "Raw source of " + (node.path || "root") + " — JSON5, comments and ${VARIABLES} kept"
    }));
    var area = element("textarea", {
      rows: 8, class: "aiset-tree-raw-text", "aria-label": "Raw source of " + node.path
    });
    area.value = node.value_text === null || node.value_text === undefined ? "" : node.value_text;
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
    var reason = node.exists === false ? "not stored yet" : "nothing to show";
    return element("span", {
      class: "aiset-tree-type " + entry.kind,
      title: node.type + ": " + reason,
      text: entry.glyph
    });
  };

  TreeEditor.prototype._typeChooser = function (node) {
    var self = this;
    var select = element("select", { "aria-label": "Value shape for " + node.path, class: "aiset-tree-shape" });
    select.appendChild(element("option", { value: "", text: "shape…" }));
    (node.field.children_options || []).forEach(function (option) {
      select.appendChild(element("option", { value: option.type, text: option.type }));
    });
    select.addEventListener("change", function () {
      if (!select.value) { return; }
      var sample = { string: '""', int: "0", number: "0", bool: "false", null: "null",
                     array: "[]", object: "{}", union: "{}" };
      self._stage(node, sample[select.value] || "null");
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
    var button = this._button("default", title, "text:\u21ba", function () {
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
      if (!isComposite(node) && !this._templateInfo(node) && !this.envDraft[node.path]) {
        wrap.appendChild(this._envButton(node));
      }
    }
    var reset = this._defaultControl(node);
    if (reset) { wrap.appendChild(reset); }
    if (caps.add) {
      wrap.appendChild(this._addItemControl(node, !!(node.field && node.field.children_options)));
    }
    if (caps.remove && (node.kind === "array_item" || node.type === "array")) {
      wrap.appendChild(this._button("remove", node.type === "array" ? "Remove this list" : "Remove this item", "trash", function () {
        self.stageOperations([{ op: "remove", path: node.path }], "user");
      }));
      if (caps.reorder) {
        wrap.appendChild(this._button("up", "Move up", "arrow-up", function () { self._move(node, -1); }));
        wrap.appendChild(this._button("down", "Move down", "arrow-down", function () { self._move(node, 1); }));
      }
    }
    if (caps.remove_child && node.kind === "object") {
      wrap.appendChild(this._addPropertyControl(node));
    }
    return wrap;
  };

  TreeEditor.prototype._addItemControl = function (node, typed) {
    var self = this;
    var button = this._button("add", "Add an item", "plus", function () {
      if (!typed) { self._appendItem(node, defaultValueFor(node.field)); return; }
      self._showItemChooser(node);
    });
    return button;
  };

  TreeEditor.prototype._showItemChooser = function (node) {
    var self = this;
    var existing = this.toolbar.querySelector(".aiset-tree-chooser");
    if (existing) { existing.remove(); }
    var chooser = element("span", { class: "aiset-tree-chooser" });
    chooser.appendChild(label(" new item: "));
    (node.field.children_options || []).forEach(function (option) {
      var button = element("button", { type: "button", text: option.type });
      button.addEventListener("click", function () {
        self.stageOperations([{ op: "add", path: node.path + "/-", value_text: defaultValueFor(option) }], "user");
        chooser.remove();
      });
      chooser.appendChild(button);
    });
    this.toolbar.appendChild(chooser);
  };

  TreeEditor.prototype._appendItem = function (node, valueText) {
    this.stageOperations([{ op: "add", path: node.path + "/-", value_text: valueText }], "user");
  };

  TreeEditor.prototype._addPropertyControl = function (node) {
    var self = this;
    var caps = node.capabilities || {};
    if (caps.key_options && caps.key_options.length) {
      var select = element("select", { "aria-label": "New key for " + node.path, class: "aiset-tree-key" });
      select.appendChild(element("option", { value: "", text: "add property…" }));
      caps.key_options.forEach(function (key) {
        select.appendChild(element("option", { value: key, text: key }));
      });
      select.addEventListener("change", function () {
        if (!select.value) { return; }
        self.stageOperations([{ op: "add", path: node.path + "/" + escapeToken(select.value), value_text: defaultValueFor(node.additional_child) }], "user");
        select.value = "";
      });
      return select;
    }
    var input = element("input", {
      type: "text", class: "aiset-tree-key", "aria-label": "New key for " + node.path,
      placeholder: caps.key_pattern || "key"
    });
    input.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" || !input.value) { return; }
      self.stageOperations([{ op: "add", path: node.path + "/" + escapeToken(input.value),
                              value_text: defaultValueFor(node.additional_child) }], "user");
      input.value = "";
    });
    return input;
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
          "M7 11.2h2v1.2H7z", "M7 13.4h2v.8H7z"]
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
    return new TreeEditor(host, options || {});
  }

  api.renderTreeEditor = renderTreeEditor;
  api.mountTree = mountTree;
  api.TreeEditor = TreeEditor;
  api.request = request;
})(window);