"""Source-preserving JSON5/template engine (SPEC.md sections 6 and 7).

Parses JSON5 documents that may contain environment template tokens
(``${VAR}``, ``${VAR:-default}``) into a concrete syntax tree with exact source
spans, comment ownership, and localized edit operations. A read that performs no
edit never rewrites the file, and accepted edits keep every untouched source
byte identical. There is no parse-and-dump fallback (SPEC.md 7.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from .errors import CommentPreservationConflict, ParseError, PathError
from .pointer import APPEND_MARKER, parse_pointer

IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*?))?\}")
TEMPLATE_START = "${"
WHITESPACE = " \t\r\n\f\v\u00a0\ufeff"
LINE_BREAKS = "\r\n\u2028\u2029"

SCALAR_KINDS = ("string", "number", "boolean", "null", "template")


@dataclass
class TemplateRef:
    """An explicit placeholder node kept unresolved in the stored tree."""

    name: str
    default: str | None = None

    def source_text(self) -> str:
        if self.default is None:
            return "${" + self.name + "}"
        return "${" + self.name + ":-" + self.default + "}"


@dataclass
class Comment:
    """A source comment with its exact span and text."""

    kind: str  # "line" or "block"
    start: int
    end: int
    text: str

    def text_with_newline(self) -> str:
        return self.text + "\n" if self.kind == "line" else self.text


class Node:
    """Base class of the concrete syntax tree."""

    kind = "scalar"

    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end
        self.opening_comments: list[Comment] = []

    def structural_kind(self) -> str:
        return self.kind if self.kind in ("object", "array") else "scalar"

    def descendants(self) -> Iterator["Node"]:
        yield self

    def has_template(self) -> bool:
        return any(node.has_template() for node in self.descendants() if node is not self)

    def has_comments(self) -> bool:
        """Structural flag; exact comment detection needs the document."""
        return False


class ScalarNode(Node):
    kind = "scalar"

    def __init__(self, start: int, end: int, raw: str, value: Any) -> None:
        super().__init__(start, end)
        self.raw = raw
        self.value = value


class StringNode(ScalarNode):
    kind = "string"

    def __init__(self, start: int, end: int, raw: str, value: str, templates: bool) -> None:
        super().__init__(start, end, raw, value)
        self.templates = templates

    def has_template(self) -> bool:
        return self.templates or super().has_template()


class NumberNode(ScalarNode):
    kind = "number"


class BooleanNode(ScalarNode):
    kind = "boolean"


class NullNode(ScalarNode):
    kind = "null"


class TemplateNode(Node):
    kind = "template"

    def __init__(self, start: int, end: int, raw: str, name: str, default: str | None) -> None:
        super().__init__(start, end)
        self.raw = raw
        self.name = name
        self.default = default

    def has_template(self) -> bool:
        return True

    def value(self) -> TemplateRef:
        return TemplateRef(self.name, self.default)


@dataclass
class Member:
    label: str
    key_raw: str
    key_start: int
    key_end: int
    node: Node
    leading: list[Comment] = field(default_factory=list)
    mid: list[Comment] = field(default_factory=list)
    trailing: list[Comment] = field(default_factory=list)
    comma_pos: int | None = None

    @property
    def commented(self) -> bool:
        return bool(self.leading or self.mid or self.trailing or self.node.has_comments())


@dataclass
class Item:
    node: Node
    leading: list[Comment] = field(default_factory=list)
    trailing: list[Comment] = field(default_factory=list)
    comma_pos: int | None = None

    @property
    def commented(self) -> bool:
        return bool(self.leading or self.trailing or self.node.has_comments())


class ObjectNode(Node):
    kind = "object"

    def __init__(self, start: int, end: int) -> None:
        super().__init__(start, end)
        self.members: list[Member] = []
        self.block_end: list[Comment] = []

    def member(self, label: str) -> Member | None:
        for entry in self.members:
            if entry.label == label:
                return entry
        return None

    def descendants(self) -> Iterator[Node]:
        yield self
        for entry in self.members:
            yield from entry.node.descendants()


class ArrayNode(Node):
    kind = "array"

    def __init__(self, start: int, end: int) -> None:
        super().__init__(start, end)
        self.items: list[Item] = []
        self.block_end: list[Comment] = []

    def descendants(self) -> Iterator[Node]:
        yield self
        for item in self.items:
            yield from item.node.descendants()


def _commented_inside(document: "Document", node: Node) -> bool:
    """True when at least one comment lies strictly inside the node span."""
    return any(node.start < comment.start < node.end for comment in document.comments)


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

_NUMBER_RE = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?|Infinity|NaN)$"
)
_KEYWORD_VALUES = {"true": True, "false": False, "null": None}
_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "/": "/",
    "\n": "",
}


class _Parser:
    def __init__(self, text: str, document: "Document") -> None:
        self.text = text
        self.document = document
        self.pos = 0

    # -- low level -------------------------------------------------------
    def fail(self, message: str, pos: int | None = None) -> ParseError:
        offset = self.pos if pos is None else pos
        line, column = self.document.line_col(offset)
        return ParseError(f"{message} (line {line}, column {column})")

    def peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.text[index] if index < len(self.text) else ""

    def starts_with(self, value: str) -> bool:
        return self.text.startswith(value, self.pos)

    def read_line_comment(self) -> Comment:
        start = self.pos
        self.pos += 2
        while self.pos < len(self.text) and self.text[self.pos] not in LINE_BREAKS:
            self.pos += 1
        comment = Comment("line", start, self.pos, self.text[start : self.pos])
        self.document.comments.append(comment)
        return comment

    def read_block_comment(self) -> Comment:
        start = self.pos
        end = self.text.find("*/", self.pos + 2)
        if end < 0:
            raise self.fail("Unterminated block comment", start)
        self.pos = end + 2
        comment = Comment("block", start, self.pos, self.text[start : self.pos])
        self.document.comments.append(comment)
        return comment

    def skip_whitespace(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in WHITESPACE:
            self.pos += 1

    def skip_trivia(self) -> list[Comment]:
        found: list[Comment] = []
        while True:
            self.skip_whitespace()
            if self.starts_with("//"):
                found.append(self.read_line_comment())
            elif self.starts_with("/*"):
                found.append(self.read_block_comment())
            else:
                return found

    def take_same_line_comments(self) -> list[Comment]:
        """Comments that follow the current position without a line break."""
        found: list[Comment] = []
        while True:
            probe = self.pos
            while probe < len(self.text) and self.text[probe] in " \t":
                probe += 1
            if probe >= len(self.text) or self.text[probe] == "\n":
                break
            if self.text.startswith("//", probe) or self.text.startswith("/*", probe):
                self.pos = probe
                found.append(self.read_line_comment() if self.text[probe : probe + 2] == "//" else self.read_block_comment())
                continue
            break
        return found

    # -- values ----------------------------------------------------------
    def parse_document_value(self) -> Node:
        self.document_comments = self.skip_trivia()
        node = self.parse_value()
        node.opening_comments = self.document_comments
        self.document_trailing = self.skip_trivia()
        self.skip_whitespace()
        if self.pos < len(self.text):
            raise self.fail("Trailing content after the root value")
        return node

    def parse_value(self) -> Node:
        char = self.peek()
        if char == "{":
            return self.parse_object()
        if char == "[":
            return self.parse_array()
        if char in "'\"":
            return self.parse_string()
        if self.starts_with(TEMPLATE_START):
            return self.parse_template()
        return self.parse_literal()

    def parse_object(self) -> ObjectNode:
        start = self.pos
        self.pos += 1  # '{'
        node = ObjectNode(start, start + 1)
        node.opening_comments = self.take_same_line_comments()
        seen: dict[str, int] = {}
        while True:
            pending = self.skip_trivia()
            if self.peek() == "}":
                node.block_end = pending
                self.pos += 1
                node.end = self.pos
                return node
            label, key_start, key_end, key_raw = self.parse_key()
            if label in seen:
                line, column = self.document.line_col(key_start)
                raise ParseError(
                    f"Duplicate object key {label!r} (line {line}, column {column}); "
                    "an ambiguous key is never edited"
                )
            seen[label] = key_start
            if self.peek() != ":":
                raise self.fail("Expected ':' after an object key")
            self.pos += 1
            mid = self.skip_trivia()
            value = self.parse_value()
            opening, value.opening_comments = value.opening_comments, []
            comma_pos = None
            if self.peek() == ",":
                comma_pos = self.pos
                self.pos += 1
            trailing = opening + self.take_same_line_comments()
            node.members.append(
                Member(label, key_raw, key_start, key_end, value, pending, mid, trailing, comma_pos)
            )

    def parse_array(self) -> ArrayNode:
        start = self.pos
        self.pos += 1  # '['
        node = ArrayNode(start, start + 1)
        node.opening_comments = self.take_same_line_comments()
        while True:
            pending = self.skip_trivia()
            if self.peek() == "]":
                node.block_end = pending
                self.pos += 1
                node.end = self.pos
                return node
            value = self.parse_value()
            opening, value.opening_comments = value.opening_comments, []
            comma_pos = None
            if self.peek() == ",":
                comma_pos = self.pos
                self.pos += 1
            trailing = opening + self.take_same_line_comments()
            node.items.append(Item(value, pending, trailing, comma_pos))

    def parse_key(self) -> tuple[str, int, int, str]:
        char = self.peek()
        if char in "'\"":
            node = self.parse_string()
            assert isinstance(node, StringNode)
            return node.value, node.start, node.end, node.raw
        start = self.pos
        while self.pos < len(self.text) and (
            self.text[self.pos].isalnum() or self.text[self.pos] in "_$.-"
        ):
            self.pos += 1
        if self.pos == start:
            raise self.fail("Expected an object key")
        raw = self.text[start : self.pos]
        return raw, start, self.pos, raw

    def parse_string(self) -> StringNode:
        start = self.pos
        quote = self.text[self.pos]
        self.pos += 1
        chunks: list[str] = []
        has_templates = False
        while True:
            if self.pos >= len(self.text):
                raise self.fail("Unterminated string", start)
            char = self.text[self.pos]
            if char == quote:
                self.pos += 1
                break
            if char in LINE_BREAKS:
                raise self.fail("Unescaped line break in string")
            if char == "\\":
                self.pos += 1
                chunks.append(self.parse_escape())
                continue
            if self.text.startswith(TEMPLATE_START, self.pos) and has_placeholder(self.text, self.pos):
                has_templates = True
            chunks.append(char)
            self.pos += 1
        raw = self.text[start : self.pos]
        return StringNode(start, self.pos, raw, "".join(chunks), has_templates)

    def parse_escape(self) -> str:
        if self.pos >= len(self.text):
            raise self.fail("Dangling escape character")
        char = self.text[self.pos]
        self.pos += 1
        if char == "u":
            hex_digits = self.text[self.pos : self.pos + 4]
            if len(hex_digits) != 4 or any(c not in "0123456789abcdefABCDEF" for c in hex_digits):
                raise self.fail("Malformed \\u escape")
            self.pos += 4
            return chr(int(hex_digits, 16))
        if char == "x":
            hex_digits = self.text[self.pos : self.pos + 2]
            if len(hex_digits) != 2:
                raise self.fail("Malformed \\x escape")
            self.pos += 2
            return chr(int(hex_digits, 16))
        if char in LINE_BREAKS:
            if char == "\r" and self.peek() == "\n":
                self.pos += 1
            return ""
        if char not in _ESCAPES:
            raise self.fail(f"Unsupported escape sequence \\{char}")
        return _ESCAPES[char]

    def parse_template(self) -> TemplateNode:
        start = self.pos
        end = self.text.find("}", self.pos + 2)
        if end < 0:
            raise self.fail("Unterminated template token", start)
        inner = self.text[start + 2 : end]
        self.pos = end + 1
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)(?::-(.*))?", inner, re.DOTALL)
        if not match:
            raise self.fail(
                "Unsupported template token; only ${VAR} and ${VAR:-default} are supported",
                start,
            )
        return TemplateNode(start, self.pos, self.text[start : self.pos], match.group(1), match.group(2))

    def parse_literal(self) -> ScalarNode:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in WHITESPACE and self.text[self.pos] not in ",:{}[]":
            if self.text[self.pos] in LINE_BREAKS or self.text.startswith(TEMPLATE_START, self.pos):
                break
            self.pos += 1
        raw = self.text[start : self.pos]
        if not raw:
            raise self.fail("Expected a value")
        if raw in _KEYWORD_VALUES:
            cls = BooleanNode if isinstance(_KEYWORD_VALUES[raw], bool) else NullNode
            return cls(start, self.pos, raw, _KEYWORD_VALUES[raw])
        if raw in ("undefined", "True", "False"):
            raise self.fail(f"Unsupported literal {raw!r}", start)
        if not _NUMBER_RE.match(raw):
            raise self.fail(f"Invalid value token {raw!r}", start)
        return NumberNode(start, self.pos, raw, _to_number(raw, start))


def has_placeholder(text: str, pos: int) -> bool:
    match = PLACEHOLDER_RE.match(text, pos)
    return match is not None


def _to_number(raw: str, pos: int) -> int | float:
    try:
        if raw.lower().startswith(("0x", "-0x", "+0x")):
            return int(raw, 16)
        if raw in ("Infinity", "+Infinity"):
            raise ValueError("non-finite")
        if raw == "-Infinity":
            raise ValueError("non-finite")
        if raw == "NaN":
            raise ValueError("not a number")
        if "." in raw or "e" in raw or "E" in raw:
            return float(raw)
        return int(raw)
    except ValueError as exc:
        raise ParseError(f"Number {raw!r} is not portable: {exc}") from exc


# --------------------------------------------------------------------------
# document
# --------------------------------------------------------------------------


class Document:
    """A parsed source document that keeps every original byte."""

    def __init__(self, text: str, *, origin: str = "<memory>") -> None:
        self.text = text
        self.origin = origin
        self.comments: list[Comment] = []
        self.document_comments: list[Comment] = []
        self.document_trailing: list[Comment] = []
        parser = _Parser(text, self)
        self.root: Node = parser.parse_document_value()
        self.document_comments = parser.document_comments
        self.document_trailing = parser.document_trailing

    # -- positions -------------------------------------------------------
    def line_col(self, offset: int) -> tuple[int, int]:
        line = self.text.count("\n", 0, min(offset, len(self.text))) + 1
        last_newline = self.text.rfind("\n", 0, min(offset, len(self.text)))
        return line, offset - last_newline

    def line_indent(self, offset: int) -> str:
        start = self.text.rfind("\n", 0, offset) + 1
        prefix = self.text[start:offset]
        return prefix if prefix.strip() == "" else ""

    # -- navigation ------------------------------------------------------
    def find(self, pointer: str) -> Node | None:
        """Return the node addressed by a pointer, or None when absent."""
        node: Node = self.root
        for token in parse_pointer(pointer):
            if isinstance(node, ObjectNode):
                member = node.member(token)
                if member is None:
                    return None
                node = member.node
            elif isinstance(node, ArrayNode):
                if not token.isdigit():
                    raise PathError(f"Array index expected, got {token!r} in {pointer!r}")
                index = int(token)
                if index >= len(node.items):
                    return None
                node = node.items[index].node
            else:
                raise PathError(f"Path segment {token!r} does not address a container in {pointer!r}")
        return node

    def find_parent(self, pointer: str) -> tuple[Node, str]:
        tokens = parse_pointer(pointer)
        if not tokens:
            raise PathError("The root pointer is read-only in v1")
        parent = self.root
        for token in tokens[:-1]:
            if isinstance(parent, ObjectNode):
                member = parent.member(token)
                if member is None:
                    raise PathError(f"Missing object key {token!r} in {parent_path(pointer)}")
                parent = member.node
            elif isinstance(parent, ArrayNode):
                if not token.isdigit() or int(token) >= len(parent.items):
                    raise PathError(f"Missing array index {token!r} in {pointer}")
                parent = parent.items[int(token)].node
            else:
                raise PathError(f"Path segment {token!r} does not address a container in {pointer!r}")
        return parent, tokens[-1]

    # -- values ----------------------------------------------------------
    def source_of(self, node: Node) -> str:
        return self.text[node.start : node.end]

    def stored_value(self, node: Node) -> Any:
        """Parse a node into Python data, keeping template tokens explicit."""
        if isinstance(node, TemplateNode):
            return TemplateRef(node.name, node.default)
        if isinstance(node, ScalarNode):
            return node.value
        if isinstance(node, ObjectNode):
            return {member.label: self.stored_value(member.node) for member in node.members}
        if isinstance(node, ArrayNode):
            return [self.stored_value(item.node) for item in node.items]
        raise ParseError("Unknown syntax node")

    def value_text(self, node: Node) -> str:
        return self.source_of(node)

    def format_of(self, node: Node) -> str:
        return "json5-template" if node.has_template() else "json5"

    def paths(self, pointer: str = "") -> list[str]:
        """Every pointer present under the given pointer (self included)."""
        node = self.find(pointer)
        if node is None:
            return []
        out = [pointer]

        def walk(prefix: str, current: Node) -> None:
            if isinstance(current, ObjectNode):
                for member in current.members:
                    child = prefix + "/" + escape(member.label)
                    out.append(child)
                    walk(child, member.node)
            elif isinstance(current, ArrayNode):
                for index, item in enumerate(current.items):
                    child = f"{prefix}/{index}"
                    out.append(child)
                    walk(child, item.node)

        walk(pointer, node)
        return out

    # -- editing ---------------------------------------------------------
    def apply_set(self, pointer: str, value_text: str, *, indent_unit: str | None = None) -> str:
        """Return the full source text after one localized replacement."""
        tokens = parse_pointer(pointer)
        if not tokens:
            raise PathError("The root pointer is read-only in v1")
        fragment = parse_fragment(value_text)
        parent, token = self.find_parent(pointer)
        if isinstance(parent, ObjectNode):
            member = parent.member(token)
            if member is None:
                return self._create_member(parent, token, fragment)
            trivia = member.leading + member.mid + member.trailing
            return self._replace_node(member.node, fragment, trivia, pointer)
        if isinstance(parent, ArrayNode):
            if not token.isdigit():
                raise PathError(f"Array index expected, got {token!r} in {pointer!r}")
            index = int(token)
            if index >= len(parent.items):
                raise PathError("Setting an array element requires an existing index")
            item = parent.items[index]
            trivia = item.leading + item.trailing
            return self._replace_node(item.node, fragment, trivia, pointer)
        raise PathError(f"Path {pointer!r} does not address a container")

    # -- structural edits ------------------------------------------------
    def apply_add(self, pointer: str, value_text: str) -> str:
        """Append an array item (`-` token) or create a permitted object key."""
        tokens = parse_pointer(pointer, allow_append=True)
        if not tokens:
            raise PathError("The root pointer is read-only")
        fragment = parse_fragment(value_text)
        if tokens[-1] == APPEND_MARKER:
            container = self.find("/".join(pointer.split("/")[:-1]))
            if not isinstance(container, ArrayNode):
                raise PathError("The append token '-' requires an array")
            return self._append_item(container, fragment)
        parent = self.find("/".join(pointer.split("/")[:-1]))
        if not isinstance(parent, ObjectNode):
            raise PathError(f"Path {pointer!r} does not address an object")
        return self._create_member(parent, tokens[-1], fragment)

    def apply_remove(self, pointer: str) -> str:
        """Remove one array item or one object property with its own comments."""
        parent, token = self.find_parent(pointer)
        if isinstance(parent, ArrayNode):
            index = self._array_index(parent, token, pointer)
            item = parent.items[index]
            start = _line_start(
                self.text, item.leading[0].start if item.leading else item.node.start
            )
            end = _item_end(item)
            last = index == len(parent.items) - 1
            if last and len(parent.items) > 1:
                # The preceding separator is the one that disappears with the item.
                start = _absorb_previous_separator(self.text, start, parent.start)
                return self._splice(start, end, "")
            if item.comma_pos is not None:
                end = item.comma_pos + 1
            elif not last:
                end = _after_comma(self.text, end)
            start, end = _tidy_inline(self.text, start, end)
            return self._splice(start, _extend_line(self.text, end), "")
        if isinstance(parent, ObjectNode):
            member = parent.member(token)
            if member is None:
                raise PathError(f"Missing object key {token!r}")
            start = _line_start(
                self.text, member.leading[0].start if member.leading else member.key_start
            )
            end = _member_end(member)
            position = index_of_member(parent, token)
            last = position == len(parent.members) - 1
            if last and len(parent.members) > 1:
                start = _absorb_previous_separator(self.text, start, parent.start)
                return self._splice(start, end, "")
            if member.comma_pos is not None:
                end = member.comma_pos + 1
            elif not last:
                end = _after_comma(self.text, end)
            start, end = _tidy_inline(self.text, start, end)
            return self._splice(start, _extend_line(self.text, end), "")
        raise PathError(f"Path {pointer!r} does not address a container")

    def apply_move(self, source: str, target: str) -> str:
        """Move one array item, taking its attached comments with it."""
        parent_pointer, token = self.find_parent(source)
        if not isinstance(parent_pointer, ArrayNode):
            raise PathError("Only array items can be moved")
        index = self._array_index(parent_pointer, token, source)
        _, target_token = self.find_parent(target)
        position = self._array_index(parent_pointer, target_token, target, allow_end=True)
        blocks = [block_of(self, entry) for entry in parent_pointer.items]
        moved = blocks.pop(index)
        blocks.insert(position, moved)
        remaining = blocks

        base_indent = self.base_indent_at(parent_pointer.start)
        unit = self._indent_unit(parent_pointer)
        body = self._render_array_body(parent_pointer, remaining, base_indent, unit)
        return self._splice(parent_pointer.start, parent_pointer.end, body)

    def apply_rename(self, pointer: str, new_key: str) -> str:
        """Rename one object key in place, keeping its value and comments."""
        new_key = "" if new_key is None else str(new_key)
        if not new_key:
            raise PathError("A new key is required")
        parent, token = self.find_parent(pointer)
        if not isinstance(parent, ObjectNode):
            raise PathError(f"Path {pointer!r} does not address an object key")
        member = parent.member(token)
        if member is None:
            raise PathError(f"Missing object key {token!r}")
        if new_key == token:
            return self.text
        if parent.member(new_key) is not None:
            raise PathError(f"Duplicate object key {new_key!r}")
        key_text = new_key if IDENTIFIER_RE.match(new_key) else quote_key(new_key)
        return self._splice(member.key_start, member.key_end, key_text)

    def _array_index(
        self, parent: ArrayNode, token: str, pointer: str, *, allow_end: bool = False
    ) -> int:
        if not token.isdigit():
            raise PathError(f"Array index expected, got {token!r} in {pointer!r}")
        index = int(token)
        limit = len(parent.items) + (1 if allow_end else 0)
        if index >= limit:
            raise PathError(f"Array index out of range in {pointer!r}")
        return index

    def _append_item(self, parent: ArrayNode, fragment: "Document") -> str:
        """Append one item using the array's own layout and comma style."""
        base_indent = self.base_indent_at(parent.start)
        unit = self._indent_unit(parent)
        multiline = "\n" in self.source_of(parent)
        block = reindent(fragment.source_of(fragment.root), base_indent + unit)
        if not multiline:
            if not parent.items:
                return self._splice(parent.start + 1, parent.end - 1, block)
            at = _before_close(parent)
            return self._splice(at, at, f", {block}")
        entry_indent = _inner_indent(self, parent, base_indent, unit)
        keep_comma = bool(parent.items) and _has_trailing_comma(
            self.text, _item_end(parent.items[-1])
        )
        entry = entry_indent + block
        if not parent.items:
            at = _after_open(parent)
            return self._splice(at, at, "\n" + entry + ("," if keep_comma else ""))
        last = parent.items[-1]
        if last.comma_pos is not None:
            # Insert after the item and its comments so trailing trivia stays put.
            at = max(last.comma_pos + 1, _item_end(last))
            return self._splice(at, at, "\n" + entry + ",")
        at = _item_end(last)
        return self._splice(at, at, ",\n" + entry)

    def _render_array_body(
        self, parent: ArrayNode, blocks: list[tuple[str, int | None]], base_indent: str, unit: str
    ) -> str:
        keep_comma = bool(parent.items) and _has_trailing_comma(
            self.text, _item_end(parent.items[-1])
        )
        if not blocks:
            return "[]" if not parent.opening_comments and not parent.block_end else self._render_array_tail(parent, base_indent)
        if "\n" not in self.source_of(parent):
            # An inline array keeps its inline layout.
            last_index = len(blocks) - 1
            parts = [
                _with_separator(block, keep_comma and index == last_index)
                for index, block in enumerate(blocks)
            ]
            opening = (" ".join(c.text for c in parent.opening_comments) + " ") if parent.opening_comments else ""
            tail = (" " + " ".join(c.text for c in parent.block_end)) if parent.block_end else ""
            return "[" + opening + ", ".join(parts) + tail + "]"
        entry_indent = _inner_indent(self, parent, base_indent, unit)
        lines = ["["]
        if parent.opening_comments:
            lines[-1] += " " + " ".join(c.text for c in parent.opening_comments)
        for index, block in enumerate(blocks):
            last = index == len(blocks) - 1
            rendered = _with_separator(block, keep_comma or not last)
            lines.append("\n".join(entry_indent + line for line in rendered.split("\n")))
        for comment in parent.block_end:
            lines.append(entry_indent + comment.text)
        lines.append(base_indent + "]")
        return "\n".join(lines)

    def _render_array_tail(self, parent: ArrayNode, base_indent: str) -> str:
        entry_indent = base_indent + self._indent_unit(parent)
        lines = ["["]
        for comment in parent.block_end:
            lines.append(entry_indent + comment.text)
        lines.append(base_indent + "]")
        return "\n".join(lines)

    # -- edit helpers ----------------------------------------------------
    def _replace_node(
        self, old: Node, fragment: "Document", trivia: list[Comment], pointer: str
    ) -> str:
        replacement = self._replacement_text(old, fragment, fragment.root, trivia, pointer)
        return self._splice(old.start, old.end, replacement)

    def _replacement_text(
        self,
        old: Node,
        fragment: "Document",
        submitted: Node,
        trivia: list[Comment],
        pointer: str,
    ) -> str:
        """Replacement text for one value, preserving every attached comment."""
        old_kind = old.structural_kind()
        new_kind = submitted.structural_kind()
        if old_kind == new_kind == "object":
            return self._object_replacement(old, fragment, submitted, pointer)
        if old_kind == new_kind == "array":
            return self._array_replacement(old, fragment, submitted, pointer)
        if old_kind != new_kind and (trivia or self._commented_inside(old)):
            raise CommentPreservationConflict(
                f"Replacing the commented value at {pointer} with a different structural "
                "type would detach its comments"
            )
        return reindent(fragment.source_of(submitted), self._continuation_indent(old))

    def _commented_inside(self, node: Node) -> bool:
        return any(node.start < comment.start < node.end for comment in self.comments)

    def _member_commented(self, member: Member) -> bool:
        return bool(
            member.leading or member.mid or member.trailing or self._commented_inside(member.node)
        )

    def _item_commented(self, item: Item) -> bool:
        return bool(item.leading or item.trailing or self._commented_inside(item.node))

    def base_indent_at(self, offset: int) -> str:
        """Leading whitespace of the line containing offset."""
        line_start = self.text.rfind("\n", 0, offset) + 1
        prefix = self.text[line_start:offset]
        return prefix[: len(prefix) - len(prefix.lstrip(" \t"))]

    def _continuation_indent(self, node: Node) -> str:
        """Indentation for continuation lines of a value starting at node."""
        return self.base_indent_at(node.start) + self._indent_unit(node)

    def _object_replacement(
        self, old: ObjectNode, fragment: "Document", submitted: ObjectNode, pointer: str
    ) -> str:
        old_text = self.source_of(old)
        if not self._commented_inside(old):
            return reindent(fragment.source_of(submitted), self._continuation_indent(old))

        keep_comma = bool(old.members) and old.members[-1].comma_pos is not None
        old_members = {member.label: member for member in old.members}
        chunks: list[str] = []
        used: set[str] = set()
        last_index = len(submitted.members) - 1
        for index, new_member in enumerate(submitted.members):
            comma = "" if index == last_index and not keep_comma else ","
            old_member = old_members.get(new_member.label)
            if old_member is None or not self._member_commented(old_member):
                chunks.append(_submitted_chunk(fragment, new_member, comma))
                continue
            if old_member.node.structural_kind() != new_member.node.structural_kind():
                raise CommentPreservationConflict(
                    f"Cannot change the structural type of commented member "
                    f"{new_member.label!r} at {pointer}"
                )
            used.add(new_member.label)
            chunks.append(
                _chunk_with_old_comments(fragment, old_member, new_member, comma)
            )

        missing = [
            label
            for label, member in old_members.items()
            if self._member_commented(member) and label not in used
        ]
        if missing:
            raise CommentPreservationConflict(
                "Replacement drops commented members: " + ", ".join(sorted(missing))
            )
        multiline = "\n" in old_text or "\n" in fragment.source_of(submitted)
        return _build_object_body(
            self, old, chunks, multiline, self.base_indent_at(old.start), self._indent_unit(old)
        )

    def _array_replacement(
        self, old: ArrayNode, fragment: "Document", submitted: ArrayNode, pointer: str
    ) -> str:
        if len(old.items) != len(submitted.items):
            if any(self._item_commented(item) for item in old.items) or self._commented_inside(old):
                raise CommentPreservationConflict(
                    "Changing the array length would remove, insert or reorder commented items"
                )
            return reindent(fragment.source_of(submitted), self._continuation_indent(old))
        edits: list[tuple[int, int, str]] = []
        for old_item, new_item in zip(old.items, submitted.items):
            trivia = old_item.leading + old_item.trailing
            edits.append(
                (
                    old_item.node.start,
                    old_item.node.end,
                    self._replacement_text(
                        old_item.node, fragment, new_item.node, trivia, pointer
                    ),
                )
            )
        result = self.text
        for start, end, replacement in sorted(edits, key=lambda edit: edit[0], reverse=True):
            result = result[:start] + replacement + result[end:]
        return result

    def _create_member(self, parent: ObjectNode, label: str, fragment: "Document") -> str:
        if label in {member.label for member in parent.members}:
            raise PathError(f"Duplicate object key {label!r}")
        submitted = fragment.root
        key_text = label if IDENTIFIER_RE.match(label) else quote_key(label)
        base_indent = self.base_indent_at(parent.start)
        multiline = "\n" in self.source_of(parent)
        unit = self._indent_unit(parent)
        value_text = reindent(fragment.source_of(submitted), base_indent + unit)
        if multiline:
            inner_indent = _inner_indent(self, parent, base_indent, unit)
            entry = f"{inner_indent}{key_text}: {value_text}"
            if not parent.members:
                return self._splice(_after_open(parent), _after_open(parent), "\n" + entry)
            last = parent.members[-1]
            if last.comma_pos is None:
                at = _member_end(last)
                return self._splice(at, at, ",\n" + entry)
            # Insert after the member and its comments so trailing trivia stays put.
            at = max(last.comma_pos + 1, _member_end(last))
            return self._splice(at, at, "\n" + entry + ",")
        entry = f"{key_text}: {value_text}"
        if not parent.members:
            return self._splice(parent.start + 1, parent.end - 1, entry)
        at = _before_close(parent)
        return self._splice(at, at, f", {entry}")

    def _splice(self, start: int, end: int, replacement: str) -> str:
        return self.text[:start] + replacement + self.text[end:]

    def _indent_unit(self, node: Node) -> str:
        """Infer the local indentation unit from the surrounding source."""
        outer = self.base_indent_at(node.start)
        if isinstance(node, ObjectNode) and node.members:
            inner = self.base_indent_at(node.members[0].key_start)
            if inner.startswith(outer) and len(inner) > len(outer):
                return inner[len(outer) :] or "  "
        if isinstance(node, ArrayNode) and node.items:
            inner = self.base_indent_at(node.items[0].node.start)
            if inner.startswith(outer) and len(inner) > len(outer):
                return inner[len(outer) :] or "  "
        return "  "


def escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def parent_path(pointer: str) -> str:
    tokens = parse_pointer(pointer)
    return "/" + "/".join(escape(token) for token in tokens[:-1]) if len(tokens) > 1 else ""


def quote_key(label: str) -> str:
    return '"' + label.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_fragment(value_text: str) -> Document:
    """Parse exactly one JSON5/template value submitted by a client."""
    if value_text is None:
        raise PathError("value_text is required")
    if not value_text.strip():
        raise PathError("value_text must contain exactly one JSON5 value")
    return Document(value_text, origin="<value_text>")


def reindent(text: str, continuation_indent: str) -> str:
    """Shift continuation lines so a spliced value matches its new location."""
    if "\n" not in text:
        return text
    lines = text.split("\n")
    first_indent = len(lines[0]) - len(lines[0].lstrip(" \t"))
    delta = len(continuation_indent) - first_indent
    out = [lines[0]]
    for line in lines[1:]:
        if delta >= 0:
            out.append(continuation_indent + line)
        else:
            strip = min(-delta, len(line) - len(line.lstrip(" \t")))
            out.append(line[strip:])
    return "\n".join(out)


# --------------------------------------------------------------------------
# edit helpers (module level)
# --------------------------------------------------------------------------


def deindent(text: str, amount: int) -> str:
    """Remove up to `amount` leading whitespace characters from every line."""
    if amount <= 0:
        return text
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = 0
        while stripped < amount and stripped < len(line) and line[stripped] in " \t":
            stripped += 1
        out.append(line[stripped:])
    return "\n".join(out)


