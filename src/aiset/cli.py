"""Command line interface (SPEC_service.md section 12).

`aiset validate-descriptor` runs the development diagnostic without starting a
backend or loading project settings.
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "validate-descriptor":
        return _validate_descriptor(args)
    parser.print_help()  # pragma: no cover - argparse guards this
    return 2


def _validate_descriptor(args: argparse.Namespace) -> int:
    try:
        source = sys.stdin.read() if args.descriptor == "-" else open(args.descriptor, encoding="utf-8").read()
    except OSError as exc:
        print(f"aiset: cannot read {args.descriptor}: {exc.strerror}", file=sys.stderr)
        return 2
    try:
        diagnostic = validate_descriptor(source, mode="strict" if args.strict else "default")
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
        location = issue["path"] or "/"
        if issue.get("line"):
            location += f" (line {issue['line']}, column {issue.get('column')})"
        print(f"[{issue['severity']}] {issue['code']} {location}: {issue['message']}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())