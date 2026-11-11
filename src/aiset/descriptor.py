"""Descriptor loading, validation, composition and compilation.

Implements the complete descriptor grammar of SPEC.md section 4.6: envelope
rules, node grammar, structural rules per type, `env`/`ui`/`helper`/`hooks`
shapes, templates (`typedef`), explicit fragment composition, and the
`validate_descriptor` development operation with unknown-property reporting.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .errors import DescriptorError, InvalidDescriptor
from .jsonsrc import Document

DESCRIPTOR_VERSION = "1.0"
PRIMITIVE_TYPES = (
    "string", "int", "number", "bool", "null", "object", "array", "union", "any",
)
SCALAR_TYPES = ("string", "int", "number", "bool", "null", "any")
# `any` accepts every JSON value, so it carries no constraint of its own and is
# never part of the "this key does not apply to this type" check: a host that
# reaches for it has decided that the value is opaque, and the limits of
# validator.check_limits still apply to its depth, size and nesting.
APPLY_VALUES = ("live", "reload", "restart")
CONVERT_VALUES = ("string", "int", "number", "bool")
HOOK_EVENTS = ("before_create", "before_update", "after_create", "after_update")
HELPER_ACTIONS = ("create", "edit")
PRESENTATIONS = ("modal", "wizard")
SCOPES = ("node", "subtree")

ENVELOPE_KEYS = ("descriptor_version", "project", "config_version", "default_language", "root")
LOCALIZED_KEYS = ("text", "default")
_LANGUAGE_RE = re.compile(
    r"^(?:[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*|x(?:-[A-Za-z0-9]{1,8})+)$"
)


def normalize_language_tag(tag: Any) -> str | None:
    """Return a normalized BCP-47-like tag, or None when it is malformed."""
    if not isinstance(tag, str) or not _LANGUAGE_RE.fullmatch(tag):
        return None
    parts = tag.split("-")
    normalized: list[str] = []
    for index, part in enumerate(parts):
        if index == 0:
            normalized.append(part.lower())
        elif len(part) == 4 and part.isalpha():
            normalized.append(part[:1].upper() + part[1:].lower())
        elif len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def _localized_text(
    value: Any, document_default: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve a description/title form to (default string, normalized map)."""
    if isinstance(value, str):
        return value, None
    if not isinstance(value, dict):
        return None, None
    text = value.get("text")
    if not isinstance(text, dict):
        return None, None
    normalized: dict[str, str] = {}
    for tag, string in text.items():
        normalized_tag = normalize_language_tag(tag)
        if normalized_tag is not None and isinstance(string, str):
            normalized[normalized_tag] = string
    default = value.get("default")
    default_tag = normalize_language_tag(default) if isinstance(default, str) else None
    if default_tag is None or default_tag not in normalized:
        default_tag = document_default if document_default in normalized else None
    if default_tag is None and normalized:
        default_tag = next(iter(normalized))
    if default_tag is None:
        return None, None
    return normalized[default_tag], {"default": default_tag, "text": normalized}


def _resolve_localized(
    localized: dict[str, Any] | None, default_text: str | None, locale: str | None
) -> str | None:
    """Resolve a localized value for one locale, falling back to its default."""
    if not localized:
        return default_text
    text = localized.get("text") or {}
    if locale:
        normalized = normalize_language_tag(locale)
        if normalized in text:
            return text[normalized]
    return default_text


ENV_KEYS = ("allowed", "convert")
UI_KEYS = ("label", "group", "order", "help", "widget", "rows", "placeholder")
HELPER_KEYS = ("tag", "actions", "presentation", "settings")
BINDING_KEYS = ("tag", "scope", "settings")

NODE_KEYS = (
    "type",
    "description",
    "title",
    "required",
    "nullable",
    "default",
    "enum",
    "const",
    "minimum",
    "maximum",
    "min_length",
    "max_length",
    "pattern",
    "min_items",
    "max_items",
    "unique_items",
    "children",
    "id",
    "children_options",
    "additional_children",
    "key_pattern",
    "key_enum",
    "env",
    "secret",
    "read_only",
    "apply",
    "validators",
    "ui",
    "helper",
    "hooks",
    "typedef",
)

# Property name -> accepted Python types (SPEC.md 4.6.2).
PROPERTY_TYPES: dict[str, tuple[type, ...]] = {
    "type": (str,),
    "description": (str, dict),
    "title": (str, dict),
    "required": (bool,),
    "nullable": (bool,),
    "enum": (list,),
    "minimum": (int, float),
    "maximum": (int, float),
    "min_length": (int,),
    "max_length": (int,),
    "pattern": (str,),
    "min_items": (int,),
    "max_items": (int,),
    "unique_items": (bool,),
    "children": (dict, str),
    "id": (str,),
    "children_options": (list,),
    "additional_children": (dict,),
    "key_pattern": (str,),
    "key_enum": (list,),
    "env": (dict,),
    "secret": (bool,),
    "read_only": (bool,),
    "apply": (str,),
    "validators": (list,),
    "ui": (dict,),
    "helper": (dict,),
    "hooks": (dict,),
    "typedef": (str,),
}

STRUCTURAL_KEYS = (
    "children",
    "children_options",
    "additional_children",
    "key_pattern",
    "key_enum",
    "id",
)
COMPOSITE_KEYS = ("children", "children_options", "additional_children")
CONSTRAINT_BY_TYPE = {
    "string": ("min_length", "max_length", "pattern"),
    "int": ("minimum", "maximum"),
    "number": ("minimum", "maximum"),
    "array": ("min_items", "max_items", "unique_items"),
    "any": (),
}

UNKNOWN_PROPERTY = "UNKNOWN_DESCRIPTOR_PROPERTY"


# --------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------


@dataclass
class Issue:
    """A structured descriptor diagnostic (SPEC.md 4.5)."""

    code: str
    severity: str
    path: str
    message: str
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "severity": self.severity, "path": self.path,
                               "message": self.message}
        if self.line is not None:
            out["line"] = self.line
        if self.column is not None:
            out["column"] = self.column
        return out


@dataclass
class Diagnostic:
    """Result of validate_descriptor."""

    valid: bool
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": [issue.to_dict() for issue in self.issues]}


def revision_of(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]


def parse_descriptor(source: str, *, origin: str = "<descriptor>") -> Any:
    """Parse descriptor source (JSON5) into plain Python data."""
    document = Document(source, origin=origin)
    return document.stored_value(document.root)