def _after_open(parent: ObjectNode) -> int:
    """Position right after '{' plus its same-line comments."""
    offset = parent.start + 1
    for comment in parent.opening_comments:
        offset = max(offset, comment.end)
    return offset


def _before_close(parent: ObjectNode) -> int:
    close = parent.end - 1
    for comment in parent.block_end:
        close = min(close, comment.start)
    return close


def _item_end(item: Item) -> int:
    offset = item.node.end
    for comment in item.trailing:
        offset = max(offset, comment.end)
    return offset


def index_of_member(parent: ObjectNode, token: str) -> int:
    for index, member in enumerate(parent.members):
        if member.label == token:
            return index
    return -1


def block_of(document: "Document", item: Item) -> tuple[str, str]:
    """Split one array item into (value source, trailing comments).

    The item's own comma is excluded, so a rebuilt array can place the
    separator after the value and before any trailing comment.
    """
    start = item.leading[0].start if item.leading else item.node.start
    value = deindent(document.text[start : item.node.end], len(document.base_indent_at(start)))
    comments = "".join(f" {comment.text}" for comment in item.trailing)
    return value, comments


def _with_separator(block: tuple[str, str], needed: bool) -> str:
    """Assemble one item: value, then the separator, then its trailing comments."""
    value, comments = block
    return value + ("," if needed else "") + comments


