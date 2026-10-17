"""HTTP adapters (SPEC.md 8.2, SPEC_service.md section 10).

Two dependency-free adapters over one dispatcher: a WSGI application that the
standalone demo serves directly and a host can mount inside its own
authenticated server, and an ASGI application for hosts whose server is already
async. Both share the same routing, so they cannot drift apart.

The adapters are thin; every decision belongs to the service.
"""

from __future__ import annotations

import email.utils
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs

from . import __version__
from .errors import AisetError, BadRequest, PayloadTooLarge
from .merge import PREFERENCES, merge
from .service import Principal, Service

JSON_HEADERS = [("Content-Type", "application/json; charset=utf-8")]


@dataclass
class _Request:
    """One normalized request, independent of the transport that carried it."""

    method: str
    path: str
    query: str = ""
    body: bytes = b""
    # The WSGI environ is kept so that a host-provided `principal_resolver` sees
    # the same mapping it would see behind the WSGI adapter. `scope` is the ASGI
    # equivalent, for `principal_from_scope`.
    environ: dict[str, Any] | None = None
    scope: Any = None
    # Set by the ASGI adapter once it has resolved an asynchronous principal, so
    # that the synchronous dispatcher never has to deal with an awaitable.
    principal: Any = None


def create_app(
    service: Service,
    *,
    base: str = "/api/settings",
    principal_resolver: Callable[[dict[str, Any]], Principal] | None = None,
    static_dir: str | Path | None = None,
    assets_dir: str | Path | None = None,
    static_map: dict[str, str] | None = None,
    public_documents: bool = False,
) -> Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]:
    """Build the WSGI application for one service.

    `static_map` adds host files (for example a host script or stylesheet) to the
    bundled frontend: route path -> file name inside `static_dir`. The bundled
    browser assets under `/assets/` are served with or without `static_dir`.

    `GET /documents` requires `settings_read_source` by default; a host that
    wants a public document list (a liveness probe, for example) opts in with
    `public_documents=True` rather than getting it by accident.
    """
    dispatch = _build_dispatcher(
        service,
        base=base,
        principal_resolver=_environ_resolver(principal_resolver),
        static_dir=static_dir,
        assets_dir=assets_dir,
        static_map=static_map,
        public_documents=public_documents,
    )

    def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        request = _Request(
            method=environ.get("REQUEST_METHOD", "GET").upper(),
            path=environ.get("PATH_INFO", "") or "/",
            query=environ.get("QUERY_STRING", ""),
            body=_wsgi_body(environ),
            environ=environ,
        )
        return dispatch(request, start_response)

    return app


def _environ_resolver(
    principal_resolver: Callable[[dict[str, Any]], Principal] | None,
) -> Callable[["_Request"], Principal]:
    """Adapt a host environ resolver to the transport-independent dispatcher."""

    def resolve(request: "_Request") -> Principal:
        if principal_resolver is None:
            return Principal.demo()
        return principal_resolver(request.environ if request.environ is not None else {})

    return resolve


def _build_dispatcher(
    service: Service,
    *,
    base: str,
    principal_resolver: Callable[[_Request], Principal] | None = None,
    static_dir: str | Path | None = None,
    assets_dir: str | Path | None = None,
    static_map: dict[str, str] | None = None,
    public_documents: bool = False,
) -> Callable[[_Request, Callable[..., Any]], Iterable[bytes]]:
    """Route one normalized request; shared by every transport."""
    base = base.rstrip("/")
    static_root = Path(static_dir) if static_dir else None
    asset_root = Path(assets_dir) if assets_dir else Path(__file__).parent / "assets"

    def resolve_principal(request: _Request) -> Principal:
        if request.principal is not None:
            return request.principal
        if principal_resolver is None:
            return Principal.demo()
        return principal_resolver(request)

    def dispatch(request: _Request, start_response: Callable[..., Any]) -> Iterable[bytes]:
        method = request.method
        path = request.path or "/"
        try:
            if path == "/api/health" or path == f"{base}/health":
                return _json(start_response, 200, {"ok": True, "aiset": __version__})
            if path.startswith(base):
                route = path[len(base) :] or "/"
                # The bundled editor assets are served under the mount prefix as
                # well as at the application root, so a host that mounts only the
                # API at `base` still gets the editor without a second mount.
                if route.startswith("/assets/"):
                    return _static(start_response, static_root, route, asset_root, static_map or {})
                return _handle_api(
                    service,
                    request,
                    start_response,
                    method,
                    route,
                    resolve_principal(request),
                    public_documents=public_documents,
                )
            if static_root is not None or path.startswith("/assets/"):
                return _static(start_response, static_root, path, asset_root, static_map or {})
            return _json(
                start_response, 404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "Not found"}}
            )
        except AisetError as exc:
            return _json(start_response, exc.http_status, exc.to_envelope())
        except Exception as exc:  # noqa: BLE001 - sanitized unexpected failure
            return _json(
                start_response,
                500,
                {
                    "ok": False,
                    "error": {"code": "INTERNAL_ERROR", "message": "Unexpected server failure",
                              "detail": type(exc).__name__},
                },
            )

    return dispatch


