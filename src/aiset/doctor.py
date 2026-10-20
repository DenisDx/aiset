"""Diagnose a document and repair the mechanically fixable part.

Four fix classes, deliberately small:

| Class | Repair | Why it is in this class |
|---|---|---|
| `clamp` | move a number to its declared minimum or maximum | a bound is a fact the descriptor states |
| `coerce` | `"8080"` to `8080` when the source is an unambiguous literal | a quoted number can be deliberate |
| `drop_unknown` | remove a key the descriptor does not declare | lossy: it can be a typo or a future field |

Everything else is reported with `fix = None`. A report-only issue is a fact, not
a failure of the doctor: `const`, `enum`, `pattern`, string length, unions,
secrets, read-only nodes and unresolved templates need a decision the library
cannot make.

The doctor inspects the file on disk, not a Last-Known-Good fallback: an operator
asking "what is wrong with this file" must be told about the file.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .errors import (
    AisetError,
    BadRequest,
    Forbidden,
    RevisionConflict,
    SecretAccessDenied,
    Unauthorized,
    ValidationError,
)
from .jsonsrc import Document
from .pointer import parse_pointer

FIX_CLAMP = "clamp"
FIX_COERCE = "coerce"
FIX_DROP_UNKNOWN = "drop_unknown"

FIX_CLASSES = (FIX_CLAMP, FIX_COERCE, FIX_DROP_UNKNOWN)
# What `fix=True` means: the repair that cannot change the meaning of a value.
SAFE_CLASSES = (FIX_CLAMP,)

MAX_EDIT_DISTANCE = 2


@dataclass
class DoctorIssue:
    """One validation issue, annotated with the repair class that could handle it."""

    path: str
    rule: str
    message: str
    severity: str = "error"
    line: int | None = None
    column: int | None = None
    fix: str | None = None
    fix_path: str | None = None
    suggestion: str | None = None
    before: Any = None
    after: Any = None
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "rule": self.rule,
            "message": self.message,
            "severity": self.severity,
            "fix": self.fix,
        }
        if self.line is not None:
            out["line"] = self.line
        if self.column is not None:
            out["column"] = self.column
        if self.suggestion:
            out["suggestion"] = self.suggestion
        if self.fix_path and self.fix_path != self.path:
            out["fix_path"] = self.fix_path
        if self.fix:
            out["before"] = self.before
            out["after"] = self.after
        if self.resolved:
            out["resolved"] = True
        return out


@dataclass
class DoctorFix:
    """One planned repair, with the operation that would carry it out."""

    path: str
    action: str          # set | add | drop
    rule: str
    fix_class: str
    before: Any = None
    after: Any = None
    operation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "action": self.action,
            "rule": self.rule,
            "class": self.fix_class,
            "before": self.before,
            "after": self.after,
        }


@dataclass
class DoctorSkipped:
    """A planned repair that was not applied, and why."""

    path: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "reason": self.reason}


@dataclass
class DoctorReport:
    document: str
    revision: str
    descriptor_revision: str
    valid: bool
    issues: list[DoctorIssue] = field(default_factory=list)
    fixes: list[DoctorFix] = field(default_factory=list)
    skipped: list[DoctorSkipped] = field(default_factory=list)
    applied: bool = False
    new_revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "document": self.document,
            "revision": self.revision,
            "descriptor_revision": self.descriptor_revision,
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
            "fixes": [fix.to_dict() for fix in self.fixes],
            "skipped": [item.to_dict() for item in self.skipped],
            "applied": self.applied,
            "new_revision": self.new_revision,
        }


# --------------------------------------------------------------------------
# entry point used by Service.doctor
# --------------------------------------------------------------------------
def doctor(
    service: Any,
    document_id: str,
    *,
    principal: Any,
    fix: bool | Iterable[str] = False,
    expected_revision: str | None = None,
    expected_descriptor_revision: str | None = None,
) -> DoctorReport:
    """Diagnose one document and, when asked, apply the requested repair classes."""
    service._require(principal, "settings_read_effective")
    registration = service._registration(document_id)
    store = registration.store
    store.check_symlink()
    data, revision, text = store.read()

    if expected_revision is not None and expected_revision != revision:
        raise RevisionConflict(
            "The document changed on disk; re-read before repairing",
            detail=f"disk={revision} client={expected_revision}",
        )
    if (expected_descriptor_revision is not None
            and expected_descriptor_revision != registration.descriptor.revision):
        raise RevisionConflict(
            "The descriptor changed; reload before repairing",
            detail=f"disk={registration.descriptor.revision} client={expected_descriptor_revision}",
        )

    state, issues = service._analyze(registration, revision, text, "file")
    document = _parse(text, store.path.name)
    stored = _stored(document)

    report = DoctorReport(
        document=document_id,
        revision=revision,
        descriptor_revision=registration.descriptor.revision,
        valid=state is not None,
        issues=_annotate(service, registration, issues, stored, document),
    )
    planned = _plans(service, registration, report.issues, stored, document)
    if not planned:
        return report

    classes = _normalise_classes(fix)
    requested = [item for item in planned if item.fix_class in classes]
    report.skipped.extend(
        DoctorSkipped(item.path, f"class not requested: {item.fix_class}")
        for item in planned
        if item.fix_class not in classes
    )
    if not requested:
        return report

    try:
        service._require(principal, "settings_write")
    except (Forbidden, SecretAccessDenied, Unauthorized) as exc:
        report.skipped.extend(DoctorSkipped(item.path, f"forbidden: {exc}") for item in requested)
        return report

    operations = _ordered_operations(requested)
    if document is None:
        report.skipped.extend(DoctorSkipped(item.path, "the file does not parse") for item in requested)
        return report

    operation_state = state if state is not None else service._invalid_state(
        registration, data, revision, text, "invalid", issues
    )
    try:
        candidate_text, candidate_issues = service._apply_to_candidate(
            operation_state, operations, principal
        )
    except AisetError as exc:
        report.skipped.extend(DoctorSkipped(item.path, exc.message) for item in requested)
        return report
    errors = [issue for issue in candidate_issues if issue.severity == "error"]
    if errors:
        reason = "the document would still be invalid: " + ", ".join(
            sorted({f"{issue.path or '/'} [{issue.rule}]" for issue in errors})
        )
        report.skipped.extend(DoctorSkipped(item.path, reason) for item in requested)
        return report

    candidate = Document(candidate_text, origin=store.path.name)
    for operation in operations:
        try:
            service._check_hook_capability(operation_state, operation["path"], candidate)
        except AisetError as exc:
            report.skipped.extend(DoctorSkipped(item.path, exc.message) for item in requested)
            return report

    try:
        # The write path loads the current state first, which logs the invalid
        # document. The doctor is about to report and repair exactly that, so the
        # duplicate log line would only confuse the operator.
        import logging

        logger = logging.getLogger("aiset")
        previous_level = logger.level
        logger.setLevel(logging.CRITICAL)
        try:
            result = service.apply_operations(
                document_id,
                operations,
                expected_revision=revision,
                expected_descriptor_revision=registration.descriptor.revision,
                principal=principal,
            )
        finally:
            logger.setLevel(previous_level)
    except ValidationError as exc:
        report.skipped.extend(DoctorSkipped(item.path, exc.message) for item in requested)
        return report
    except AisetError as exc:
        report.skipped.extend(DoctorSkipped(item.path, exc.message) for item in requested)
        return report

    report.fixes = requested
    report.applied = result.stored
    report.valid = result.stored
    report.new_revision = result.revision if result.stored else None
    if result.stored:
        repaired = {operation["path"] for operation in operations}
        for issue in report.issues:
            if (issue.fix_path or issue.path) in repaired:
                issue.resolved = True
    return report


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------
def _parse(text: str, origin: str) -> Document | None:
    """The source editor for the file, or None when it does not parse."""
    try:
        return Document(text, origin=origin)
    except AisetError:
        return None


def _stored(document: Document | None) -> Any:
    """Parsed value of the file, or None when it does not parse."""
    if document is None:
        return None
    try:
        return document.stored_value(document.root)
    except AisetError:
        return None


def _annotate(
    service: Any,
    registration: Any,
    issues: Sequence[Any],
    stored: Any,
    document: Document | None,
) -> list[DoctorIssue]:
    """Attach a fix class, a before/after pair and a rename hint to each issue."""
    out: list[DoctorIssue] = []
    for issue in issues:
        annotated = DoctorIssue(
            path=issue.path,
            rule=issue.rule,
            message=issue.message,
            severity=issue.severity,
            line=issue.line,
            column=issue.column,
        )
        _classify(service, registration, annotated, stored, document)
        out.append(annotated)
    return out


def _classify(
    service: Any,
    registration: Any,
    issue: DoctorIssue,
    stored: Any,
    document: Document | None,
) -> None:
    """Decide the one fix class for an issue, if any."""
    node = _node(service, registration, issue.path)
    if _blocked(service, registration, issue.path) is not None:
        return
    value, present = _lookup(stored, parse_pointer(issue.path))

    if issue.rule == "required":
        # A required node cannot carry a default - the descriptor grammar rejects
        # it, because "required" means "explicitly present in the file". There is
        # nothing to add, so this always needs a human.
        issue.suggestion = "required with no default; a value must be chosen"
        return

    if issue.rule in ("minimum", "maximum") and node is not None:
        bound = node.minimum if issue.rule == "minimum" else node.maximum
        if bound is None or not _is_number(value):
            return
        issue.fix = FIX_CLAMP
        issue.before = value
        issue.after = bound
        return

    if issue.rule == "type" and node is not None and document is not None:
        converted = _coerce(document, issue.path, node, value)
        if converted is None:
            return
        issue.fix = FIX_COERCE
        issue.before = value
        issue.after = converted
        return

    if issue.rule == "union":
        # A value that matches no alternative usually differs from the closest
        # one by a single undeclared key. The validator reports that at the union
        # path, but the repair belongs to the key itself.
        key = _union_undeclared_key(issue.message)
        if key and node is not None and node.type == "union" and not _union_blocked(node):
            child = (issue.path + "/" + key) if issue.path else "/" + key
            if service._node_for(registration, child, required=False) is None:
                issue.fix = FIX_DROP_UNKNOWN
                issue.fix_path = child
        return

    if issue.rule == "undeclared_field":
        issue.fix = FIX_DROP_UNKNOWN
        token = issue.path.rsplit("/", 1)[-1]
        parent = issue.path.rpartition("/")[0]
        issue.suggestion = _rename_hint(service, registration, parent, token)


def _plans(
    service: Any,
    registration: Any,
    issues: Sequence[DoctorIssue],
    stored: Any,
    document: Document | None,
) -> list[DoctorFix]:
    """Turn the annotated issues into operations, one per path."""
    plans: list[DoctorFix] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        if not issue.fix:
            continue
        key = (issue.fix, issue.path)
        if key in seen:
            continue
        seen.add(key)
        if issue.fix == FIX_CLAMP:
            plans.append(DoctorFix(
                path=issue.path, action="set", rule=issue.rule, fix_class=issue.fix,
                before=issue.before, after=issue.after,
                operation={"op": "set", "path": issue.path,
                           "value_text": json.dumps(issue.after, ensure_ascii=False)},
            ))
        elif issue.fix == FIX_COERCE:
            plans.append(DoctorFix(
                path=issue.path, action="set", rule=issue.rule, fix_class=issue.fix,
                before=issue.before, after=issue.after,
                operation={"op": "set", "path": issue.path,
                           "value_text": json.dumps(issue.after, ensure_ascii=False)},
            ))
        elif issue.fix == FIX_DROP_UNKNOWN:
            target = issue.fix_path or issue.path
            plans.append(DoctorFix(
                path=target, action="drop", rule=issue.rule, fix_class=issue.fix,
                operation={"op": "drop", "path": target},
            ))
    return plans


def _ordered_operations(plans: Sequence[DoctorFix]) -> list[dict[str, Any]]:
    """Order operations so the batch is applicable.

    Adds go outermost first, so a parent exists before its child. Removals go
    innermost first, and array indices from highest to lowest, so an early
    removal cannot shift a later path.
    """
    drops = [p.operation for p in plans if p.action == "drop"]
    sets = [p.operation for p in plans if p.action == "set"]

    # Removals go innermost first and array indices from highest to lowest, so an
    # early removal cannot shift a later path.
    drops.sort(key=lambda op: _removal_key(op["path"]), reverse=True)
    return sets + drops


def _removal_key(pointer: str) -> tuple:
    """Sort key that puts children before parents and high indices before low."""
    tokens = parse_pointer(pointer)
    numeric = tuple(int(token) if token.isdigit() else -1 for token in tokens)
    return (len(tokens), numeric)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _normalise_classes(fix: bool | Iterable[str]) -> set[str]:
    """Map the `fix` argument to the set of requested classes."""
    if fix is True:
        return set(SAFE_CLASSES)
    if fix in (False, None):
        return set()
    if isinstance(fix, str):
        return {fix}
    requested = set(fix)
    unknown = requested - set(FIX_CLASSES)
    if unknown:
        raise BadRequest(f"Unknown fix class(es): {', '.join(sorted(unknown))}")
    return requested


def _blocked(service: Any, registration: Any, path: str) -> str | None:
    """Why a path must not be repaired: a secret, read-only or const ancestor.

    A fix reports `before` and `after`, so a secret node would leak its value
    through the report even when the write itself is refused. The doctor stops
    one level earlier: no class, no values.
    """
    tokens = parse_pointer(path)
    for index in range(len(tokens) + 1):
        prefix = "/" + "/".join(tokens[:index]) if index else ""
        node = _node(service, registration, prefix)
        if node is None:
            continue
        if node.secret:
            return "secret"
        if node.read_only:
            return "read-only"
        if node.const is not None:
            return "const"
    return None


def _node(service: Any, registration: Any, path: str):
    """Descriptor node at a pointer, or None when undeclared."""
    try:
        return service._node_for(registration, path, required=False)
    except AisetError:
        return None


def _lookup(value: Any, tokens: Sequence[str]) -> tuple[Any, bool]:
    """Value at a token path, and whether it exists."""
    current = value
    for token in tokens:
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return None, False
    return current, True


def _is_number(value: Any) -> bool:
    """True for an int or float, excluding bool."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coerce(document: Document, path: str, node: Any, value: Any) -> Any:
    """The literal form of an unambiguous string, or None when a human must decide."""
    if not isinstance(value, str) or "${" in value:
        return None
    source = document.find(path)
    if source is None:
        return None
    raw = document.value_text(source).strip()
    if not raw or raw[0] not in "\"'":
        return None  # already an unquoted literal, or a template
    text = value.strip()
    if node.type == "int":
        try:
            return int(text)
        except ValueError:
            return None
    if node.type == "number":
        try:
            return float(text)
        except ValueError:
            return None
    if node.type == "bool":
        if text == "true":
            return True
        if text == "false":
            return False
    return None