def _line_start(text: str, offset: int) -> int:
    """Start of the line when only whitespace precedes offset, else offset."""
    line_start = text.rfind("\n", 0, offset) + 1
    return line_start if text[line_start:offset].strip() == "" else offset


def _absorb_previous_separator(text: str, start: int, container_start: int) -> int:
    """Use the comma before a removed last item instead of leaving a gap."""
    position = text.rfind(",", container_start, start)
    if position < 0:
        return start
    return _absorb_previous_space(text, position)


def _tidy_inline(text: str, start: int, end: int) -> tuple[int, int]:
    """Drop the separator space an inline removal leaves behind."""
    start = _absorb_previous_space(text, start)
    if text[end : end + 1] == " " and start > 0 and text[start - 1 : start] in ("[", ","):
        end += 1
    return start, end


def _absorb_previous_space(text: str, start: int) -> int:
    """Remove the separator space left behind by an inline removal."""
    if start <= 0 or text[start - 1] != " ":
        return start
    previous = text[start - 2] if start >= 2 else ""
    return start - 1 if previous in "[," else start


def _extend_line(text: str, offset: int) -> int:
    """Swallow the rest of the line when only whitespace follows offset."""
    newline = text.find("\n", offset)
    if newline >= 0 and text[offset:newline].strip() == "":
        return newline + 1
    return offset


