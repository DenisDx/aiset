/* demo2 host page script (proposal_demo2.md sections 6.2, 7 and 10).
 *
 * The left pane is the reusable aiset tree editor; this file only wires the
 * host lifecycle buttons, the chat pane, and the bridge that hands assistant
 * proposals to the editor as staged operations.
 *
 * Every DOM access happens after the document is ready: the script may be
 * loaded from <head> or at the end of <body>.
 */

(function () {
  "use strict";

  var HOST_BASE = "/api/demo2";
  var session = randomSessionId();
  var tree = null;
  var inFlight = null;
  var nodes = {};

  function randomSessionId() {
    var bytes = new Uint8Array(16);
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (var index = 0; index < bytes.length; index += 1) {
        bytes[index] = Math.floor(Math.random() * 256);
      }
    }
    return Array.prototype.map.call(bytes, function (value) {
      return ("0" + value.toString(16)).slice(-2);
    }).join("");
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || payload.ok === false) {
          var error = new Error((payload.error && payload.error.message) || response.statusText);
          error.code = (payload.error && payload.error.code) || "HTTP_" + response.status;
          error.issues = (payload.error && payload.error.issues) || [];
          throw error;
        }
        return payload;
      });
    });
  }

  function text(tag, className, content) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    node.textContent = content;
    return node;
  }

  // -- chat ---------------------------------------------------------------
  function addEntry(role, body) {
    if (!nodes.history) { return; }
    var entry = text("div", "chat-entry " + role);
    entry.appendChild(text("div", "chat-role", role));
    entry.appendChild(text("div", "chat-body", body));
    nodes.history.appendChild(entry);
    nodes.history.scrollTop = nodes.history.scrollHeight;
    return entry;
  }

  function setBusy(busy) {
    if (nodes.send) { nodes.send.disabled = busy; }
    if (nodes.cancel) { nodes.cancel.disabled = !busy; }
    if (nodes.input) { nodes.input.disabled = busy; }
  }

  function send(message) {
    addEntry("user", message);
    setBusy(true);
    inFlight = post(HOST_BASE + "/chat", { session: session, message: message });
    inFlight
      .then(function (result) {
        (result.activity || []).forEach(function (item) {
          addEntry("tool", "tool " + item.tool + " " + JSON.stringify(item.arguments || {}));
        });
        addEntry("assistant", result.message || "(no answer)");
        var staged = result.staged_operations || [];
        if (staged.length && tree) {
          tree.stageOperations(staged, "ai");
          addEntry("staged", staged.length + " change(s) staged for you. Review and press Apply.");
        }
      })
      .catch(function (error) {
        addEntry("error", error.message);
      })
      .then(function () { setBusy(false); inFlight = null; });
  }

  function bindChat() {
    nodes.history = document.getElementById("chat-history");
    nodes.form = document.getElementById("chat-form");
    nodes.input = document.getElementById("chat-text");
    nodes.send = document.getElementById("chat-send");
    nodes.cancel = document.getElementById("chat-cancel");
    nodes.clear = document.getElementById("chat-clear");
    if (!nodes.form) { return; }

    nodes.form.addEventListener("submit", function (event) {
      event.preventDefault();
      var message = nodes.input.value.trim();
      if (!message || inFlight) { return; }
      nodes.input.value = "";
      send(message);
    });

    nodes.input.addEventListener("keydown", function (event) {
      /* Enter sends; Shift+Enter inserts a newline (proposal section 10.4). */
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (nodes.form.requestSubmit) { nodes.form.requestSubmit(); }
      }
    });

    nodes.cancel.addEventListener("click", function () {
      if (inFlight && inFlight.abort) { inFlight.abort(); }
      setBusy(false);
      inFlight = null;
      addEntry("tool", "request cancelled");
    });

    nodes.clear.addEventListener("click", function () { nodes.history.innerHTML = ""; });
  }

  // -- status -------------------------------------------------------------
  function refreshStatus() {
    return fetch(HOST_BASE + "/status", {
      headers: { Accept: "application/json", "X-Aiset-Session": session }
    })
      .then(function (response) { return response.json(); })
      .then(function (status) {
        var meta = document.getElementById("app-status");
        if (meta) {
          meta.textContent =
            "revision " + String(status.revision || "").slice(0, 12) +
            " · reloads " + status.reloads +
            " · last change: " + ((status.applied && status.applied.state) || "none");
        }
        var model = document.getElementById("chat-model");
        if (model) {
          model.textContent = status.ai && status.ai.enabled
            ? "model " + status.ai.model
            : "disabled";
        }
      })
      .catch(function () {
        var meta = document.getElementById("app-status");
        if (meta) { meta.textContent = "backend unavailable"; }
      });
  }

  /* The page asks the host to re-exec; poll until the backend answers again. */
  function waitForRestart() {
    var tick = window.setInterval(function () {
      fetch("/api/demo2/health")
        .then(function () {
          window.clearInterval(tick);
          window.location.reload();
        })
        .catch(function () { /* keep polling */ });
    }, 500);
  }

  /* The editor owns every view option; these checkboxes only reflect them. */
  var VIEW_OPTIONS = [
    { id: "tree-values-text", read: "getValuesAsText", write: "setValuesAsText" },
    { id: "tree-show-absent", read: "getShowAbsent", write: "setShowAbsent" }
  ];

  function bindTreeOptions(editor) {
    VIEW_OPTIONS.forEach(function (option) {
      var toggle = document.getElementById(option.id);
      if (!toggle) { return; }
      toggle.checked = editor[option.read]() === true;
      toggle.addEventListener("change", function () { editor[option.write](toggle.checked); });
    });
  }

  // -- startup ------------------------------------------------------------
  function init() {
    bindChat();
    var host = document.getElementById("settings-tree");
    if (!host || !window.aiset || !window.aiset.mountTree) {
      var meta = document.getElementById("app-status");
      if (meta) { meta.textContent = "editor assets are not loaded"; }
      return;
    }
    tree = window.aiset.mountTree(host, {
      document: "demo2",
      apiBase: "/api/settings",
      /* Reload is aiset's explicit re-read path; Restart is a host route. */
      lifecycle: [{
        id: "restart",
        label: "Restart",
        url: HOST_BASE + "/restart",
        confirm: "Restart demo2? The server will re-exec itself; staged edits stay in the browser.",
        reloadAfter: false
      }]
    });
    bindTreeOptions(tree);
    tree.on("lifecycle", function (event) {
      if (event.action === "restart") { waitForRestart(); }
    });
    tree.on("loaded", refreshStatus);
    tree.on("applied", refreshStatus);
    refreshStatus();
    window.setInterval(refreshStatus, 5000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();