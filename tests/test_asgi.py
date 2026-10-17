"""ASGI adapter parity with the WSGI adapter (SPEC_service.md section 10).

The two adapters share one dispatcher, so these tests compare them on the same
routes instead of restating the contract: anything the WSGI adapter answers must
be answered identically here.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from aiset.asgi import build_environ, create_asgi_app
from aiset.httpd import create_app
from aiset.service import Principal


class AsgiClient:
    """Minimal ASGI test client."""

    def __init__(self, app) -> None:
        self.app = app

    def request(
        self, method: str, path: str, body: dict | None = None, query: str = ""
    ) -> tuple[int, dict, dict]:
        raw_path, _, inline_query = path.partition("?")
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        headers = [(b"host", b"testserver")]
        if raw:
            headers.append((b"content-type", b"application/json"))
            headers.append((b"content-length", str(len(raw)).encode()))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": raw_path,
            "raw_path": raw_path.encode(),
            "root_path": "",
            "query_string": (inline_query or query).encode(),
            "headers": headers,
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 5555),
        }
        messages = [{"type": "http.request", "body": raw, "more_body": False}]
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        asyncio.run(self.app(scope, receive, send))
        start = next(m for m in sent if m["type"] == "http.response.start")
        payload = next(m for m in sent if m["type"] == "http.response.body")
        head = {name.decode("latin1"): value.decode("latin1") for name, value in start["headers"]}
        body_bytes = payload["body"] or b""
        decoded = {}
        if head.get("Content-Type", "").startswith("application/json") and body_bytes:
            decoded = json.loads(body_bytes)
        return start["status"], decoded, head

    def get(self, path, query=""):
        return self.request("GET", path, query=query)

    def post(self, path, body):
        return self.request("POST", path, body=body)


class WsgiClient:
    """Minimal WSGI test client, used only as the parity reference."""

    def __init__(self, app) -> None:
        self.app = app

    def request(self, method: str, path: str, body: dict | None = None, query: str = "") -> tuple[int, dict]:
        from io import BytesIO

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

        payload = b"".join(self.app(environ, start_response))
        return captured["status"], json.loads(payload) if payload else {}

    def get(self, path, query=""):
        return self.request("GET", path, query=query)

    def post(self, path, body):
        return self.request("POST", path, body=body)


@pytest.fixture
def asgi_client(service) -> AsgiClient:
    return AsgiClient(create_asgi_app(service))


def test_health(asgi_client):
    status, payload, _ = asgi_client.get("/api/health")
    assert status == 200 and payload["ok"]


def test_documents(asgi_client):
    status, payload, _ = asgi_client.get("/api/settings/documents")
    assert status == 200 and payload["documents"] == ["demo"]


def test_tree_matches_wsgi(service):
    asgi = AsgiClient(create_asgi_app(service))
    wsgi = WsgiClient(create_app(service))
    asgi_status, asgi_payload, _ = asgi.get("/api/settings/tree", query="document=demo")
    wsgi_status, wsgi_payload = wsgi.get("/api/settings/tree", query="document=demo")
    assert asgi_status == wsgi_status == 200
    assert asgi_payload == wsgi_payload


def test_bundled_assets_are_served_without_a_static_dir(asgi_client):
    status, _payload, headers = asgi_client.get("/assets/aiset.css")
    assert status == 200
    assert headers["Content-Type"] == "text/css; charset=utf-8"
    assert headers["Cache-Control"] == "no-cache, must-revalidate"


def test_unknown_asset_is_not_found(asgi_client):
    status, payload, _ = asgi_client.get("/assets/nope.js")
    assert status == 404 and payload["error"]["code"] == "NOT_FOUND"


def test_root_without_a_static_dir_is_not_found(asgi_client):
    """Without a host directory nothing may be resolved against the process CWD."""
    status, payload, _ = asgi_client.get("/")
    assert status == 404 and payload["error"]["code"] == "NOT_FOUND"
    status, payload, _ = asgi_client.get("/index.html")
    assert status == 404 and payload["error"]["code"] == "NOT_FOUND"


def test_asset_traversal_is_refused(asgi_client):
    status, _payload, _ = asgi_client.get("/assets/..%2f..%2fpyproject.toml")
    assert status == 404


def test_unknown_route(asgi_client):
    status, payload, _ = asgi_client.get("/api/settings/nope")
    assert status == 404 and payload["error"]["code"] == "NOT_FOUND"


def test_write_without_a_revision_is_refused(asgi_client):
    status, payload, _ = asgi_client.post(
        "/api/settings/operations",
        {"document": "demo", "operations": [{"op": "set", "path": "/log_level", "value_text": '"x"'}]},
    )
    assert status == 428 and payload["error"]["code"] == "REVISION_REQUIRED"


def test_merge_matches_wsgi(service):
    asgi = AsgiClient(create_asgi_app(service))
    wsgi = WsgiClient(create_app(service))
    body = {"base": {"a": 1}, "update": {"b": 2}}
    assert asgi.post("/api/settings/merge", body)[1] == wsgi.post("/api/settings/merge", body)[1]


def test_full_write_cycle(asgi_client, service, principal):
    _status, tree, _headers = asgi_client.get("/api/settings/tree", query="document=demo")
    status, payload, _ = asgi_client.post(
        "/api/settings/operations",
        {
            "document": "demo",
            "operations": [{"op": "set", "path": "/log_level", "value_text": '"warning"'}],
            "expected_revision": tree["revision"],
            "expected_descriptor_revision": tree["descriptor_revision"],
        },
    )
    assert status == 200 and payload["stored"] is True
    assert service.get("demo", "/log_level", principal=principal).value_text == '"warning"'


def test_principal_from_scope_wins(service):
    denied = Principal(id="anonymous", permissions=frozenset())
    client = AsgiClient(create_asgi_app(service, principal_from_scope=lambda scope: denied))
    status, payload, _ = client.get("/api/settings/tree", query="document=demo")
    assert status == 403 and payload["error"]["code"] == "FORBIDDEN"


def test_principal_resolver_receives_the_environ(service):
    seen: list[dict] = []
    blind = Principal(id="blind", permissions=frozenset({"settings_validate"}))

    def resolve(environ):
        seen.append(environ)
        return blind

    client = AsgiClient(create_asgi_app(service, principal_resolver=resolve))
    status, payload, _ = client.get("/api/settings/tree", query="document=demo")
    assert status == 403 and payload["error"]["code"] == "FORBIDDEN"
    assert seen and seen[0]["REQUEST_METHOD"] == "GET"
    assert seen[0]["PATH_INFO"] == "/api/settings/tree"
    assert seen[0]["QUERY_STRING"] == "document=demo"


def test_build_environ_keeps_the_full_path_and_the_mount_prefix():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/settings/operations",
        "root_path": "/api/settings",
        "raw_path": b"/api/settings/operations",
        "query_string": b"a=1",
        "scheme": "http",
        "http_version": "1.1",
        "headers": [(b"cookie", b"session=abc")],
        "server": ("h", 1),
        "client": ("c", 2),
    }
    environ = build_environ(scope, b"{}")
    assert environ["SCRIPT_NAME"] == "/api/settings"
    assert environ["PATH_INFO"] == "/api/settings/operations"
    assert environ["QUERY_STRING"] == "a=1"
    assert environ["HTTP_COOKIE"] == "session=abc"
    assert environ["wsgi.input"].read() == b"{}"
    assert environ["CONTENT_LENGTH"] == "2"


def test_non_http_scope_is_refused(service):
    app = create_asgi_app(service)

    async def call():
        async def receive():  # pragma: no cover - never reached
            return {"type": "websocket.connect"}

        async def send(message):  # pragma: no cover - never reached
            return None

        await app({"type": "websocket"}, receive, send)

    with pytest.raises(RuntimeError):
        asyncio.run(call())

def test_an_async_principal_hook_is_awaited(service):
    """Regression: an unawaited coroutine silently fell back to Principal.demo()."""
    import warnings

    denied = Principal(id="anonymous", permissions=frozenset())

    async def resolve(scope):
        await asyncio.sleep(0)
        return denied

    client = AsgiClient(create_asgi_app(service, principal_from_scope=resolve))
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        status, payload, _ = client.get("/api/settings/tree", query="document=demo")
    assert status == 403 and payload["error"]["code"] == "FORBIDDEN"


def test_an_async_hook_that_returns_nothing_falls_back(service):
    async def resolve(scope):
        return None

    client = AsgiClient(create_asgi_app(service, principal_from_scope=resolve))
    status, payload, _ = client.get("/api/settings/documents")
    assert status == 200 and payload["documents"] == ["demo"]
