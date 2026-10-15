"""The demo2 page must work with the shipped scripts in the shipped order.

Regression test for a page that loads but stays empty: the host script must
survive being loaded from <head> (before the body elements exist), mount the
tree editor, and fetch the host status.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

DEMO2 = Path(__file__).resolve().parents[1]
ROOT = DEMO2.parent

SMOKE = r"""
const fs = require("fs");
const listeners = {};

function element(tag) {
  return {
    tagName: tag, style: {}, dataset: {}, children: [], value: "", textContent: "",
    innerHTML: "", disabled: false,
    setAttribute(key, value) { this[key] = value; },
    getAttribute(key) { return this[key] || null; },
    remove() {}, focus() {}, insertBefore(child) { return child; },
    addEventListener(event, handler) { (this.events = this.events || {})[event] = handler; },
    appendChild(child) { this.children.push(child); return child; },
    cloneNode() { return element(tag); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; }, classList: { add() {}, remove() {} },
    dispatchEvent() { return true; }, requestSubmit() {},
  };
}

const byId = {
  "chat-history": element("div"), "chat-form": element("form"),
  "chat-text": element("textarea"), "chat-send": element("button"),
  "chat-cancel": element("button"), "chat-clear": element("button"),
  "settings-tree": element("div"), "app-status": element("div"), "chat-model": element("div"),
  "tree-values-text": element("input"), "tree-show-absent": element("input"),
};

const fetches = [];
global.window = {
  addEventListener: (event, handler) => { listeners[event] = handler; },
  location: { reload() {} }, crypto: { getRandomValues() {} },
  setInterval: () => 0, clearInterval: () => {},
};
global.document = {
  createElement: (tag) => element(tag),
  createElementNS: (ns, tag) => element(tag),
  createTextNode: (text) => ({ textContent: text }),
  getElementById: (id) => byId[id] || null,
  querySelector: () => element("div"),
  querySelectorAll: () => [],
  addEventListener: (event, handler) => { listeners[event] = handler; },
  readyState: "loading",              /* the script is still in <head> */
};
global.fetch = (url) => {
  fetches.push(url);
  const payload = url.indexOf("/tree") >= 0
    ? { ok: true, revision: "sha256:a", descriptor_revision: "sha256:b", exists: true,
        invalid_on_disk: false, path: "",
        node: { path: "", type: "object", exists: true, access_denied: false, kind: "object",
                origin: { kind: "file" }, apply: "restart", value_text: "{}",
                field: { type: "object" },
                capabilities: { edit: true, add: false, remove: false, reorder: false,
                                add_child: true, remove_child: false },
                children: [], items: [] } }
    : { ok: true, revision: "sha256:a", descriptor_revision: "sha256:b", reloads: 0,
        applied: { state: "applied" }, ai: { enabled: true, model: "fake-model" } };
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
};
global.confirm = () => true;
global.Event = function () {};

const assert = (condition, message) => { if (!condition) { throw new Error(message); } };

eval(fs.readFileSync(process.argv[2], "utf8"));      /* aiset.js       */
eval(fs.readFileSync(process.argv[3], "utf8"));      /* aiset-tree.js  */
let mounted = null;
const realMount = window.aiset.mountTree;
window.aiset.mountTree = (target, options) => {
  mounted = options;
  window.aiset.__editor = realMount(target, options);
  return window.aiset.__editor;
};
eval(fs.readFileSync(process.argv[4], "utf8"));      /* demo2 app.js   */

assert(typeof listeners.DOMContentLoaded === "function",
       "the host script must wait for the document, not touch the DOM while parsing");

listeners.DOMContentLoaded();

