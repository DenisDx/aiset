"""ASGI adapter (SPEC_service.md section 10).

A host whose server is already async - FastAPI, Starlette, Litestar, a raw
uvicorn application - needs no WSGI bridge of its own. `create_asgi_app` returns
a plain ASGI application that shares the dispatcher of the WSGI adapter, so the
two transports cannot drift apart and every decision still belongs to the
service.

Two details a host must know:

* the service is synchronous, so the dispatch runs in a worker thread whenever
  an asyncio loop is running. Without that, one large snapshot would stall the
  event loop of the whole host.
* `principal_from_scope` exists because `principal_resolver` is synchronous and
  cannot await a database. A host that authenticates asynchronously resolves the
  session itself and hands over a ready-made `Principal`; a host with a
  synchronous lookup can ignore it and use `principal_resolver` exactly as
  behind the WSGI adapter.
"""

from __future__ import annotations

import asyncio
import inspect
import io
from pathlib import Path
from typing import Any, Awaitable, Callable, MutableMapping

from .httpd import _build_dispatcher, _Request
from .service import Principal, Service

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]

DEFAULT_MAX_BODY_BYTES = 8 * 1024 * 1024


async def read_body(receive: Receive, limit: int) -> bytes:
    """Read one request body, stopping at `limit` bytes.

    The limit mirrors `Limits.max_body_bytes`: a body that exceeds it is read up
    to the limit and then refused with 413 by the service layer, so a huge
    upload is never accumulated in memory.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            break
        chunk = message.get("body", b"")
        total += len(chunk)
        chunks.append(chunk)
        if total >= limit or not message.get("more_body", False):
            break
    return b"".join(chunks)


def build_environ(scope: Scope, body: bytes) -> dict[str, Any]:
    """Build a PEP 3333 environ from an ASGI scope.

    One documented deviation: `PATH_INFO` keeps the full requested path instead
    of the part below `SCRIPT_NAME`, because the adapter routes on the full path
    and a host that mounts it under a prefix must not have to strip that prefix
    twice. `SCRIPT_NAME` still carries the mount prefix.
    """
    environ: dict[str, Any] = {
        "REQUEST_METHOD": scope.get("method", "GET"),
        "SCRIPT_NAME": scope.get("root_path", "") or "",
        "PATH_INFO": scope.get("path", ""),
        "RAW_PATH_INFO": scope.get("raw_path", b"").decode("latin1"),
        "QUERY_STRING": scope.get("query_string", b"").decode("latin1"),
        "SERVER_PROTOCOL": f"HTTP/{scope.get('http_version', '1.1')}",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": scope.get("scheme", "http"),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "CONTENT_TYPE": "",
        "CONTENT_LENGTH": str(len(body)),
    }
    server = scope.get("server") or ("localhost", 80)
    environ["SERVER_NAME"] = str(server[0])
    environ["SERVER_PORT"] = str(server[1])
    client = scope.get("client")
    if client:
        environ["REMOTE_ADDR"] = str(client[0])
    for name, value in scope.get("headers", []):
        key = name.decode("latin1").lower()
        text = value.decode("latin1")
        if key == "content-length":
            environ["CONTENT_LENGTH"] = text
        elif key == "content-type":
            environ["CONTENT_TYPE"] = text
        else:
            header = "HTTP_" + key.upper().replace("-", "_")
            environ[header] = f"{environ[header]},{text}" if header in environ else text
    return environ


async def _offload(func: Callable[..., Any], *args: Any) -> Any:
    """Run blocking work off the event loop when there is one to protect."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return func(*args)
    return await asyncio.to_thread(func, *args)


def create_asgi_app(
    service: Service,
    *,
    base: str = "/api/settings",
    principal_resolver: Callable[[dict[str, Any]], Principal] | None = None,
    principal_from_scope: Callable[[Scope], Principal | None] | None = None,
    static_dir: str | Path | None = None,
    assets_dir: str | Path | None = None,
    static_map: dict[str, str] | None = None,
    public_documents: bool = False,
) -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    """Build the ASGI application for one service.

    `principal_from_scope` is consulted first and wins when it returns a
    `Principal`; otherwise `principal_resolver` receives the PEP 3333 environ,
    which keeps one contract for both transports.

    `principal_from_scope` may be synchronous or asynchronous, and an awaitable
    is awaited **before** the request is dispatched. That matters: the
    dispatcher runs in a worker thread, where an unawaited coroutine would be
    discarded and the request would silently fall back to `Principal.demo()`.
    """

    def resolve_principal(request: _Request) -> Principal:
        if request.principal is not None:
            return request.principal
        if principal_resolver is not None:
            return principal_resolver(request.environ if request.environ is not None else {})
        return Principal.demo()

    async def resolve_from_scope(scope: Scope) -> Principal | None:
        """Run the host hook, awaiting it when the host made it asynchronous."""
        if principal_from_scope is None:
            return None
        principal = principal_from_scope(scope)
        if inspect.isawaitable(principal):
            principal = await principal
        return principal if isinstance(principal, Principal) else None

    dispatch = _build_dispatcher(
        service,
        base=base,
        principal_resolver=resolve_principal,
        static_dir=static_dir,
        assets_dir=assets_dir,
        static_map=static_map,
        public_documents=public_documents,
    )

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - websockets are not handled
            raise RuntimeError(f"create_asgi_app handles http requests, got {scope['type']!r}")
        body = await read_body(receive, service.settings.limits.max_body_bytes)
        environ = build_environ(scope, body)
        request = _Request(
            method=environ["REQUEST_METHOD"],
            path=environ["PATH_INFO"],
            query=environ["QUERY_STRING"],
            body=body,
            environ=environ,
            scope=scope,
            principal=await resolve_from_scope(scope),
        )
        captured: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]], exc_info=None) -> None:
            if exc_info is not None:
                raise exc_info[1].with_traceback(exc_info[2])
            captured["status"] = status
            captured["headers"] = headers

        def run() -> tuple[str, list[tuple[bytes, bytes]], bytes]:
            chunks = list(dispatch(request, start_response))
            status = captured.get("status", "500 Internal Server Error")
            headers = [
                (str(name).encode("latin1"), str(value).encode("latin1"))
                for name, value in captured.get("headers", [])
            ]
            return status, headers, b"".join(chunks)

        status, headers, payload = await _offload(run)
        await send(
            {
                "type": "http.response.start",
                "status": int(status.split(" ", 1)[0]),
                "headers": headers,
            }
        )
        await send({"type": "http.response.body", "body": payload})

    app.resolve_principal = resolve_principal  # type: ignore[attr-defined]
    return app


__all__ = ["create_asgi_app", "build_environ", "read_body"]