# --------------------------------------------------------------------------
# compiled nodes
# --------------------------------------------------------------------------


class Node:
    """A compiled descriptor node."""

    __slots__ = (
        "type",
        "raw",
        "path",
        "label",
        "field_name",
        "description",
        "description_localized",
        "title",
        "title_localized",
        "required",
        "nullable",
        "default",
        "enum",
        "const",
        "has_default",
        "minimum",
        "maximum",
        "min_length",
        "max_length",
        "pattern",
        "min_items",
        "max_items",
        "unique_items",
        "children",
        "additional_children",
        "item_node",
        "option_nodes",
        "key_pattern",
        "key_enum",
        "env_allowed",
        "env_convert",
        "secret",
        "read_only",
        "apply",
        "validators",
        "ui",
        "helper",
        "hooks",
        "typedef_name",
        "parent",
    )

    def __init__(self, **kwargs: Any) -> None:
        for slot in self.__slots__:
            setattr(self, slot, kwargs.get(slot))

    def child(self, field_name: str) -> "Node | None":
        return self.children.get(field_name) if self.children else None

    def is_scalar(self) -> bool:
        return self.type not in ("object", "array", "union")

    def describe(
        self, *, locale: str | None = None, include_localized: bool = False
    ) -> dict[str, Any]:
        """Field metadata; an optional locale selects localized text."""
        out: dict[str, Any] = {"type": self.type}
        for key, value in (
            ("description", _resolve_localized(self.description_localized, self.description, locale)),
            ("title", _resolve_localized(self.title_localized, self.title, locale)),
            ("required", self.required),
            ("nullable", self.nullable),
            ("default", self.default),
            ("enum", self.enum),
            ("const", self.const),
            ("minimum", self.minimum),
            ("maximum", self.maximum),
            ("min_length", self.min_length),
            ("max_length", self.max_length),
            ("pattern", self.pattern),
            ("min_items", self.min_items),
            ("max_items", self.max_items),
            ("unique_items", self.unique_items),
            ("apply", self.apply),
            ("secret", self.secret),
            ("read_only", self.read_only),
        ):
            if value is not None:
                out[key] = value
        if include_localized and self.description_localized is not None:
            out["description_localized"] = dict(self.description_localized)
        if include_localized and self.title_localized is not None:
            out["title_localized"] = dict(self.title_localized)
        if self.env_allowed:
            out["env"] = {"allowed": True}
            if self.env_convert:
                out["env"]["convert"] = self.env_convert
        if self.children:
            out["children"] = {
                name: node.describe(locale=locale, include_localized=include_localized)
                for name, node in self.children.items()
            }
        if self.item_node is not None and self.type == "array":
            # An array describes every item with a single node. A client needs
            # that shape to offer the right control for a new entry, and the
            # descriptor itself is written exactly this way.
            out["children"] = self.item_node.describe(
                locale=locale, include_localized=include_localized
            )
        if self.option_nodes:
            out["children_options"] = [
                option.describe(locale=locale, include_localized=include_localized)
                for option in self.option_nodes
            ]
        if self.additional_children is not None:
            out["additional_children"] = self.additional_children.describe(
                locale=locale, include_localized=include_localized
            )
        if self.key_pattern:
            out["key_pattern"] = self.key_pattern
        if self.key_enum:
            out["key_enum"] = list(self.key_enum)
        if self.ui:
            out["ui"] = dict(self.ui)
        if self.helper:
            out["helper"] = dict(self.helper)
        if self.hooks:
            out["hooks"] = {
                event: [dict(binding) for binding in bindings]
                for event, bindings in self.hooks.items()
            }
        if self.validators:
            out["validators"] = list(self.validators)
        return out


@dataclass
class CompiledDescriptor:
    """An immutable compiled descriptor plus its lossless raw form."""

    raw: dict[str, Any]
    root: Node
    source: str
    revision: str
    project: str | None = None
    config_version: str | None = None
    default_language: str | None = None

    def to_authorized_dict(self) -> dict[str, Any]:
        """Authorized export; localized text is flattened for legacy readers."""
        return {
            "descriptor_version": DESCRIPTOR_VERSION,
            "project": self.project,
            "config_version": self.config_version,
            "default_language": self.default_language,
            "revision": self.revision,
            "root": self.root.describe(),
        }


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def validate_descriptor(
    source: str, *, mode: str = "default", known_templates: dict[str, Any] | None = None
) -> Diagnostic:
    """Development operation (SPEC.md 4.5, 4.6.9). No config file is read.

    `known_templates` supplies names from typedef sources or fragments so a
    reference to a template defined elsewhere is not reported as unknown.
    """
    try:
        data = parse_descriptor(source)
    except Exception as exc:  # syntax errors are reported, not raised
        return Diagnostic(valid=False, issues=[Issue("DESCRIPTOR_SYNTAX", "error", "", str(exc))])
    return _validate_data(data, mode=mode, known_templates=known_templates, source=source)


def _validate_data(
    data: Any,
    *,
    mode: str,
    known_templates: dict[str, Any] | None = None,
    source: str | None = None,
) -> Diagnostic:
    """Validate an already-parsed descriptor; positions are optional."""
    issues: list[Issue] = []
    if not isinstance(data, dict):
        issues.append(Issue("DESCRIPTOR_SYNTAX", "error", "", "Descriptor root must be an object"))
        return Diagnostic(valid=False, issues=issues)
    _check_envelope(data, issues)
    templates = _collect_typedefs(data, issues)
    templates.update(known_templates or {})
    raw_default = data.get("default_language")
    document_default = (
        normalize_language_tag(raw_default) if isinstance(raw_default, str) else None
    )
    _check_template_references(data, templates, issues)
    unresolved = any(
        issue.code in ("UNKNOWN_TYPE", "TEMPLATE_CYCLE") for issue in issues
    )
    root = data.get("root")
    if isinstance(root, dict):
        # Validation sees the effective node: a template reference inherits the
        # template's shape, including children and children_options.
        checked_root = root
        if not unresolved:
            try:
                checked_root = expand_templates(
                    root, templates, "/root", keep_typedef=True
                )
            except DescriptorError:
                # The unresolved reference is already reported above.
                pass
        _check_node(
            checked_root,
            "/root",
            issues,
            allow_id=False,
            templates=templates,
            document_default_language=document_default,
        )
    else:
        issues.append(Issue("DESCRIPTOR_STRUCTURE", "error", "/root", "root must be an object node"))
    strict = mode == "strict"
    if strict:
        for issue in issues:
            if issue.code == UNKNOWN_PROPERTY:
                issue.severity = "error"
    if source is not None:
        _locate_issues(source, issues)
    valid = not any(issue.severity == "error" for issue in issues)
    return Diagnostic(valid=valid, issues=issues)