setTimeout(() => {
  assert(mounted, "the tree editor was not mounted");
  assert(mounted.document === "demo2", "the editor must target the demo2 document");
  assert(mounted.lifecycle && mounted.lifecycle[0].id === "restart",
         "the host must contribute its Restart action");
  assert(fetches.some((url) => url.indexOf("/api/settings/tree") === 0),
         "the editor must load the tree snapshot");
  assert(fetches.indexOf("/api/demo2/status") >= 0, "the page must ask the host for status");
  assert(byId["app-status"].textContent.indexOf("sha256:a") >= 0,
         "the status line must show the revision");
  assert(byId["chat-model"].textContent === "model fake-model",
         "the chat header must show the configured model");

  /* the checkbox in the pane head drives the reusable editor option */
  assert(byId["tree-values-text"].checked === false, "composite text is off by default");
  byId["tree-values-text"].checked = true;
  byId["tree-values-text"].events.change();
  assert(window.aiset.__editor.getValuesAsText() === true,
         "the checkbox must switch the editor to the text representation");

  assert(byId["tree-show-absent"].checked === false, "absent nodes are off by default");
  byId["tree-show-absent"].checked = true;
  byId["tree-show-absent"].events.change();
  assert(window.aiset.__editor.getShowAbsent() === true,
         "the checkbox must switch the editor to the absent representation");
  console.log("page smoke OK");
}, 30);
"""


@pytest.fixture(scope="module")
def node() -> str:
    path = shutil.which("node")
    if path is None:
        pytest.skip("node is not available")
    return path


def test_page_boots_with_the_shipped_scripts(node, tmp_path):
    script = tmp_path / "page.js"
    script.write_text(SMOKE, encoding="utf-8")
    result = subprocess.run(
        [
            node,
            str(script),
            str(ROOT / "src" / "aiset" / "assets" / "aiset.js"),
            str(ROOT / "src" / "aiset" / "assets" / "aiset-tree.js"),
            str(DEMO2 / "frontend" / "app.js"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "page smoke OK" in result.stdout


def test_page_loads_the_shipped_assets_in_order(node):
    html = (DEMO2 / "frontend" / "index.html").read_text(encoding="utf-8")
    order = [html.index("/assets/aiset.css"), html.index("/assets/aiset.js"),
             html.index("/assets/aiset-tree.js"), html.index("/app.js")]
    assert order == sorted(order), "assets must load in dependency order"
    for src in ("/assets/aiset.css", "/assets/aiset.js", "/assets/aiset-tree.js", "/app.js"):
        assert src in html
    assert "/styles.css" in html
    assert 'id="settings-tree"' in html and 'id="chat-history"' in html
    assert 'id="tree-values-text"' in html, "the pane must offer the values-as-text switch"
    assert 'id="tree-show-absent"' in html, "the pane must offer the show-absent switch"


def test_stylesheet_themes_every_value_control():
    """Number inputs were never themed, so int fields stayed white."""
    css = (DEMO2 / "frontend" / "styles.css").read_text(encoding="utf-8")
    for selector in ('input[type="text"]', 'input[type="number"]', 'textarea', 'select'):
        assert selector in css, f"{selector} must be part of the demo2 palette"
    assert ".aiset-tree-action" in css, "square icon buttons need a size"
    assert ".aiset-tree-source" in css, "the text representation needs a block style"


def test_descriptor_declares_visible_placeholders():
    """A placeholder is only useful where the stored value is empty or absent."""
    descriptor = (DEMO2 / "descriptor.json5").read_text(encoding="utf-8")
    from aiset.descriptor import compile_descriptor

    compiled = compile_descriptor(descriptor)
    placeholders = {
        "/server/host": "0.0.0.0",
        "/fixtures/scalars/empty_text": "an empty string is stored here; type to replace it",
        "/fixtures/scalars/multiline": "first line\nsecond line",
        "/fixtures/optionality/absent_field": "not written yet — type to add the key",
        "/fixtures/optionality/defaulted_field": "default-value",
    }
    for path, expected in placeholders.items():
        node = compiled.root
        for token in path.strip("/").split("/"):
            node = node.children[token]
        assert (node.ui or {}).get("placeholder") == expected, path


def test_page_scripts_are_valid(node):
    for name in ("app.js",):
        result = subprocess.run([node, "--check", str(DEMO2 / "frontend" / name)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
