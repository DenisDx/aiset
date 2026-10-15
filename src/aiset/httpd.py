"""HTTP adapter (SPEC.md 8.2, SPEC_service.md section 10).

A dependency-free WSGI application: the standalone demo serves it directly and a
host mounts the same app inside its own authenticated server. It is a thin
adapter; every decision belongs to the service.
"""

from __future__ import annotations

import email.utils
import json
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs

from . import __version__
from .errors import AisetError, BadRequest, PayloadTooLarge
from .merge import merge
from .service import Principal, Service

JSON_HEADERS = [("Content-Type", "application/json; charset=utf-8")]


def create_app(
    service: Service,
    *,
    base: str = "/api/settings",
    principal_resolver: Callable[[dict[str, Any]], Principal] | None = None,
    static_dir: str | Path | None = None,
    assets_dir: str | Path | None = None,
    static_map: dict[str, str] | None = None,
) -> Callable[[dict[str, Any], Callable[..., Any]], Iterable[bytes]]:
    """Build the WSGI application for one service.

    `static_map` adds host files (for example a host script or stylesheet) to
    the bundled frontend: route path -> file name inside `static_dir`.
    """
    base = base.rstrip("/")
    static_root = Path(static_dir) if static_dir else None
    asset_root = Path(assets_dir) if assets_dir else Path(__file__).parent / "assets"

    def resolve_principal(environ: dict[str, Any]) -> Principal:
        if principal_resolver is not None:
            return principal_resolver(environ)
        return Principal.demo()

    def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "") or "/"
        try:
            if path == "/api/health" or path == f"{base}/health":
                return _json(start_response, 200, {"ok": True, "aiset": __version__})
            if path.startswith(base):
                return _handle_api(
                    service, environ, start_response, method, path[len(base) :] or "/", resolve_principal
                )
            if static_root is not None:
                return _static(start_response, static_root, path, asset_root, static_map or {})
            return _json(start_response, 404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "Not found"}})
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

    return app


# --------------------------------------------------------------------------
# api routes
# --------------------------------------------------------------------------


def _handle_api(
    service: Service,
    environ: dict[str, Any],
    start_response: Callable[..., Any],
    method: str,
    route: str,
    resolve_principal: Callable[[dict[str, Any]], Principal],
) -> Iterable[bytes]:
    principal = resolve_principal(environ)
    query = parse_qs(environ.get("QUERY_STRING", ""))

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
        return _json(start_response, 200, {"ok": True, "documents": sorted(service.documents)})

    if method == "POST" and route == "/validate":
        payload = _body(environ, service)
        result = service.validate(
            _one(payload, "document"),
            _one(payload, "path") or "",
            payload.get("value_text") or "",
            expected_revision=payload.get("expected_revision"),
            expected_descriptor_revision=payload.get("expected_descriptor_revision"),
            principal=principal,
        )
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/value":
        payload = _body(environ, service)
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
        payload = _body(environ, service)
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
        payload = _body(environ, service)
        names = payload.get("names")
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            raise BadRequest("'names' must be a nonempty array of variable names")
        present = service.env_status(_one(payload, "document"), names, principal=principal)
        return _json(start_response, 200, {"ok": True, "present": present})

    if method == "POST" and route == "/load":
        payload = _body(environ, service)
        result = service.load(_one(payload, "document"), principal=principal)
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/load/lkg":
        payload = _body(environ, service)
        result = service.load_lkg(_one(payload, "document"), principal=principal)
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/descriptor/validate":
        payload = _body(environ, service)
        source = payload.get("descriptor_source") or ""
        mode = payload.get("mode") or "default"
        result = service.validate_descriptor(source, mode=mode)
        return _json(start_response, 200, result.to_dict())

    if method == "POST" and route == "/merge":
        payload = _body(environ, service)
        if "base" not in payload or "update" not in payload:
            raise BadRequest("merge requires 'base' and 'update'")
        return _json(start_response, 200, {"ok": True, "merged": merge(payload["base"], payload["update"])})

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


def _body(environ: dict[str, Any], service: Service) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise BadRequest("Invalid Content-Length") from None
    if length > service.settings.limits.max_body_bytes:
        raise PayloadTooLarge(f"Request body exceeds {service.settings.limits.max_body_bytes} bytes")
    stream = environ.get("wsgi.input")
    raw = stream.read(length) if stream is not None and length else b""
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
    root: Path,
    path: str,
    assets_root: Path,
    static_map: dict[str, str] | None = None,
) -> Iterable[bytes]:
    """Serve the bundled frontend (assets live inside the package)."""
    if path in ("/", "/index.html"):
        target = root / "index.html"
    elif static_map and path in static_map:
        name = static_map[path]
        if "/" in name or ".." in name:
            return _not_found(start_response)
        target = root / name
    elif path.startswith("/assets/"):
        name = path[len("/assets/") :]
        if "/" in name or ".." in name:
            return _not_found(start_response)
        target = assets_root / name
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