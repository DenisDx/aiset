"""Environment template resolution (SPEC.md section 6).

One global policy for every host: explicit host overrides, then the process
environment, then a supplied `.env` mapping, then the placeholder's inline
default, then the descriptor/config default. `:-` uses POSIX shell semantics
and is the only supported operator. Resolution is single pass: environment
values are data and can never inject structure.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from .descriptor import Node
from .jsonsrc import TemplateRef
from .validator import MAX_EXACT_INT, MIN_EXACT_INT, ValueIssue

PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}")


@dataclass
class Resolver:
    """Resolver inputs; tests inject their own mapping instead of the process env."""

    overrides: Mapping[str, str] = field(default_factory=dict)
    dotenv: Mapping[str, str] = field(default_factory=dict)
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)

    def lookup(self, name: str, inline_default: str | None) -> tuple[str, str]:
        """Return (value, source) where source is overrides/env/dotenv/default/empty."""
        for mapping, origin in (
            (self.overrides, "override"),
            (self.environ, "env"),
            (self.dotenv, "dotenv"),
        ):
            if name in mapping:
                value = mapping[name]
                if value != "":
                    return value, origin
                if inline_default is None:
                    return "", origin
        if inline_default is not None:
            return inline_default, "inline_default"
        return "", "empty"

    def resolve_text(self, text: str, path: str, issues: list[ValueIssue],
                     provenance: dict[str, Any] | None) -> str:
        """Substitute placeholders inside a string; the result is data, not source."""

        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(3)
            value, origin = self.lookup(name, default)
            if provenance is not None:
                entry: dict[str, Any] = {"kind": "environment", "variable": name}
                if origin != "env":
                    entry["source"] = origin
                provenance[path] = entry
            return value

        return PLACEHOLDER_RE.sub(replace, text)


def resolve_value(
    value: Any,
    node: Node | None,
    resolver: Resolver,
    path: str,
    issues: list[ValueIssue],
    *,
    provenance: dict[str, Any] | None = None,
) -> Any:
    """Resolve a stored semantic tree into an effective value."""
    if isinstance(value, TemplateRef):
        return _resolve_template(value, node, resolver, path, issues, provenance)
    if isinstance(value, str):
        if not PLACEHOLDER_RE.search(value):
            _record_file(value, path, provenance)
            return value
        if node is None or not node.env_allowed:
            _record_file(value, path, provenance)
            return value
        resolved = resolver.resolve_text(value, path, issues, provenance)
        if node.env_convert and node.env_convert != "string":
            return _convert(resolved, node, path, issues)
        return resolved
    if isinstance(value, dict) and node is not None:
        return {
            key: resolve_value(
                item,
                _object_child_node(node, key),
                resolver,
                f"{path}/{_escape(key)}",
                issues,
                provenance=provenance,
            )
            for key, item in value.items()
        }
    if isinstance(value, list) and node is not None:
        return [
            resolve_value(item, _array_item_node(node, index), resolver,
                          f"{path}/{index}", issues, provenance=provenance)
            for index, item in enumerate(value)
        ]
    _record_file(value, path, provenance)
    return value


def _record_file(value: Any, path: str, provenance: dict[str, Any] | None) -> None:
    if provenance is not None and path:
        provenance[path] = {"kind": "file"}


def _object_child_node(node: Node, key: str) -> Node | None:
    child = node.children.get(key) if node.children else None
    if child is not None:
        return child
    if node.additional_children is None:
        return None
    if node.key_enum and key not in node.key_enum:
        return None
    return node.additional_children


def _array_item_node(node: Node, index: int) -> Node | None:
    if node.option_nodes is not None:
        return node.option_nodes[0] if node.option_nodes else None
    return node.item_node


def _resolve_template(
    ref: TemplateRef,
    node: Node | None,
    resolver: Resolver,
    path: str,
    issues: list[ValueIssue],
    provenance: dict[str, Any] | None,
) -> Any:
    if node is None or not node.env_allowed:
        issues.append(
            ValueIssue(path, "env_not_allowed",
                       "Unquoted placeholder requires env.allowed on the descriptor node")
        )
        return None
    value, origin = resolver.lookup(ref.name, ref.default)
    if provenance is not None:
        entry: dict[str, Any] = {"kind": "environment", "variable": ref.name}
        if origin != "env":
            entry["source"] = origin
        provenance[path] = entry
    convert = node.env_convert or "string"
    return _convert(value, node, path, issues, convert=convert, raw=value)


def _convert(
    value: str, node: Node, path: str, issues: list[ValueIssue], *, convert: str | None = None,
    raw: Any = None,
) -> Any:
    convert = convert or (node.env_convert or "string")
    if convert == "string":
        return value
    if convert == "bool":
        if value == "true":
            return True
        if value == "false":
            return False
        issues.append(
            ValueIssue(path, "env_conversion", "Boolean conversion accepts only 'true' or 'false'")
        )
        return None
    text = (raw if isinstance(raw, str) else str(raw)).strip()
    if not text:
        issues.append(ValueIssue(path, "env_conversion", "Empty value cannot be converted"))
        return None
    try:
        number: int | float
        if convert == "int":
            if not re.fullmatch(r"[+-]?\d+", text):
                raise ValueError("not an integer")
            number = int(text)
            if not MIN_EXACT_INT <= number <= MAX_EXACT_INT:
                raise ValueError("outside the exact integer range")
        else:
            number = float(text)
            if number != number or number in (float("inf"), float("-inf")):
                raise ValueError("not finite")
    except ValueError:
        issues.append(ValueIssue(path, "env_conversion", f"Value cannot be converted to {convert}"))
        return None
    return number


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def effective_at(
    stored: Any,
    node: Node | None,
    resolver: Resolver,
    path: str,
    *,
    provenance: dict[str, Any] | None = None,
) -> tuple[Any, list[ValueIssue]]:
    """Effective value of one subtree, with defaults applied inside it."""
    if node is None or stored is MISSING or is_missing(stored):
        if node is not None and node.has_default:
            if provenance is not None:
                provenance[path or "/"] = {"kind": "default"}
            return node.default, []
        return MISSING, []
    issues: list[ValueIssue] = []
    filled = _with_defaults(stored, node, path, issues, provenance)
    resolved = resolve_value(filled, node, resolver, path, issues, provenance=provenance)
    return resolved, issues


def build_effective(
    stored: Any,
    node: Node,
    resolver: Resolver,
    *,
    provenance: dict[str, Any] | None = None,
) -> tuple[Any, list[ValueIssue]]:
    """Effective snapshot: resolved, defaulted and validated values (SPEC.md 6)."""
    issues: list[ValueIssue] = []
    value = _with_defaults(stored, node, "", issues, provenance)
    value = resolve_value(value, node, resolver, "", issues, provenance=provenance)
    return value, issues


def _with_defaults(
    stored: Any,
    node: Node | None,
    path: str,
    issues: list[ValueIssue],
    provenance: dict[str, Any] | None,
) -> Any:
    """Insert effective defaults for absent optional fields; source is untouched."""
    if node is None:
        return stored
    if stored is _MISSING:
        if node.has_default:
            if provenance is not None:
                provenance[path or "/"] = {"kind": "default"}
            return node.default
        return _MISSING
    if isinstance(stored, dict) and node.type == "object":
        result: dict[str, Any] = {}
        names = set(node.children or {})
        for name, child in (node.children or {}).items():
            if name in stored:
                result[name] = _with_defaults(
                    stored[name], child, f"{path}/{_escape(name)}", issues, provenance
                )
            else:
                filled = _with_defaults(_MISSING, child, f"{path}/{_escape(name)}", issues, provenance)
                if filled is not _MISSING:
                    result[name] = filled
        for key, item in stored.items():
            if key in names:
                continue
            child = node.additional_children if node.additional_children is not None else None
            result[key] = _with_defaults(item, child, f"{path}/{_escape(key)}", issues, provenance)
        return result
    if isinstance(stored, list) and node.type == "array":
        return [
            _with_defaults(item, _item_node(node, index), f"{path}/{index}", issues, provenance)
            for index, item in enumerate(stored)
        ]
    return stored


def _item_node(node: Node, index: int) -> Node | None:
    if node.option_nodes:
        return node.option_nodes[0]
    return node.item_node


class _Missing:
    """Sentinel for an absent value; distinct from an explicit null."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "<missing>"


_MISSING = _Missing()
MISSING = _MISSING


def is_missing(value: Any) -> bool:
    return value is _MISSING