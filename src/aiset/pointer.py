"""JSON Pointer parsing and traversal (SPEC.md sections 5.1 and 5.3.1)."""

from __future__ import annotations

from typing import Any, Sequence

from .errors import PathError

APPEND_MARKER = "-"


def escape_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def unescape_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def parse_pointer(pointer: str, *, allow_append: bool = False) -> list[str]:
    """Split a JSON Pointer into unescaped tokens; "" is the root.

    The array append token "-" is rejected by default; structural add operations
    pass `allow_append=True` because they address a new last item.
    """
    if not isinstance(pointer, str):
        raise PathError("Path must be a string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PathError(f"Path must be empty or start with '/': {pointer!r}")
    tokens: list[str] = []
    for raw in pointer.split("/")[1:]:
        if raw == APPEND_MARKER and not allow_append:
            raise PathError("Array append marker '-' is not supported for this operation")
        index = 0
        out: list[str] = []
        while index < len(raw):
            char = raw[index]
            if char == "~":
                nxt = raw[index + 1] if index + 1 < len(raw) else ""
                if nxt == "0":
                    out.append("~")
                elif nxt == "1":
                    out.append("/")
                else:
                    raise PathError(f"Malformed escape in path segment: {raw!r}")
                index += 2
                continue
            out.append(char)
            index += 1
        tokens.append("".join(out))
    return tokens


def format_pointer(tokens: Sequence[str]) -> str:
    return "".join("/" + escape_token(token) for token in tokens)


def child_pointer(pointer: str, token: str) -> str:
    return pointer + "/" + escape_token(token)


def parent_pointer(pointer: str) -> str:
    tokens = parse_pointer(pointer)
    if not tokens:
        raise PathError("The root pointer has no parent")
    return format_pointer(tokens[:-1])


def is_index(token: str) -> bool:
    return token.isdigit() and (token == "0" or not token.startswith("0"))


def resolve_node(container: Any, token: str, *, where: str = "") -> Any:
    """Return container[token]; numbers address arrays only."""
    label = f" at {where}" if where else ""
    if isinstance(container, dict):
        if token not in container:
            raise PathError(f"Missing object key {token!r}{label}")
        return container[token]
    if isinstance(container, list):
        if not is_index(token):
            raise PathError(f"Array index expected, got {token!r}{label}")
        index = int(token)
        if index >= len(container):
            raise PathError(f"Array index out of range: {token!r}{label}")
        return container[index]
    raise PathError(f"Path segment {token!r} does not address a container{label}")


def resolve(root: Any, pointer: str) -> Any:
    """Resolve a JSON Pointer against plain Python data."""
    node = root
    for token in parse_pointer(pointer):
        node = resolve_node(node, token, where=pointer)
    return node


def contains(root: Any, pointer: str) -> bool:
    """True when the pointer addresses an existing value (no exception)."""
    try:
        resolve(root, pointer)
    except PathError:
        return False
    return True


def iter_tokens(pointer: str) -> list[str]:
    return parse_pointer(pointer)