def _wsgi_body(environ: dict[str, Any]) -> bytes:
    """Read the request body a WSGI server has already placed in the environ."""
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise BadRequest("Invalid Content-Length") from None
    stream = environ.get("wsgi.input")
    if stream is None or length <= 0:
        return b""
    return stream.read(length)


# --------------------------------------------------------------------------
# api routes
# --------------------------------------------------------------------------


def _handle_api(
    service: Service,
    request: _Request,
    start_response: Callable[..., Any],
    method: str,
    route: str,
    principal: Principal,
    *,
    public_documents: bool = False,
) -> Iterable[bytes]:
    query = parse_qs(request.query)

    if method == "GET" and route == "/descriptor":
        document = _one(query, "document")
        view = _one(query, "view") or "authorized"
        result = service.descriptor(document, view=view, principal=principal)
        return _json(start_response, 200, result.to_dict())

    if method == "GET" and route == "/value":
        document = _one(query, "document")
        path = _one(query, "path") or ""
        view = _one(query, "view") or "source"
        result = service.get(document, path, view=view, principal=principal)
        return _json(start_response, 200, result.to_dict())

    if method == "GET" and route == "/tree":
        result = service.tree(
            _one(query, "document"),
            _one(query, "path") or "",
            view=_one(query, "view") or "source",
            principal=principal,
        )
        return _json(start_response, 200, {"ok": True, **result})

    if method == "GET" and route == "/documents":
        documents = sorted(service.documents) if public_documents else service.list_documents(principal=principal)
        return _json(start_response, 200, {"ok": True, "documents": documents})

    if method == "POST" and route == "/validate":
        payload = _body(request, service)
        result = service.validate(
            _one(payload, "document"),
            _one(payload, "path") or "",
            payload.get("value_text") or "",
            expected_revision=payload.get("expected_revision"),
            expected_descriptor_revision=payload.get("expected_descriptor_revision"),
            principal=principal,
        )
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/document/validate":
        payload = _body(request, service)
        source = payload.get("source")
        if not isinstance(source, str):
            raise BadRequest("'source' must be a string")
        result = service.validate_document(_one(payload, "document"), source, principal=principal)
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/value":
        payload = _body(request, service)
        result = service.set(
            _one(payload, "document"),
            _one(payload, "path") or "",
            payload.get("value_text") or "",
            expected_revision=payload.get("expected_revision"),
            expected_descriptor_revision=payload.get("expected_descriptor_revision"),
            principal=principal,
        )
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route in ("/operations", "/operations/validate"):
        payload = _body(request, service)
        result = service.apply_operations(
            _one(payload, "document"),
            _operations(payload),
            expected_revision=payload.get("expected_revision"),
            expected_descriptor_revision=payload.get("expected_descriptor_revision"),
            principal=principal,
            dry_run=route.endswith("/validate"),
        )
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/env":
        payload = _body(request, service)
        names = payload.get("names")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise BadRequest("'names' must be a nonempty array of variable names")
        present = service.env_status(_one(payload, "document"), names, principal=principal)
        return _json(start_response, 200, {"ok": True, "present": present})

    if method == "POST" and route == "/load":
        payload = _body(request, service)
        result = service.load(_one(payload, "document"), principal=principal)
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/load/lkg":
        payload = _body(request, service)
        result = service.load_lkg(_one(payload, "document"), principal=principal)
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/descriptor/validate":
        payload = _body(request, service)
        source = payload.get("descriptor_source") or ""
        mode = payload.get("mode") or "default"
        result = service.validate_descriptor(source, mode=mode)
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/merge":
        payload = _body(request, service)
        if "base" not in payload or "update" not in payload:
            raise BadRequest("merge requires 'base' and 'update'")
        prefer = str(payload.get("prefer") or "base")
        if prefer not in PREFERENCES:
            raise BadRequest(f"'prefer' must be one of {list(PREFERENCES)}, got {prefer!r}")
        return _json(
            start_response,
            200,
            {"ok": True, "prefer": prefer, "merged": merge(payload["base"], payload["update"], prefer=prefer)},
        )

    raise AisetError("Unknown route", code="NOT_FOUND")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _operations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the operation list of a staged batch request."""
    operations = payload.get("operations")
    if not isinstance(operations, list) or not all(isinstance(item, dict) for item in operations):
        raise BadRequest("'operations' must be a nonempty array of operation objects")
    return operations


def _one(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _body(request: _Request, service: Service) -> dict[str, Any]:
    """Decode a JSON object request body, enforcing the configured body limit."""
    if len(request.body) > service.settings.limits.max_body_bytes:
        raise PayloadTooLarge(f"Request body exceeds {service.settings.limits.max_body_bytes} bytes")
    raw = request.body
    if len(raw) > service.settings.limits.max_body_bytes:
        raise PayloadTooLarge("Request body is too large")
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequest(f"Malformed JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise BadRequest("Request body must be a JSON object")
    return payload


def _not_found(start_response: Callable[..., Any]) -> Iterable[bytes]:
    return _json(start_response, 404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "Not found"}})


def _json(start_response: Callable[..., Any], status: int, payload: dict[str, Any]) -> Iterable[bytes]:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    start_response(f"{status} {_reason(status)}", JSON_HEADERS + [("Content-Length", str(len(body)))])
    return [body]


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json5": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}


def _http_date(timestamp: float) -> str:
    """RFC 1123 date, used for the Last-Modified validator."""
    return email.utils.formatdate(timestamp, usegmt=True)


def _static(
    start_response: Callable[..., Any],
    root: Path | None,
    path: str,
    assets_root: Path,
    static_map: dict[str, str] | None = None,
) -> Iterable[bytes]:
    """Serve the bundled browser assets and, when a host supplies one, its files.

    `/assets/*` always resolves inside the package, with or without `static_dir`,
    so a host that only wants the API still gets the editor. `root` is required
    for every other route: without it there is no host directory to serve from
    and no path is resolved against the process working directory.
    """
    if path.startswith("/assets/"):
        name = path[len("/assets/") :]
        if "/" in name or ".." in name:
            return _not_found(start_response)
        target = assets_root / name
    elif root is None:
        return _not_found(start_response)
    elif path in ("/", "/index.html"):
        target = root / "index.html"
    elif static_map and path in static_map:
        name = static_map[path]
        if "/" in name or ".." in name:
            return _not_found(start_response)
        target = root / name
    else:
        return _not_found(start_response)
    if not target.is_file():
        return _not_found(start_response)
    body = target.read_bytes()
    content_type = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
    # Assets are served straight from disk: a stale cached script or stylesheet
    # is indistinguishable from a broken one, so never let a browser keep it.
    start_response(
        f"200 {_reason(200)}",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-cache, must-revalidate"),
            ("Last-Modified", _http_date(target.stat().st_mtime)),
        ],
    )
    return [body]


REASONS = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    413: "Payload Too Large",
    422: "Unprocessable Entity",
    428: "Precondition Required",
    500: "Internal Server Error",
    501: "Not Implemented",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def _reason(status: int) -> str:
    return REASONS.get(status, "Status")