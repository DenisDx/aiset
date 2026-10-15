"""Minimal `.env` reader for demo2 (proposal_demo2.md section 5.1).

The file is parsed as data: values are returned as a mapping and handed to the
aiset resolver. Nothing is written to `os.environ`, so the process environment
keeps priority exactly as the single global resolver policy requires, and no
value is copied into logs, responses, HTML or saved JSON5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parse `KEY=value` lines; blank lines and `#` comments are ignored."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    return parse_env(file_path.read_text(encoding="utf-8"))


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        if not key:
            continue
        values[key] = _unquote(value.strip())
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def merge(*mappings: Mapping[str, str]) -> dict[str, str]:
    """Later mappings win; used only for explicit host overrides in tests."""
    merged: dict[str, str] = {}
    for mapping in mappings:
        merged.update(mapping)
    return merged