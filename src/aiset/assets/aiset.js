/* aiset reusable UI assets (SPEC.md 9, SPEC_service.md 17).
 * No framework, no build step, no CDN. The host includes these files (or the
 * string from aiset.include_assets()) and inserts the HTML fragment returned by
 * aiset.render_node_editor() / aiset.render_full_editor().
 *
 * Browser-side validation is optional and advisory: the server is always
 * authoritative and revalidates every candidate. */

(function (global) {
  "use strict";

  var BASE = "/api/settings";
  var documents = [];
  var current = null;
  var revision = null;
  var descriptorRevision = null;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "text") { node.textContent = attrs[key]; }
      else if (key === "html") { node.innerHTML = attrs[key]; }
      else if (key.indexOf("on") === 0) { node.addEventListener(key.slice(2), attrs[key]); }
      else { node.setAttribute(key, attrs[key]); }
    });
    (children || []).forEach(function (child) { if (child) { node.appendChild(child); } });
    return node;
  }

  function request(method, path, body) {
    var options = { method: method, headers: { "Accept": "application/json" } };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(BASE + path, options).then(function (response) {
      return response.json().then(function (payload) {
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

  function status(state, message) {
    var box = state.querySelector("[data-role=status]");
    if (!box) { return; }
    box.textContent = message;
    box.setAttribute("data-state", state);
  }

  function renderIssues(state, issues) {
    var list = state.querySelector("[data-role=issues]");
    if (!list) { return; }
    list.innerHTML = "";
    (issues || []).forEach(function (issue) {
      var path = issue.path || "/";
      if (issue.line) { path += " (line " + issue.line + ", column " + issue.column + ")"; }
      list.appendChild(el("li", { text: "[" + issue.severity + "] " + path + ": " + issue.message }));
    });
  }

  /* Best-effort local check only: it never blocks a submission. */
  function localCheck(valueText, field) {
    var text = (valueText || "").trim();
    if (!text) { return "Value is empty; the server will reject it."; }
    try { JSON.parse(text); } catch (error) {
      /* JSON5 and templates are accepted by the server, so this is only a hint. */
    }
    if (field && field.type === "int" && /^[-+]?\d+$/.test(text)) {
      var number = parseInt(text, 10);
      if (field.minimum !== undefined && number < field.minimum) {
        return "Below the declared minimum (" + field.minimum + ").";
      }
      if (field.maximum !== undefined && number > field.maximum) {
        return "Above the declared maximum (" + field.maximum + ").";
      }
    }
    return "Local check passed; server validation is still required.";
  }

  function describeField(field) {
    if (!field) { return ""; }
    var parts = [field.type];
    if (field.required) { parts.push("required"); }
    if (field.read_only) { parts.push("read-only"); }
    if (field.secret) { parts.push("secret"); }
    if (field.minimum !== undefined || field.maximum !== undefined) {
      parts.push("range " + (field.minimum === undefined ? "-inf" : field.minimum) + ".." +
                 (field.maximum === undefined ? "inf" : field.maximum));
    }
    if (field.default !== undefined) { parts.push("default " + JSON.stringify(field.default)); }
    return parts.join(", ");
  }

  function editor(documentId, initialPath) {
    var state = {
      document: documentId,
      path: initialPath || "",
      revision: null,
      descriptor_revision: null
    };

    var pathInput = el("input", { type: "text", class: "aiset-path", value: state.path,
                                  placeholder: "/logging/levels/workers" });
    var valueInput = el("textarea", { class: "aiset-value", rows: 8, spellcheck: "false" });
    var fieldInfo = el("div", { class: "aiset-field", "data-role": "field" });
    var statusBox = el("div", { class: "aiset-status", "data-role": "status" });
    var issuesList = el("ul", { class: "aiset-issues", "data-role": "issues" });
    var localBox = el("div", { class: "aiset-local", "data-role": "local" });

    function payload(extra) {
      var body = {
        document: state.document,
        path: state.path,
        value_text: valueInput.value,
        expected_revision: state.revision,
        expected_descriptor_revision: state.descriptor_revision
      };
      Object.keys(extra || {}).forEach(function (key) { body[key] = extra[key]; });
      return body;
    }

    function doRead() {
      state.path = pathInput.value;
      statusBox.textContent = "Reading...";
      request("GET", "/value?document=" + encodeURIComponent(state.document) +
              "&path=" + encodeURIComponent(state.path) + "&view=source")
        .then(function (result) {
          state.revision = result.revision;
          state.descriptor_revision = result.descriptor_revision;
          fieldInfo.textContent = describeField(result.field) +
            (result.field && result.field.description ? " — " + result.field.description : "");
          fieldInfo.setAttribute("data-read-only", String(!!(result.field && result.field.read_only)));
          renderIssues(state, []);
          if (result.exists) {
            valueInput.value = result.value_text;
            status(state, "Read (" + result.format + ", revision " + result.revision.slice(0, 12) + ").");
          } else if (result.default_applied) {
            valueInput.value = result.value_text || "";
            status(state, "Absent optional field; the effective default is shown and is not stored.");
          } else {
            valueInput.value = "";
            status(state, "Absent permitted optional field: you may create it.");
          }
        })
        .catch(function (error) {
          status(state, "Read failed: " + error.message);
          renderIssues(state, error.issues);
        });
    }

    function doValidate() {
      localBox.textContent = localCheck(valueInput.value, null);
      status(state, "Validating (server authoritative)...");
      request("POST", "/validate", payload())
        .then(function (result) {
          renderIssues(state, result.issues);
          status(state, result.valid
            ? (result.preservable ? "Valid and source-preservable." : "Valid, but source cannot be preserved.")
            : "Rejected by server validation; nothing was written.");
        })
        .catch(function (error) {
          renderIssues(state, error.issues);
          status(state, "Validation failed: " + error.message);
        });
    }

    function doSave() {
      localBox.textContent = localCheck(valueInput.value, null);
      status(state, "Saving...");
      request("POST", "/value", payload())
        .then(function (result) {
          state.revision = result.revision;
          renderIssues(state, result.issues || []);
          var application = (result.application && result.application.state) || "unknown";
          status(state, "Stored. Application: " + application +
            (application === "restart_required" ? " (a host restart would be required)" : "") + ".");
        })
        .catch(function (error) {
          renderIssues(state, error.issues);
          if (error.code === "REVISION_CONFLICT" || error.status === 409) {
            status(state, "Conflict: the file changed. Your text is kept — press Read to reconcile.");
          } else {
            status(state, "Not saved: " + error.message);
          }
        });
    }

    /* Changing the path invalidates the captured revisions: re-read instead of
     * silently sending stale ones (SPEC.md 9). */
    pathInput.addEventListener("change", function () {
      state.revision = null;
      state.descriptor_revision = null;
      status(state, "Path changed; reading the new field...");
      doRead();
    });

    return el("div", { class: "aiset-editor" }, [
      el("div", { class: "aiset-toolbar" }, [
        el("label", { class: "aiset-label", text: "Document" }),
        el("input", { type: "text", class: "aiset-document", value: state.document,
                      onchange: function (event) {
                        state.document = event.target.value;
                        state.revision = null;
                        doRead();
                      } }),
        el("label", { class: "aiset-label", text: "JSON Pointer" }),
        pathInput,
        el("button", { type: "button", text: "Read", onclick: doRead }),
        el("button", { type: "button", text: "Validate", onclick: doValidate }),
        el("button", { type: "button", text: "Save", onclick: doSave })
      ]),
      fieldInfo,
      el("div", { class: "aiset-hint", text: "Path example: /logging/levels/workers — source is edited as JSON5; strings must be quoted." }),
      valueInput,
      localBox,
      statusBox,
      issuesList
    ]);
  }

  function includeAssets(apiBase) {
    if (apiBase) { BASE = apiBase; }
    var snippet = document.getElementById("aiset-assets");
    if (snippet) { return snippet.innerHTML; }
    return '<link rel="stylesheet" href="/assets/aiset.css">' +
           '<script src="/assets/aiset.js"></script>';
  }

  function renderNodeEditor(documentId, path) {
    return includeAssets() + '<div data-aiset-node="' + (documentId || "") + '"></div>';
  }

  function renderFullEditor(documentId) {
    return includeAssets() + '<div data-aiset-full="' + (documentId || "") + '"></div>';
  }

  function mount(target, documentId, path) {
    var host = typeof target === "string" ? document.querySelector(target) : target;
    if (!host) { return null; }
    var instance = editor(documentId || current || "", path || "");
    host.innerHTML = "";
    host.appendChild(instance);
    return instance;
  }

  function loadDocuments(done) {
    request("GET", "/documents").then(function (result) {
      documents = result.documents || [];
      current = current || documents[0] || null;
      done(documents);
    }).catch(function () { done([]); });
  }

  function ready(done) {
    loadDocuments(function (list) { done(list); });
    document.addEventListener("DOMContentLoaded", function () {
      var host = document.querySelector("[data-aiset-full], [data-aiset-node]");
      if (!host) { return; }
      var documentId = host.getAttribute("data-aiset-full") || host.getAttribute("data-aiset-node");
      var path = host.getAttribute("data-aiset-path") || "/";
      mount(host, documentId, path);
    });
  }

  global.aiset = {
    includeAssets: includeAssets,
    renderNodeEditor: renderNodeEditor,
    renderFullEditor: renderFullEditor,
    mount: mount,
    ready: ready,
    documents: function () { return documents.slice(); }
  };
})(window);