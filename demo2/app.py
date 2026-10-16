#!/usr/bin/env python3
"""demo2: a complete aiset host application (proposal_demo2.md).

It uses aiset as the only configuration storage, validation and editing layer:
the host never parses, validates, edits or atomically writes JSON5 itself. The
host adds what aiset deliberately leaves to the application - process lifecycle,
HTTP routes, and the configuration assistant bound to an OpenAI-compatible
provider.

    ./run_demo2.sh
    ./run_demo2.sh --demo2.server.port:8384

Command-line overrides use the `--<dotted.path>:<value>` convention, have the
highest precedence for the running process, and are never written to
`config.json5`.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiset.errors import AisetError  # noqa: E402
from aiset.httpd import create_app  # noqa: E402
from aiset.merge import merge  # noqa: E402
from aiset.jsonsrc import Document  # noqa: E402
from aiset.resolver import Resolver  # noqa: E402
from aiset.service import Principal, Service  # noqa: E402
from aiset.store import Settings  # noqa: E402

from agent import AgentError, ConfigurationAgent  # noqa: E402
from env import load_env_file  # noqa: E402

HERE = Path(__file__).resolve().parent
DOCUMENT = "demo2"
# A component document that overrides one section of the main configuration
# (SPEC.md 10.1). Its descriptor also owns the templates both documents share.
OVERRIDE_DOCUMENT = "conf2"
OVERRIDE_DIRNAME = "conf2"
OVERRIDE_MOUNT = "includes.conf2"
LOGGER = logging.getLogger("demo2")

# Seconds between the restart acknowledgment and the process re-execution.
RESTART_DELAY = 0.3


class Demo2Error(RuntimeError):
    """A startup problem that must be reported instead of hidden."""


class Host:
    """The demo2 application state shared by routes and callbacks."""

    def __init__(self, service: Service, settings: Settings, agent: ConfigurationAgent | None) -> None:
        self.service = service
        self.settings = settings
        self.agent = agent
        self.applied: dict[str, Any] = {"state": "applied", "revision": None, "paths": []}
        self.reloads = 0
        # The reported application state of every committed change, including
        # levels the application callback is not invoked for (SPEC.md 8.2).
        service.subscribe(
            DOCUMENT, [""], self._record_change, principal=Principal.demo()
        )

    def _record_change(self, event) -> None:
        self.applied = {
            "state": event.application_state,
            "paths": list(event.changed_paths),
            "revision": event.revision,
        }

    # -- lifecycle ------------------------------------------------------
    def on_application(self, before: Any, after: Any, changed_paths: list[str]) -> None:
        """Host application callback: reload for `reload`, remember for `restart`."""
        level = "live"
        for path in changed_paths:
            from aiset.descriptor import node_at

            node = node_at(self.service.documents[DOCUMENT].descriptor, path)
            if node is not None and node.apply:
                level = max(level, node.apply, key=lambda value: ("live", "reload", "restart").index(value))
        self.applied = {
            "state": f"{level}_required" if level != "live" else "applied",
            "paths": list(changed_paths),
            "revision": self.service.states[DOCUMENT].revision,
        }
        LOGGER.info("application level=%s paths=%s", self.applied["state"], changed_paths)

    def reread(self) -> dict[str, Any]:
        """Explicit re-read; a valid external edit is adopted, an invalid one is recovered."""
        self.reloads += 1
        result = self.service.reread(DOCUMENT, principal=Principal.demo())
        return {
            "ok": True,
            "loaded": result.loaded,
            "revision": result.revision,
            "invalid_on_disk": result.invalid_on_disk,
            "reason": result.reason,
            "reloads": self.reloads,
        }

    def restart(self) -> dict[str, Any]:
        """Acknowledge the request; the process is re-executed after the reply."""
        return {
            "ok": True,
            "restarting": True,
            "message": f"demo2 will restart in {RESTART_DELAY:g}s with the same interpreter and arguments",
            "applied": self.applied,
            "pid": os.getpid(),
        }


# --------------------------------------------------------------------------
# startup
# --------------------------------------------------------------------------


def parse_overrides(argv: list[str]) -> dict[str, Any]:
    """Parse `--<dotted.path>:<value>` overrides (proposal section 4)."""
    overrides: dict[str, Any] = {}
    for argument in argv:
        if not argument.startswith("--") or ":" not in argument:
            continue
        path, _, raw = argument[2:].partition(":")
        if not path:
            continue
        node: Any = overrides
        tokens = path.split(".")
        for token in tokens[:-1]:
            node = node.setdefault(token, {})
            if not isinstance(node, dict):
                raise Demo2Error(f"Conflicting override path: {path}")
        node[tokens[-1]] = _parse_value(raw)
    return overrides


def _parse_value(raw: str) -> Any:
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    try:
        document = Document(text)
        return document.stored_value(document.root)
    except AisetError:
        return text


def deep_update(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def normalize_overrides(overrides: dict[str, Any], document: str = DOCUMENT) -> dict[str, Any]:
    """Accept `--<document>.<config.path>:<value>` and a bare `<config.path>`."""
    if document in overrides and isinstance(overrides[document], dict):
        rest = {key: value for key, value in overrides.items() if key != document}
        return deep_update(rest, overrides[document])
    return overrides


def override_paths(state_dir: Path) -> dict[str, Path]:
    """Files of the component document, when the component folder is present."""
    folder = state_dir / OVERRIDE_DIRNAME
    found = {"folder": folder}
    for name in ("config.json5", "descriptor.json5"):
        path = folder / name
        if path.is_file():
            found[name.rsplit(".", 1)[0]] = path
    return found


def build_override(service: Service, state_dir: Path, dotenv: dict[str, str]) -> dict[str, Any]:
    """Register the component document and merge it onto the main section.

    The component file is a partial update (SPEC.md 10.1): it is merged onto
    `includes.conf2`, never written over it, and the base stays on disk.
    """
    paths = override_paths(state_dir)
    if "config" not in paths or "descriptor" not in paths:
        return {"ok": False, "reason": "no component document", "changed": []}
    service.register(
        OVERRIDE_DOCUMENT,
        paths["config"],
        paths["descriptor"].read_text(encoding="utf-8"),
        resolver=Resolver(dotenv=dotenv),
    )
    loaded = service.load(OVERRIDE_DOCUMENT, principal=Principal.demo())
    if loaded.invalid_on_disk:
        raise Demo2Error(f"Override document is invalid: {loaded.reason}")
    return {"ok": True, "effective": loaded.effective, "paths": paths}


# The component document is merged with the library default: the base wins every
# conflict, so the update fills gaps and deep-merges objects (SPEC_.md 5).
MERGE_PREFER = "base"


def merged_override(host: Any) -> dict[str, Any]:
    """The effective value of the merged section and what the update changed."""
    service = host.service
    if OVERRIDE_DOCUMENT not in service.documents:
        return {"ok": False, "reason": "no component document", "changed": []}
    update = service.states.get(OVERRIDE_DOCUMENT)
    base = service.states.get(DOCUMENT)
    if update is None or base is None:
        return {"ok": False, "reason": "not loaded", "changed": []}
    section = ((base.effective.get("includes") or {}).get(OVERRIDE_DOCUMENT) or {})
    merged = merge(section, update.effective, prefer=MERGE_PREFER)
    return {
        "ok": True,
        "document": OVERRIDE_DOCUMENT,
        "mount": OVERRIDE_MOUNT,
        "prefer": MERGE_PREFER,
        "base": section,
        "merged": merged,
        "changed": changed_paths(section, merged),
        "from_update": changed_paths(section, update.effective),
        "revision": update.revision,
    }


def changed_paths(base: Any, merged: Any, prefix: str = "") -> list[str]:
    """Every path whose value differs between the base section and the merge."""
    if not isinstance(base, dict) or not isinstance(merged, dict):
        return [] if base == merged else [prefix or "/"]
    out: list[str] = []
    for key, value in merged.items():
        path = f"{prefix}/{key}"
        if key not in base:
            out.append(path)
        elif isinstance(value, dict) and isinstance(base[key], dict):
            out.extend(changed_paths(base[key], value, path))
        elif base[key] != value:
            out.append(path)
    return out


def build(config_path: Path, descriptor_path: Path, env_path: Path, overrides: dict[str, Any]):
    """Register the document and return (service, settings, effective)."""
    dotenv = load_env_file(env_path)
    settings = Settings(backup_depth=5, lock_timeout_seconds=5.0)
    service = Service(settings, audit=lambda name, payload: LOGGER.info("audit %s %s", name, sorted(payload)))
    override_descriptor = override_paths(config_path.parent).get("descriptor")
    service.register(
        DOCUMENT,
        config_path,
        descriptor_path.read_text(encoding="utf-8"),
        # The component descriptor owns the shared `typedef`s: the main
        # descriptor may use them without redeclaring them (SPEC.md 4.6.10).
        typedef_sources=[override_descriptor.read_text(encoding="utf-8")] if override_descriptor else [],
        # `.env` is data for the resolver; the process environment has priority,
        # exactly as the single global policy of SPEC.md section 6 requires.
        resolver=Resolver(dotenv=dotenv),
    )
    loaded = service.load(DOCUMENT, principal=Principal.demo())
    if loaded.invalid_on_disk:
        raise Demo2Error(
            f"Configuration is invalid: {loaded.reason}. Fix {config_path.name} or run with a valid backup."
        )
    build_override(service, config_path.parent, dotenv)
    if overrides:
        # Startup overrides apply to the running process only.
        deep_update(loaded.effective, normalize_overrides(overrides))
    return service, settings, loaded.effective


def resolve_listen(effective: dict[str, Any]) -> tuple[str, int]:
    server = effective.get("server") or {}
    host = str(server.get("host") or "0.0.0.0")
    try:
        port = int(server.get("port") or 8383)
    except (TypeError, ValueError) as exc:
        raise Demo2Error(f"server.port must resolve to an integer, got {server.get('port')!r}") from exc
    return host, port


def build_agent(effective: dict[str, Any]) -> ConfigurationAgent | None:
    settings = effective.get("ai") or {}
    if not settings.get("enabled"):
        LOGGER.info("ai assistant disabled by configuration")
        return None
    model = str(settings.get("model") or "").strip()
    if not model:
        raise Demo2Error("ai.model must not be empty; set DEMO2_AI_MODEL in demo2/.env")
    provider = settings.get("provider") or {}
    base_url = str(provider.get("base_url") or "").strip()
    if not base_url:
        raise Demo2Error("ai.provider.base_url must not be empty; set DEMO2_AI_BASE_URL in demo2/.env")
    return ConfigurationAgent(
        service=None,  # wired by create_app once the service exists
        base_url=base_url,
        api_key=str(provider.get("api_key") or ""),
        model=model,
        timeout_seconds=float(settings.get("timeout_seconds") or 60),
        temperature=float(settings.get("temperature") if settings.get("temperature") is not None else 0.2),
        max_tool_rounds=int(settings.get("max_tool_rounds") or 8),
    )


# --------------------------------------------------------------------------
# host routes
# --------------------------------------------------------------------------


def host_app(host: Host, frontend: Path, restart_hook: Callable[[], None] | None = None):
    """Mount aiset plus the demo2 routes and static frontend."""
    app = create_app(
        host.service,
        base="/api/settings",
        static_dir=frontend,
        principal_resolver=lambda environ: Principal.demo(),
        static_map={"/app.js": "app.js", "/styles.css": "styles.css"},
    )

    def dispatch(environ, start_response):
        path = environ.get("PATH_INFO", "")
        method = environ.get("REQUEST_METHOD", "GET").upper()
        if path.startswith("/api/demo2/"):
            return _route(host, environ, start_response, method, path[len("/api/demo2/") :], restart_hook)
        return app(environ, start_response)

    return dispatch


def _json(start_response, status: int, payload: dict[str, Any]):
    import json

    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    start_response(
        f"{status} {_REASONS.get(status, 'Status')}",
        [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))],
    )
    return [body]


_AGENT_STATUS = {
    "PROVIDER_UNREACHABLE": 503,
    "PROVIDER_TIMEOUT": 504,
    "PROVIDER_HTTP_ERROR": 502,
    "PROVIDER_PROTOCOL": 502,
    "BAD_REQUEST": 400,
}

_REASONS = {
    200: "OK",
    502: "Bad Gateway",
    504: "Gateway Timeout",
    400: "Bad Request",
    404: "Not Found",
    409: "Conflict",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def _route(host: Host, environ, start_response, method: str, route: str, restart_hook):
    try:
        if method == "GET" and route == "health":
            return _json(start_response, 200, {"ok": True, "app": "demo2", "document": DOCUMENT})
        if method == "GET" and route == "status":
            loaded = host.service._state(DOCUMENT)  # noqa: SLF001 - host-owned view of its own state
            return _json(
                start_response,
                200,
                {
                    "ok": True,
                    "revision": loaded.revision,
                    "descriptor_revision": host.service.documents[DOCUMENT].descriptor.revision,
                    "applied": host.applied,
                    "reloads": host.reloads,
                    "documents": sorted(host.service.documents),
                    "override": merged_override(host),
                    "ai": {"enabled": host.agent is not None, "model": host.agent.model if host.agent else None},
                },
            )
        if method == "POST" and route == "reload":
            return _json(start_response, 200, host.reread())
        if method == "POST" and route == "restart":
            result = host.restart()
            if restart_hook is not None:
                # The acknowledgment must reach the browser before the process
                # is replaced, so the re-execution is scheduled, not immediate.
                threading.Timer(RESTART_DELAY, restart_hook).start()
            return _json(start_response, 200, result)
        if method == "POST" and route == "chat":
            payload = _body(environ)
            if host.agent is None:
                return _json(
                    start_response,
                    503,
                    {"ok": False, "error": {"code": "UNSUPPORTED_CAPABILITY",
                                            "message": "The AI assistant is disabled by configuration"}},
                )
            try:
                result = host.agent.handle(payload)
            except AgentError as exc:
                # Provider and protocol failures stay explicit, never success-shaped.
                return _json(
                    start_response,
                    _AGENT_STATUS.get(exc.code, 502),
                    {
                        "ok": False,
                        "error": {
                            "code": exc.code,
                            "message": str(exc),
                            "detail": exc.detail[:400] if exc.detail else "",
                        },
                    },
                )
            return _json(start_response, 200, {"ok": True, **result})
        if method == "GET" and route == "chat/history":
            session = environ.get("HTTP_X_AISET_SESSION", "")
            history = host.agent.history(session) if host.agent else []
            return _json(start_response, 200, {"ok": True, "messages": history})
        return _json(
            start_response,
            404,
            {"ok": False, "error": {"code": "NOT_FOUND", "message": f"Unknown host route {route!r}"}},
        )
    except AisetError as exc:
        return _json(start_response, exc.http_status, exc.to_envelope())
    except Exception as exc:  # noqa: BLE001 - sanitized host failure
        LOGGER.error("host route failed: %s", exc)
        return _json(
            start_response,
            500,
            {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Unexpected host failure"}},
        )


def _body(environ) -> dict[str, Any]:
    import json

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise Demo2Error("Invalid Content-Length") from None
    if length > 1024 * 1024:
        raise Demo2Error("Request body is too large")
    stream = environ.get("wsgi.input")
    raw = stream.read(length) if stream is not None and length else b""
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Demo2Error(f"Malformed JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise Demo2Error("Request body must be a JSON object")
    return payload


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    argv = list(sys.argv[1:] if argv is None else argv)
    overrides = parse_overrides(argv)
    state_dir = Path(os.environ.get("DEMO2_STATE_DIR") or HERE)
    config_path = Path(os.environ.get("DEMO2_CONFIG") or state_dir / "config.json5")
    descriptor_path = Path(os.environ.get("DEMO2_DESCRIPTOR") or state_dir / "descriptor.json5")
    env_path = Path(os.environ.get("DEMO2_ENV") or state_dir / ".env")
    frontend = Path(os.environ.get("DEMO2_FRONTEND") or HERE / "frontend")

    try:
        service, settings, effective = build(config_path, descriptor_path, env_path, overrides)
    except (Demo2Error, AisetError) as exc:
        print(f"demo2: {exc}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=getattr(logging, str(effective.get("runtime", {}).get("log_level", "info")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        agent = build_agent(effective)
    except Demo2Error as exc:
        print(f"demo2: {exc}", file=sys.stderr)
        return 1

    host = Host(service, settings, agent)
    service.on_application(host.on_application)
    if agent is not None:
        agent.service = service

    host_name, port = resolve_listen(effective)
    interval = float(effective.get("runtime", {}).get("reread_interval_seconds") or 0)

    class Quiet(WSGIRequestHandler):
        def log_message(self, *args: Any) -> None:
            return

    def restart_hook() -> None:
        """Re-execute this file with the same interpreter and arguments (POSIX)."""
        argv_replacement = [sys.executable, str(Path(__file__).resolve()), *argv]
        os.execv(sys.executable, argv_replacement)

    app = host_app(host, frontend, restart_hook=restart_hook)
    try:
        server = make_server(host_name, port, app, handler_class=Quiet)
    except OSError as exc:
        print(
            f"demo2: cannot bind {host_name}:{port} ({exc.strerror}); "
            "the host does not choose another port silently",
            file=sys.stderr,
        )
        return 1

    if interval > 0:
        _start_timer(host, interval)
    shown = "127.0.0.1" if host_name in ("0.0.0.0", "::") else host_name
    print(f"demo2 listening on http://{shown}:{port}  (Ctrl-C to stop)", flush=True)
    print(f"  document {DOCUMENT}: {config_path}", flush=True)
    print(f"  ai assistant: {'on' if agent else 'off'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        server.server_close()
    return 0


def _start_timer(host: Host, interval: float) -> None:
    import threading
    import time

    def loop() -> None:
        while True:
            time.sleep(interval)
            try:
                host.reread()
            except Exception as exc:  # noqa: BLE001 - the timer must not die
                LOGGER.warning("reread failed: %s", exc)

    threading.Thread(target=loop, daemon=True, name="demo2-reread").start()


if __name__ == "__main__":
    raise SystemExit(main())