def _union_undeclared_key(message: str) -> str | None:
    """The key named by a union diagnostic, or None.

    The validator formats the closest alternative's first issues into the union
    message; only `undeclared_field` is safe to act on here.
    """
    match = re.search(r"undeclared_field: Field '([^']+)' is not declared", message)
    return match.group(1) if match else None


def _union_blocked(node: Any) -> bool:
    """Whether every repair below a union is forbidden by a read-only shape.

    A secret alternative does not block dropping a key that no alternative
    declares: the key is not part of the secret subtree, and the service still
    asks for `settings_edit_secret` before touching a secret-bearing union.
    """
    options = node.option_nodes or []
    return any(option.read_only or option.const is not None for option in options)


def _rename_hint(service: Any, registration: Any, parent: str, token: str) -> str | None:
    """Suggest a declared sibling when the undeclared key looks like a typo."""
    node = _node(service, registration, parent)
    if node is None:
        return None
    candidates = set(node.children or {})
    candidates.update(node.key_enum or ())
    best: tuple[int, str] | None = None
    for candidate in candidates:
        distance = _edit_distance(token, candidate)
        if distance <= MAX_EDIT_DISTANCE and (best is None or distance < best[0]):
            best = (distance, candidate)
    if best is None:
        return None
    return f"did you mean {best[1]!r}? (rename it instead of deleting)"


def _edit_distance(left: str, right: str) -> int:
    """Levenshtein distance, bounded in practice by short key names."""
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, start=1):
        current = [i]
        for j, char_right in enumerate(right, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (char_left != char_right),
            ))
        previous = current
    return previous[-1]
