"""CLI, merge, Config object and the standalone demo application."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aiset.cli import main
from aiset.config_obj import Config, Origin, place_mount, resolve_mount, split_mount
from aiset.errors import DescriptorError
from aiset.merge import merge
from tests.conftest import DEMO_CONFIG, DEMO_DESCRIPTOR

ROOT = Path(__file__).resolve().parents[1]

# -- merge -----------------------------------------------------------------


def test_merge_keeps_the_base_on_a_conflict_by_default():
    """SPEC_.md correction 5: the base decides, objects still merge."""
    assert merge({"a": 1}, {"a": 2}) == {"a": 1}
    assert merge({"a": [1, 2]}, {"a": [3]}) == {"a": [1, 2]}
    assert merge({"a": None}, {"a": 1}) == {"a": None}
    assert merge({"a": 1}, {"a": {"b": 2}}) == {"a": 1}
    assert merge({"a": {"b": 1}}, {"a": 5}) == {"a": {"b": 1}}
    assert merge({"a": "base"}, {"a": None}) == {"a": "base"}


def test_merge_objects_recursively():
    assert merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}}) == {"a": {"b": 1, "c": 2}}
    assert merge({"a": {"b": 1}}, {"a": {"c": 2}}) == {"a": {"b": 1, "c": 2}}


def test_update_priority_is_the_former_behaviour():
    """The old rule stays available through the extra parameter."""
    assert merge({"a": 1}, {"a": 2}, prefer="update") == {"a": 2}
    assert merge({"a": [1, 2]}, {"a": [3]}, prefer="update") == {"a": [3]}
    assert merge({"a": {"b": 1}}, {"a": 5}, prefer="update") == {"a": 5}
    assert merge({"a": 1}, {"a": None}, prefer="update") == {"a": None}
    assert merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}}, prefer="update") == {"a": {"b": 1, "c": 3}}


def test_merge_rejects_an_unknown_preference():
    with pytest.raises(ValueError):
        merge({}, {}, prefer="whatever")


def test_merge_keeps_base_only_and_adds_update_only():
    assert merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_merge_cannot_delete_a_field():
    assert merge({"a": 1}, {}) == {"a": 1}


def test_merge_does_not_mutate_inputs():
    base = {"a": {"b": 1}}
    update = {"a": {"b": 2}}
    merge(base, update)
    assert base == {"a": {"b": 1}} and update == {"a": {"b": 2}}


def test_merge_chains_over_one_base():
    assert merge(merge({"a": 1}, {"a": 2}, prefer="update"), {"a": 3}, prefer="update") == {"a": 3}
    assert merge(merge({"a": 1}, {"a": 2}), {"a": 3}) == {"a": 1}


def test_merge_returns_a_new_value_in_both_modes():
    base = {"a": {"b": 1}}
    update = {"a": {"b": 2, "c": 3}}
    assert merge(base, update) == {"a": {"b": 1, "c": 3}}
    assert merge(base, update, prefer="update") == {"a": {"b": 2, "c": 3}}
    assert base == {"a": {"b": 1}} and update == {"a": {"b": 2, "c": 3}}


# -- Config object and mount grammar ---------------------------------------


def test_split_mount_handles_escapes():
    assert split_mount("workers.my\\.worker") == ["workers", "my.worker"]
    assert split_mount("items.[id=x]") == ["items", "[id=x]"]


def test_resolve_mount_object_and_identity():
    data = {"workers": {"items": [{"id": "a"}, {"id": "b"}]}}
    container, key = resolve_mount(data, "workers.items.[id=b]")
    assert container[key] == {"id": "b"}


def test_resolve_mount_zero_match_is_explicit():
    data = {"workers": {"items": [{"id": "a"}]}}
    with pytest.raises(DescriptorError):
        resolve_mount(data, "workers.items.[id=zzz]")


def test_resolve_mount_duplicate_match_is_explicit():
    data = {"workers": {"items": [{"id": "a"}, {"id": "a"}]}}
    with pytest.raises(DescriptorError):
        resolve_mount(data, "workers.items.[id=a]")


def test_place_mount_merges_into_a_base():
    base = {"workers": {"a": {"enabled": True}}}
    result = place_mount(base, "workers.b", {"enabled": False})
    assert result["workers"] == {"a": {"enabled": True}, "b": {"enabled": False}}
    assert "b" not in base["workers"]


def test_config_load_and_update(tmp_path):
    path = tmp_path / "config.json5"
    path.write_text(DEMO_CONFIG, encoding="utf-8")
    config = Config.load(path)
    assert config.data["version"] == "1.0"
    assert isinstance(config.origin, Origin)
    # The default keeps the base on a conflict; the update fills what is missing.
    updated = config.update({"log_level": "critical", "extra": 1})
    assert updated.data["log_level"] == "info", "the base wins by default"
    assert updated.data["extra"] == 1, "a field only in the update is taken"
    assert config.data["log_level"] == "info"

    overriding = config.update({"log_level": "critical"}, prefer="update")
    assert overriding.data["log_level"] == "critical", "the old rule stays available"
    assert config.data["log_level"] == "info"


def test_config_reload(tmp_path):
    path = tmp_path / "config.json5"
    path.write_text(DEMO_CONFIG, encoding="utf-8")
    config = Config.load(path)
    revision = config.revision
    path.write_text("{ version: '1.0' }\n", encoding="utf-8")
    config.reload()
    assert config.revision != revision
    assert config.data == {"version": "1.0"}


# -- CLI -------------------------------------------------------------------


def test_cli_validates_a_descriptor(capsys):
    code = main(["validate-descriptor", str(ROOT / "examples" / "descriptor.json5")])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["valid"] is True


def test_cli_text_format(capsys):
    code = main(["validate-descriptor", str(ROOT / "examples" / "descriptor.json5"), "--format", "text"])
    out = capsys.readouterr().out
    assert code == 0 and out.startswith("valid: True")


def test_cli_reports_unknown_properties(capsys, tmp_path):
    path = tmp_path / "d.json5"
    path.write_text(DEMO_DESCRIPTOR, encoding="utf-8")
    code = main(["validate-descriptor", str(path)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["valid"] is True
    assert any(issue["code"] == "UNKNOWN_DESCRIPTOR_PROPERTY" for issue in payload["issues"])


def test_cli_strict_mode_exit_status(capsys, tmp_path):
    path = tmp_path / "d.json5"
    path.write_text(DEMO_DESCRIPTOR, encoding="utf-8")
    assert main(["validate-descriptor", str(path), "--strict"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is False


def test_cli_missing_file_returns_2(capsys):
    assert main(["validate-descriptor", "/nonexistent/descriptor.json5"]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_cli_reads_standard_input(monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO('{ descriptor_version: "1.0", root: { type: "object" } }'))
    assert main(["validate-descriptor", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_cli_invalid_descriptor_returns_1(capsys, tmp_path):
    path = tmp_path / "d.json5"
    path.write_text("{ descriptor_version: '9.9', root: {} }", encoding="utf-8")
    assert main(["validate-descriptor", str(path)]) == 1


def _document_files(tmp_path, config_text):
    config = tmp_path / "config.json5"
    config.write_text(config_text, encoding="utf-8")
    descriptor = tmp_path / "descriptor.json5"
    descriptor.write_text(DEMO_DESCRIPTOR, encoding="utf-8")
    return config, descriptor


def test_cli_validates_a_document(capsys, tmp_path):
    config, descriptor = _document_files(tmp_path, DEMO_CONFIG)
    code = main(["validate-document", "--config", str(config), "--descriptor", str(descriptor)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["valid"] is True


def test_cli_document_reports_an_undeclared_key(capsys, tmp_path):
    config, descriptor = _document_files(tmp_path, "{ not_declared: 1 }")
    code = main([
        "validate-document", "--config", str(config), "--descriptor", str(descriptor), "--format", "text",
    ])
    out = capsys.readouterr().out
    assert code == 1 and out.startswith("valid: False")
    assert "not_declared" in out


def test_cli_document_missing_file_returns_2(capsys, tmp_path):
    _config, descriptor = _document_files(tmp_path, DEMO_CONFIG)
    code = main([
        "validate-document", "--config", str(tmp_path / "nope.json5"), "--descriptor", str(descriptor),
    ])
    assert code == 2
    assert "cannot read" in capsys.readouterr().err


def test_cli_document_resolves_from_an_env_file(capsys, tmp_path):
    config = tmp_path / "config.json5"
    config.write_text('{ port: "${MYAPP_PORT:-8080}" }', encoding="utf-8")
    descriptor = tmp_path / "descriptor.json5"
    descriptor.write_text(
        '{ descriptor_version: "1.0", root: { type: "object", children: '
        '{ port: { type: "int", env: { allowed: true, convert: "int" } } } } }',
        encoding="utf-8",
    )
    env = tmp_path / ".env"
    env.write_text("MYAPP_PORT=9999\n", encoding="utf-8")
    code = main([
        "validate-document", "--config", str(config), "--descriptor", str(descriptor),
        "--env", str(env), "--quiet",
    ])
    assert code == 0


# -- demo application ------------------------------------------------------


def demo_module():
    sys.path.insert(0, str(ROOT))
    import demo_app

    return demo_app


def test_demo_override_parsing():
    app = demo_module()
    overrides = app.parse_overrides(
        ["--aiset.port:12345", '--aiset.host:"127.0.0.1"', "--storage.backup_depth:3"]
    )
    assert overrides == {"aiset": {"port": 12345, "host": "127.0.0.1"}, "storage": {"backup_depth": 3}}


def test_demo_override_quoting_rules():
    app = demo_module()
    assert app.parse_overrides(['--logging.level:"debug"'])["logging"]["level"] == "debug"
    assert app.parse_overrides(["--storage.backup_depth:3"])["storage"]["backup_depth"] == 3
    assert app.parse_overrides(["--aiset.port:0"])["aiset"]["port"] == 0


def test_demo_seeds_state_only_when_absent(tmp_path):
    app = demo_module()
    args = app.build_parser().parse_args(["--state-dir", str(tmp_path / "state")])
    layout = app.prepare(args, {})
    config = layout["documents"]["demo"]["config"]
    assert config.exists() and "aiset demo configuration" in config.read_text()
    config.write_text("{ edited: true }\n", encoding="utf-8")
    app.prepare(args, {})
    assert config.read_text() == "{ edited: true }\n"


def test_demo_never_touches_tracked_examples(tmp_path):
    app = demo_module()
    examples = tmp_path / "examples"
    examples.mkdir()
    for name in ("descriptor.json5", "config.json5", "aiset_descriptor.json5", "aiset.json5"):
        (examples / name).write_text((ROOT / "examples" / name).read_text(encoding="utf-8"),
                                     encoding="utf-8")
    before = {path.name: path.read_bytes() for path in examples.iterdir()}
    args = app.build_parser().parse_args(
        ["--state-dir", str(tmp_path / "state"), "--examples-dir", str(examples)]
    )
    app.prepare(args, {})
    assert {path.name: path.read_bytes() for path in examples.iterdir()} == before


def test_demo_rejects_a_non_writable_state_dir(tmp_path):
    app = demo_module()
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    args = app.build_parser().parse_args(["--state-dir", str(locked / "state")])
    try:
        with pytest.raises(app.DemoError):
            app.prepare(args, {})
    finally:
        locked.chmod(0o700)


def test_demo_builds_a_service_with_both_documents(tmp_path):
    app = demo_module()
    args = app.build_parser().parse_args(["--state-dir", str(tmp_path / "state")])
    layout = app.prepare(args, {"aiset": {"port": 9999}})
    from aiset.store import Settings

    settings = Settings.from_mapping(layout["settings_data"])
    assert settings.demo_port == 9999
    service = app.build_service(layout, settings)
    assert sorted(service.documents) == ["aiset", "demo"]
    from aiset.service import Principal

    principal = Principal.demo()
    assert service.load("demo", principal=principal).loaded == "file"
    assert service.load("aiset", principal=principal).loaded == "file"


def test_demo_default_port_is_8383():
    app = demo_module()
    args = app.build_parser().parse_args(["--state-dir", "/tmp/aiset-demo-port-check"])
    layout = app.prepare(args, {})
    from aiset.store import Settings

    settings = Settings.from_mapping(layout["settings_data"])
    assert settings.demo_port == 8383
    assert settings.demo_host == "0.0.0.0"


def test_demo_reports_a_bind_failure(tmp_path, monkeypatch):
    app = demo_module()
    args = app.build_parser().parse_args(["--state-dir", str(tmp_path / "state")])
    layout = app.prepare(args, {})
    from aiset.store import Settings

    settings = Settings.from_mapping(layout["settings_data"])
    service = app.build_service(layout, settings)

    import wsgiref.simple_server

    def failing(*args, **kwargs):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(wsgiref.simple_server, "make_server", failing)
    with pytest.raises(app.DemoError) as excinfo:
        app.serve(layout, service, settings, ROOT / "frontend")
    assert "does not choose another port" in str(excinfo.value)


def test_demo_serves_the_real_ui_and_api(tmp_path):
    """End-to-end: the documented entry point answers on an ephemeral port."""
    import socket
    import threading
    import urllib.request
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    app = demo_module()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    args, extra = app.build_parser().parse_known_args(
        ["--state-dir", str(tmp_path / "state"), f"--aiset.port:{port}", '--aiset.host:"127.0.0.1"']
    )
    layout = app.prepare(args, app.parse_overrides(extra))
    from aiset.store import Settings

    settings = Settings.from_mapping(layout["settings_data"])
    service = app.build_service(layout, settings)

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args):
            return

    server = make_server(
        settings.demo_host, settings.demo_port, app.create_app(service, static_dir=ROOT / "frontend"),
        handler_class=Quiet,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            assert response.status == 200
            assert b"aiset settings editor" in response.read()
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/settings/value?document=demo&path=/log_level&view=source"
        ) as response:
            payload = json.loads(response.read())
        assert payload["value_text"] == '"info"'
    finally:
        server.shutdown()
        server.server_close()

# -- doctor CLI ------------------------------------------------------------


def _doctor_file(tmp_path: Path, replacements=None) -> Path:
    text = DEMO_CONFIG
    for old, new in (replacements or []):
        text = text.replace(old, new)
    target = tmp_path / "config.json5"
    target.write_text(text, encoding="utf-8")
    return target


def test_cli_doctor_reports_and_exits_1(capsys, tmp_path):
    target = _doctor_file(
        tmp_path, [("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")]
    )
    code = main([
        "doctor", "--config", str(target),
        "--descriptor", str(ROOT / "examples" / "descriptor.json5"),
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["valid"] is False
    issue = next(item for item in payload["issues"] if item["path"] == "/http_port")
    assert issue["fix"] == "clamp"


def test_cli_doctor_fix_writes_and_exits_0(capsys, tmp_path):
    target = _doctor_file(
        tmp_path, [("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")]
    )
    code = main([
        "doctor", "--config", str(target),
        "--descriptor", str(ROOT / "examples" / "descriptor.json5"),
        "--fix",
    ])
    capsys.readouterr()
    assert code == 0
    assert "http_port: 65535" in target.read_text(encoding="utf-8")


def test_cli_doctor_class_is_required_for_a_lossy_repair(capsys, tmp_path):
    target = _doctor_file(
        tmp_path, [('  version: "1.0",', '  version: "1.0",\n  stale_key: 1,')]
    )
    code = main([
        "doctor", "--config", str(target),
        "--descriptor", str(ROOT / "examples" / "descriptor.json5"),
        "--fix",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1 and payload["applied"] is False
    assert "stale_key" in target.read_text(encoding="utf-8")

    code = main([
        "doctor", "--config", str(target),
        "--descriptor", str(ROOT / "examples" / "descriptor.json5"),
        "--class", "drop_unknown",
    ])
    capsys.readouterr()
    assert code == 0
    assert "stale_key" not in target.read_text(encoding="utf-8")


def test_cli_doctor_text_format(capsys, tmp_path):
    target = _doctor_file(
        tmp_path, [("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")]
    )
    code = main([
        "doctor", "--config", str(target),
        "--descriptor", str(ROOT / "examples" / "descriptor.json5"),
        "--format", "text",
    ])
    out = capsys.readouterr().out
    assert code == 1
    assert out.startswith("valid: False")
    assert "/http_port [maximum]" in out