def _has_trailing_comma(text: str, offset: int) -> bool:
    return _after_comma(text, offset) > offset


def _after_comma(text: str, offset: int) -> int:
    probe = offset
    while probe < len(text) and text[probe] in " \t":
        probe += 1
    if probe < len(text) and text[probe] == ",":
        return probe + 1
    return offset


def _member_end(member: Member) -> int:
    offset = member.node.end
    for comment in member.trailing:
        offset = max(offset, comment.end)
    return offset


def _member_start(member: Member) -> int:
    return member.leading[0].start if member.leading else member.key_start


def _inner_indent(document: Document, parent: "ObjectNode | ArrayNode", base_indent: str, unit: str) -> str:
    """Indentation of the first child of a block, derived from the source."""
    if isinstance(parent, ObjectNode) and parent.members:
        indent = document.base_indent_at(parent.members[0].key_start)
    elif isinstance(parent, ArrayNode) and parent.items:
        first = parent.items[0]
        indent = document.base_indent_at(first.leading[0].start if first.leading else first.node.start)
    else:
        indent = ""
    return indent or base_indent + unit


def _member_lines(document: Document, member: Member, comma: str) -> list[str]:
    """Relative lines of a submitted member with its own comments in place."""
    indent = len(document.base_indent_at(member.key_start))
    value = deindent(document.source_of(member.node), indent).split("\n")
    mid = "".join(f"{comment.text} " for comment in member.mid)
    trailing = "".join(f" {comment.text}" for comment in member.trailing)
    value[0] = f"{member.key_raw}: {mid}{value[0]}"
    value[-1] = value[-1] + comma + trailing
    return [comment.text for comment in member.leading] + value