def _locate_issues(source: str, issues: list[Issue]) -> None:
    """Attach the source position of every issue that carries only a path.

    The descriptor is a JSON5 document and an issue path is a JSON Pointer into
    it, so the position is read from the same parser the editor uses. A path
    that names a property which is not there (`/type is required`) is reported
    at the nearest existing ancestor, which is where the author has to look.
    """
    try:
        document = Document(source, origin="descriptor.json5")
    except Exception:  # pragma: no cover - the syntax issue already reported it
        return
    for issue in issues:
        if issue.line is not None:
            continue
        pointer = issue.path
        while True:
            node = _find_or_none(document, pointer)
            if node is not None:
                issue.line, issue.column = document.line_col(node.start)
                break
            if not pointer:
                break
            pointer = pointer.rpartition("/")[0]


def _find_or_none(document: Document, pointer: str) -> Any:
    """`Document.find` that reports a malformed pointer as "not found"."""
    try:
        return document.find(pointer)
    except Exception:
        return None


def _check_envelope(data: dict[str, Any], issues: list[Issue]) -> None:
    version = data.get("descriptor_version")
    if not isinstance(version, str):
        issues.append(
            Issue("DESCRIPTOR_VERSION", "error", "/descriptor_version", "descriptor_version is required")
        )
    elif version != DESCRIPTOR_VERSION:
        issues.append(
            Issue(
                "DESCRIPTOR_VERSION",
                "error",
                "/descriptor_version",
                f"Unsupported descriptor version {version!r}; recognized: {DESCRIPTOR_VERSION!r}",
            )
        )
    for key in ("project", "config_version"):
        if key in data and not isinstance(data[key], str):
            issues.append(Issue("DESCRIPTOR_STRUCTURE", "error", "/" + key, f"{key} must be a string"))
    if "default_language" in data:
        if not isinstance(data["default_language"], str):
            issues.append(
                Issue("DESCRIPTOR_STRUCTURE", "error", "/default_language",
                      "default_language must be a string")
            )
        elif normalize_language_tag(data["default_language"]) is None:
            issues.append(
                Issue("INVALID_LANGUAGE_TAG", "error", "/default_language",
                      "default_language is not a well-formed language tag")
            )
    if "root" not in data:
        issues.append(Issue("DESCRIPTOR_STRUCTURE", "error", "/root", "root is required"))
    for key in data:
        if key not in ENVELOPE_KEYS:
            issues.append(
                Issue(
                    UNKNOWN_PROPERTY,
                    "warning",
                    "/" + key,
                    "Property is not interpreted by the shared settings library",
                )
            )


def _check_localized_text(
    node: dict[str, Any],
    key: str,
    path: str,
    issues: list[Issue],
    document_default: str | None,
) -> None:
    """Validate the object form of `description`/`title` (F1 rules R3, R8, R9)."""
    if key not in node:
        return
    value = node[key]
    if isinstance(value, str):
        return
    if not isinstance(value, dict):
        return  # the property-type check already reported it
    field_path = f"{path}/{key}"
    for unknown in value:
        if unknown not in LOCALIZED_KEYS:
            issues.append(
                Issue("INVALID_LOCALIZED_TEXT", "error", f"{field_path}/{unknown}",
                      "Unknown localized text property")
            )
    text = value.get("text")
    if not isinstance(text, dict) or not text:
        issues.append(
            Issue("INVALID_LOCALIZED_TEXT", "error", f"{field_path}/text",
                  "localized text must be a nonempty object")
        )
        return
    normalized: set[str] = set()
    for tag, string in text.items():
        normalized_tag = normalize_language_tag(tag)
        if normalized_tag is None:
            issues.append(
                Issue("INVALID_LANGUAGE_TAG", "error", f"{field_path}/text/{tag}",
                      "malformed language tag")
            )
        elif normalized_tag in normalized:
            issues.append(
                Issue("INVALID_LANGUAGE_TAG", "error", f"{field_path}/text/{tag}",
                      "duplicate language tag after normalization")
            )
        else:
            normalized.add(normalized_tag)
        if not isinstance(string, str) or not string:
            issues.append(
                Issue("INVALID_LOCALIZED_TEXT", "error", f"{field_path}/text/{tag}",
                      "localized text entries must be nonempty strings")
            )
    default = value.get("default")
    if default is not None:
        default_tag = normalize_language_tag(default)
        if default_tag is None:
            issues.append(
                Issue("INVALID_LANGUAGE_TAG", "error", f"{field_path}/default",
                      "malformed language tag")
            )
        elif default_tag not in normalized:
            issues.append(
                Issue("INVALID_LOCALIZED_TEXT", "error", f"{field_path}/default",
                      "default language has no entry in text")
            )
    elif document_default is None:
        issues.append(
            Issue("INVALID_LOCALIZED_TEXT", "error", field_path,
                  "localized text requires a default or a document default_language")
        )
    elif normalize_language_tag(document_default) not in normalized:
        issues.append(
            Issue("INVALID_LOCALIZED_TEXT", "error", field_path,
                  "document default_language has no entry in text")
        )


def _type_ok(value: Any, expected: tuple[type, ...]) -> bool:
    if bool in expected:
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if int in expected or float in expected:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, expected)


def _resolve_type_name(type_name: str, templates: dict[str, Any]) -> str:
    """Follow template references to the primitive type they ultimately define."""
    seen: set[str] = set()
    current = type_name
    while current not in PRIMITIVE_TYPES and current in templates and current not in seen:
        seen.add(current)
        template = templates[current]
        resolved = template.get("type") if isinstance(template, dict) else None
        if not isinstance(resolved, str):
            break
        current = resolved
    return current


