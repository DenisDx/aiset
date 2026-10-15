"""Value validation against a compiled descriptor (SPEC.md sections 4 and 5).

Server-side rules are exact and authoritative (SPEC.md 9): `bool` is never an
`int`, fractional values are rejected for `int`, numeric bounds and the
portable exact integer range are enforced, and missing, explicit null and
default values stay distinguishable.
"""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from .descriptor import Node
from .jsonsrc import TemplateRef

MAX_EXACT_INT = 9007199254740991
MIN_EXACT_INT = -9007199254740991


@dataclass
class ValueIssue:
    """Structured validation problem (SPEC_service.md section 7)."""

    path: str
    rule: str
    message: str
    severity: str = "error"
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"path": self.path, "rule": self.rule, "message": self.message,
                               "severity": self.severity}
        if self.line is not None:
            out["line"] = self.line
        if self.column is not None:
            out["column"] = self.column
        return out


@dataclass
class Limits:
    """Operational limits (SPEC.md section 11); all are configurable."""

    max_file_size: int = 8 * 1024 * 1024
    max_body_size: int = 8 * 1024 * 1024
    max_depth: int = 64
    max_collection_size: int = 100_000
    max_string_length: int = 1024 * 1024
    max_pattern_length: int = 512
    regex_timeout_ms: int = 100
    max_body_bytes: int = 8 * 1024 * 1024


DEFAULT_LIMITS = Limits()

# Portable regex subset (SPEC.md 4.2): no backreferences, no inline flags,
# no lookaround, no conditional patterns.
FORBIDDEN_PATTERN_FEATURES = ("(?=", "(?!", "(?<", "(?P=", "\\1", "\\g<")
_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


@dataclass
class ValidationContext:
    """Carries limits and collected warnings during one validation pass."""

    limits: Limits = field(default_factory=Limits)
    issues: list[ValueIssue] = field(default_factory=list)

    def add(self, path: str, rule: str, message: str, severity: str = "error") -> None:
        self.issues.append(ValueIssue(path=path, rule=rule, message=message, severity=severity))


def check_limits(value: Any, limits: Limits, *, path: str = "") -> list[ValueIssue]:
    """Cheap structural limits, applied before expensive validation."""
    issues: list[ValueIssue] = []

    def walk(node: Any, current: str, depth: int) -> None:
        if depth > limits.max_depth:
            issues.append(ValueIssue(current or "", "max_depth", f"Depth exceeds {limits.max_depth}"))
            return
        if isinstance(node, dict):
            if len(node) > limits.max_collection_size:
                issues.append(
                    ValueIssue(current, "max_collection_size",
                               f"Object exceeds {limits.max_collection_size} keys")
                )
            for key, item in node.items():
                if len(key) > limits.max_string_length:
                    issues.append(
                        ValueIssue(current, "max_string_length", "Object key is too long")
                    )
                walk(item, f"{current}/{_escape(key)}", depth + 1)
        elif isinstance(node, list):
            if len(node) > limits.max_collection_size:
                issues.append(
                    ValueIssue(current, "max_collection_size",
                               f"Array exceeds {limits.max_collection_size} items")
                )
            for index, item in enumerate(node):
                walk(item, f"{current}/{index}", depth + 1)
        elif isinstance(node, str):
            if len(node) > limits.max_string_length:
                issues.append(
                    ValueIssue(current, "max_string_length",
                               f"String exceeds {limits.max_string_length} characters")
                )
        elif isinstance(node, float) and not math.isfinite(node):
            issues.append(ValueIssue(current, "finite", "Value must be finite"))

    walk(value, path, 0)
    return issues


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


# --------------------------------------------------------------------------
# type helpers
# --------------------------------------------------------------------------


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def type_matches(node_type: str, value: Any) -> bool:
    if node_type == "string":
        return isinstance(value, str)
    if node_type == "bool":
        return isinstance(value, bool)
    if node_type == "int":
        return is_int(value)
    if node_type == "number":
        return is_number(value) and not (isinstance(value, float) and not math.isfinite(value))
    if node_type == "null":
        return value is None
    if node_type == "object":
        return isinstance(value, dict)
    if node_type == "array":
        return isinstance(value, list)
    if node_type == "union":
        return True
    return True


def type_error(node: Node, value: Any) -> str:
    return f"Expected {node.type}, got {_kind_of(value)}"


