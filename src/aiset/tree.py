"""Tree snapshots for generated editors (SPEC_service.md section 20).

One consistent, authorized snapshot of a subtree: the descriptor nodes, stored
source fragments, effective origin metadata and per-node capabilities. The
browser renders the whole tree from a single revision instead of issuing one
request per node.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .descriptor import Node
from .jsonsrc import ArrayNode, ObjectNode, TemplateNode
from .pointer import unescape_token
from .resolver import MISSING, effective_at
from .service import DocumentRegistration, DocumentState
from .validator import Limits, ValidationContext, validate_value

_DECORATION = re.compile(r"[-=_*~.\s]+")
# "// -- section ---" structures the file but explains nothing about a value.
_SECTION_RULE = re.compile(r"^[-=~*_]{2,}\s")


@dataclass
class Capabilities:
    """What one node permits, already filtered by descriptor and permissions."""

    edit: bool = False
    add: bool = False
    remove: bool = False
    reorder: bool = False
    add_child: bool = False
    remove_child: bool = False
    key_options: list[str] = field(default_factory=list)
    key_pattern: str | None = None
    unsupported: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "edit": self.edit,
            "add": self.add,
            "remove": self.remove,
            "reorder": self.reorder,
            "add_child": self.add_child,
            "remove_child": self.remove_child,
        }
        if self.key_options:
            out["key_options"] = list(self.key_options)
        if self.key_pattern:
            out["key_pattern"] = self.key_pattern
        if self.unsupported:
            out["unsupported"] = self.unsupported
        return out


def build_tree(
    state: DocumentState,
    path: str = "",
    *,
    view: str = "source",
    can_read_secret: bool = True,
    limits: Limits | None = None,
) -> dict[str, Any]:
    """Build the tree payload for one revision of one document."""
    limits = limits or Limits()
    registration: DocumentRegistration = state.registration
    root = state.document.find(path)
    node = _node_at(registration, path)
    builder = _TreeBuilder(state, view, can_read_secret, limits)
    payload: dict[str, Any] = {
        "document": registration.document_id,
        "path": path,
        "view": view,
        "revision": state.revision,
        "descriptor_revision": registration.descriptor.revision,
        "invalid_on_disk": state.invalid_on_disk,
        "loaded_from": state.loaded_from,
    }
    payload["exists"] = root is not None
    # A subtree snapshot reports the comments that introduce its own root.
    payload["node"] = builder.build(
        path, node, root, editable=True, comments=state.document.document_comments
    )
    return payload


class _TreeBuilder:
    def __init__(
        self, state: DocumentState, view: str, can_read_secret: bool, limits: Limits
    ) -> None:
        self.state = state
        self.view = view
        self.can_read_secret = can_read_secret
        self.limits = limits

    # -- public ----------------------------------------------------------
    def build(
        self,
        path: str,
        node: Node | None,
        cst: Any,
        *,
        editable: bool,
        comments: Iterable[Any] = (),
    ) -> dict[str, Any]:
        exists = True
        value_text = None
        effective = None
        default_applied = False
        origin: dict[str, Any] = {"kind": "file"}
        denied = False

        if cst is not None:
            value_text = self.state.document.value_text(cst)
            stored = self.state.document.stored_value(cst)
        else:
            exists = False
            stored = MISSING

        if self.view == "effective" and node is not None:
            if stored is MISSING:
                if node.has_default:
                    effective = node.default
                    default_applied = True
                    origin = {"kind": "default"}
                else:
                    effective = None
                    origin = {"kind": "absent"}
            else:
                provenance: dict[str, Any] = {}
                effective, _ = effective_at(
                    stored, node, self.state.registration.resolver, path, provenance=provenance
                )
                origin = _origin_of(provenance, path, self.state.provenance)

        if node is not None and not self.can_read_secret and self._subtree_has_secret(node):
            # A fragment containing an inaccessible secret is denied, not redacted.
            denied = True

        kind = _kind_of(self.state.registration, node, path)
        notes = [text for text in (_comment_text(c) for c in comments) if text]
        entry: dict[str, Any] = {
            "path": path,
            "exists": exists,
            "access_denied": denied,
            "origin": origin,
            "kind": kind,
            "capabilities": self._capabilities(path, node, cst, kind=kind, editable=editable, denied=denied),
        }
        if denied:
            entry["value_text"] = None
            entry["effective"] = None
        else:
            entry["value_text"] = value_text
            if self.view == "effective":
                entry["effective"] = effective
        if notes:
            # Comments of the source file: the only place that explains why a
            # value is written the way it is.
            entry["comments"] = notes
        if default_applied:
            entry["default_applied"] = True
        if node is not None:
            entry["field"] = node.describe()
            entry["apply"] = node.apply
            entry["type"] = node.type
            if node.type == "union" and stored is not MISSING:
                matched = _matched_option(stored, node, path, self.limits)
                if matched is not None:
                    entry["matched_option"] = matched
        else:
            entry["type"] = "undeclared"
            entry["apply"] = None
            entry["field"] = None
        if isinstance(cst, TemplateNode):
            # An unquoted ${VAR} / ${VAR:-default} node: the host edits the
            # variable name and the inline default separately.
            entry["template"] = {"name": cst.name, "default": cst.default}
        if node is not None and node.additional_children is not None:
            entry["additional_child"] = node.additional_children.describe()
        entry["children"] = self._children(path, node, cst, editable=editable)
        entry["items"] = self._items(path, node, cst, editable=editable)
        return entry

    def _subtree_has_secret(self, node: Node | None) -> bool:
        if node is None:
            return False
        if node.secret:
            return True
        for child in (node.children or {}).values():
            if self._subtree_has_secret(child):
                return True
        return self._subtree_has_secret(node.additional_children)

    # -- internals -------------------------------------------------------
    def _capabilities(
        self, path: str, node: Node | None, cst: Any, *, kind: str, editable: bool, denied: bool
    ) -> dict[str, Any]:
        caps = Capabilities()
        if node is None:
            return caps.to_dict()
        if _hooks_unsupported(self.state.registration, path):
            # Descriptor hook bindings are recognized but not executed in this
            # build; a write anywhere in the bound subtree is refused, so the
            # snapshot reports no capability and a reason (SPEC.md 17/19).
            caps.unsupported = "hooks"
            return caps.to_dict()
        parent_path, _, token = _split(path)
        parent_node = _node_at(self.state.registration, parent_path) if parent_path is not None else None
        caps.edit = bool(editable and not denied and not node.read_only)
        if not denied and self._subtree_has_secret(node) and not self.can_read_secret:
            caps.edit = False
        if kind == "array_item":
            # Removing or moving one item addresses its own path (SPEC_service
            # section 20), so the capability belongs to the item, not the array.
            array_path, _, _ = _split(path)
            array_node = _node_at(self.state.registration, array_path) if array_path else None
            array_cst = self.state.document.find(array_path) if array_path else None
            mutable = not denied and _array_items_mutable(array_node, array_cst)
            caps.remove = mutable
            caps.reorder = mutable and array_cst is not None and len(array_cst.items) > 1
        elif node.type == "array":
            caps.add = not denied and not node.read_only
            caps.remove = (
                not denied
                and not node.read_only
                and _array_item_removable(parent_node, self.state.document.find(path))
            )
        elif node.type == "object":
            caps.add_child = not denied and not node.read_only and bool(
                node.additional_children is not None or node.children
            )
            caps.remove_child = not denied and _parent_allows_removal(parent_node, node, token)
        # An entry of a dynamic object collection is addressed by its own path,
        # like an array item, so it can be removed directly, whatever its value
        # type. The container that owns `additional_children` is not an entry.
        dynamic_entry = (
            parent_node is not None
            and parent_node.type == "object"
            and parent_node.additional_children is not None
            and (not parent_node.children or unescape_token(token) not in parent_node.children)
        )
        if dynamic_entry and not denied and _parent_allows_removal(parent_node, node, token):
            caps.remove = True
        caps.key_options = list(node.key_enum or [])
        caps.key_pattern = node.key_pattern
        return caps.to_dict()

    def _children(self, path: str, node: Node | None, cst: Any, *, editable: bool) -> list[dict[str, Any]]:
        """Stored members in file order, then declared members that are absent.

        A declared but unwritten key belongs to the snapshot as well, marked
        `exists: false`, so an editor can offer it without guessing the
        descriptor on its own. Hosts decide whether to render it.
        """
        if node is None or node.type != "object":
            return []
        out: list[dict[str, Any]] = []
        stored: set[str] = set()
        if isinstance(cst, ObjectNode):
            for child in cst.members:
                token = _escape(child.label)
                child_path = f"{path}/{token}"
                stored.add(token)
                child_node = _node_at(self.state.registration, child_path)
                out.append(
                    self.build(
                        child_path, child_node, child.node, editable=editable, comments=child.leading
                    )
                )
        for name, child_node in (node.children or {}).items():
            token = _escape(name)
            if token in stored:
                continue
            out.append(self.build(f"{path}/{token}", child_node, None, editable=editable))
        return out

    def _items(self, path: str, node: Node | None, cst: Any, *, editable: bool) -> list[dict[str, Any]]:
        if node is None or node.type != "array" or not isinstance(cst, ArrayNode):
            return []
        out: list[dict[str, Any]] = []
        for index, item in enumerate(cst.items):
            item_path = f"{path}/{index}"
            out.append(
                self.build(
                    item_path,
                    _node_at(self.state.registration, item_path),
                    item.node,
                    editable=editable,
                    comments=item.leading,
                )
            )
        return out


def _comment_text(comment: Any) -> str:
    """One source comment as a plain line, without its marker."""
    raw = comment if isinstance(comment, str) else comment.text
    lines: list[str] = []
    for piece in raw.splitlines():
        line = piece.strip()
        for marker in ("//", "/*", "*/"):
            if line.startswith(marker):
                line = line[len(marker) :].strip()
        if line.startswith("*"):
            line = line[1:].strip()
        if line and not _DECORATION.fullmatch(line) and not _SECTION_RULE.match(line):
            lines.append(line)
    return " ".join(lines).strip()


def _origin_of(provenance: dict[str, Any], path: str, state_provenance: dict[str, Any]) -> dict[str, Any]:
    entry = provenance.get(path)
    if entry is None:
        entry = state_provenance.get(path)
    if entry is None:
        return {"kind": "file"}
    return dict(entry)


def _array_items_mutable(array_node: Node | None, array_cst: Any) -> bool:
    """Items can be removed or moved unless the array itself is protected."""
    if array_node is None or array_node.read_only or array_node.required:
        return False
    return isinstance(array_cst, ArrayNode) and bool(array_cst.items)


def _array_item_removable(parent_node: Node | None, array_node: Any) -> bool:
    """An array is removable from its parent unless the parent is protected."""
    if array_node is None:
        return False
    if parent_node is not None and (parent_node.read_only or parent_node.required):
        return False
    return True


def _parent_allows_removal(parent: Node | None, child: Node, token: str) -> bool:
    if parent is None:
        return False
    if child.required or child.read_only or child.const is not None:
        return False
    if parent.children and token in parent.children:
        return True
    return parent.additional_children is not None


def _hooks_unsupported(registration: DocumentRegistration, path: str) -> bool:
    """True when the node or an ancestor carries descriptor hook bindings.

    Hook bindings are recognized but not executed in this build, and a write
    anywhere in the bound subtree is refused (SPEC.md 19.2), so the whole subtree
    is reported as unsupported.
    """
    from .pointer import format_pointer, parse_pointer

    tokens = parse_pointer(path)
    for index in range(len(tokens) + 1):
        prefix = format_pointer(tokens[:index])
        node = _node_at(registration, prefix) if prefix else registration.descriptor.root
        if node is not None and node.hooks:
            return True
    return False


def _matched_option(value: Any, node: Node, path: str, limits: Limits) -> int | None:
    """Index of the first `union` alternative a stored value validates against."""
    if not node.option_nodes:
        return None
    for index, option in enumerate(node.option_nodes):
        if not validate_value(value, option, path, ValidationContext(limits=limits)):
            return index
    return None


def _kind_of(registration: DocumentRegistration, node: Node | None, path: str) -> str:
    """Shape of one node: an array, one of its items, a dynamic key or a leaf.

    An item is recognised by its parent rather than by its own type: a string
    inside an array is still an item and can be removed or reordered.
    """
    if node is None:
        return "undeclared"
    if node.type == "array":
        return "array"
    parent_path, _, token = _split(path)
    parent = _node_at(registration, parent_path) if parent_path else None
    if parent is not None and parent.type == "array":
        return "array_item"
    if node.type == "object":
        if parent is not None and parent.type == "object" and parent.additional_children is not None:
            if not parent.children or unescape_token(token) not in parent.children:
                return "dynamic_key"
        return "dynamic_key" if node.additional_children is not None and not node.children else "object"
    return "leaf"


def _split(path: str) -> tuple[str | None, str, str]:
    if not path:
        return None, "", ""
    parent, _, token = path.rpartition("/")
    return (parent or None), token, token


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _node_at(registration: DocumentRegistration, path: str) -> Node | None:
    from .descriptor import node_at

    return node_at(registration.descriptor, path)