def _check_node(
    node: dict[str, Any],
    path: str,
    issues: list[Issue],
    *,
    allow_id: bool = False,
    templates: dict[str, Any] | None = None,
    document_default_language: str | None = None,
) -> None:
    """Validate one node definition and recurse into its children (4.6.2/4.6.3)."""
    templates = templates or {}
    if not isinstance(node, dict):
        issues.append(Issue("DESCRIPTOR_STRUCTURE", "error", path, "Node must be an object"))
        return
    for key, value in node.items():
        if key in PROPERTY_TYPES:
            expected = PROPERTY_TYPES[key]
            if key == "type":
                continue
            if not _type_ok(value, expected):
                issues.append(
                    Issue("INVALID_PROPERTY_TYPE", "error", f"{path}/{key}",
                          f"Property {key!r} has an unsupported value type")
                )
        elif key == "default" or key == "const":
            continue
        else:
            issues.append(
                Issue(
                    UNKNOWN_PROPERTY,
                    "warning",
                    f"{path}/{key}",
                    "Property is not interpreted by the shared settings library",
                )
            )

    node_type = node.get("type")
    if not isinstance(node_type, str):
        issues.append(Issue("DESCRIPTOR_STRUCTURE", "error", f"{path}/type", "type is required"))
        return
    # A template reference is expanded before structural checks; resolving the
    # name here keeps scalar constraints correct for aliases as well.
    resolved_type = _resolve_type_name(node_type, templates)

    if node.get("required") is True and "default" in node:
        issues.append(
            Issue("INVALID_STRUCTURE", "error", f"{path}/default",
                  "required with default is invalid: required means explicitly present")
        )
    if "enum" in node and "const" in node:
        issues.append(
            Issue("INVALID_STRUCTURE", "error", f"{path}/const",
                  "enum with const is invalid: one fixed value cannot also list alternatives")
        )
    if node.get("apply") is not None and node.get("apply") not in APPLY_VALUES:
        issues.append(
            Issue("INVALID_PROPERTY_VALUE", "error", f"{path}/apply",
                  f"apply must be one of {', '.join(APPLY_VALUES)}")
        )
    if not allow_id and "id" in node:
        issues.append(
            Issue("INVALID_ID", "error", f"{path}/id",
                  "id is accepted only as a direct entry of an object's children mapping")
        )
    if "typedef" in node and not isinstance(node["typedef"], str):
        issues.append(Issue("INVALID_PROPERTY_TYPE", "error", f"{path}/typedef", "typedef must be a string"))
    if isinstance(node.get("typedef"), str) and node["typedef"] in PRIMITIVE_TYPES:
        issues.append(
            Issue("TEMPLATE_SHADOWS_PRIMITIVE", "error", f"{path}/typedef",
                  f"Template name {node['typedef']!r} shadows a primitive type")
        )
    _check_enum_and_const(node, path, issues)
    _check_localized_text(node, "description", path, issues, document_default_language)
    _check_localized_text(node, "title", path, issues, document_default_language)
    _check_scalar_constraints(node, path, issues, resolved_type)
    _check_env(node, path, issues)
    _check_ui(node, path, issues)
    _check_helper(node, path, issues)
    _check_hooks(node, path, issues)
    _check_validators(node, path, issues)

    children = node.get("children")
    additional = node.get("additional_children")
    options = node.get("children_options")

    if resolved_type == "object":
        if isinstance(children, dict):
            for label, child in children.items():
                child_path = f"{path}/children/{label}"
                if not isinstance(child, dict):
                    issues.append(Issue("DESCRIPTOR_STRUCTURE", "error", child_path, "Child must be an object node"))
                    continue
                _check_node(
                    child,
                    child_path,
                    issues,
                    allow_id=True,
                    templates=templates,
                    document_default_language=document_default_language,
                )
        elif "children" in node:
            issues.append(
                Issue("DESCRIPTOR_STRUCTURE", "error", f"{path}/children",
                      "children of an object must map labels to nodes")
            )
        if isinstance(additional, dict):
            _check_node(
                additional,
                f"{path}/additional_children",
                issues,
                templates=templates,
                document_default_language=document_default_language,
            )
        elif "additional_children" in node:
            issues.append(
                Issue("DESCRIPTOR_STRUCTURE", "error", f"{path}/additional_children",
                      "additional_children must be an object node")
            )
        if ("key_pattern" in node) and ("key_enum" in node):
            issues.append(
                Issue("INVALID_STRUCTURE", "error", path,
                      "key_pattern and key_enum are mutually exclusive")
            )
        if "key_enum" in node and additional is None:
            issues.append(
                Issue("INVALID_STRUCTURE", "error", f"{path}/key_enum",
                      "key_enum requires additional_children")
            )
        _check_unique_field_names(node, path, issues)
    elif resolved_type == "array":
        if isinstance(children, dict):
            if is_item_node(children):
                _check_node(
                    children,
                    f"{path}/children",
                    issues,
                    templates=templates,
                    document_default_language=document_default_language,
                )
            else:
                issues.append(
                    Issue("DESCRIPTOR_STRUCTURE", "error", f"{path}/children",
                          "array children must be a single node describing every item")
                )
        if isinstance(options, list) and isinstance(children, dict):
            issues.append(
                Issue("INVALID_STRUCTURE", "error", path,
                      "children and children_options are mutually exclusive on arrays")
            )
        elif "children" not in node and not isinstance(options, list):
            issues.append(
                Issue("INVALID_STRUCTURE", "error", path,
                      "an array requires exactly one of children or children_options")
            )
        elif "children" in node and isinstance(options, list):
            issues.append(
                Issue("INVALID_STRUCTURE", "error", path,
                      "children and children_options are mutually exclusive on arrays")
            )
        if isinstance(options, list):
            if not options:
                issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/children_options",
                                    "children_options must be a nonempty array"))
            for index, option in enumerate(options):
                _check_node(
                    option,
                    f"{path}/children_options/{index}",
                    issues,
                    templates=templates,
                    document_default_language=document_default_language,
                )
    elif resolved_type == "union":
        if isinstance(options, list):
            if not options:
                issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/children_options",
                                    "a union requires a nonempty children_options"))
            for index, option in enumerate(options):
                _check_node(
                    option,
                    f"{path}/children_options/{index}",
                    issues,
                    templates=templates,
                    document_default_language=document_default_language,
                )
        else:
            issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/children_options",
                                "a union requires children_options"))
        if isinstance(children, (dict, str)):
            issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/children",
                                "a union describes alternatives only through children_options"))
        if isinstance(additional, dict):
            issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/additional_children",
                                "additional_children is not valid on a union"))
    else:
        for key in COMPOSITE_KEYS:
            if key in node:
                issues.append(
                    Issue("INVALID_STRUCTURE", "error", f"{path}/{key}",
                          f"{key} is not valid on type {resolved_type!r}")
                )
        if "key_pattern" in node or "key_enum" in node:
            issues.append(Issue("INVALID_STRUCTURE", "error", path,
                                "key constraints are not valid on a scalar type"))

    if "pattern" in node and isinstance(node["pattern"], str):
        try:
            re.compile(node["pattern"])
        except re.error as exc:
            issues.append(
                Issue("INVALID_PATTERN", "error", f"{path}/pattern", f"Unsupported pattern: {exc}")
            )
    if "key_pattern" in node and isinstance(node["key_pattern"], str):
        try:
            re.compile(node["key_pattern"])
        except re.error as exc:
            issues.append(
                Issue("INVALID_PATTERN", "error", f"{path}/key_pattern",
                      f"Unsupported pattern: {exc}")
            )
    if "default" in node:
        _check_default(node, f"{path}/default", issues, templates)


