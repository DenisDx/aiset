"""Command line interface (SPEC_service.md section 12).

`aiset validate-descriptor` runs the development diagnostic without starting a
backend or loading project settings. `aiset validate-document` loads a real
configuration file against its descriptor, which is the check a host wants in CI.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from . import __version__
from .descriptor import validate_descriptor
from .errors import AisetError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiset", description="aiset command line tools")
    parser.add_argument("--version", action="version", version=f"aiset {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser(
        "validate-descriptor",
        help="validate a descriptor file without starting a backend",
    )
    validate.add_argument("descriptor", help="descriptor file, or '-' for standard input")
    validate.add_argument("--strict", action="store_true", help="unknown properties become errors")
    validate.add_argument(
        "--format", choices=("json", "text"), default="json", help="output format (default json)"
    )
    validate.add_argument(
        "--quiet", action="store_true", help="print nothing when the diagnostic is valid"
    )
    validate.add_argument(
        "--typedef",
        action="append",
        default=[],
        metavar="FILE",
        help="descriptor whose typedefs the target may use; repeatable, as in service.register",
    )

    document = sub.add_parser(
        "validate-document",
        help="load a configuration file against a descriptor and report issues",
    )
    document.add_argument("--config", required=True, metavar="FILE", help="configuration file to load")
    document.add_argument("--descriptor", required=True, metavar="FILE", help="its descriptor")
    document.add_argument(
        "--typedef",
        action="append",
        default=[],
        metavar="FILE",
        help="descriptor whose typedefs the configuration may use; repeatable",
    )
    document.add_argument(
        "--env",
        metavar="FILE",
        help="read placeholders from this file instead of the process environment",
    )
    document.add_argument("--strict", action="store_true", help="unknown descriptor properties become errors")
    document.add_argument(
        "--format", choices=("json", "text"), default="json", help="output format (default json)"
    )
    document.add_argument(
        "--quiet", action="store_true", help="print nothing when the document is valid"
    )
    doctor = sub.add_parser(
        "doctor",
        help="diagnose a configuration file and optionally repair the fixable part",
    )
    doctor.add_argument("--config", required=True, metavar="FILE", help="configuration file to diagnose")
    doctor.add_argument("--descriptor", required=True, metavar="FILE", help="its descriptor")
    doctor.add_argument(
        "--typedef", action="append", default=[], metavar="FILE",
        help="descriptor whose typedefs the configuration may use; repeatable",
    )
    doctor.add_argument(
        "--env", metavar="FILE",
        help="read placeholders from this file instead of the process environment",
    )
    doctor.add_argument("--strict", action="store_true", help="unknown descriptor properties become errors")
    doctor.add_argument(
        "--fix", action="store_true",
        help="apply the safe repairs (clamp); the file is written only if it becomes valid",
    )
    doctor.add_argument(
        "--class", dest="classes", action="append", default=[], metavar="CLASS",
        help="repair class to apply: clamp, coerce, drop_unknown; repeatable",
    )
    doctor.add_argument(
        "--format", choices=("json", "text"), default="json", help="output format (default json)"
    )
    return parser


def _typedefs(paths: Sequence[str]) -> dict[str, Any]:
    """Collect the templates of every `--typedef` source, as `register` does."""
    from .descriptor import _collect_typedefs, parse_descriptor

    templates: dict[str, Any] = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                templates.update(_collect_typedefs(parse_descriptor(handle.read(), origin=f"<{path}>")))
        except OSError as exc:
            print(f"aiset: cannot read {path}: {exc.strerror}", file=sys.stderr)
            raise SystemExit(2) from exc
    return templates


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate-descriptor":
        return _validate_descriptor(args)
    if args.command == "validate-document":
        return _validate_document(args)
    if args.command == "doctor":
        return _doctor(args)
    parser.print_help()  # pragma: no cover - argparse guards this
    return 2


def _read_file(path: str) -> str:
    return open(path, encoding="utf-8").read()


def _read_env(path: str) -> dict[str, str]:
    """Read KEY=VALUE pairs explicitly; the process environment is not consulted."""
    mapping: dict[str, str] = {}
    for line in _read_file(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        mapping[key.strip()] = value
    return mapping


def _emit(payload: dict[str, Any], args: argparse.Namespace) -> None:
    if args.quiet and payload["valid"]:
        return
    if args.format == "json":
        import json

        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)


def _validate_document(args: argparse.Namespace) -> int:
    from .resolver import Resolver
    from .service import Principal, Service

    try:
        descriptor_source = _read_file(args.descriptor)
        config_source = _read_file(args.config)
        typedef_sources = [_read_file(path) for path in args.typedef]
        env_mapping = _read_env(args.env) if args.env else {}
    except OSError as exc:
        print(f"aiset: cannot read {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 2

    diagnostic = validate_descriptor(
        descriptor_source,
        mode="strict" if args.strict else "default",
        known_templates=_typedefs(args.typedef),
    )
    descriptor_errors = [issue for issue in diagnostic.issues if issue.severity == "error"]
    if descriptor_errors:
        _emit({"ok": False, "valid": False, "issues": [issue.to_dict() for issue in descriptor_errors]}, args)
        return 1

    resolver = Resolver(overrides={}, dotenv=env_mapping, environ={}) if args.env else Resolver()
    service = Service()
    try:
        service.register(
            "document",
            args.config,
            descriptor_source,
            resolver=resolver,
            typedef_sources=typedef_sources,
        )
        result = service.validate_document("document", config_source, principal=Principal.demo())
    except AisetError as exc:
        print(f"aiset: {exc.message}", file=sys.stderr)
        return 1
    _emit(
        {"ok": result.valid, "valid": result.valid, "issues": [issue.to_dict() for issue in result.issues]},
        args,
    )
    return 0 if result.valid else 1


def _doctor(args: argparse.Namespace) -> int:
    """Run the doctor against a real file; `--fix` writes it only when it becomes valid."""
    import json

    from .resolver import Resolver
    from .service import Principal, Service

    try:
        descriptor_source = _read_file(args.descriptor)
        typedef_sources = [_read_file(path) for path in args.typedef]
        env_mapping = _read_env(args.env) if args.env else {}
    except OSError as exc:
        print(f"aiset: cannot read {exc.filename}: {exc.strerror}", file=sys.stderr)
        return 2

    diagnostic = validate_descriptor(
        descriptor_source,
        mode="strict" if args.strict else "default",
        known_templates=_typedefs(args.typedef),
    )
    errors = [issue for issue in diagnostic.issues if issue.severity == "error"]
    if errors:
        payload = {"ok": False, "valid": False,
                   "issues": [issue.to_dict() for issue in errors]}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json"
              else _doctor_text(payload))
        return 1

    resolver = Resolver(overrides={}, dotenv=env_mapping, environ={}) if args.env else Resolver()
    fix: object = args.classes if args.classes else bool(args.fix)
    service = Service()
    try:
        service.register(
            "document", args.config, descriptor_source,
            resolver=resolver, typedef_sources=typedef_sources,
        )
        report = service.doctor("document", principal=Principal.demo(), fix=fix)
    except AisetError as exc:
        print(f"aiset: {exc.message}", file=sys.stderr)
        return 1

    payload = report.to_dict()
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_doctor_text(payload))
    if payload["valid"]:
        return 0
    return 2 if payload["applied"] else 1


def _doctor_text(payload: dict[str, Any]) -> str:
    """One line per issue, path first, then the applied fixes."""
    lines = [f"valid: {payload['valid']}"]
    for issue in payload.get("issues", []):
        location = issue.get("path") or "/"
        line = f"  {location} [{issue.get('rule') or issue.get('code')}] {issue.get('message')}"
        if issue.get("fix"):
            line += f"  -> {issue['fix']}"
            if issue.get("before") is not None or issue.get("after") is not None:
                line += f" ({issue.get('before')} => {issue.get('after')})"
        elif issue.get("suggestion"):
            line += f"  ({issue['suggestion']})"
        lines.append(line)
    for fix in payload.get("fixes", []):
        lines.append(f"  applied {fix['action']} {fix['path']}: {fix.get('before')} => {fix.get('after')}")
    for item in payload.get("skipped", []):
        lines.append(f"  skipped {item['path']}: {item['reason']}")
    if payload.get("new_revision"):
        lines.append(f"  revision: {payload['new_revision']}")
    return "\n".join(lines)


def _validate_descriptor(args: argparse.Namespace) -> int:
    try:
        source = sys.stdin.read() if args.descriptor == "-" else open(args.descriptor, encoding="utf-8").read()
    except OSError as exc:
        print(f"aiset: cannot read {args.descriptor}: {exc.strerror}", file=sys.stderr)
        return 2
    try:
        diagnostic = validate_descriptor(
            source,
            mode="strict" if args.strict else "default",
            known_templates=_typedefs(args.typedef),
        )
    except AisetError as exc:  # pragma: no cover - validate_descriptor reports, not raises
        print(f"aiset: {exc.message}", file=sys.stderr)
        return 2
    payload = diagnostic.to_dict()
    if args.quiet and payload["valid"]:
        return 0
    if args.format == "json":
        import json

        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_text(payload)
    return 0 if payload["valid"] else 1


def _print_text(payload: dict[str, Any]) -> None:
    print(f"valid: {payload['valid']}")
    for issue in payload["issues"]:
        location = issue.get("path") or "/"
        if issue.get("line"):
            location += f" (line {issue['line']}, column {issue.get('column')})"
        # Descriptor diagnostics use `code`, value issues use `rule`.
        code = issue.get("code") or issue.get("rule") or ""
        print(f"[{issue['severity']}] {code} {location}: {issue['message']}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())