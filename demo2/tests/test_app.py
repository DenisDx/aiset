"""demo2 host tests: startup, seeding, routes, lifecycle, and the assistant.

The assistant is exercised against a local fake OpenAI-compatible provider, so
no external model and no network access are required (proposal section 12.1).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO2 = ROOT / "demo2"
sys.path.insert(0, str(DEMO2))
sys.path.insert(0, str(ROOT / "src"))

from aiset.service import Principal  # noqa: E402
from app import Demo2Error, Host, build, host_app, parse_overrides, resolve_listen  # noqa: E402
from env import load_env_file, parse_env  # noqa: E402


# -- helpers ---------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    for name in ("config.json5.example", "descriptor.json5", ".env.example"):
        shutil.copy(DEMO2 / name, tmp_path / name)
    # The component folder ships with the host: its descriptor owns the shared
    # `typedef`s and its file is the override update.
    shutil.copytree(DEMO2 / "conf2", tmp_path / "conf2")
    return tmp_path


def seed(workspace: Path) -> tuple[Path, Path, Path]:
    return (
        workspace / "config.json5",
        workspace / "descriptor.json5",
        workspace / ".env",
    )


@pytest.fixture
def started(workspace: Path):
    """A seeded workspace with a ready service, host, and WSGI app."""
    config, descriptor, env = seed(workspace)
    shutil.copy(DEMO2 / "config.json5.example", config)
    shutil.copy(DEMO2 / ".env.example", env)
    service, settings, effective = build(config, descriptor, env, {})
    host = Host(service, settings, None)
    service.on_application(host.on_application)
    return host, config, descriptor, env


class Client:
    """Minimal WSGI client for the host application."""

    def __init__(self, host: Host, frontend: Path = DEMO2 / "frontend") -> None:
        self.app = host_app(host, frontend)
        self.host = host

    def request(self, method: str, path: str, body: dict | None = None, headers: dict | None = None):
        from io import BytesIO

        raw = json.dumps(body).encode() if body is not None else b""
        route, _, query = path.partition("?")
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": route,
            "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(raw)),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": BytesIO(raw),
        }
        environ.update({f"HTTP_{key.upper().replace('-', '_')}": value for key, value in (headers or {}).items()})
        captured: dict = {}

        def start_response(status, response_headers):
            captured["status"] = int(status.split()[0])
            captured["headers"] = response_headers

        payload = b"".join(self.app(environ, start_response))
        return captured["status"], json.loads(payload) if payload[:1] in (b"{", b"[") else payload

    def get(self, path, headers=None):
        return self.request("GET", path, headers=headers)

    def post(self, path, body=None, headers=None):
        return self.request("POST", path, body or {}, headers=headers)


# -- environment -----------------------------------------------------------


def test_env_parser_ignores_comments_and_quotes():
    parsed = parse_env('# comment\nDEMO2_PORT=8383\nDEMO2_HOST="127.0.0.1"\nexport A=b\nbroken\n')
    assert parsed == {"DEMO2_PORT": "8383", "DEMO2_HOST": "127.0.0.1", "A": "b"}


def test_env_file_is_missing_safe(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == {}


def test_env_is_data_and_not_exported(tmp_path, workspace):
    config, descriptor, env = seed(workspace)
    shutil.copy(DEMO2 / "config.json5.example", config)
    (workspace / ".env").write_text("DEMO2_PORT=8390\nDEMO2_AI_MODEL=local-model\n", encoding="utf-8")
    service, _, effective = build(config, descriptor, env, {})
    assert effective["server"]["port"] == 8390
    assert effective["ai"]["model"] == "local-model"
    assert "DEMO2_PORT" not in __import__("os").environ


# -- startup ---------------------------------------------------------------


def test_default_port_and_conversion(workspace):
    config, descriptor, env = seed(workspace)
    shutil.copy(DEMO2 / "config.json5.example", config)
    (workspace / ".env").write_text("DEMO2_PORT=8383\nDEMO2_HOST=0.0.0.0\n", encoding="utf-8")
    _, _, effective = build(config, descriptor, env, {})
    host, port = resolve_listen(effective)
    assert (host, port) == ("0.0.0.0", 8383)
    assert isinstance(effective["server"]["port"], int)


def test_startup_override_wins_and_is_not_persisted(workspace):
    config, descriptor, env = seed(workspace)
    shutil.copy(DEMO2 / "config.json5.example", config)
    (workspace / ".env").write_text("DEMO2_PORT=8383\n", encoding="utf-8")
    before = config.read_text(encoding="utf-8")
    _, _, effective = build(config, descriptor, env, {"server": {"port": 8399}})
    assert effective["server"]["port"] == 8399
    assert config.read_text(encoding="utf-8") == before


def test_overrides_use_the_demo_convention():
    assert parse_overrides(["--demo2.server.port:8384", '--server.host:"127.0.0.1"']) == {
        "demo2": {"server": {"port": 8384}},
        "server": {"host": "127.0.0.1"},
    }


def test_invalid_configuration_is_reported(workspace):
    config, descriptor, env = seed(workspace)
    config.write_text("{ server: { port: -1 } }\n", encoding="utf-8")
    shutil.copy(DEMO2 / ".env.example", env)
    with pytest.raises(Demo2Error):
        build(config, descriptor, env, {})


def test_ai_model_is_required(workspace):
    from app import build_agent

    with pytest.raises(Demo2Error):
        build_agent({"ai": {"enabled": True, "model": "  ", "provider": {"base_url": "http://x/v1"}}})


def test_ai_disabled_returns_no_agent(workspace):
    from app import build_agent

    assert build_agent({"ai": {"enabled": False}}) is None


def component_templates() -> dict:
    """Templates the component descriptor owns (SPEC.md 4.6.10)."""
    from aiset.descriptor import _collect_typedefs, parse_descriptor

    source = (DEMO2 / "conf2" / "descriptor.json5").read_text(encoding="utf-8")
    return _collect_typedefs(parse_descriptor(source))


def test_descriptor_is_strict_clean():
    from aiset.descriptor import validate_descriptor

    diagnostic = validate_descriptor(
        (DEMO2 / "descriptor.json5").read_text(encoding="utf-8"),
        mode="strict",
        known_templates=component_templates(),
    )
    assert diagnostic.valid, [issue.to_dict() for issue in diagnostic.issues]


def test_example_configuration_validates():
    from aiset.service import Service

    service = Service()
    service.register(
        "demo2",
        DEMO2 / "config.json5.example",
        (DEMO2 / "descriptor.json5").read_text(encoding="utf-8"),
        typedef_sources=[(DEMO2 / "conf2" / "descriptor.json5").read_text(encoding="utf-8")],
    )
    loaded = service.load("demo2", principal=Principal.demo())
    assert loaded.invalid_on_disk is False, [i.to_dict() for i in loaded.issues]


# -- routes and lifecycle --------------------------------------------------


def test_health_and_status(started):
    client = Client(started[0])
    status, payload = client.get("/api/demo2/health")
    assert status == 200 and payload["app"] == "demo2"
    status, payload = client.get("/api/demo2/status")
    assert payload["revision"].startswith("sha256:")
    assert payload["ai"]["enabled"] is False


def test_reload_route_adopts_external_changes(started):
    host, config, _, _ = started
    client = Client(host)
    config.write_text(
        config.read_text(encoding="utf-8").replace('text: "hello demo2"', 'text: "changed outside"'),
        encoding="utf-8",
    )
    status, payload = client.post("/api/demo2/reload")
    assert status == 200 and payload["ok"] is True and payload["reloads"] == 1
    assert host.service.get("demo2", "/fixtures/scalars/text", principal=Principal.demo()).value_text == (
        '"changed outside"'
    )


def test_restart_route_acknowledges_before_re_executing(started):
    import app as demo2_app

    host = started[0]
    calls: list[bool] = []
    app = host_app(host, DEMO2 / "frontend", restart_hook=lambda: calls.append(True))
    from io import BytesIO

    environ = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/demo2/restart", "QUERY_STRING": "",
               "CONTENT_LENGTH": "0", "wsgi.input": BytesIO(b"")}
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])

    payload = json.loads(b"".join(app(environ, start_response)))
    assert captured["status"] == 200 and payload["restarting"] is True
    # The acknowledgment is already delivered; the re-execution follows it.
    assert calls == []
    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    assert calls == [True]
    assert demo2_app.RESTART_DELAY > 0


def test_unknown_host_route(started):
    status, payload = Client(started[0]).post("/api/demo2/nope")
    assert status == 404 and payload["error"]["code"] == "NOT_FOUND"


def test_chat_without_agent_is_explicit(started):
    status, payload = Client(started[0]).post("/api/demo2/chat", {"message": "hi"})
    assert status == 503 and payload["error"]["code"] == "UNSUPPORTED_CAPABILITY"


def test_aiset_routes_are_mounted(started):
    client = Client(started[0])
    status, payload = client.get("/api/settings/value?document=demo2&path=/server/port&view=source")
    assert status == 200 and payload["value_text"] == "${DEMO2_PORT:-8383}"
    status, tree = client.get("/api/settings/tree?document=demo2&path=/fixtures/constraints")
    assert status == 200 and tree["node"]["field"]["type"] == "object"


def test_frontend_and_assets_are_served(started):
    from io import BytesIO

    host = started[0]
    app = host_app(host, DEMO2 / "frontend")
    for path, needle in (("/", b"aiset settings host"), ("/app.js", b"mountTree"),
                         ("/styles.css", b"--accent"), ("/assets/aiset-tree.js", b"renderTreeEditor"),
                         ("/assets/aiset-host-theme.css", b"--aiset-accent")):
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "", "wsgi.input": BytesIO(b"")}
        captured: dict = {}

        def start_response(status, headers):
            captured["status"] = int(status.split()[0])

        body = b"".join(app(environ, start_response))
        assert captured["status"] == 200, path
        assert needle in body, path


def test_application_callback_reports_policy(started):
    host, config, descriptor, env = started
    client = Client(host)
    loaded = host.service.load("demo2", principal=Principal.demo())
    status, payload = client.post(
        "/api/settings/value",
        {
            "document": "demo2",
            "path": "/fixtures/apply_policy/restart_field",
            "value_text": '"changed"',
            "expected_revision": loaded.revision,
            "expected_descriptor_revision": host.service.documents["demo2"].descriptor.revision,
        },
    )
    assert status == 200 and payload["application"]["state"] == "restart_required"
    status, status_payload = client.get("/api/demo2/status")
    assert status_payload["applied"]["state"] == "restart_required"


def test_staged_batch_through_the_tree_api(started):
    host, config, descriptor, _ = started
    client = Client(host)
    loaded = host.service.load("demo2", principal=Principal.demo())
    body = {
        "document": "demo2",
        "operations": [
            {"op": "set", "path": "/fixtures/arrays/strings/0", "value_text": '"gamma"'},
            {"op": "add", "path": "/fixtures/arrays/strings/-", "value_text": '"delta"'},
            {"op": "remove", "path": "/fixtures/arrays/strings/1"},
        ],
        "expected_revision": loaded.revision,
        "expected_descriptor_revision": host.service.documents["demo2"].descriptor.revision,
    }
    status, result = client.post("/api/settings/operations", body)
    assert status == 200 and result["stored"] is True
    text = config.read_text(encoding="utf-8")
    assert 'strings: ["gamma", "delta"]' in text or '"gamma"' in text


# -- launcher --------------------------------------------------------------


def run_launcher(workspace: Path, args: list[str] | None = None) -> subprocess.CompletedProcess:
    launcher = ROOT / "run_demo2.sh"
    return subprocess.run(
        [str(launcher), *(args or [])],
        capture_output=True,
        text=True,
        timeout=30,
        env={"DEMO2_STATE_DIR": str(workspace), "PATH": "/usr/bin:/bin", "HOME": str(workspace)},
    )


def test_launcher_seeds_missing_files_without_overwrite(workspace):
    (workspace / "config.json5.example").write_text(
        (DEMO2 / "config.json5.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = run_launcher(workspace, ["--demo2.server.port:1"])
    assert "seeded" in result.stdout or result.returncode != 0
    assert (workspace / "config.json5").exists()
    assert (workspace / ".env").exists()
    # A second run must not overwrite the local files.
    (workspace / "config.json5").write_text("{ edited: true }\n", encoding="utf-8")
    (workspace / ".env").write_text("DEMO2_PORT=9999\n", encoding="utf-8")
    run_launcher(workspace, ["--demo2.server.port:1"])
    assert (workspace / "config.json5").read_text(encoding="utf-8") == "{ edited: true }\n"
    assert (workspace / ".env").read_text(encoding="utf-8") == "DEMO2_PORT=9999\n"


def test_launcher_requires_the_local_interpreter(workspace):
    launcher = ROOT / "run_demo2.sh"
    script = launcher.read_text(encoding="utf-8")
    assert ".venv/bin/python" in script
    assert "python3 " not in script.replace("python3 -m venv", "")
    assert script.startswith("#!/bin/sh") and "set -eu" in script


def test_component_document_merges_with_the_base_in_front(started):
    """SPEC_.md correction 5: the base wins, the update only fills the gaps."""
    from app import merged_override

    host, config, _descriptor, _env = started
    result = merged_override(host)
    assert result["ok"] is True
    assert result["document"] == "conf2" and result["mount"] == "includes.conf2"
    assert result["prefer"] == "base"

    merged = result["merged"]
    assert merged["value1"] == "base value", "a scalar present in both keeps the base"
    assert merged["value2"] == [1, 2], "an array present in both keeps the base"
    assert merged["value3"] is False, "a flag present in both keeps the base"
    assert merged["value4"] == "new value", "a field only in the update is taken"
    assert merged["value5"] == "only in the base", "a field only in the base is kept"
    assert merged["typedefvalue1"]["subValue4"] == {
        "innerSubValue1": "inner value",       # only in the update, merged in
        "innerSubValue2": "only in the base",   # only in the base, kept
    }
    assert set(result["changed"]) == {
        "/value4",
        "/typedefvalue1/subValue4/innerSubValue1",
        "/typedefvalue2/subValue4/innerSubValue1",
        # the typed structures: one nested value and one key only in the update
        "/testobjobj/shared/subValue4/innerSubValue1",
        "/testobjobj/extra",
    }
    assert "/value1" in result["from_update"], "the update would have won under the old rule"
    assert "includes" in config.read_text(encoding="utf-8"), "the base file is not overwritten"


def test_editing_the_merged_section_always_writes_the_base(started):
    """A value shown from the update is still edited in the base document."""
    host, config, _descriptor, _env = started
    component = config.parent / "conf2" / "config.json5"
    before = component.read_text(encoding="utf-8")
    service = host.service
    loaded = service.load("demo2", principal=Principal.demo())
    result = service.set(
        "demo2", "/includes/conf2/value4", '"edited in the base"',
        expected_revision=loaded.revision,
        expected_descriptor_revision=loaded.descriptor_revision,
        principal=Principal.demo(),
    )
    assert result.stored is True
    assert '"edited in the base"' in config.read_text(encoding="utf-8"), "the base holds the change"
    assert component.read_text(encoding="utf-8") == before, "the component document is untouched"


def test_main_descriptor_uses_the_shared_typedefs(started):
    """The main descriptor compiles only with the component descriptor loaded."""
    host, _config, _descriptor, _env = started
    descriptor = host.service.documents["demo2"].descriptor
    node = descriptor.root.children["includes"].children["conf2"].children["typedefvalue1"]
    assert node.type == "object", "the template is expanded into a real object"
    assert set(node.children) == {"subValue1", "subValue2", "subValue3", "subValue4", "subValue5"}
    assert node.helper["tag"] == "node_form", "the helper binding travels with the template"


def test_the_shared_template_types_an_array_and_an_object(started):
    """The template is used as the type of array items and of object values."""
    host, _config, _descriptor, _env = started
    descriptor = host.service.documents["demo2"].descriptor
    conf2 = descriptor.root.children["includes"].children["conf2"]

    items = conf2.children["testobjarray"]
    assert items.type == "array"
    assert items.item_node is not None, "the array declares the shape of its items"
    assert items.item_node.type == "object", "an item resolves to the template"
    assert set(items.item_node.children) == {"subValue1", "subValue2", "subValue3", "subValue4", "subValue5"}
    assert items.item_node.helper["tag"] == "node_form", "an item opens the form of the template"

    values = conf2.children["testobjobj"]
    assert values.type == "object"
    assert values.additional_children is not None, "every key holds that template"
    assert values.additional_children.type == "object"
    assert set(values.additional_children.children) == set(items.item_node.children)


def test_the_typed_structures_validate_and_reach_the_tree(started):
    from app import merged_override

    host, _config, _descriptor, _env = started
    service = host.service
    loaded = service.load("demo2", principal=Principal.demo())
    result = service.apply_operations(
        "demo2",
        [
            {"op": "set", "path": "/includes/conf2/testobjobj/shared/subValue2", "value_text": "22"},
            {"op": "add", "path": "/includes/conf2/testobjobj/fresh",
             "value_text": "{\n  subValue1: \"a new key\",\n  subValue2: 5\n}\n"},
        ],
        expected_revision=loaded.revision,
        expected_descriptor_revision=loaded.descriptor_revision,
        principal=Principal.demo(),
        dry_run=True,
    )
    assert result.dry_run is True, "nothing is written by a dry run"
    assert result.valid is True, [issue.message for issue in result.issues]

    tree = service.tree("demo2", "/includes/conf2/testobjarray/0", principal=Principal.demo())
    assert tree["node"]["type"] == "object"
    assert [child["path"].rsplit("/", 1)[-1] for child in tree["node"]["children"]][:2] == ["subValue1", "subValue2"]
    assert tree["node"]["field"]["helper"]["tag"] == "node_form"
    assert tree["node"]["children"][0]["field"]["ui"]["label"] == "Text", "the form fields are described"

    merged = merged_override(host)["merged"]
    assert [item["subValue1"] for item in merged["testobjarray"]] == ["base item one", "base item two"], (
        "an array present in both keeps the base, element types included"
    )
    assert merged["testobjobj"]["shared"]["subValue1"] == "base shared", "the base keeps its own values"
    assert merged["testobjobj"]["shared"]["subValue4"]["innerSubValue1"] == "override inner", (
        "a value only in the update is taken"
    )
    assert merged["testobjobj"]["extra"]["subValue1"] == "only the override has this key", (
        "a key only in the update is taken as a whole"
    )


def test_a_new_typed_entry_is_created_with_its_required_fields(started):
    """Adding an entry of testobjarray/testobjobj needs only the required child."""
    host, _config, _descriptor, _env = started
    service = host.service
    loaded = service.load("demo2", principal=Principal.demo())

    def check(operations):
        return service.apply_operations(
            "demo2", operations,
            expected_revision=loaded.revision,
            expected_descriptor_revision=loaded.descriptor_revision,
            principal=Principal.demo(), dry_run=True,
        )

    # What the editor stages for "+" on an array of templated items: an empty
    # object, then only the fields the user actually filled in.
    result = check([
        {"op": "add", "path": "/includes/conf2/testobjarray/-", "value_text": "{}"},
        {"op": "set", "path": "/includes/conf2/testobjarray/2/subValue1", "value_text": "\"typed\""},
        {"op": "set", "path": "/includes/conf2/testobjarray/2/subValue2", "value_text": "33"},
    ])
    assert result.valid is True, [issue.message for issue in result.issues]

    # And for a new key of an object whose values are templated objects.
    result = check([
        {"op": "add", "path": "/includes/conf2/testobjobj/second", "value_text": "{}"},
        {"op": "set", "path": "/includes/conf2/testobjobj/second/subValue1", "value_text": "\"typed\""},
        {"op": "set", "path": "/includes/conf2/testobjobj/second/subValue4", "value_text": "{}"},
        {"op": "set", "path": "/includes/conf2/testobjobj/second/subValue4/innerSubValue1",
         "value_text": "\"inner\""},
        {"op": "set", "path": "/includes/conf2/testobjobj/second/subValue5", "value_text": "[]"},
        {"op": "add", "path": "/includes/conf2/testobjobj/second/subValue5/-", "value_text": "\"item\""},
    ])
    assert result.valid is True, [issue.message for issue in result.issues]

    # A name is a path segment, so renaming drops the old key and writes the new.
    result = check([
        {"op": "remove", "path": "/includes/conf2/testobjobj/shared"},
        {"op": "add", "path": "/includes/conf2/testobjobj/renamed",
         "value_text": "{\n  subValue1: \"renamed\"\n}"},
    ])
    assert result.valid is True, [issue.message for issue in result.issues]


def test_only_required_children_of_the_templates_are_written(started):
    """An entry starts as its required fields; the rest stays unwritten."""
    host, _config, _descriptor, _env = started
    descriptor = host.service.documents["demo2"].descriptor
    conf2 = descriptor.root.children["includes"].children["conf2"]
    shape = conf2.children["testobjobj"].additional_children
    required = [name for name, node in shape.children.items() if node.required]
    optional = [name for name, node in shape.children.items() if not node.required]
    assert required == ["subValue1"], "one identity field is required, as the demo declares it"
    assert optional == ["subValue2", "subValue3", "subValue4", "subValue5"]
    item = conf2.children["testobjarray"].item_node
    assert item.children["subValue1"].required is True, "every item of the array needs the same field"


def test_status_reports_both_documents_and_the_override(started):
    from app import merged_override

    host, _config, _descriptor, _env = started
    payload = merged_override(host)
    assert payload["ok"] is True
    assert sorted(host.service.documents) == ["conf2", "demo2"]


def test_launcher_serves_and_reports_bind_failure(workspace):
    """The documented entry point serves the app and fails clearly on a busy port."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = dict(**__import__("os").environ)
    env["DEMO2_STATE_DIR"] = str(workspace)
    env["DEMO2_HOST"] = "127.0.0.1"
    env["DEMO2_PORT"] = str(port)
    process = subprocess.Popen(
        [str(ROOT / "run_demo2.sh")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, env=env,
    )
    try:
        deadline = time.time() + 30
        ready = False
        while time.time() < deadline and not ready:
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/demo2/health", timeout=1) as response:
                    ready = json.loads(response.read())["ok"] is True
            except Exception:  # noqa: BLE001 - the server may still be starting
                time.sleep(0.2)
        assert ready, "demo2 did not answer on the configured port"
        assert (workspace / "config.json5").exists()

        # A second instance on the same port must fail clearly.
        conflict = subprocess.run(
            [str(ROOT / "run_demo2.sh")], capture_output=True, text=True, timeout=30,
            env={**env, "DEMO2_PORT": str(port)},
        )
        assert conflict.returncode != 0
        assert "does not choose another port" in (conflict.stdout + conflict.stderr)
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()


# -- fake provider ---------------------------------------------------------


class FakeProvider:
    """A local OpenAI-compatible provider driven by scripted replies."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.status = 200
        self.body: str = "{}"

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 - stdlib naming
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self.server.provider.requests.append(payload)
                reply = (
                    self.server.provider.replies.pop(0)
                    if self.server.provider.replies
                    else {"choices": [{"message": {"role": "assistant", "content": "done"}}]}
                )
                provider = self.server.provider
                body = (provider.body.encode("utf-8") if provider.body != "{}"
                        else json.dumps(reply).encode("utf-8"))
                code = provider.status
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.provider = self
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def provider():
    created: list[FakeProvider] = []

    def factory(replies: list[dict]) -> FakeProvider:
        item = FakeProvider(replies)
        created.append(item)
        return item

    yield factory
    for item in created:
        item.close()


def tool_call(name: str, arguments: dict, call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def agent_with(provider: FakeProvider, host, **kwargs):
    from agent import ConfigurationAgent

    return ConfigurationAgent(
        service=host.service,
        base_url=provider.base_url,
        api_key="test-key",
        model="test-model",
        timeout_seconds=5.0,
        **kwargs,
    )


def test_agent_reads_configuration(provider, started):
    host = started[0]
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_get", {"path": "/server/port"})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "The port is a placeholder."}}]},
    ])
    agent = agent_with(fake, host)
    result = agent.handle({"message": "what is the port?", "session": "s1"})
    assert result["message"] == "The port is a placeholder."
    assert result["activity"][0]["tool"] == "settings_get"
    tool_message = fake.requests[1]["messages"][-1]
    assert json.loads(tool_message["content"])["value_text"] == "${DEMO2_PORT:-8383}"


def test_agent_stages_operations_without_writing(provider, started, workspace):
    host, config, _, _ = started
    before = config.read_text(encoding="utf-8")
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_stage_operations", {
                                      "operations": [{"op": "set", "path": "/fixtures/scalars/count",
                                                      "value_text": "9"}],
                                      "note": "raise the count"})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Staged: count is now 9."}}]},
    ])
    agent = agent_with(fake, host)
    result = agent.handle({"message": "set count to 9"})
    assert result["staged_operations"] == [
        {"op": "set", "path": "/fixtures/scalars/count", "value_text": "9"}
    ]
    assert config.read_text(encoding="utf-8") == before


def test_agent_proposals_appear_in_the_editor(provider, started):
    host, config, _, _ = started
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_stage_operations", {
                                      "operations": [{"op": "add", "path": "/fixtures/arrays/strings/-",
                                                      "value_text": '"delta"'}]})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Added delta."}}]},
    ])
    agent = agent_with(fake, host)
    result = agent.handle({"message": "add delta"})
    loaded = host.service.load("demo2", principal=Principal.demo())
    applied = host.service.apply_operations(
        "demo2",
        result["staged_operations"],
        expected_revision=loaded.revision,
        expected_descriptor_revision=host.service.documents["demo2"].descriptor.revision,
        principal=Principal.demo(),
    )
    assert applied.stored is True
    assert "delta" in config.read_text(encoding="utf-8")


def test_agent_validates_before_staging(provider, started):
    host, config, _, _ = started
    before = config.read_text(encoding="utf-8")
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_stage_operations", {
                                      "operations": [{"op": "set", "path": "/fixtures/constraints/bounded",
                                                      "value_text": "99"}]})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "That exceeds the maximum."}}]},
    ])
    agent = agent_with(fake, host)
    result = agent.handle({"message": "set bounded to 99"})
    assert result["staged_operations"] == []
    tool_message = json.loads(fake.requests[1]["messages"][-1]["content"])
    assert tool_message["staged"] is False and tool_message["valid"] is False
    assert config.read_text(encoding="utf-8") == before


def test_agent_normalizes_paths_to_canonical_pointers(provider, started):
    """A model writes "/" for the root; the tool must read the whole document."""
    from agent import _path

    host = started[0]
    assert _path({"path": "/"}) == ""
    assert _path({"path": ""}) == ""
    assert _path({"path": "root"}) == ""
    assert _path({"path": "server/port"}) == "/server/port"
    assert _path({"path": "/fixtures/arrays/"}) == "/fixtures/arrays"

    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_get_tree", {"path": "/"})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "read the root"}}]},
    ])
    agent_with(fake, host).handle({"message": "show the whole configuration"})
    tool_content = json.loads(fake.requests[1]["messages"][-1]["content"])
    assert tool_content["path"] == ""
    assert tool_content["node"]["children"], "the root tree must contain its sections"


def test_agent_is_told_how_to_address_the_configuration(provider, started):
    """An unknown path comes back with the declared sections, not a bare error."""
    host = started[0]
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_get", {"path": "/nope"})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "retrying"}}]},
    ])
    agent_with(fake, host).handle({"message": "read /nope"})
    tool_content = json.loads(fake.requests[1]["messages"][-1]["content"])
    assert tool_content["code"] == "NOT_FOUND"
    assert "server" in tool_content["available_sections"]
    assert 'root is the empty path ""' in tool_content["hint"]


def test_agent_rejects_an_undeclared_path(provider, started):
    host, _, _, _ = started
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_get", {"path": "/nope"})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "There is no such path."}}]},
    ])
    agent = agent_with(fake, host)
    result = agent.handle({"message": "read /nope"})
    assert result["message"] == "There is no such path."
    tool_message = json.loads(fake.requests[1]["messages"][-1]["content"])
    assert tool_message["ok"] is False and tool_message["code"] == "NOT_FOUND"


def test_agent_reports_an_unreachable_provider(provider, started):
    from agent import AgentError

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    agent = agent_with(provider([]), started[0])
    agent.base_url = f"http://127.0.0.1:{closed_port}/v1"
    with pytest.raises(AgentError) as excinfo:
        agent.handle({"message": "hello"})
    assert excinfo.value.code in ("PROVIDER_UNREACHABLE", "PROVIDER_HTTP_ERROR")


def test_agent_reports_http_errors(provider, started):
    from agent import AgentError

    fake = provider([])
    fake.status = 500
    fake.body = "server error"
    agent = agent_with(fake, started[0])
    with pytest.raises(AgentError) as excinfo:
        agent.handle({"message": "hello"})
    assert excinfo.value.code == "PROVIDER_HTTP_ERROR"


def test_chat_route_reports_provider_failures_explicitly(provider, started):
    """A provider failure must not look like a successful empty answer."""
    host = started[0]
    fake = provider([])
    fake.status = 404
    fake.body = json.dumps({"error": {"message": 'model "missing" not found'}})
    host.agent = agent_with(fake, host)
    status, payload = Client(host).post("/api/demo2/chat", {"message": "hello"})
    assert status == 502
    assert payload["error"]["code"] == "PROVIDER_HTTP_ERROR"
    assert "not found" in payload["error"]["message"]


def test_chat_route_reports_an_unreachable_provider(started):
    host = started[0]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    host.agent = agent_with(FakeProvider([]), host)
    host.agent.base_url = f"http://127.0.0.1:{closed_port}/v1"
    status, payload = Client(host).post("/api/demo2/chat", {"message": "hello"})
    assert status == 503
    assert payload["error"]["code"] == "PROVIDER_UNREACHABLE"


def test_agent_recovers_from_malformed_tool_arguments(provider, started):
    """One malformed tool call must not lose the whole answer."""
    host = started[0]
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [{"id": "c1", "type": "function", "function": {
                                      "name": "settings_get", "arguments": "{'path': '/server/port'}"}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Port read."}}]},
    ])
    result = agent_with(fake, host).handle({"message": "read the port"})
    assert result["message"] == "Port read."
    tool_content = json.loads(fake.requests[1]["messages"][-1]["content"])
    assert tool_content["value_text"] == "${DEMO2_PORT:-8383}"


def test_agent_asks_the_model_to_resend_broken_arguments(provider, started):
    host = started[0]
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [{"id": "c1", "type": "function", "function": {
                                      "name": "settings_get", "arguments": "total nonsense"}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Sorry, retrying."}}]},
    ])
    result = agent_with(fake, host).handle({"message": "read the port"})
    assert result["message"] == "Sorry, retrying."
    tool_content = json.loads(fake.requests[1]["messages"][-1]["content"])
    assert tool_content["code"] == "AGENT_BAD_ARGUMENTS"
    assert "again" in tool_content["message"]


def test_agent_reports_malformed_responses(provider, started):
    from agent import AgentError

    fake = provider([{"unexpected": True}])
    agent = agent_with(fake, started[0])
    with pytest.raises(AgentError) as excinfo:
        agent.handle({"message": "hello"})
    assert excinfo.value.code == "PROVIDER_PROTOCOL"


def test_agent_stops_at_the_tool_round_limit(provider, started):
    host = started[0]
    loop = {
        "choices": [{"message": {"role": "assistant", "content": "",
                                 "tool_calls": [tool_call("settings_get", {"path": "/server/port"},
                                                          call_id="loop")]}}]
    }
    fake = provider([loop, loop, loop])
    agent = agent_with(fake, host, max_tool_rounds=3)
    result = agent.handle({"message": "loop"})
    assert result["rounds"] == 3
    assert "tool round limit" in result["message"]


def test_agent_history_is_bounded_and_per_session(provider, started):
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        {"choices": [{"message": {"role": "assistant", "content": "ok again"}}]},
    ])
    agent = agent_with(fake, started[0])
    agent.handle({"message": "first", "session": "a"})
    agent.handle({"message": "second", "session": "b"})
    assert len(agent.history("a")) == 2
    assert len(agent.history("b")) == 2
    agent.forget("a")
    assert agent.history("a") == []


def test_agent_context_excludes_secret_values(provider, started, workspace):
    host, config, _, env = started
    # A real resolved secret in .env must never reach the model.
    env.write_text(env.read_text(encoding="utf-8") + "DEMO2_FIXTURE_PASSWORD=super-secret-value\n",
                   encoding="utf-8")
    rebuilt = build(config, workspace / "descriptor.json5", env, {})
    host.service, host.settings, _ = rebuilt
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_get_tree", {"path": "/fixtures/secrets"})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "done"}}]},
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_get_tree", {"path": "/fixtures"})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "done"}}]},
    ])
    agent = agent_with(fake, host)
    agent.handle({"message": "show the secrets"})
    secrets = json.loads(fake.requests[1]["messages"][-1]["content"])
    payload = json.dumps(secrets)
    assert "super-secret-value" not in payload
    assert '"access_denied": true' in payload

    agent.handle({"message": "describe everything"})
    whole = fake.requests[3]["messages"][-1]["content"]
    assert "super-secret-value" not in whole
    assert "super-secret-value" not in json.dumps(fake.requests)
    for request in fake.requests:
        assert "super-secret-value" not in json.dumps(request)


def test_chat_route_returns_staged_operations(provider, started):
    host = started[0]
    fake = provider([
        {"choices": [{"message": {"role": "assistant", "content": "",
                                  "tool_calls": [tool_call("settings_stage_operations", {
                                      "operations": [{"op": "set", "path": "/fixtures/scalars/count",
                                                      "value_text": "11"}]})]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "Staged."}}]},
    ])
    host.agent = agent_with(fake, host)
    client = Client(host)
    status, payload = client.post("/api/demo2/chat", {"message": "set count to 11", "session": "s"})
    assert status == 200
    assert payload["staged_operations"][0]["path"] == "/fixtures/scalars/count"
    assert payload["model"] == "test-model"
    status, history = client.get("/api/demo2/chat/history", headers={"X-Aiset-Session": "s"})
    assert any(item["role"] == "user" for item in history["messages"])


def test_api_key_never_reaches_the_browser(provider, started):
    host = started[0]
    fake = provider([{"choices": [{"message": {"role": "assistant", "content": "hi"}}]}])
    agent = agent_with(fake, host)
    host.agent = agent
    client = Client(host)
    status, status_payload = client.get("/api/demo2/status")
    assert "test-key" not in json.dumps(status_payload)
    status, payload = client.get("/api/settings/descriptor?document=demo2")
    assert "test-key" not in json.dumps(payload)
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "", "wsgi.input": None}
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])

    page = b"".join(host_app(host, DEMO2 / "frontend")(environ, start_response))
    assert b"test-key" not in page