def _check_enum_and_const(node: dict[str, Any], path: str, issues: list[Issue]) -> None:
    options = node.get("enum")
    if isinstance(options, list):
        if not options:
            issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/enum", "enum must be nonempty"))
        seen = [repr(value) for value in options]
        if len(set(seen)) != len(seen):
            issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/enum", "enum values must be unique"))
    for key in ("min_length", "max_length", "min_items", "max_items"):
        if key in node and isinstance(node[key], int) and node[key] < 0:
            issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/{key}", f"{key} must not be negative"))
    for low, high in (("min_length", "max_length"), ("min_items", "max_items"), ("minimum", "maximum")):
        if isinstance(node.get(low), (int, float)) and isinstance(node.get(high), (int, float)):
            if node[low] > node[high]:
                issues.append(
                    Issue("INVALID_STRUCTURE", "error", f"{path}/{high}", f"{high} must not be below {low}")
                )


def _check_scalar_constraints(
    node: dict[str, Any], path: str, issues: list[Issue], resolved_type: str
) -> None:
    allowed = CONSTRAINT_BY_TYPE.get(resolved_type, ())
    reported: set[str] = set()
    for keys in CONSTRAINT_BY_TYPE.values():
        for key in keys:
            if key in node and key not in allowed and key not in reported:
                reported.add(key)
                issues.append(
                    Issue("INVALID_STRUCTURE", "error", f"{path}/{key}",
                          f"{key} does not apply to type {resolved_type!r}")
                )


def _check_env(node: dict[str, Any], path: str, issues: list[Issue]) -> None:
    env = node.get("env")
    if env is None:
        return
    for key in env:
        if key not in ENV_KEYS:
            issues.append(
                Issue(UNKNOWN_PROPERTY, "warning", f"{path}/env/{key}",
                      "Property is not interpreted by the shared settings library")
            )
    if not isinstance(env.get("allowed"), bool):
        issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/env/allowed",
                            "env.allowed is required and must be a boolean"))
    convert = env.get("convert")
    if convert is not None and convert not in CONVERT_VALUES:
        issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/env/convert",
                            f"convert must be one of {', '.join(CONVERT_VALUES)}"))


def _check_ui(node: dict[str, Any], path: str, issues: list[Issue]) -> None:
    ui = node.get("ui")
    if not isinstance(ui, dict):
        return
    for key, value in ui.items():
        child_path = f"{path}/ui/{key}"
        if key not in UI_KEYS:
            issues.append(
                Issue(UNKNOWN_PROPERTY, "warning", child_path,
                      "Property is not interpreted by the shared settings library")
            )
        elif key == "rows" and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
            issues.append(Issue("INVALID_STRUCTURE", "error", child_path, "ui.rows must be a positive integer"))
        elif key in ("label", "group", "widget", "placeholder", "help") and not isinstance(value, str):
            issues.append(Issue("INVALID_STRUCTURE", "error", child_path, f"ui.{key} must be a string"))


def _check_helper(node: dict[str, Any], path: str, issues: list[Issue]) -> None:
    helper = node.get("helper")
    if not isinstance(helper, dict):
        return
    for key, value in helper.items():
        child_path = f"{path}/helper/{key}"
        if key not in HELPER_KEYS:
            issues.append(
                Issue(UNKNOWN_PROPERTY, "warning", child_path,
                      "Property is not interpreted by the shared settings library")
            )
    if not isinstance(helper.get("tag"), str) or not helper.get("tag"):
        issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/helper/tag", "helper.tag is required"))
    actions = helper.get("actions")
    if not isinstance(actions, list) or not actions:
        issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/helper/actions",
                            "helper.actions must be a nonempty array"))
    elif any(action not in HELPER_ACTIONS for action in actions):
        issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/helper/actions",
                            f"helper.actions must be a subset of {', '.join(HELPER_ACTIONS)}"))
    presentation = helper.get("presentation")
    if presentation is not None and presentation not in PRESENTATIONS:
        issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/helper/presentation",
                            f"helper.presentation must be one of {', '.join(PRESENTATIONS)}"))


def _check_hooks(node: dict[str, Any], path: str, issues: list[Issue]) -> None:
    hooks = node.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, bindings in hooks.items():
        event_path = f"{path}/hooks/{event}"
        if event not in HOOK_EVENTS:
            issues.append(
                Issue("INVALID_HOOK_EVENT", "error", event_path,
                      f"Unknown hook event; supported: {', '.join(HOOK_EVENTS)}")
            )
            continue
        if not isinstance(bindings, list) or not bindings:
            issues.append(Issue("INVALID_STRUCTURE", "error", event_path,
                                "hook bindings must be a nonempty array"))
            continue
        for index, binding in enumerate(bindings):
            binding_path = f"{event_path}/{index}"
            if not isinstance(binding, dict):
                issues.append(Issue("INVALID_STRUCTURE", "error", binding_path, "Binding must be an object"))
                continue
            for key, value in binding.items():
                if key not in BINDING_KEYS:
                    issues.append(
                        Issue(UNKNOWN_PROPERTY, "warning", f"{binding_path}/{key}",
                              "Property is not interpreted by the shared settings library")
                    )
                elif key == "scope" and value not in SCOPES:
                    issues.append(Issue("INVALID_STRUCTURE", "error", f"{binding_path}/{key}",
                                        f"scope must be one of {', '.join(SCOPES)}"))
                elif key == "tag" and (not isinstance(value, str) or not value):
                    issues.append(Issue("INVALID_STRUCTURE", "error", f"{binding_path}/{key}",
                                        "tag is required"))


