"""Config object model (SPEC.md 10.2, SPEC_service.md section 15).

A Config bundles data with origin metadata and the operations a host needs to
load, update, save and re-apply configuration. Layer order is host-managed;
aiset supplies creation, merge and metadata, never a fixed layer policy.

Mount grammar (chosen and documented here, as required by SPEC.md 10.2):

    mount      := segment ( "." segment )*
    segment    := name | selector
    name       := plain characters, with a literal dot written as "\\."
    selector   := "[" field "=" value "]"

`a.b` selects object keys; `items.[id=myworker]` selects the array element whose
`id` equals `myworker`. A selector that matches zero elements, or more than one,
is an explicit error: aiset never guesses an ambiguous mount.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .descriptor import compile_descriptor
from .errors import DescriptorError, NotFound
from .jsonsrc import Document, TemplateRef
from .merge import merge
from .service import ChangeEvent, Principal, Service, SetResult, Subscription
from .store import Settings, Store, revision_of_bytes

IDENTITY_FIELDS = ("id", "name", "key")


@dataclass
class Origin:
    """Where a Config came from (SPEC.md 10.2)."""

    file: str
    loaded_at: str
    mount: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "loaded_at": self.loaded_at, "mount": self.mount}


def split_mount(mount: str) -> list[str]:
    """Split a mount string into segments, honouring `\\.` and `[field=value]`."""
    if mount == "":
        return []
    segments: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(mount):
        char = mount[index]
        if char == "\\" and index + 1 < len(mount):
            current.append(mount[index + 1])
            index += 2
            continue
        if char == ".":
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))
    if any(segment == "" for segment in segments):
        raise DescriptorError(f"Empty mount segment in {mount!r}")
    return segments


def resolve_mount(data: Any, mount: str) -> tuple[Any, Any]:
    """Return (container, key) for a mount; ambiguous selectors are errors."""
    segments = split_mount(mount)
    if not segments:
        raise DescriptorError("Mount must not be empty")
    container = data
    for position, segment in enumerate(segments[:-1]):
        container = _step(container, segment, mount, position)
    last = segments[-1]
    if last.startswith("[") and last.endswith("]"):
        field, _, expected = last[1:-1].partition("=")
        if not field or not expected:
            raise DescriptorError(f"Malformed identity selector {last!r} in {mount!r}")
        index = _identity_index(container, field, expected, mount)
        return container, index
    return container, last


def _step(container: Any, segment: str, mount: str, position: int) -> Any:
    if segment.startswith("[") and segment.endswith("]"):
        field, _, expected = segment[1:-1].partition("=")
        container = _identity_index(container, field, expected, mount)
    elif isinstance(container, list):
        raise DescriptorError(f"Segment {segment!r} at position {position} requires a selector in {mount!r}")
    elif isinstance(container, dict):
        if segment not in container:
            raise DescriptorError(f"Missing mount segment {segment!r} in {mount!r}")
        container = container[segment]
    else:
        raise DescriptorError(f"Mount {mount!r} does not address a container")
    return container


def _identity_index(container: Any, field: str, expected: str, mount: str) -> int:
    if not isinstance(container, list):
        raise DescriptorError(f"Selector [{field}={expected}] in {mount!r} requires an array")
    matches = [
        index
        for index, item in enumerate(container)
        if isinstance(item, dict) and str(item.get(field)) == expected
    ]
    if not matches:
        raise DescriptorError(f"Selector [{field}={expected}] matches no element in {mount!r}")
    if len(matches) > 1:
        raise DescriptorError(
            f"Selector [{field}={expected}] is ambiguous in {mount!r}: {len(matches)} matches"
        )
    return matches[0]


def place_mount(data: dict[str, Any], mount: str | None, value: Any) -> dict[str, Any]:
    """Return a copy of `data` with `value` placed at `mount`."""
    result = copy.deepcopy(data)
    if not mount:
        if not isinstance(value, dict):
            raise DescriptorError("The root mount requires an object value")
        return value
    container, key = resolve_mount(result, mount)
    if isinstance(container, list):
        container[int(key) if isinstance(key, int) else key] = value
    else:
        container[str(key)] = value
    return result


class Config:
    """Host-facing configuration object."""

    def __init__(
        self,
        data: dict[str, Any],
        *,
        origin: Origin,
        store: Store,
        service: Service | None = None,
        descriptor_revision: str = "",
    ) -> None:
        self.data = data
        self.origin = origin
        self.store = store
        self.service = service
        self.descriptor_revision = descriptor_revision
        self.revision = revision_of_bytes(_bytes(data))
        self.metadata: dict[str, Any] = {"origin": origin.to_dict(), "subscriptions": []}

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        mount: str | None = None,
        typedef_sources: Sequence[str] = (),
        descriptor_path: str | Path | None = None,
        settings: Settings | None = None,
        principal: Principal | None = None,
    ) -> "Config":
        """Load a JSON5/template file into a Config, optionally mounted in a base."""
        settings = settings or Settings()
        store = Store("config", path, settings)
        data, _, text = store.read()
        parsed = Document(text, origin=Path(path).name)
        value = parsed.stored_value(parsed.root)
        if not isinstance(value, dict):
            raise DescriptorError("A Config must be an object document")
        if descriptor_path:
            compile_descriptor(
                Path(descriptor_path).read_text(encoding="utf-8"),
                typedef_sources=typedef_sources,
                strict=True,
            )
        origin = Origin(
            file=str(path),
            loaded_at=datetime.now(timezone.utc).isoformat(),
            mount=mount,
        )
        config = cls(value, origin=origin, store=store)
        if mount:
            config.data = place_mount(value, mount, value)
        return config

    def update(self, other: "Config | dict[str, Any]") -> "Config":
        """Merge another Config or mapping onto this one; the base is unchanged."""
        update = other.data if isinstance(other, Config) else other
        merged = merge(self.data, update)
        origin = Origin(
            file=f"{self.origin.file}+update",
            loaded_at=datetime.now(timezone.utc).isoformat(),
            mount=self.origin.mount,
        )
        return Config(merged, origin=origin, store=self.store, descriptor_revision=self.descriptor_revision)

    def reload(self) -> "Config":
        data, _, text = self.store.read()
        parsed = Document(text, origin=self.store.path.name)
        self.data = parsed.stored_value(parsed.root)
        self.revision = revision_of_bytes(data)
        return self

    def save(
        self,
        *,
        expected_revision: str | None = None,
        expected_descriptor_revision: str | None = None,
        principal: Principal | None = None,
        pointer: str = "",
        value_text: str | None = None,
    ) -> SetResult:
        """Persist through the service pipeline; without a service this is a raw write."""
        if self.service is None:
            raise NotFound("This Config is not bound to a service")
        return self.service.set(
            self.store.document_id,
            pointer,
            value_text if value_text is not None else _dump(self.data),
            expected_revision=expected_revision,
            expected_descriptor_revision=expected_descriptor_revision,
            principal=principal or Principal.demo(),
        )

    def subscribe(
        self, paths: Sequence[str], callback: Callable[[ChangeEvent], Any], *, principal: Principal
    ) -> Subscription:
        if self.service is None:
            raise NotFound("This Config is not bound to a service")
        return self.service.subscribe(self.store.document_id, paths, callback, principal=principal)

    def rollback(self, reason: str, *, principal: Principal) -> SetResult:
        if self.service is None:
            raise NotFound("This Config is not bound to a service")
        return self.service.rollback(self.store.document_id, reason, principal=principal)

    def on_probe_changes(self, callback: Callable[..., Any]) -> None:
        if self.service is None:
            raise NotFound("This Config is not bound to a service")
        self.service.on_probe_changes(callback)

    def on_after_save(self, callback: Callable[..., Any]) -> None:
        if self.service is None:
            raise NotFound("This Config is not bound to a service")
        self.service.on_after_save(callback)

    def path(self, mount: str | None = None) -> Any:
        """Read a mounted value using the documented mount grammar."""
        if not mount:
            return self.data
        container, key = resolve_mount(self.data, mount)
        return container[key]


def _dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, default=_plain)


def _bytes(value: Any) -> bytes:
    import json

    return json.dumps(value, ensure_ascii=False, default=_plain).encode("utf-8")


def _plain(value: Any) -> Any:
    """Placeholder references serialize to their source text, never to a secret."""
    if isinstance(value, TemplateRef):
        return value.source_text()
    return str(value)