def _kind_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, TemplateRef):
        return "template"
    return type(value).__name__


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def validate_value(
    value: Any,
    node: Node | None,
    path: str,
    context: ValidationContext,
    *,
    present: bool = True,
) -> list[ValueIssue]:
    """Validate one value against its descriptor node."""
    issues: list[ValueIssue] = []
    if node is None:
        issues.append(ValueIssue(path, "undeclared_path", "Path is not declared by the descriptor"))
        return issues
    if isinstance(value, TemplateRef):
        issues.append(
            ValueIssue(path, "unresolved_template",
                       "Placeholder must be resolved before validation")
        )
        return issues
    if not present:
        return issues
    if value is None:
        if node.nullable or node.type == "null":
            return issues
        issues.append(ValueIssue(path, "nullable", "Value must not be null"))
        return issues

    if node.type == "union":
        return _validate_union(value, node, path, context)
    if not type_matches(node.type, value):
        issues.append(ValueIssue(path, "type", type_error(node, value)))
        return issues

    if node.type == "int":
        if isinstance(value, int) and not MIN_EXACT_INT <= value <= MAX_EXACT_INT:
            issues.append(
                ValueIssue(path, "exact_range",
                           f"Integer must be within [{MIN_EXACT_INT}, {MAX_EXACT_INT}]")
            )
    if node.type == "object":
        issues.extend(_validate_object(value, node, path, context))
    elif node.type == "array":
        issues.extend(_validate_array(value, node, path, context))
    elif node.type == "string":
        issues.extend(_validate_string(value, node, path, context))

    if node.type in ("int", "number"):
        if node.minimum is not None and value < node.minimum:
            issues.append(ValueIssue(path, "minimum", f"Must be at least {node.minimum}"))
        if node.maximum is not None and value > node.maximum:
            issues.append(ValueIssue(path, "maximum", f"Must be at most {node.maximum}"))

    if node.const is not None and not _same(node.const, value):
        issues.append(ValueIssue(path, "const", "Value differs from the fixed value"))
    if node.enum is not None and not any(_same(option, value) for option in node.enum):
        issues.append(ValueIssue(path, "enum", "Value is not one of the allowed values"))
    return issues


def _same(expected: Any, actual: Any) -> bool:
    """Equality without implicit type conversion (true is not 1)."""
    if isinstance(expected, bool) != isinstance(actual, bool):
        return False
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return float(expected) == float(actual)
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, list):
        return len(expected) == len(actual) and all(_same(a, b) for a, b in zip(expected, actual))
    if isinstance(expected, dict):
        return expected.keys() == actual.keys() and all(
            _same(expected[key], actual[key]) for key in expected
        )
    return expected == actual


def _validate_union(value: Any, node: Node, path: str, context: ValidationContext) -> list[ValueIssue]:
    options = node.option_nodes or []
    matched: list[ValueIssue] = []
    reported: list[ValueIssue] | None = None
    for option in options:
        found = validate_value(value, option, path, context)
        if not found:
            return []
        if reported is None or len(found) < len(reported):
            reported = found
        matched.extend(found)
    detail = "; ".join(f"{issue.rule}: {issue.message}" for issue in (reported or matched)[:3])
    return [
        ValueIssue(path, "union", f"Value matches none of the {len(options)} alternatives ({detail})")
    ]


def _validate_object(
    value: dict[str, Any], node: Node, path: str, context: ValidationContext
) -> list[ValueIssue]:
    issues: list[ValueIssue] = []
    limits = context.limits
    if len(value) > limits.max_collection_size:
        issues.append(
            ValueIssue(path, "max_collection_size", f"Object exceeds {limits.max_collection_size} keys")
        )
    for key, item in value.items():
        if len(key) > limits.max_string_length:
            issues.append(ValueIssue(path, "max_string_length", "Object key is too long"))
        child_path = f"{path}/{_escape(key)}"
        child = node.children.get(key) if node.children else None
        if child is None:
            if node.additional_children is None:
                issues.append(
                    ValueIssue(child_path, "undeclared_field", f"Field {key!r} is not declared")
                )
                continue
            if node.key_enum and key not in node.key_enum:
                issues.append(
                    ValueIssue(child_path, "key_enum", f"Key {key!r} is not in key_enum")
                )
            if node.key_pattern and not _regex_ok(node.key_pattern, key, context):
                issues.append(
                    ValueIssue(child_path, "key_pattern", f"Key {key!r} does not match key_pattern")
                )
            child = node.additional_children
        issues.extend(validate_value(item, child, child_path, context))
    for name, child in (node.children or {}).items():
        if child.required and name not in value:
            issues.append(
                ValueIssue(f"{path}/{_escape(name)}", "required", f"Field {name!r} is required")
            )
    return issues