def _check_validators(node: dict[str, Any], path: str, issues: list[Issue]) -> None:
    validators = node.get("validators")
    if not isinstance(validators, list):
        return
    for index, validator in enumerate(validators):
        if not isinstance(validator, str) or not validator:
            issues.append(Issue("INVALID_STRUCTURE", "error", f"{path}/validators/{index}",
                                "validator ids must be nonempty strings"))


def _check_unique_field_names(node: dict[str, Any], path: str, issues: list[Issue]) -> None:
    children = node.get("children")
    if not isinstance(children, dict):
        return
    seen: dict[str, str] = {}
    for label, child in children.items():
        if not isinstance(child, dict):
            continue
        field_name = child.get("id") if isinstance(child.get("id"), str) else label
        if field_name in seen:
            issues.append(
                Issue("DUPLICATE_FIELD", "error", f"{path}/children/{label}",
                      f"Field name {field_name!r} is declared twice (also by {seen[field_name]!r})")
            )
        seen[field_name] = label


def _check_default(
    node: dict[str, Any], path: str, issues: list[Issue], templates: dict[str, Any]
) -> None:
    from .validator import value_matches_node  # local import: validator depends on this module

    try:
        expanded = expand_templates(node, templates, path)
        compiled = build_node(expanded, path, parent=None, templates=templates)
    except DescriptorError:
        # The template reference or node shape is reported by its own check.
        return
    if not value_matches_node(node.get("default"), compiled):
        issues.append(
            Issue("INVALID_DEFAULT", "error", path, "default does not satisfy the node constraints")
        )


# --------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------


def is_item_node(children: dict[str, Any]) -> bool:
    """An array item node is a node object; an object children map is labelled."""
    return isinstance(children.get("type"), str)


def _child_nodes(node: dict[str, Any], path: str) -> Iterable[tuple[dict[str, Any], str]]:
    """Yield structural child nodes: children, additional_children, options."""
    children = node.get("children")
    if isinstance(children, dict):
        if is_item_node(children):
            yield children, f"{path}/children"
        else:
            for label, child in children.items():
                if isinstance(child, dict):
                    yield child, f"{path}/children/{label}"
    additional = node.get("additional_children")
    if isinstance(additional, dict):
        yield additional, f"{path}/additional_children"
    options = node.get("children_options")
    if isinstance(options, list):
        for index, option in enumerate(options):
            if isinstance(option, dict):
                yield option, f"{path}/children_options/{index}"


def _root_nodes(data: Any, path: str = "") -> Iterable[tuple[dict[str, Any], str]]:
    """The descriptor root node, when `data` is a descriptor envelope."""
    if isinstance(data, dict) and isinstance(data.get("root"), dict):
        yield data["root"], f"{path}/root" if path else "/root"
    else:
        yield data, path


def _collect_typedefs(data: Any, issues: list[Issue] | None = None, path: str = "") -> dict[str, dict]:
    """Collect `typedef` declarations; duplicate names are descriptor errors."""
    templates: dict[str, dict] = {}

    def walk(node: dict[str, Any], node_path: str) -> None:
        if not isinstance(node, dict):
            return
        name = node.get("typedef")
        if isinstance(name, str):
            if name in templates and issues is not None:
                issues.append(
                    Issue("DUPLICATE_TYPEDEF", "error", f"{node_path}/typedef",
                          f"Template name {name!r} is declared more than once")
                )
            templates.setdefault(name, node)
        for child, child_path in _child_nodes(node, node_path):
            walk(child, child_path)

    for root, root_path in _root_nodes(data, path):
        walk(root, root_path)
    return templates


