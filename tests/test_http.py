"""HTTP adapter parity with the Python service (SPEC_service.md sections 10, 18)."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest

from aiset.httpd import create_app
from aiset.service import Principal


class Client:
    """Minimal WSGI test client."""

    def __init__(self, app) -> None:
        self.app = app

    def request(self, method: str, path: str, body: dict | None = None, query: str = "") -> tuple[int, dict]:
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": BytesIO(raw),
        }
        captured: dict = {}

        def start_response(status, headers):
            captured["status"] = int(status.split()[0])
            captured["headers"] = headers

        chunks = self.app(environ, start_response)
        payload = b"".join(chunks)
        return captured["status"], json.loads(payload) if payload else {}

    def get(self, path, query=""):
        return self.request("GET", path, query=query)

    def post(self, path, body):
        return self.request("POST", path, body=body)


@pytest.fixture
def client(service) -> Client:
    return Client(create_app(service))


def revision_pair(service, principal):
    loaded = service.load("demo", principal=principal)
    return loaded.revision, loaded.descriptor_revision


def test_health(client):
    status, payload = client.get("/api/health")
    assert status == 200 and payload["ok"]


def test_list_documents(client):
    status, payload = client.get("/api/settings/documents")
    assert status == 200 and payload["documents"] == ["demo"]


def test_descriptor_route(client):
    status, payload = client.get("/api/settings/descriptor", "document=demo&view=authorized")
    assert status == 200
    assert payload["descriptor"]["root"]["type"] == "object"
    assert payload["revision"].startswith("sha256:")


def test_value_route_matches_the_python_service(client, service, principal):
    status, payload = client.get(
        "/api/settings/value", "document=demo&path=/log_level&view=source"
    )
    assert status == 200
    direct = service.get("demo", "/log_level", principal=principal).to_dict()
    assert payload == direct


def test_value_route_reports_format_and_etag(client):
    status, payload = client.get("/api/settings/value", "document=demo&path=/title&view=source")
    assert payload["format"] == "json5-template" and len(payload["etag"]) == 64


def test_validate_route(client, service, principal):
    source, descriptor = revision_pair(service, principal)
    status, payload = client.post(
        "/api/settings/validate",
        {"document": "demo", "path": "/log_level", "value_text": '"nonsense"',
         "expected_revision": source, "expected_descriptor_revision": descriptor},
    )
    assert status == 200 and payload["valid"] is False and payload["issues"]
    assert payload["issues"][0]["line"]


def test_set_route(client, service, principal, demo_dir):
    source, descriptor = revision_pair(service, principal)
    status, payload = client.post(
        "/api/settings/value",
        {"document": "demo", "path": "/log_level", "value_text": '"debug"',
         "expected_revision": source, "expected_descriptor_revision": descriptor},
    )
    assert status == 200 and payload["stored"] is True
    assert payload["application"]["state"] == "applied"
    assert 'log_level: "debug"' in (demo_dir / "config.json5").read_text()


def test_stale_revision_returns_409(client, service, principal):
    source, descriptor = revision_pair(service, principal)
    status, payload = client.post(
        "/api/settings/value",
        {"document": "demo", "path": "/log_level", "value_text": '"debug"',
         "expected_revision": "sha256:stale", "expected_descriptor_revision": descriptor},
    )
    assert status == 409 and payload["error"]["code"] == "REVISION_CONFLICT"


def test_missing_revision_returns_428(client):
    status, payload = client.post(
        "/api/settings/value",
        {"document": "demo", "path": "/log_level", "value_text": '"debug"'},
    )
    assert status == 428 and payload["error"]["code"] == "REVISION_REQUIRED"


def test_validation_failure_returns_422(client, service, principal):
    source, descriptor = revision_pair(service, principal)
    status, payload = client.post(
        "/api/settings/value",
        {"document": "demo", "path": "/counters/fraction", "value_text": "9",
         "expected_revision": source, "expected_descriptor_revision": descriptor},
    )
    assert status == 422 and payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["issues"][0]["rule"] == "maximum"


def test_unknown_document_returns_404(client):
    status, payload = client.get("/api/settings/descriptor", "document=nope")
    assert status == 404 and payload["error"]["code"] == "NOT_FOUND"


def test_unknown_route_returns_404(client):
    status, payload = client.get("/api/settings/nope")
    assert status == 404


def test_load_and_load_lkg_routes(client, service, principal):
    status, payload = client.post("/api/settings/load", {"document": "demo"})
    assert status == 200 and payload["loaded"] == "file"
    status, payload = client.post("/api/settings/load/lkg", {"document": "demo"})
    assert status == 404 and payload["error"]["code"] == "NO_VALID_BACKUP"


def test_descriptor_validate_route(client):
    status, payload = client.post(
        "/api/settings/descriptor/validate",
        {"descriptor_source": "{ descriptor_version: '1.0', root: { type: 'object' } }"},
    )
    assert status == 200 and payload["valid"] is True
    status, payload = client.post(
        "/api/settings/descriptor/validate",
        {"descriptor_source": "{ descriptor_version: '1.0', root: { type: 'object', x_demo: 1 } }",
         "mode": "strict"},
    )
    assert payload["valid"] is False


def test_merge_route(client):
    status, payload = client.post(
        "/api/settings/merge",
        {"base": {"a": {"b": 1}, "keep": True}, "update": {"a": {"c": 2}}},
    )
    assert status == 200 and payload["merged"] == {"a": {"b": 1, "c": 2}, "keep": True}
    assert payload["prefer"] == "base", "the base decides unless the caller says otherwise"


def test_merge_route_accepts_update_priority(client):
    status, payload = client.post(
        "/api/settings/merge",
        {"base": {"a": 1, "keep": 2}, "update": {"a": 9}, "prefer": "update"},
    )
    assert status == 200 and payload["merged"] == {"a": 9, "keep": 2}
    assert payload["prefer"] == "update"

    status, payload = client.post(
        "/api/settings/merge", {"base": {}, "update": {}, "prefer": "whatever"}
    )
    assert status == 400 and payload["error"]["code"] == "BAD_REQUEST"


def test_secret_route_denies_readers(service):
    app = create_app(
        service,
        principal_resolver=lambda environ: Principal(
            id="reader", permissions=frozenset({"settings_read_source"})
        ),
    )
    client = Client(app)
    status, payload = client.get("/api/settings/value", "document=demo&path=/credentials&view=source")
    assert status == 403 and payload["error"]["code"] == "SECRET_ACCESS_DENIED"


def test_malformed_json_body_returns_400(client):
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/api/settings/value",
        "QUERY_STRING": "",
        "CONTENT_LENGTH": "5",
        "wsgi.input": BytesIO(b"{bad}"),
    }
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])

    body = b"".join(client.app(environ, start_response))
    assert captured["status"] == 400
    assert json.loads(body)["error"]["code"] == "BAD_REQUEST"


def test_body_too_large_returns_413(service):
    service.settings.limits.max_body_bytes = 10
    client = Client(create_app(service))
    status, payload = client.post("/api/settings/value", {"document": "demo", "value_text": "x" * 100})
    assert status == 413 and payload["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_static_frontend_and_assets_are_served(service):
    client = Client(create_app(service, static_dir=Path("frontend")))
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "", "wsgi.input": BytesIO(b"")}
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["type"] = dict(headers).get("Content-Type")

    page = b"".join(client.app(environ, start_response))
    assert captured["status"] == 200 and "text/html" in captured["type"]
    assert b"aiset settings editor" in page

    environ["PATH_INFO"] = "/assets/aiset.js"
    start_response  # noqa: B018 - keep the reference readable
    script = b"".join(client.app(environ, start_response))
    assert b"renderNodeEditor" in script


def test_env_route_reports_presence_only(service, resolver, principal):
    resolver.dotenv["AISET_PRESENT"] = "value"
    client = Client(create_app(service))
    status, payload = client.post(
        "/api/settings/env", {"document": "demo", "names": ["AISET_PRESENT", "AISET_ABSENT"]}
    )
    assert status == 200
    assert payload["present"] == {"AISET_PRESENT": True, "AISET_ABSENT": False}
    assert "value" not in str(payload), "the route must never echo a value"

    status, payload = client.post("/api/settings/env", {"document": "demo", "names": "AISET_PRESENT"})
    assert status == 400 and payload["error"]["code"] == "BAD_REQUEST"


def test_unsupported_internal_error_is_sanitized(service):
    def broken(*args, **kwargs):
        raise RuntimeError("internal detail")

    service._state = broken  # type: ignore[method-assign]
    client = Client(create_app(service))
    status, payload = client.get("/api/settings/value", "document=demo&path=/title")
    assert status == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "internal detail" not in json.dumps(payload)

def test_static_assets_are_never_served_stale(service):
    """A cached script or stylesheet looks exactly like a broken one."""
    client = Client(create_app(service, static_dir=Path("frontend")))
    environ = {
        "REQUEST_METHOD": "GET", "PATH_INFO": "/assets/aiset-tree.js",
        "QUERY_STRING": "", "wsgi.input": BytesIO(b""),
    }
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = {key.lower(): value for key, value in headers}

    body = b"".join(client.app(environ, start_response))
    assert captured["status"] == 200
    assert captured["headers"]["cache-control"] == "no-cache, must-revalidate"
    assert captured["headers"]["last-modified"], "the asset must carry a validator"
    assert b"expandAll" in body