def _validate_array(
    value: list[Any], node: Node, path: str, context: ValidationContext
) -> list[ValueIssue]:
    issues: list[ValueIssue] = []
    limits = context.limits
    if len(value) > limits.max_collection_size:
        issues.append(
            ValueIssue(path, "max_collection_size", f"Array exceeds {limits.max_collection_size} items")
        )
    if node.min_items is not None and len(value) < node.min_items:
        issues.append(ValueIssue(path, "min_items", f"Must contain at least {node.min_items} items"))
    if node.max_items is not None and len(value) > node.max_items:
        issues.append(ValueIssue(path, "max_items", f"Must contain at most {node.max_items} items"))
    if node.unique_items:
        for index, item in enumerate(value):
            if any(_same(item, other) for other in value[index + 1 :]):
                issues.append(ValueIssue(f"{path}/{index}", "unique_items", "Items must be unique"))
                break
    for index, item in enumerate(value):
        item_path = f"{path}/{index}"
        if node.option_nodes is not None:
            issues.extend(_validate_union(item, node, item_path, context))
        else:
            issues.extend(validate_value(item, node.item_node, item_path, context))
    return issues


def _validate_string(
    value: str, node: Node, path: str, context: ValidationContext
) -> list[ValueIssue]:
    issues: list[ValueIssue] = []
    length = len(value)
    if node.min_length is not None and length < node.min_length:
        issues.append(ValueIssue(path, "min_length", f"Must be at least {node.min_length} characters"))
    if node.max_length is not None and length > node.max_length:
        issues.append(ValueIssue(path, "max_length", f"Must be at most {node.max_length} characters"))
    if node.pattern:
        if len(node.pattern) > context.limits.max_pattern_length:
            issues.append(
                ValueIssue(path, "pattern_length", "Pattern exceeds the configured pattern length")
            )
        elif not _portable_pattern(node.pattern):
            issues.append(
                ValueIssue(path, "pattern", "Pattern uses features outside the portable subset")
            )
        else:
            outcome = _match_with_timeout(node.pattern, value, context.limits.regex_timeout_ms)
            if outcome is None:
                issues.append(
                    ValueIssue(path, "pattern", "Pattern evaluation timed out; check not performed",
                               severity="warning")
                )
            elif not outcome:
                issues.append(ValueIssue(path, "pattern", "Value does not match the pattern"))
    return issues


def _portable_pattern(pattern: str) -> bool:
    if len(pattern) > 512:
        return False
    return not any(feature in pattern for feature in FORBIDDEN_PATTERN_FEATURES)


def _compile(pattern: str) -> re.Pattern[str] | None:
    if pattern in _PATTERN_CACHE:
        return _PATTERN_CACHE[pattern]
    try:
        compiled = re.compile(pattern)
    except re.error:
        compiled = None
    _PATTERN_CACHE[pattern] = compiled  # type: ignore[assignment]
    return compiled


def _regex_ok(pattern: str, subject: str, context: ValidationContext) -> bool:
    outcome = _match_with_timeout(pattern, subject, context.limits.regex_timeout_ms)
    return outcome is not False


def _match_with_timeout(pattern: str, subject: str, timeout_ms: int) -> bool | None:
    """Match with a bounded evaluation; None marks an undetermined outcome."""
    compiled = _compile(pattern)
    if compiled is None:
        return False
    if len(subject) <= 4096:
        return compiled.search(subject) is not None
    result: list[bool | None] = []
    done = threading.Event()

    def worker() -> None:
        try:
            result.append(compiled.search(subject) is not None)
        except Exception:  # pragma: no cover - defensive
            result.append(None)
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    done.wait(timeout_ms / 1000.0)
    return result[0] if done.is_set() else None


def value_matches_node(value: Any, node: Node) -> bool:
    """True when a literal value satisfies the node (used for descriptor defaults)."""
    context = ValidationContext()
    return not validate_value(value, node, node.path or "", context)


def validate_document(value: Any, node: Node, *, limits: Limits | None = None) -> list[ValueIssue]:
    """Validate a whole candidate configuration; limits first."""
    limits = limits or DEFAULT_LIMITS
    issues = check_limits(value, limits)
    if issues:
        return issues
    context = ValidationContext(limits=limits)
    issues.extend(validate_value(value, node, "", context))
    return issues