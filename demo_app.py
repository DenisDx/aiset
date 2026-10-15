#!/usr/bin/env python3
"""Standalone aiset demo (SPEC.md 3.3).

Plain HTTP internal test application: no TLS, no Host/Origin/CSRF/CORS checks,
default bind 0.0.0.0 on port 8383. It runs the same service, store, resolver and
UI assets used by a host integration; there is no demo-only implementation.

    python demo_app.py
    python demo_app.py --aiset.port:12345 --aiset.host:"127.0.0.1"
    python demo_app.py --state-dir /tmp/aiset-demo --aiset.port:0

Command-line parameters use the `--<dotted.path>:<value>` convention and override
the demo configuration. Values are parsed with the same rules as `value_text`:
strings must be quoted, bare tokens are parsed as JSON5.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
if (ROOT / "src").is_dir() and str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from aiset.errors import AisetError  # noqa: E402
from aiset.httpd import create_app  # noqa: E402
from aiset.jsonsrc import Document  # noqa: E402
from aiset.resolver import Resolver  # noqa: E402
from aiset.service import Service  # noqa: E402
from aiset.store import Settings  # noqa: E402

DOCUMENTS = {
    "demo": {"descriptor": "descriptor.json5", "config": "config.json5"},
    "aiset": {"descriptor": "aiset_descriptor.json5", "config": "aiset.json5"},
}


class DemoError(RuntimeError):
    """A startup problem that must be reported instead of hidden."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="demo_app.py",
        description="Run the standalone aiset settings editor",
        add_help=True,
        allow_abbrev=False,
    )
    parser.add_argument("--state-dir", default=None, help="writable directory for editable files")
    parser.add_argument("--config", default=None, help="explicit demo configuration file")
    parser.add_argument("--descriptor", default=None, help="explicit demo descriptor file")
    parser.add_argument("--aiset-config", default=None, help="explicit aiset settings file")
    parser.add_argument("--aiset-descriptor", default=None, help="explicit aiset descriptor file")
    parser.add_argument("--examples-dir", default=None, help="directory holding the tracked examples")
    parser.add_argument("--frontend-dir", default=None, help="directory holding the demo frontend")
    return parser


def parse_overrides(argv: Sequence[str]) -> dict[str, Any]:
    """Parse `--<dotted.path>:<value>` parameters (SPEC.md 3.3)."""
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
                raise DemoError(f"Conflicting override path: {path}")
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


def seed(example: Path, target: Path) -> bool:
    """Seed an editable file from a tracked example only when it is absent."""
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(example.read_bytes())
    return True


def read_json5(path: Path) -> dict[str, Any]:
    document = Document(path.read_text(encoding="utf-8"), origin=path.name)
    value = document.stored_value(document.root)
    if not isinstance(value, dict):
        raise DemoError(f"{path} must contain an object document")
    return value


def prepare(args: argparse.Namespace, overrides: dict[str, Any]) -> dict[str, Any]:
    """Resolve paths, seed missing state, and apply overrides to aiset settings."""
    examples = Path(args.examples_dir) if args.examples_dir else ROOT / "examples"
    state_dir = Path(args.state_dir) if args.state_dir else ROOT / ".local" / "demo"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".writable"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise DemoError(f"Demo state directory is not writable: {state_dir} ({exc.strerror})") from exc

    aiset_config = Path(args.aiset_config) if args.aiset_config else state_dir / "aiset.json5"
    aiset_descriptor = (
        Path(args.aiset_descriptor) if args.aiset_descriptor else examples / "aiset_descriptor.json5"
    )
    if not aiset_config.exists():
        seed(examples / "aiset.json5", aiset_config)
    settings_data = read_json5(aiset_config)
    deep_update(settings_data, overrides)

    demo_config = Path(args.config) if args.config else state_dir / "config.json5"
    demo_descriptor = Path(args.descriptor) if args.descriptor else examples / "descriptor.json5"
    if not demo_config.exists():
        seed(examples / "config.json5", demo_config)

    return {
        "state_dir": state_dir,
        "examples": examples,
        "settings_data": settings_data,
        "documents": {
            "demo": {"config": demo_config, "descriptor": demo_descriptor},
            "aiset": {"config": aiset_config, "descriptor": aiset_descriptor},
        },
    }


def build_service(layout: dict[str, Any], settings: Settings) -> Service:
    service = Service(settings)
    resolver = Resolver()
    for document_id, paths in layout["documents"].items():
        service.register(
            document_id,
            paths["config"],
            paths["descriptor"].read_text(encoding="utf-8"),
            resolver=resolver,
        )
    return service


def start_reread_timer(service: Service, settings: Settings) -> threading.Thread | None:
    """Optional periodic external re-read (SPEC.md 10.4); disabled by default."""
    interval = settings.reread_interval_seconds
    if not interval:
        return None

    def loop() -> None:
        while True:
            time.sleep(interval)
            for document_id in list(service.documents):
                try:
                    service.reread(document_id)
                except Exception as exc:  # noqa: BLE001 - the timer must not die
                    logging.getLogger("aiset").warning("reread_failed %s %s", document_id, exc)

    thread = threading.Thread(target=loop, daemon=True, name="aiset-reread")
    thread.start()
    return thread


def serve(layout: dict[str, Any], service: Service, settings: Settings, frontend: Path) -> int:
    from wsgiref.simple_server import WSGIRequestHandler, make_server

    class QuietHandler(WSGIRequestHandler):
        """The demo logs through the library; access logging stays off."""

        def log_message(self, *args: Any) -> None:  # noqa: D102 - stdlib override
            return

    app = create_app(service, base="/api/settings", static_dir=frontend)
    port = int(settings.demo_port)
    try:
        server = make_server(settings.demo_host, port, app, handler_class=QuietHandler)
    except OSError as exc:
        raise DemoError(
            f"Cannot bind {settings.demo_host}:{port} ({exc.strerror}); "
            "the demo does not choose another port silently"
        ) from exc
    start_reread_timer(service, settings)
    host = settings.demo_host
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"aiset demo listening on http://{shown}:{port}  (Ctrl-C to stop)", flush=True)
    for document_id, paths in sorted(layout["documents"].items()):
        print(f"  document {document_id}: {paths['config']}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    finally:
        server.server_close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args, remaining = parser.parse_known_args(argv)
    overrides = parse_overrides(remaining)
    try:
        layout = prepare(args, overrides)
        settings = Settings.from_mapping(layout["settings_data"])
        logging.basicConfig(
            level=getattr(logging, settings.logging_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        service = build_service(layout, settings)
        frontend = Path(args.frontend_dir) if args.frontend_dir else ROOT / "frontend"
        return serve(layout, service, settings, frontend)
    except (DemoError, AisetError) as exc:
        print(f"aiset demo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())