def _check_template_references(data: Any, templates: dict[str, Any], issues: list[Issue]) -> None:
    def walk(node: dict[str, Any], node_path: str, seen: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        if isinstance(node_type, str) and node_type not in PRIMITIVE_TYPES:
            if node_type not in templates:
                issues.append(
                    Issue("UNKNOWN_TYPE", "error", f"{node_path}/type",
                          f"Unknown type or template {node_type!r}")
                )
            elif node_type in seen:
                issues.append(
                    Issue("TEMPLATE_CYCLE", "error", f"{node_path}/type",
                          f"Cyclic template reference: {' -> '.join(seen + (node_type,))}")
                )
            else:
                walk(templates[node_type], f"{node_path}<{node_type}>", seen + (node_type,))
        for child, child_path in _child_nodes(node, node_path):
            walk(child, child_path, seen)

    for root, root_path in _root_nodes(data):
        walk(root, root_path, ())


def expand_templates(
    data: Any,
    templates: dict[str, dict],
    path: str = "",
    *,
    keep_typedef: bool = False,
) -> Any:
    """Replace `type: "<template>"` references by the template definition.

    `keep_typedef` keeps the node's own `typedef` declaration so validation can
    still report a template that shadows a primitive type.
    """
    if isinstance(data, dict) and isinstance(data.get("root"), dict):
        expanded = dict(data)
        expanded["root"] = expand_templates(
            data["root"], templates, f"{path}/root", keep_typedef=keep_typedef
        )
        return expanded
    if not isinstance(data, dict):
        return data
    node = dict(data) if keep_typedef else {
        key: value for key, value in data.items() if key != "typedef"
    }
    node_type = node.get("type")
    if isinstance(node_type, str) and node_type not in PRIMITIVE_TYPES:
        template = templates.get(node_type)
        if template is None:
            raise DescriptorError(f"Unknown type or template {node_type!r}", path=path)
        base = {
            key: value
            for key, value in template.items()
            if key != "typedef"
        }
        node = _merge_template(
            expand_templates(base, templates, path, keep_typedef=keep_typedef), node
        )
    children = node.get("children")
    if isinstance(children, dict):
        if node.get("type") == "array" and is_item_node(children):
            # An array describes every item with a single node, so a template
            # named there resolves like any other node position (SPEC.md 4.6.10).
            node["children"] = expand_templates(
                children, templates, f"{path}/children", keep_typedef=keep_typedef
            )
        else:
            node["children"] = {
                label: expand_templates(
                    child, templates, f"{path}/children/{label}", keep_typedef=keep_typedef
                )
                for label, child in children.items()
            }
    if isinstance(node.get("additional_children"), dict):
        node["additional_children"] = expand_templates(
            node["additional_children"], templates, f"{path}/additional_children",
            keep_typedef=keep_typedef,
        )
    options = node.get("children_options")
    if isinstance(options, list):
        node["children_options"] = [
            expand_templates(
                option, templates, f"{path}/children_options/{index}",
                keep_typedef=keep_typedef,
            )
            for index, option in enumerate(options)
        ]
    return node


def _merge_template(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Object children/options merge by key; everything else is replaced.

    The referencing node's own `type` is the template reference itself, so it is
    never copied over the resolved definition (SPEC.md 4.6.10).
    """
    merged = dict(base)
    override = {key: value for key, value in override.items() if key != "type"}
    for key, value in override.items():
        if key in ("children", "children_options") and isinstance(value, (dict, list)) and isinstance(
            base.get(key), type(value)
        ):
            combined = dict(base[key])
            if key == "children" and is_item_node(combined) and is_item_node(value):
                combined = _merge_template(combined, value)
            elif key == "children_options":
                combined = list(base[key])
                for index, item in enumerate(value):
                    if index < len(combined):
                        combined[index] = _merge_template(combined[index], item)
                    else:
                        combined.append(item)
            else:
                for label, child in value.items():
                    combined[label] = _merge_template(combined[label], child) if label in combined else child
            merged[key] = combined
        else:
            merged[key] = value
    return merged


# --------------------------------------------------------------------------
# composition
# --------------------------------------------------------------------------


@dataclass
class DescriptorFragment:
    """A descriptor file mounted at a path of the base descriptor."""

    source: str
    mount: str


def compose_fragments(data: dict[str, Any], fragments: Iterable[DescriptorFragment]) -> dict[str, Any]:
    """Attach each fragment's root at its mount path (SPEC.md 4.3)."""
    composed = dict(data)
    for fragment in fragments:
        fragment_data = parse_descriptor(fragment.source, origin="<fragment>")
        if not isinstance(fragment_data, dict) or not isinstance(fragment_data.get("root"), dict):
            raise DescriptorError("A descriptor fragment must contain a root object node",
                                  path=fragment.mount)
        _mount(composed, fragment.mount, fragment_data["root"])
    return composed


def _mount(data: dict[str, Any], mount: str, root: dict[str, Any]) -> None:
    """Attach a fragment root at `mount`; a free position is required (SPEC.md 4.3)."""
    from .pointer import parse_pointer

    tokens = parse_pointer(mount)
    if not tokens or tokens[0] != "root":
        raise DescriptorError(f"Fragment mount must start with /root, got {mount!r}", path=mount)
    container = data["root"]
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "children":
            if not isinstance(container.get("children"), dict):
                raise DescriptorError(f"Fragment mount {mount!r} does not exist", path=mount)
            container = container["children"]
            index += 1
            if index >= len(tokens):
                raise DescriptorError(
                    f"Fragment mount {mount!r} must address a free field name", path=mount
                )
            label = tokens[index]
            if index == len(tokens) - 1:
                if label in container:
                    raise DescriptorError(
                        f"Fragment mount {mount!r} collides with an existing descriptor node",
                        path=mount,
                    )
                container[label] = root
                return
            existing = container.get(label)
            if not isinstance(existing, dict):
                raise DescriptorError(f"Fragment mount {mount!r} does not exist", path=mount)
            container = existing
            index += 1
            continue
        if index == len(tokens) - 1:
            if token in container:
                raise DescriptorError(
                    f"Fragment mount {mount!r} collides with an existing descriptor node", path=mount
                )
            container[token] = root
            return
        existing = container.get(token)
        if not isinstance(existing, dict):
            raise DescriptorError(f"Fragment mount {mount!r} does not exist", path=mount)
        container = existing
        index += 1
    if container.get("children") or container.get("additional_children"):
        raise DescriptorError(
            "A fragment cannot replace a populated root node; mount it under a field name",
            path=mount,
        )
    data["root"] = root


def _merge_conflict(existing: dict[str, Any], incoming: dict[str, Any], path: str) -> None:
    if existing == incoming:
        return
    raise DescriptorError(
        "Fragment redefines an existing node; conflicting definitions are an error",
        path=path,
    )


# --------------------------------------------------------------------------
# compilation
# --------------------------------------------------------------------------


def compile_descriptor(
    source: str,
    *,
    typedef_sources: Iterable[str] = (),
    fragments: Iterable[DescriptorFragment] = (),
    strict: bool = False,
) -> CompiledDescriptor:
    """Validate and compile descriptor source into effective nodes."""
    data = parse_descriptor(source)
    if not isinstance(data, dict):
        raise InvalidDescriptor(
            "Descriptor is invalid",
            issues=[
                {
                    "code": "DESCRIPTOR_SYNTAX",
                    "severity": "error",
                    "path": "",
                    "message": "Descriptor root must be an object",
                }
            ],
        )
    typedef_list = list(typedef_sources)
    fragment_list = list(fragments)
    templates = _collect_typedefs(data)
    sources = typedef_list + [fragment.source for fragment in fragment_list]
    labels = ["typedef source"] * len(typedef_list) + ["fragment"] * len(fragment_list)
    for extra, label in zip(sources, labels):
        extra_templates = _collect_typedefs(parse_descriptor(extra, origin=f"<{label}>"))
        for name, node in extra_templates.items():
            if name in templates:
                raise DescriptorError(
                    f"Template name {name!r} is declared more than once", path="/root"
                )
            templates[name] = node

    diagnostic = validate_descriptor(
        source, mode="strict" if strict else "default", known_templates=templates
    )
    errors = [issue for issue in diagnostic.issues if issue.severity == "error"]
    if errors:
        raise InvalidDescriptor("Descriptor is invalid", issues=[issue.to_dict() for issue in errors])

    expanded = expand_templates(data.get("root"), templates, "/root")
    data = dict(data)
    data["root"] = expanded
    if fragment_list:
        data = compose_fragments(data, fragment_list)
        final = _validate_data(
            data, mode="strict" if strict else "default", known_templates=templates
        )
        errors = [issue for issue in final.issues if issue.severity == "error"]
        if errors:
            raise InvalidDescriptor(
                "Composed descriptor is invalid", issues=[issue.to_dict() for issue in errors]
            )

    default_language = (
        normalize_language_tag(data.get("default_language"))
        if isinstance(data.get("default_language"), str)
        else None
    )
    root = build_node(
        data["root"],
        "/root",
        parent=None,
        templates=templates,
        default_language=default_language,
    )
    return CompiledDescriptor(
        raw=data,
        root=root,
        source=source,
        revision=revision_of(source),
        project=data.get("project"),
        config_version=data.get("config_version"),
        default_language=default_language,
    )


def _dump(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)


def build_node(
    raw: dict[str, Any],
    path: str,
    *,
    parent: Node | None,
    templates: dict[str, Any],
    default_language: str | None = None,
) -> Node:
    """Build one compiled node; inherited flags come from the parent node."""
    if not isinstance(raw, dict):
        raise DescriptorError("Node must be an object", path=path)
    node_type = raw.get("type")
    if not isinstance(node_type, str):
        raise DescriptorError("type is required", path=path)
    env = raw.get("env") or {}
    description, description_localized = _localized_text(
        raw.get("description"), default_language
    )
    title, title_localized = _localized_text(raw.get("title"), default_language)

    def inherited(name: str) -> Any:
        if name in raw:
            return raw[name]
        return getattr(parent, name) if parent else None

    node = Node(
        type=node_type,
        raw=raw,
        path=path,
        label=None,
        field_name=None,
        description=description,
        description_localized=description_localized,
        title=title,
        title_localized=title_localized,
        required=bool(raw.get("required", False)),
        nullable=bool(raw.get("nullable", False)),
        default=raw.get("default"),
        has_default="default" in raw,
        enum=list(raw["enum"]) if isinstance(raw.get("enum"), list) else None,
        const=raw.get("const"),
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
        min_length=raw.get("min_length"),
        max_length=raw.get("max_length"),
        pattern=raw.get("pattern"),
        min_items=raw.get("min_items"),
        max_items=raw.get("max_items"),
        unique_items=raw.get("unique_items"),
        children=None,
        additional_children=None,
        item_node=None,
        option_nodes=None,
        key_pattern=raw.get("key_pattern"),
        key_enum=list(raw["key_enum"]) if isinstance(raw.get("key_enum"), list) else None,
        env_allowed=bool(env.get("allowed", False)),
        env_convert=env.get("convert"),
        secret=bool(inherited("secret")),
        read_only=bool(inherited("read_only")),
        apply=raw.get("apply") or (parent.apply if parent else "restart") or "restart",
        validators=list(raw["validators"]) if isinstance(raw.get("validators"), list) else [],
        ui=dict(raw["ui"]) if isinstance(raw.get("ui"), dict) else None,
        helper=dict(raw["helper"]) if isinstance(raw.get("helper"), dict) else None,
        hooks=dict(raw["hooks"]) if isinstance(raw.get("hooks"), dict) else None,
        typedef_name=raw.get("typedef"),
        parent=parent,
    )

    if node_type == "object":
        raw_children = raw.get("children")
        if isinstance(raw_children, dict):
            children: dict[str, Node] = {}
            for label, child_raw in raw_children.items():
                child_path = f"{path}/children/{label}"
                if not isinstance(child_raw, dict):
                    raise DescriptorError("Child must be an object node", path=child_path)
                field_name = child_raw.get("id") if isinstance(child_raw.get("id"), str) else label
                if field_name in children:
                    raise DescriptorError(f"Duplicate field name {field_name!r}", path=child_path)
                child = build_node(
                    child_raw,
                    child_path,
                    parent=node,
                    templates=templates,
                    default_language=default_language,
                )
                child.label = label
                child.field_name = field_name
                children[field_name] = child
            node.children = children or None
        additional = raw.get("additional_children")
        if isinstance(additional, dict):
            node.additional_children = build_node(
                additional,
                f"{path}/additional_children",
                parent=node,
                templates=templates,
                default_language=default_language,
            )
    elif node_type in ("array", "union"):
        raw_children = raw.get("children")
        if isinstance(raw_children, dict) and is_item_node(raw_children):
            node.item_node = build_node(
                raw_children,
                f"{path}/children",
                parent=node,
                templates=templates,
                default_language=default_language,
            )
        options = raw.get("children_options")
        if isinstance(options, list):
            node.option_nodes = [
                build_node(
                    option,
                    f"{path}/children_options/{index}",
                    parent=node,
                    templates=templates,
                    default_language=default_language,
                )
                for index, option in enumerate(options)
            ]
    return node


def node_at(descriptor: "CompiledDescriptor | Node", pointer: str) -> Node | None:
    """Resolve a descriptor node by JSON Pointer over the compiled tree.

    A member whose type is a `union` resolves through the alternatives, the
    same way the resolver does: the first alternative that declares the key.
    Without this, any edit below a union member was refused as an undeclared
    path even though the very same value loaded and validated.
    """
    from .pointer import parse_pointer

    node = descriptor.root if isinstance(descriptor, CompiledDescriptor) else descriptor
    for token in parse_pointer(pointer):
        if node.type == "object":
            child = node.children.get(token) if node.children else None
            if child is None:
                child = _union_child_node(node, token)
            if child is None:
                if node.additional_children is None:
                    return None
                if node.key_enum and token not in node.key_enum:
                    return None
                if node.key_pattern and not re.match(node.key_pattern, token):
                    return None
                child = node.additional_children
            node = child
        elif node.type == "array":
            node = _array_item_node(node, token)
            if node is None:
                return None
        elif node.type == "union":
            # Only a key can address a union reached this way: an array item of
            # union type was already resolved by the array branch above.
            node = _union_child_node(node, token)
            if node is None:
                return None
        else:
            return None
    return node


def _union_child_node(node: Node, token: str) -> Node | None:
    """One member of an object typed as a union, resolved by declaration order."""
    for option in node.option_nodes or ():
        if option.type == "object" and token in (option.children or {}):
            return option.children[token]
    return None


def _array_item_node(node: Node, token: str) -> Node | None:
    """Array item nodes are positional; identity-based editing is a later phase.

    A `children_options` array may hold more items than options; the first
    option is then the structural hint for the editor, while validation still
    accepts any alternative.
    """
    if not token.isdigit() or (token != "0" and token.startswith("0")):
        return None
    if node.option_nodes is not None:
        index = min(int(token), len(node.option_nodes) - 1)
        return node.option_nodes[index] if node.option_nodes else None
    return node.item_node
