"""UI asset contracts (SPEC_service.md sections 17 and 21).

The browser assets are checked without a browser: syntax is validated with node
when it is available, and the public helper API is exercised against a small
DOM stub. The test skips when node is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "aiset" / "assets"
JS_FILES = ["aiset.js", "aiset-tree.js"]

SMOKE = r"""
const fs = require("fs");

function stubElement() {
  const node = {
    style: {}, dataset: {}, children: [], value: "", textContent: "", disabled: false,
    checked: false, className: "", innerHTML: "",
    setAttribute(key, value) {
      /* Boolean attributes are disabled by presence, as in a real browser. */
      if (key === "disabled" || key === "checked" || key === "readonly" || key === "required") {
        this[key] = true;
      } else {
        this[key] = value;
      }
    },
    getAttribute(key) { return this[key] === undefined ? null : this[key]; }, remove() {},
    addEventListener(event, handler) { (this.events = this.events || {})[event] = handler; },
    querySelector() { return stubElement(); },
    querySelectorAll() { return []; }, closest() { return null; },
    appendChild(child) { this.children.push(child); return child; },
    cloneNode() { return stubElement(); }, focus() {},
  };
  return node;
}

function taggedElement(tag) {
  const node = stubElement();
  node.tagName = tag;
  return node;
}

const doc = {
  createElement: (tag) => taggedElement(tag),
  createElementNS: (ns, tag) => taggedElement(tag),
  getElementById: () => null,
  createTextNode: (text) => ({ nodeType: 3, textContent: text }),
  querySelector: () => stubElement(),
  querySelectorAll: () => [],
  addEventListener() {},
};

global.window = { innerWidth: 1280, innerHeight: 800 };  /* the raw window must respect them */
global.document = doc;
global.confirm = () => true;