def _submitted_chunk(document: Document, member: Member, comma: str = ",") -> str:
    """Relative source of a submitted member, including its own comments."""
    return "\n".join(_member_lines(document, member, comma))


def _keep_only_absent(comments: list[Comment], submitted: str) -> list[Comment]:
    """Re-attach an original comment unless the submitted text already carries it.

    A comment that the client sent back inside the value keeps its own position;
    adding it a second time would duplicate it (SPEC.md 7.1).
    """
    return [comment for comment in comments if comment.text not in submitted]


def _chunk_with_old_comments(
    document: Document, old_member: Member, new_member: Member, comma: str = ","
) -> str:
    """Relative source of a submitted member carrying the original trivia."""
    submitted = document.source_of(new_member.node)
    value = deindent(submitted, len(document.base_indent_at(new_member.node.start))).split("\n")
    mid = "".join(
        f"{comment.text} " for comment in _keep_only_absent(old_member.mid, submitted)
    )
    trailing = "".join(
        f" {comment.text}" for comment in _keep_only_absent(old_member.trailing, submitted)
    )
    value[0] = f"{new_member.key_raw}: {mid}{value[0]}"
    value[-1] = value[-1] + comma + trailing
    lines = [comment.text for comment in new_member.leading]
    lines.extend(comment.text for comment in _keep_only_absent(old_member.leading, submitted))
    lines.extend(value)
    return "\n".join(lines)


def _build_object_body(
    document: Document,
    old: ObjectNode,
    chunks: list[str],
    multiline: bool,
    base_indent: str,
    unit: str,
) -> str:
    """Assemble the replacement text of an object, keeping its comments."""
    if not multiline:
        body = " ".join(chunk.replace("\n", " ").strip() for chunk in chunks)
        return "{" + body + "}"

    entry_indent = _inner_indent(document, old, base_indent, unit)
    lines = ["{"]
    for chunk in chunks:
        lines.append("\n".join(entry_indent + line for line in chunk.split("\n")))
    for comment in old.block_end:
        lines.append(entry_indent + comment.text)
    lines.append(base_indent + "}")
    return "\n".join(lines)


def parse(text: str, *, origin: str = "<memory>") -> Document:
    return Document(text, origin=origin)