const TREE = {
  ok: true, document: "demo2", path: "", view: "source",
  revision: "sha256:rev", descriptor_revision: "sha256:desc", invalid_on_disk: false,
  exists: true,
  node: {
    path: "", type: "object", exists: true, access_denied: false, kind: "object",
    origin: { kind: "file" }, apply: "restart", value_text: "{}",
    field: { type: "object", description: "root" },
    capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: true, remove_child: false },
    children: [{
      path: "/server", type: "object", exists: true, access_denied: false, kind: "object",
      origin: { kind: "file" }, apply: "restart", value_text: "{}",
      field: { type: "object", description: "server" },
      capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
      children: [{
        path: "/server/enabled", type: "bool", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "live", value_text: "true",
        field: { type: "bool", description: "switch" },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/level", type: "string", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "reload", value_text: '"debug"',
        comments: ["Backend log level", "Read by the host on reload."],
        field: { type: "string", description: "Logging level", default: "info", apply: "reload",
                 enum: ["debug", "info", "error"] },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/typed", type: "object", exists: true, access_denied: false, kind: "object",
        origin: { kind: "file" }, apply: "reload", value_text: "{\n  a: 1\n}",
        field: { type: "object", description: "typed element",
                 helper: { tag: "node_form", actions: ["create", "edit"], presentation: "modal",
                           settings: { note: "subform" } } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [{
          path: "/server/typed/a", type: "int", exists: true, access_denied: false, kind: "leaf",
          origin: { kind: "file" }, apply: "reload", value_text: "1",
          field: { type: "int", description: "a" },
          capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
          children: [], items: [],
        }],
        items: [],
      }, {
        path: "/server/env_port", type: "int", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "restart", value_text: "${SERVER_PORT:-8383}",
        template: { name: "SERVER_PORT", default: "8383" },
        field: { type: "int", description: "port", minimum: 1, maximum: 65535, env: { allowed: true, convert: "int" } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        /* A string placeholder is quoted in the file, a converted one is not,
         * and one without a default writes ${VAR}. */
        path: "/server/env_quoted", type: "string", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "restart", value_text: '"${SERVER_MODE:-safe}"',
        template: { name: "SERVER_MODE", default: "safe" },
        field: { type: "string", description: "quoted placeholder", env: { allowed: true } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/env_enum", type: "string", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "reload", value_text: '"${SERVER_LEVEL:-info}"',
        template: { name: "SERVER_LEVEL", default: "info" },
        field: { type: "string", description: "enum behind a placeholder",
                 enum: ["info", "debug", "error"], env: { allowed: true } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/env_nodefault", type: "string", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "restart", value_text: '"${SERVER_BASE}"',
        template: { name: "SERVER_BASE" },
        field: { type: "string", description: "placeholder without a default", env: { allowed: true } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/env_bare", type: "int", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "restart", value_text: "${SERVER_SIZE:-10}",
        template: { name: "SERVER_SIZE", default: "10" },
        field: { type: "int", description: "converted placeholder", env: { allowed: true, convert: "int" } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/plain_int", type: "int", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "restart", value_text: "42",
        field: { type: "int", description: "plain" },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/open_int", type: "int", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "restart", value_text: "7",
        field: { type: "int", description: "env allowed", env: { allowed: true, convert: "int" } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/nullable_text", type: "string", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "live", value_text: "null",
        field: { type: "string", description: "stored as an explicit null", nullable: true },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/absent_int", type: "int", exists: false, access_denied: false, kind: "leaf",
        origin: { kind: "absent" }, apply: "live", value_text: null,
        field: { type: "int", description: "not stored yet" },
        capabilities: { edit: false, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/port", type: "int", exists: true, access_denied: false, kind: "leaf",
        origin: { kind: "file" }, apply: "restart", value_text: "8383",
        field: { type: "int", description: "port", minimum: 1, maximum: 65535 },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [], items: [],
      }, {
        path: "/server/numbers", type: "array", exists: true, access_denied: false, kind: "array",
        origin: { kind: "file" }, apply: "restart", value_text: "[7]",
        field: { type: "array", description: "int items",
                 children: { type: "int", description: "One number" } },
        capabilities: { edit: true, add: true, remove: true, reorder: false, add_child: false, remove_child: false },
        children: [],
        items: [{
          path: "/server/numbers/0", type: "int", exists: true, access_denied: false, kind: "array_item",
          origin: { kind: "file" }, apply: "restart", value_text: "7",
          field: { type: "int", description: "One number" },
          capabilities: { edit: true, add: false, remove: true, reorder: true, add_child: false, remove_child: false },
          children: [], items: [],
        }],
      }, {
        path: "/server/directory", type: "object", exists: true, access_denied: false, kind: "dynamic_key",
        origin: { kind: "file" }, apply: "reload", value_text: "{}",
        field: { type: "object", description: "keys the user names",
                 additional_children: {
                   type: "object", description: "One templated card", required: true,
                   children: { label: { type: "string", required: true, description: "name" },
                               weight: { type: "int", description: "optional" } } } },
        additional_child: {
          type: "object", description: "One templated card", required: true,
          children: { label: { type: "string", required: true, description: "name" },
                      weight: { type: "int", description: "optional" } } },
        capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: true, remove_child: true },
        children: [{
          path: "/server/directory/alpha", type: "object", exists: true, access_denied: false, kind: "dynamic_key",
          origin: { kind: "file" }, apply: "reload", value_text: "{\n  label: \"a\"\n}",
          field: { type: "object", description: "One templated card", required: true,
                   children: { label: { type: "string", required: true, description: "name" },
                               weight: { type: "int", description: "optional" } } },
          capabilities: { edit: true, add: false, remove: true, reorder: false, add_child: true, remove_child: true },
          children: [{
            path: "/server/directory/alpha/label", type: "string", exists: true, access_denied: false, kind: "leaf",
            origin: { kind: "file" }, apply: "reload", value_text: '"a"',
            field: { type: "string", description: "name", required: true },
            capabilities: { edit: true, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
            children: [], items: [],
          }, {
            path: "/server/directory/alpha/weight", type: "int", exists: false, access_denied: false, kind: "leaf",
            origin: { kind: "absent" }, apply: "reload", value_text: null,
            field: { type: "int", description: "optional" },
            capabilities: { edit: false, add: false, remove: false, reorder: false, add_child: false, remove_child: false },
            children: [], items: [],
          }],
          items: [],
        }],
        items: [],
      }, {
        path: "/server/hosts", type: "array", exists: true, access_denied: false, kind: "array_item",
        origin: { kind: "file" }, apply: "restart", value_text: '["127.0.0.1"]',
        field: { type: "array", description: "hosts" },
        capabilities: { edit: true, add: true, remove: false, reorder: false, add_child: false, remove_child: false },
        children: [],
        items: [{
          path: "/server/hosts/0", type: "string", exists: true, access_denied: false, kind: "array_item",
          origin: { kind: "file" }, apply: "restart", value_text: '"127.0.0.1"',
          field: { type: "string", description: "host" },
          capabilities: { edit: true, add: false, remove: true, reorder: true, add_child: false, remove_child: false },
          children: [], items: [],
        }, {
          path: "/server/hosts/1", type: "string", exists: true, access_denied: false, kind: "array_item",
          origin: { kind: "file" }, apply: "restart", value_text: '"10.0.0.1"',
          field: { type: "string", description: "host" },
          capabilities: { edit: true, add: false, remove: true, reorder: true, add_child: false, remove_child: false },
          children: [], items: [],
        }],
      }],
      items: [],
    }],
    items: [],
  },
};

const calls = [];
global.fetch = (url, options) => {
  calls.push({ url, method: (options && options.method) || "GET", body: options && options.body });
  let payload = { ok: true, valid: true, issues: [], stored: true, dry_run: false,
    revision: "sha256:new", application: { state: "applied" } };
  if (url.indexOf("/tree") >= 0) { payload = TREE; }
  if (url.indexOf("/env") >= 0) { payload = { ok: true, present: { SERVER_PORT: true } }; }
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
};

eval(fs.readFileSync(process.argv[2], "utf8"));
eval(fs.readFileSync(process.argv[3], "utf8"));
const aiset = global.window.aiset;

const assert = (condition, message) => {
  if (!condition) { throw new Error(message); }
};
const has = (text, needle) => text.indexOf(needle) >= 0;

assert(has(aiset.includeAssets(), "/assets/aiset-tree.js"), "includeAssets must load the tree editor");
assert(has(aiset.includeAssets(), "aiset.css"), "includeAssets must load the stylesheet");
assert(has(aiset.renderTreeEditor("demo2"), 'data-aiset-tree="demo2"'), "tree fragment must carry the document id");
assert(has(aiset.renderTreeEditor("demo2"), "aiset-tree-toolbar"), "tree fragment must include a toolbar");
assert(has(aiset.renderFullEditor("demo2"), "aiset-tree-editor"), "render_full_editor must delegate to the tree editor");
assert(has(aiset.renderNodeEditor("demo2", "/server"), "data-aiset-node"), "node editor fragment must keep its id");

const host = doc.createElement();
const first = aiset.mountTree(host, { document: "demo2" });
aiset.mountTree(doc.createElement(), { document: "demo3" });

first.stageOperations([{ op: "set", path: "/server/port", value_text: "8384" }], "user");
assert(first.getPendingOperations().length === 1, "one staged operation expected");
assert(first.getPendingOperations()[0].path === "/server/port", "staged path must survive");

// A second instance must not share staged state.
const second = aiset.mountTree(doc.createElement(), { document: "demo3" });
assert(second.getPendingOperations().length === 0, "instances must not share pending operations");

first.stageOperations([{ op: "set", path: "/server/port", value_text: "8384" }], "ai");
assert(first.getPendingOperations().length === 1, "the same operation must replace its staged copy");
first.revert("/server/port");
assert(first.getPendingOperations().length === 0, "revert must drop the staged operation");

first.stageOperations([
  { op: "set", path: "/server/port", value_text: "8384" },
  { op: "add", path: "/server/extra/-", value_text: "1" },
], "ai");
assert(first.getPendingOperations().length === 2, "operations from the agent stage like user operations");

/* view options: expand all, collapse all, optional text of composite nodes */
const find = (node, predicate) => {
  if (predicate(node)) { return node; }
  for (const child of (node.children || [])) {
    const found = find(child, predicate);
    if (found) { return found; }
  }
  return null;
};
const titled = (title) => (node) => node.title === title;

first.ready.then(() => {
assert(typeof first.expandAll === "function" && typeof first.collapseAll === "function",
       "the editor must expose expandAll and collapseAll");
first.expandAll();
assert(first.isExpanded("") === true, "expand all keeps the document root open");
assert(first.isExpanded("/server") === true, "expand all must open every section");
assert(first.isExpanded("/server/hosts") === true, "expand all must reach nested sections");
assert(first.isExpanded("/server/port") === false, "a leaf has nothing to expand");
assert(find(first.treeNode, (node) => node.className === "aiset-tree-source") === null,
       "an object or array shows no text block unless the host asks for one");

first.collapseAll();
assert(first.isExpanded("/server") === false, "collapse all must close every section");
assert(first.isExpanded("") === true, "collapse all keeps the document root open");

const viewButtons = first.toolbar.children.filter((child) => child.className === "aiset-tree-view");
const viewLabels = viewButtons.map((child) => child.textContent);
assert(viewLabels.indexOf("Expand all") >= 0, "the toolbar must offer Expand all");
assert(viewLabels.indexOf("Collapse all") >= 0, "the toolbar must offer Collapse all");
assert(viewButtons.every((child) => child.title), "a view button explains itself on hover");

const removeButton = find(first.treeNode, titled("Remove this item"));
assert(removeButton, "a removable array item must offer a Remove button");
assert(removeButton.children[0] && removeButton.children[0].tagName === "svg",
       "action buttons must carry an icon; the meaning lives in the title");
assert(find(first.treeNode, (node) => node.className === "aiset-tree-source") === null,
       "composite text is hidden until the host asks for it");

assert(first.getValuesAsText() === false, "text of composite nodes is opt-in");
first.setValuesAsText(true);
assert(first.getValuesAsText() === true, "the text option must be readable");
first.expandAll();
const source = find(first.treeNode, (node) => node["aria-label"] === "Stored text of /server/hosts");
assert(source, "composite nodes show their stored text when asked");
assert(source.textContent === '["127.0.0.1"]', "the stored text must be the source fragment");
first.setValuesAsText(false);
first.expandAll();
first.collapseAll();

/* declared but unwritten keys are opt-in */
assert(first.getShowAbsent() === false, "absent nodes are opt-in");
const absentRows = (node) => node.dataset && node.dataset.absent === "true";
assert(find(first.treeNode, absentRows) === null,
       "an unwritten key must not be rendered until the host asks for it");
first.expandAll();
first.setShowAbsent(true);
assert(first.getShowAbsent() === true, "the absent option must be readable");
const absent = find(first.treeNode, (node) => node.dataset && node.dataset.absent === "true" && node.dataset.path === "/server/absent_int");
assert(absent, "the host asked for unwritten keys, so they must appear");
first.setShowAbsent(false);
first.expandAll();

/* the name explains the node, and a default value can be restored */
const level = first._find("/server/level");
const levelRow = first._renderNode(level, false).children[0];
const levelName = levelRow.children.find((child) => child.className === "aiset-tree-name");
assert(levelName.title.indexOf("Backend log level") >= 0, "the tooltip carries the source comments");
assert(levelName.title.indexOf("description: Logging level") >= 0, "the descriptor description is repeated there");
assert(levelName.title.indexOf('default: "info"') >= 0, "the default value is part of the tooltip");
assert(levelName.title.indexOf('one of: ["debug","info","error"]') >= 0, "the tooltip lists the constraints");
assert(levelName.title.indexOf('value: "debug"') >= 0, "the tooltip shows the stored value");
assert(levelName.title.indexOf("apply: reload") >= 0, "the tooltip shows the apply policy");

const levelActions = levelRow.children.find((child) => child.className === "aiset-tree-actions");
const restore = levelActions.children.find((child) => child.title && child.title.indexOf("Restore the default") >= 0);
assert(restore, "a node with a default offers the default button");
assert(restore.children[0].tagName === "span" && restore.children[0].textContent === "\u2302",
       "the default button carries a text caption, so the font rules reach it");
restore.events.click();
const staged = first.getPendingOperations();
const last = staged[staged.length - 1];
assert(last.op === "set" && last.path === "/server/level" && last.value_text === '"info"',
       "clicking it stages the declared default, quoted for a string");
first.revert("/server/level");

first.expandAll();

/* a ${VAR:-default} node edits the name and the fallback apart */
const portNode = first._find("/server/env_port");
const templateInfo = first._templateInfo(portNode);
assert(templateInfo.name === "SERVER_PORT" && templateInfo.fallback === "8383",
       "the snapshot template is split into name and fallback");
const portWrap = first._renderNode(portNode, false).children[0].children
  .find((child) => child.className.indexOf("aiset-tree-value") >= 0);
const nameInput = portWrap.children.find((child) => child.className === "aiset-tree-env");
const fallbackInput = portWrap.children.find((child) => child.type === "number");
assert(nameInput.value === "SERVER_PORT", "the variable name has its own control");
assert(fallbackInput.value === "8383", "the inline fallback uses the control of the declared type");

nameInput.value = "OTHER_PORT";
nameInput.events.change();
fallbackInput.value = "9000";
fallbackInput.events.change();
const templated = first.getPendingOperations().slice(-1)[0];
assert(templated.value_text === "${OTHER_PORT:-9000}",
       "changing either part rewrites the substitution, never a bare value");

nameInput.value = "";
nameInput.events.change();
assert(first.getPendingOperations().slice(-1)[0].value_text === "9000",
       "an empty variable name stores the inline value and drops the substitution");
first.revert("/server/env_port");
first.expandAll();

/* dropping hides the name field, and the row reads as the plain value again */
first.hiddenTemplate = {};
first.expandAll();
const dropRow = first._renderNode(first._find("/server/env_port"), false).children[0].children;
dropRow.find((child) => child.className.indexOf("aiset-tree-value") === 0).children
  .find((child) => child.className.indexOf("env-off") >= 0).events.click();
const afterDrop = first._renderNode(first._find("/server/env_port"), false).children[0].children;
const afterValue = afterDrop.find((child) => child.className.indexOf("aiset-tree-value") === 0);
assert(!afterValue.children.some((child) => child.className === "aiset-tree-env"),
       "the name field is gone after dropping");
assert(afterValue.children[0].value === "8383", "the row shows the inline value");
const afterActions = afterDrop.find((child) => child.className === "aiset-tree-actions").children;
assert(afterActions.some((child) => child.children[0] && child.children[0].textContent === ".env"),
       "and the .env button is back in place of the drop button");
assert(!afterActions.some((child) => child.children[0] && child.children[0].textContent === "\u2298"),
       "the drop button gave way to it");
/* coming back with .env restores the name field and the drop button */
const backWithEnv = afterActions.find((child) => child.children[0] && child.children[0].textContent === ".env");
backWithEnv.events.click();
const restored = first._renderNode(first._find("/server/env_port"), false).children[0].children;
const restoredValue = restored.find((child) => child.className.indexOf("aiset-tree-value") === 0).children;
const restoredName = restoredValue.find((child) => child.className === "aiset-tree-env");
assert(restoredName, "the name field is back");
assert(restoredName.value === "SERVER_PORT", "filled with the variable the file holds");
assert(restoredValue.some((child) => child.className.indexOf("env-off") >= 0),
       "the drop button is back as well");
const restoredActions = restored.find((child) => child.className === "aiset-tree-actions").children;
assert(!restoredActions.some((child) => child.children[0] && child.children[0].textContent === ".env"),
       "and the .env button gave way to it");
delete first.envDraft["/server/env_port"];

/* revert restores the substitution view together with the clean row */
first.hiddenTemplate["/server/env_port"] = true;
first._render();
const revertBack = first._structuralControls(first._find("/server/env_port")).children
  .find((child) => child.className.indexOf("revert") >= 0);
assert(revertBack, "the dropped node is staged, so it offers a revert");
revertBack.events.click();
const afterRevert = first._renderNode(first._find("/server/env_port"), false).children[0].children;
const afterRevertValue = afterRevert.find((child) => child.className.indexOf("aiset-tree-value") === 0).children;
assert(afterRevertValue.some((child) => child.className === "aiset-tree-env"),
       "revert brings the name field back");
assert(afterRevertValue.some((child) => child.className.indexOf("env-off") >= 0),
       "and the drop button with it");
assert(first._pendingFor("/server/env_port") === false, "the row is clean again");
first.revert("/server/env_port");
first.hiddenTemplate = {};
first.expandAll();

/* a dirty node carries its own revert, and it shares no glyph with the default */
first.stageOperations([{ op: "set", path: "/server/port", value_text: "8385" }], "user");
const dirtyActions = first._structuralControls(first._find("/server/port")).children;
const revertButton = dirtyActions.find((child) => child.className.indexOf("revert") >= 0);
assert(revertButton, "a staged node offers a revert of its own");
assert(revertButton.children[0].textContent === "\u21ba", "revert keeps the circular arrow");
const defaultButton = dirtyActions.find((child) => child.className.indexOf("default") >= 0);
assert(defaultButton && defaultButton.children[0].textContent === "\u2302",
       "the default value uses another sign");
revertButton.events.click();
assert(first._pendingFor("/server/port") === false, "revert drops the staged operation");
assert(!first._structuralControls(first._find("/server/port")).children
  .some((child) => child.className.indexOf("revert") >= 0), "and the button goes away with it");
first.stageOperations([{ op: "set", path: "/server/port", value_text: "8384" }], "ai");
first.expandAll();

/* the .env control is a button on a plain value, and never on a substituted one */
const actionsOf = (path) => first._structuralControls(first._find(path)).children;
const envButtonOf = (path) => actionsOf(path).find(
  (child) => child.children[0] && child.children[0].textContent === ".env");
assert(envButtonOf("/server/open_int"), "a plain value offers the .env button");
assert(envButtonOf("/server/open_int").disabled === false, "and it works");
const forbidden = envButtonOf("/server/plain_int");
assert(forbidden, "the button is offered where the descriptor has no env.allowed too");
assert(forbidden.disabled === false, "it still works: the server refuses, it does not silently hide");
assert(forbidden.title.indexOf("server will refuse") >= 0, "the tooltip warns beforehand");
assert(forbidden.className.indexOf("env") >= 0, "the action kind must reach the class, or the pill never applies");
assert(envButtonOf("/server/env_port") === undefined,
       "a node that already uses a substitution has no .env button");
assert(envButtonOf("/server/level") && envButtonOf("/server/level").disabled === false,
       "every editable scalar carries a working .env button");

/* a plain node can be switched into the environment mode */
envButtonOf("/server/open_int").events.click();
assert(first.envDraft["/server/open_int"] === true, "the button opens the substitution mode");
const envWrap = first._renderNode(first._find("/server/open_int"), false).children[0].children
  .find((child) => child.className.indexOf("aiset-tree-value") >= 0);
const envName = envWrap.children.find((child) => child.className === "aiset-tree-env");
const envFallback = envWrap.children.find((child) => child.type === "number");
assert(envName.value === "" && envFallback.value === "7",
       "the environment mode starts from the stored value with an empty name");
envName.value = "OPEN_INT";
envName.events.change();
assert(first.getPendingOperations().slice(-1)[0].value_text === "${OPEN_INT:-7}",
       "naming a variable turns the plain node into a substitution");
first.revert("/server/open_int");
delete first.envDraft["/server/open_int"];
first.expandAll();

/* raw source editing replaces the subtree and is validated before staging */
first.rawMode["/server"] = true;
const raw = first._renderNode(first._find("/server"), false);
assert(raw.children.some((child) => child.className === "aiset-tree-raw"),
       "the raw editor replaces the children of the node");
assert(!raw.children.some((child) => child.className === "aiset-tree-children"),
       "the subtree is hidden while the raw fragment is edited");
delete first.rawMode["/server"];
first.expandAll();

/* the raw button reads as a button, not as a text field */
const rawActions = first._structuralControls(first._find("/server")).children;
const rawButton = rawActions.find((child) => child.children[0] && child.children[0].textContent === "{..}");
assert(rawButton, "the raw editor is opened by a {..} button");
assert(rawButton.children[0].tagName === "span", "the label is text, so it can be bold and centred");
assert(rawButton.title.indexOf("raw source") >= 0, "the button still explains itself on hover");

/* the raw window grows with its text, within the pane and the screen */
const area = first._rawEditor(first._find("/server")).children[1];
first.treeNode.clientWidth = 400;
area.clientWidth = 100; area.scrollWidth = 5000;
area.clientHeight = 300; area.scrollHeight = 50;
first._fitRaw(area);
assert(area.style.width === "352px", "a wide fragment stops at the pane width minus padding");
assert(!area.style.height, "a fragment that fits keeps its height");
area.clientWidth = 400; area.scrollWidth = 300;
first._fitRaw(area);
assert(area.style.width === "352px", "a manual resize is never undone while the text still fits");
area.clientHeight = 100; area.scrollHeight = 5000;
first._fitRaw(area);
assert(area.style.height === "560px", "a tall fragment stops at the screen height minus the chrome");

/* the presence check is a button of the drafting mode, never of a stored
   substitution: there the variable is already visible in the name field */
const envControl = (path) => first._renderNode(first._find(path), false).children[0]
  .children.find((child) => child.className.indexOf("aiset-tree-value") === 0).children
  .filter((child) => child.className === "aiset-tree-env-state");
assert(envControl("/server/env_port").length === 0,
       "a stored ${VAR} shows no presence button: its name is already in the field");
assert(envControl("/server/open_int").length === 0, "a plain value shows none either");
envButtonOf("/server/open_int").events.click();
assert(envControl("/server/open_int").length === 0,
       "an empty name shows nothing at all: no dot, no empty pill");
first.envDraft["/server/open_int"] = { name: "OPEN_INT", fallback: "7" };
const presence = envControl("/server/open_int")[0];
assert(presence.tagName === "button" && presence.disabled === false,
       "a named variable turns the control into a working button");
assert(presence.title.indexOf("OPEN_INT") >= 0, "it names the variable it checks");
delete first.envDraft["/server/open_int"];
first.expandAll();

/* the row looks the same everywhere: a caption pill per action, and no badge
   repeating the variable name the field already shows */
const badgesOf = (path) => first._renderNode(first._find(path), false).children[0].children
  .find((child) => child.className === "aiset-tree-badges").children.map((child) => child.textContent);
assert(badgesOf("/server/env_port").indexOf("env SERVER_PORT") < 0,
       "the green badge must not repeat the variable name");
assert(badgesOf("/server/open_int").indexOf("env") < 0,
       "nor must a bare env badge appear in the draft mode");
const pillsOf = (path) => first._structuralControls(first._find(path)).children
  .filter((child) => child.className.indexOf("pill") >= 0);
assert(pillsOf("/server/env_port").every((child) => child.title),
       "every caption button explains itself on hover");
const readOnly = first._find("/server/level");
readOnly.capabilities.edit = false;
const readOnlyPills = pillsOf("/server/level");
assert(readOnlyPills.every((child) => child.disabled === true),
       "a read-only row still shows the buttons, and all of them explain why they are inert");
readOnly.capabilities.edit = true;
assert(pillsOf("/server/open_int").length === 3,
       "a plain value carries the raw, environment and default buttons");
const restoreWithoutDefault = pillsOf("/server/absent_int").find((child) => child.className.indexOf("default") >= 0);
assert(restoreWithoutDefault && restoreWithoutDefault.disabled === true,
       "the default button is always there and explains itself when there is no default");

/* an explicit null is a checkbox, and it locks the text control */
const nullable = first._find("/server/nullable_text");
assert(nullable, "the fixture must contain the nullable node");
assert(first._isNull(nullable) === true, "a stored null must be recognised");
assert(first._isNull(first._find("/server/port")) === false, "a number is never null");
const nullBox = find(first.treeNode, (node) => node.className === "aiset-tree-null");
assert(nullBox, "a nullable field must offer the null switch");
assert(nullBox.checked === true, "the switch reflects the stored null");
const locked = find(first.treeNode, (node) => node.disabled === true && node.value === "null");
assert(locked, "a stored null cannot be edited as text");
first.expandAll();

/* every leaf carries a coloured type mark in the column where objects show + */
const leafRow = first._renderNode(first._find("/server/level"), false).children[0];
const leafToggle = leafRow.children[0];
assert(leafToggle.className.indexOf("aiset-tree-toggle-type") >= 0,
       "a leaf has no +/-, so the same box carries the type");
const glyph = leafToggle.children[0];
assert(glyph.className.indexOf("aiset-tree-type") === 0, "the mark is the type glyph");
assert(glyph.className.indexOf("string") >= 0, "the mark carries the type for styling");
assert(glyph.title.indexOf("string") >= 0, "and explains itself on hover");

const intToggle = first._renderNode(first._find("/server/port"), false).children[0].children[0];
assert(intToggle.children[0].textContent === "i" && intToggle.children[0].className.indexOf("int") >= 0,
       "an integer is marked with a green i");

const boolToggle = first._renderNode(first._find("/server/enabled"), false).children[0].children[0];
assert(boolToggle.children[0].textContent === "b" && boolToggle.children[0].className.indexOf("bool") >= 0,
       "a boolean is marked with a violet b");

const objectToggle = first._renderNode(first._find("/server"), false).children[0].children[0];
assert(objectToggle.tagName === "button" && (objectToggle.textContent === "+" || objectToggle.textContent === "-"),
       "an object still opens with + and -");
assert(!objectToggle.children.length, "and carries no type mark");
first.setShowAbsent(false);

/* a helper binding opens a modal form; its result stages like any other edit */
const typedActions = first._structuralControls(first._find("/server/typed")).children;
const formButton = typedActions.find((child) => child.className.indexOf("form") >= 0);
assert(formButton, "a node with a helper binding offers the form button");
assert(formButton.disabled === false, "the shipped helper is registered, so it works");
assert(formButton.title.indexOf("node_form") >= 0, "the button names the helper it runs");

const typedNode = first._find("/server/typed");
first.expanded["/server/typed"] = true;
global.document.body = global.document.body || { children: [], appendChild(node) { this.children.push(node); } };
const submitted = first.runHelper(typedNode);
const dialog = global.document.body.children[0];
assert(dialog.className === "aiset-form", "the helper opens a dialog");
assert(dialog.children.some((child) => child.className === "aiset-form-title"), "with a title");
assert(dialog.children.some((child) => child.className === "aiset-form-actions"), "with actions");
const formRow = dialog.children.find((child) => child.className === "aiset-form-row");
assert(formRow.dataset.staged === "1", "the row carries the stored value");
formRow.dataset.staged = "7";
dialog.children.find((child) => child.className === "aiset-form-actions").children[1].events.click();

return submitted.then(() => {
  const staged = first.getPendingOperations().filter((item) => item.path === "/server/typed");
  assert(staged.length === 1 && staged[0].value_text === "{\n  a: 7\n}\n",
         "the form stages the fragment it built");
  first.revert("/server/typed");
  assert(first._pendingFor("/server/typed") === false, "and that result is undoable too");
  return first.applyPending();
});
}).then(() => {
  /* The staged view: the store keeps its own snapshot, the user must see the
   * operations that are already staged (SPEC_service.md 13). */
  const nodeAt = (node, path) => {
    if (node.path === path) { return node; }
    for (const child of (node.children || []).concat(node.items || [])) {
      const found = nodeAt(child, path);
      if (found) { return found; }
    }
    return null;
  };
  const view = () => first._viewTree().node;
  const hosts = () => nodeAt(view(), "/server/hosts");

  first.stageOperations([
    { op: "set", path: "/server/port", value_text: "8384" },
    { op: "remove", path: "/server/hosts/0" },
    { op: "add", path: "/server/newprop", value_text: "5" },
    { op: "move", from: "/server/hosts/1", path: "/server/hosts/0" },
  ], "user");

  assert(nodeAt(view(), "/server/port").value_text === "8384",
         "a staged value is the value the editor shows");
  assert(first._find("/server/port").value_text === "8383",
         "the snapshot itself is never touched by staging");
  assert(nodeAt(view(), "/server/port").staged === undefined,
         "an edited value is not a new entry, so it carries no new mark");

  const removed = nodeAt(view(), "/server/hosts/0");
  assert(removed && removed.pending_delete === true,
         "a staged removal stays in the tree and is marked as deleted");
  first.expandAll();
  const deletedRow = find(first.treeNode, (node) => node.dataset && node.dataset.deleted === "true");
  assert(deletedRow, "the deleted mark reaches the row");
  assert(deletedRow.className.indexOf("is-deleted") >= 0, "and the row is styled as deleted");

  assert(hosts().items.map((item) => item.value_text).join(",") === '"10.0.0.1","127.0.0.1"',
         "a staged move reorders what the user sees");

  const property = nodeAt(view(), "/server/newprop");
  assert(property && property.staged === true, "a staged property of an object appears as well");
  assert(property.value_text === "5", "with the staged value");
  const newRow = find(first.treeNode, (node) => node.dataset && node.dataset.path === "/server/newprop");
  const dirtyRow = find(first.treeNode, (node) => node.dataset && node.dataset.path === "/server/port");
  assert(newRow && newRow.dataset.staged === "true", "a staged addition is marked as new");
  assert(dirtyRow && dirtyRow.dataset.staged === "false",
         "an edited row is only dirty, never marked as a new entry");

  /* the raw editor always shows the stored source, not the staged fragment */
  assert(first._rawEditor(first._find("/server/port")).children[1].value === "8383",
         "raw editing starts from the file, never from a pending change");
  /* A node is dirty while its staged value differs from the file, and nothing
   * more: toggling a value back to what the file says cleans it again. */
  first.revert("/server/enabled");
  first.stageOperations([{ op: "set", path: "/server/enabled", value_text: "false" }], "user");
  assert(first._pendingFor("/server/enabled") === true, "a changed checkbox is dirty");
  assert(nodeAt(view(), "/server/enabled").value_text === "false", "and shows the new value");
  first.stageOperations([{ op: "set", path: "/server/enabled", value_text: "true" }], "user");
  assert(first._pendingFor("/server/enabled") === false,
         "toggling a checkbox back clears dirty instead of doing nothing");
  assert(first.getPendingOperations().filter((item) => item.path === "/server/enabled").length === 0,
         "and leaves no staged operation behind");
  assert(nodeAt(view(), "/server/enabled").value_text === "true", "the stored value is back");

  /* A substitution is compared by its variable and its default, never by its
   * spelling: the quotes belong to the JSON5 literal around it, and ${VAR}
   * says what ${VAR:-} says. */
  const quoted = "/server/env_quoted";
  const stagedFor = (path) => first.getPendingOperations().filter((item) => item.path === path)[0];
  first._stageTemplate(first._find(quoted), "SERVER_MODE", "fast");
  assert(stagedFor(quoted).value_text === '"${SERVER_MODE:-fast}"',
         "a string placeholder keeps its quotes, as the file writes it");
  assert(first._pendingFor(quoted) === true, "a changed default is dirty");
  first._stageTemplate(first._find(quoted), "SERVER_MODE", "safe");
  assert(first._pendingFor(quoted) === false, "and clean again when the default returns");

  first._stageTemplate(first._find(quoted), "OTHER_MODE", "safe");
  assert(first._pendingFor(quoted) === true, "another variable is a different value");
  first.revert(quoted);

  first._stageTemplate(first._find("/server/env_nodefault"), "SERVER_BASE", "");
  assert(first._pendingFor("/server/env_nodefault") === false,
         "${VAR} and ${VAR:-} are the same value");

  first._stageTemplate(first._find("/server/env_bare"), "SERVER_SIZE", "20");
  assert(stagedFor("/server/env_bare").value_text === "${SERVER_SIZE:-20}",
         "a converted field keeps the bare token the file uses");
  first._stageTemplate(first._find("/server/env_bare"), "SERVER_SIZE", "10");
  assert(first._pendingFor("/server/env_bare") === false, "and turns clean when the default returns");

  /* An enum behind a placeholder changes the default, not the literal. */
  const levelRow = first._renderNode(first._find("/server/env_enum"), false);
  const levelSelect = (function find(node) {
    if (String(node.tagName).toUpperCase() === "SELECT") return node;
    for (const child of node.children || []) { const found = find(child); if (found) return found; }
    return null;
  })(levelRow);
  levelSelect.value = JSON.stringify("debug"); levelSelect.events.change();
  assert(stagedFor("/server/env_enum").value_text === '"${SERVER_LEVEL:-debug}"',
         "the enum writes the new default inside the substitution");
  assert(first._pendingFor("/server/env_enum") === true, "and the row is dirty");
  const levelBack = (function find(node) {
    if (String(node.tagName).toUpperCase() === "SELECT") return node;
    for (const child of node.children || []) { const found = find(child); if (found) return found; }
    return null;
  })(first._renderNode(first._find("/server/env_enum"), false));
  levelBack.value = JSON.stringify("info"); levelBack.events.change();
  assert(first._pendingFor("/server/env_enum") === false,
         "choosing the stored level again clears dirty");
  assert(stagedFor("/server/env_enum") === undefined, "and leaves nothing staged for it");

  /* An array that declares the shape of its items offers that shape: the new
   * row gets the control of the item type and the default of that type, and a
   * value typed into it belongs to the add instead of forming a second one. */
  first.stageOperations([{ op: "add", path: "/server/numbers/-", value_text: "0" }], "user");
  const added = nodeAt(view(), "/server/numbers/1");
  assert(added && added.type === "int", "a new array entry knows the type of the items");
  assert(added.value_text === "0", "and starts from the default of that type");
  first.expandAll();
  const newEntry = find(first.treeNode, (node) => node.dataset && node.dataset.path === "/server/numbers/1");
  const numberInput = (function find(node) {
    if (String(node.tagName).toUpperCase() === "INPUT" && node.type === "number") return node;
    for (const child of node.children || []) { const found = find(child); if (found) return found; }
    return null;
  })(newEntry);
  assert(numberInput, "and offers the control of that type, not a free text field");
  assert(added.path === "/server/numbers/1" && added.label === "1",
         "the new entry is addressed by the index it will have");
  assert(first.getPendingOperations().some((item) => item.path === "/server/numbers/-"),
         "while the operation keeps the append token the service expects");
  assert(first._pendingFor("/server/numbers/1") === true,
         "and the row counts as pending through the index");
  first.stageOperations([{ op: "set", path: "/server/numbers/1", value_text: "42" }], "user");
  const numbers = first.getPendingOperations().filter((item) => item.path === "/server/numbers/-");
  assert(numbers.length === 1 && numbers[0].op === "add" && numbers[0].value_text === "42",
         "typing a value into a new entry updates the add itself");
  first.stageOperations([{ op: "set", path: "/server/numbers/1", value_text: "7" }], "user");
  assert(first.getPendingOperations().filter((item) => item.path === "/server/numbers/-")[0].value_text === "7",
         "and follows the control");
  first.revert("/server/numbers/-");
  assert(nodeAt(view(), "/server/numbers/1") === null, "revert removes the entry from the view");

  /* Two appends to one array coexist. Keeping the default 0 is a real entry:
   * the next "+" must not replace it, and each append gets its own index. */
  first.stageOperations([{ op: "add", path: "/server/numbers/-", value_text: "0" }], "user");
  first.stageOperations([{ op: "add", path: "/server/numbers/-", value_text: "0" }], "user");
  assert(first.getPendingOperations().filter((item) => item.path === "/server/numbers/-").length === 2,
         "two appends to the same array must both survive");
  assert(nodeAt(view(), "/server/numbers/1") && nodeAt(view(), "/server/numbers/2"),
         "and appear at two distinct indexes");
  first.stageOperations([{ op: "set", path: "/server/numbers/2", value_text: "5" }], "user");
  assert(first.getPendingOperations().filter((item) => item.path === "/server/numbers/-").length === 2,
         "editing one entry does not collapse the other");
  first.stageOperations([], "user");

  /* A new entry starts empty and shows every declared fixed child regardless
   * of the show-absent setting, so the user can fill in the fields. Only the
   * fields the user actually fills are written, each by its own path. */
  const DIRECTORY = "/server/directory";
  const addEntry = (function find(node) {
    if (String(node.tagName).toUpperCase() === "BUTTON" && node.title === "Add a new entry with its own key") return node;
    for (const child of node.children || []) { const found = find(child); if (found) return found; }
    return null;
  })(first.treeNode);
  assert(addEntry, "an object the user names by itself offers to add an entry");
  addEntry.events.click();
  const keys = (function all(node, out) {
    if (node.className === "aiset-tree-key") out.push(node);
    for (const child of node.children || []) all(child, out);
    return out;
  })(first.treeNode, []);
  const draft = keys[keys.length - 1];
  assert(draft.value === "", "the new row waits for its name");
  assert(draft.disabled === false, "the new key field is editable");
  assert(first.getPendingOperations().some((item) => item.path.indexOf("/server/directory/") === 0) === false,
         "and nothing of its own is staged before it is named");
  draft.value = "beta";
  /* Enter and the following change/blur both fire: the name must be committed
   * once, not stage the same entry twice. */
  draft.events.keydown({ key: "Enter" });
  draft.events.change();
  const created = first.getPendingOperations().filter((item) => item.path === DIRECTORY + "/beta");
  assert(created.length === 1 && created[0].op === "add",
         "naming it stages the addition exactly once");
  assert(created[0].value_text === "{}", "as an empty object: only filled fields are written");

  const beta = nodeAt(view(), DIRECTORY + "/beta");
  assert(beta && beta.children.length === 2, "the new entry knows the whole declared shape");
  assert(beta.children[0].exists === false, "the required child starts unwritten");
  assert(beta.children[1].exists === false, "the optional child starts unwritten too");
  const absentChild = find(first.treeNode, (node) => node.dataset && node.dataset.path === DIRECTORY + "/beta/weight");
  assert(absentChild && absentChild.dataset.absent === "true",
         "both are visible for a new entry even with show-absent off");
  const weightInput = (function find(node) {
    if (String(node.tagName).toUpperCase() === "INPUT" && node.type === "number") return node;
    for (const child of node.children || []) { const found = find(child); if (found) return found; }
    return null;
  })(absentChild);
  assert(weightInput, "and can be filled in, because its parent is created by the same batch");
  weightInput.value = "7";
  weightInput.events.change();
  assert(first.getPendingOperations().some((item) => item.op === "set" &&
         item.path === DIRECTORY + "/beta/weight"), "which writes only that field, by its own path");

  /* A key is a path segment, so a new name is written and the old one dropped. */
  const keyField = (function all(node, out) {
    if (node.className === "aiset-tree-key" && node.value === "alpha") out.push(node);
    for (const child of node.children || []) all(child, out);
    return out;
  })(first.treeNode, [])[0];
  assert(keyField, "an existing entry shows its key where the name stood");
  keyField.value = "gamma";
  keyField.events.change();
  const ops = first.getPendingOperations();
  assert(ops.some((item) => item.op === "remove" && item.path === DIRECTORY + "/alpha"), "the old key is dropped");
  assert(ops.some((item) => item.op === "add" && item.path === DIRECTORY + "/gamma"), "and the new one is written");
  first.revert(DIRECTORY + "/alpha");
  first.revert(DIRECTORY + "/gamma");
  first.revert(DIRECTORY + "/beta");
  first.revert(DIRECTORY + "/beta/weight");
  assert(first.getPendingOperations().every((item) => item.path.indexOf(DIRECTORY) !== 0),
         "reverting the new entries leaves the rest of the batch alone");

  first.stageOperations([{ op: "set", path: "/server/port", value_text: "8385" }], "user");
  first.stageOperations([{ op: "set", path: "/server/port", value_text: "8383" }], "user");
  assert(first._pendingFor("/server/port") === false, "the same rule holds for a typed value");

  /* Editing a value cancels a staged removal of the same node. */
  first.stageOperations([{ op: "remove", path: "/server/hosts/0" }], "user");
  first.stageOperations([{ op: "set", path: "/server/hosts/0", value_text: '"10.0.0.2"' }], "user");
  assert(first.getPendingOperations().some((item) => item.op === "remove" &&
         item.path === "/server/hosts/0") === false,
         "a node being edited is not also being deleted");

  const stagedPaths = first.getPendingOperations().map((item) => item.path);
  stagedPaths.forEach((path) => first.revert(path));
  assert(first.getPendingOperations().length === 0,
         "reverting every staged path clears the view again, whatever the operation");
  assert(hosts().items.length === 2, "and the tree is the snapshot again");
})
.then(() => {
  /* earlier blocks validate other fragments, so the commit is the last pair */
  const apply = calls.filter((call) => call.url.indexOf("/operations") >= 0).slice(-2);
  assert(apply.length === 2, "apply performs validate and commit requests");
  assert(apply[0].method === "POST", "operations are POST requests");
  assert(apply[0].url.indexOf("/operations/validate") >= 0, "validation happens before the commit");
  assert(apply[1].url.indexOf("/operations") >= 0, "the commit uses the operations route");
  assert(JSON.parse(apply[0].body).operations.length === 2, "the whole batch is validated together");
  console.log("UI smoke OK");
}).catch((error) => { console.error(error.message); process.exit(1); });
"""


@pytest.fixture(scope="module")
def node() -> str:
    path = shutil.which("node")
    if path is None:
        pytest.skip("node is not available")
    return path


def test_assets_have_valid_syntax(node):
    for name in JS_FILES:
        result = subprocess.run([node, "--check", str(ASSETS / name)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_tree_editor_public_api(node, tmp_path):
    script = tmp_path / "smoke.js"
    script.write_text(SMOKE, encoding="utf-8")
    result = subprocess.run(
        [node, str(script), str(ASSETS / "aiset.js"), str(ASSETS / "aiset-tree.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "UI smoke OK" in result.stdout


def test_include_assets_lists_every_shipped_asset():
    from aiset.httpd import CONTENT_TYPES

    shipped = sorted(path.name for path in ASSETS.iterdir() if path.suffix in (".js", ".css"))
    assert shipped == ["aiset-tree.js", "aiset.css", "aiset.js"]
    assert set(CONTENT_TYPES) >= {".js", ".css"}
    source = (ASSETS / "aiset.js").read_text(encoding="utf-8")
    assert "/assets/aiset.js" in source and "/assets/aiset.css" in source


def test_python_side_exposes_the_same_names():
    from aiset.assets import ASSET_NAMES, include_assets, render_full_editor, render_node_editor, render_tree_editor

    assert ASSET_NAMES == ("aiset.css", "aiset.js", "aiset-tree.js")
    assert "/assets/aiset-tree.js" in include_assets()
    assert 'data-aiset-tree="demo2"' in render_tree_editor("demo2")
    assert 'data-aiset-node="demo2"' in render_node_editor("demo2", "/server")
    assert "aiset-tree-editor" in render_full_editor("demo2")


def test_package_ships_the_assets(tmp_path):
    import aiset.assets as assets

    assert Path(assets.ASSETS_DIR).is_dir()
    for name in assets.ASSET_NAMES:
        assert (Path(assets.ASSETS_DIR) / name).is_file()


def test_tree_payload_is_json_serializable(service, principal):
    from aiset.service import Principal

    tree = service.tree("demo", principal=Principal.demo())
    assert json.loads(json.dumps(tree))["node"]["path"] == ""
