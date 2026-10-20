"""The shared service: one read/validate/set implementation for every transport.

Python, HTTP and MCP all call this module, so they return the same values,
issue paths, conflict codes and stored/application status (SPEC_service.md 18).
The server is always authoritative: every candidate is fully revalidated here.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import logging
import re
import threading
import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .descriptor import (
    CompiledDescriptor,
    DescriptorFragment,
    Node,
    compile_descriptor,
    node_at,
    validate_descriptor,
)
from .errors import (
    AisetError,
    BadRequest,
    CallbackTimeout,
    CommentPreservationConflict,
    Forbidden,
    NoValidBackup,
    NotFound,
    PathError,
    RevisionConflict,
    RevisionRequired,
    SecretAccessDenied,
    StorageError,
    Unauthorized,
    UnsupportedCapability,
    ValidationError,
)
from .jsonsrc import Document, escape, parse_fragment
from .pointer import parse_pointer
from .resolver import MISSING, Resolver, build_effective, effective_at, is_missing
from .store import Settings, Store, decode, encode, revision_of_bytes
from .validator import ValueIssue, check_limits, validate_document

LOGGER = logging.getLogger("aiset")

PERMISSIONS = (
    "settings_read_source",
    "settings_read_effective",
    "settings_validate",
    "settings_write",
    "settings_read_secret",
    "settings_edit_secret",
    "settings_load_lkg",
    "settings_descriptor_raw",
)

APPLY_ORDER = {"live": 0, "reload": 1, "restart": 2}
# A presence query is a diagnostic, not a bulk export of the environment.
MAX_ENV_NAMES = 64
BOM = "﻿"


@dataclass(frozen=True)
class Principal:
    """An authenticated actor, or the explicit local-demo principal."""

    id: str
    permissions: frozenset[str] = frozenset(PERMISSIONS)

    @classmethod
    def demo(cls) -> "Principal":
        return cls(id="local-demo", permissions=frozenset(PERMISSIONS))

    def has(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass
class DocumentRegistration:
    """One allowlisted configuration document and its descriptor."""

    document_id: str
    store: Store
    descriptor: CompiledDescriptor
    resolver: Resolver = dataclasses.field(default_factory=Resolver)


@dataclass
class DocumentState:
    """In-memory snapshot of one registered document."""

    registration: DocumentRegistration
    revision: str
    text: str
    document: Document
    stored: Any
    effective: Any
    provenance: dict[str, Any]
    loaded_from: str = "file"
    invalid_on_disk: bool = False
    invalid_reason: str = ""
    active_revision: str | None = None
    issues: list[ValueIssue] = dataclasses.field(default_factory=list)


@dataclass
class ChangeEvent:
    """Immutable notification payload for subscriptions and callbacks."""

    document: str
    changed_paths: list[str]
    previous_revision: str
    revision: str
    application_state: str
    active_revision: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "changed_paths": list(self.changed_paths),
            "previous_revision": self.previous_revision,
            "revision": self.revision,
            "application_state": self.application_state,
            "active_revision": self.active_revision,
        }


@dataclass
class Subscription:
    """Handle returned by Service.subscribe (SPEC_service.md section 13)."""

    document_id: str
    paths: list[str]
    callback: Callable[[ChangeEvent], Any]
    service: "Service"
    active: bool = True

    def unsubscribe(self) -> None:
        self.active = False
        self.service._subscriptions = [item for item in self.service._subscriptions if item is not self]

    def matches(self, changed: Iterable[str]) -> list[str]:
        matched: list[str] = []
        for path in changed:
            for watched in self.paths:
                if path == watched or path.startswith(watched + "/") or watched.startswith(path + "/"):
                    matched.append(path)
                    break
        return matched


@dataclass
class LoadResult:
    document: str
    loaded: str
    revision: str
    descriptor_revision: str
    effective: Any = None
    provenance: dict[str, Any] = dataclasses.field(default_factory=dict)
    invalid_on_disk: bool = False
    reason: str = ""
    issues: list[ValueIssue] = dataclasses.field(default_factory=list)

    def to_dict(self, *, include_effective: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": True,
            "document": self.document,
            "loaded": self.loaded,
            "revision": self.revision,
            "descriptor_revision": self.descriptor_revision,
            "origin": {"kind": self.loaded, "document": self.document},
            "invalid_on_disk": self.invalid_on_disk,
        }
        if self.issues:
            out["issues"] = [issue.to_dict() for issue in self.issues]
        if include_effective:
            out["effective"] = self.effective
            out["provenance"] = self.provenance
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass
class GetResult:
    document: str
    path: str
    view: str
    exists: bool
    revision: str
    descriptor_revision: str
    etag: str
    value_text: str | None = None
    effective: Any = None
    format: str = "json5"
    default_applied: bool = False
    provenance: dict[str, Any] | None = None
    field: dict[str, Any] | None = None
    origin: dict[str, Any] = dataclasses.field(default_factory=lambda: {"kind": "file"})
    invalid_on_disk: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": True,
            "document": self.document,
            "path": self.path,
            "view": self.view,
            "exists": self.exists,
            "revision": self.revision,
            "descriptor_revision": self.descriptor_revision,
            "etag": self.etag,
            "origin": self.origin,
            "invalid_on_disk": self.invalid_on_disk,
        }
        if self.view == "source":
            out["format"] = self.format
        if self.field is not None:
            out["field"] = self.field
        if self.default_applied:
            out["default_applied"] = True
        if self.view == "effective" and self.provenance is not None:
            out["provenance"] = self.provenance
        if self.value_text is not None:
            out["value_text"] = self.value_text
        if self.view == "effective" and self.exists:
            out["effective"] = self.effective
        return out


@dataclass
class ValidateResult:
    document: str
    valid: bool
    preservable: bool
    issues: list[ValueIssue]
    revision: str
    descriptor_revision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "document": self.document,
            "valid": self.valid,
            "preservable": self.preservable,
            "issues": [issue.to_dict() for issue in self.issues],
            "revision": self.revision,
            "descriptor_revision": self.descriptor_revision,
        }


@dataclass
class SetResult:
    document: str
    stored: bool
    revision: str
    descriptor_revision: str
    application_state: str
    active_revision: str | None
    changed_paths: list[str] = dataclasses.field(default_factory=list)
    hook_results: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    issues: list[ValueIssue] = dataclasses.field(default_factory=list)
    detail: str = ""
    commit_report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": True,
            "document": self.document,
            "stored": self.stored,
            "revision": self.revision,
            "descriptor_revision": self.descriptor_revision,
            "application": {
                "state": self.application_state,
                "active_revision": self.active_revision,
            },
            "hook_results": self.hook_results,
        }
        if self.changed_paths:
            out["changed_paths"] = self.changed_paths
        if self.issues:
            out["issues"] = [issue.to_dict() for issue in self.issues]
        if self.detail:
            out["detail"] = self.detail
        if self.commit_report is not None:
            out["commit_report"] = self.commit_report
        return out


@dataclass
class DescriptorResult:
    document: str | None
    descriptor: dict[str, Any]
    revision: str
    valid: bool = True
    issues: list[Any] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "valid": self.valid}
        if self.document:
            out["document"] = self.document
        out["descriptor"] = self.descriptor
        out["revision"] = self.revision
        if self.issues:
            out["issues"] = [
                issue.to_dict() if hasattr(issue, "to_dict") else issue for issue in self.issues
            ]
        return out


class Service:
    """Settings service shared by every transport."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        audit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.documents: dict[str, DocumentRegistration] = {}
        self.states: dict[str, DocumentState] = {}
        self._subscriptions: list[Subscription] = []
        self._probe_changes: list[Callable[..., Any]] = []
        self._after_save: list[Callable[..., Any]] = []
        self._application: list[Callable[..., Any]] = []
        self._audit_sink = audit
        self._lock = threading.RLock()

    # -- registration ----------------------------------------------------
    def register(
        self,
        document_id: str,
        path: str | Path,
        descriptor_source: str,
        *,
        resolver: Resolver | None = None,
        typedef_sources: Sequence[str] = (),
        fragments: Sequence[DescriptorFragment] = (),
    ) -> DocumentRegistration:
        """Register one allowlisted document; clients never select a path.

        Compilation is strict about recognized definitions and lenient about
        unknown project metadata, exactly as at runtime (SPEC.md 4.5). Use
        validate_descriptor(mode="strict") for typo-free CI checks.
        """
        descriptor = compile_descriptor(
            descriptor_source,
            typedef_sources=typedef_sources,
            fragments=fragments,
            strict=False,
        )
        store = Store(document_id, path, self.settings)
        store.check_symlink()
        registration = DocumentRegistration(
            document_id=document_id,
            store=store,
            descriptor=descriptor,
            resolver=resolver or Resolver(),
        )
        self.documents[document_id] = registration
        self.states.pop(document_id, None)
        return registration

    def _registration(self, document_id: str) -> DocumentRegistration:
        registration = self.documents.get(document_id)
        if registration is None:
            raise NotFound(f"Unknown document {document_id!r}")
        return registration

    # -- callbacks -------------------------------------------------------
    # Every callback runs after the commit, outside the lock, through `_call`,
    # which supports sync and async callables and bounds them with
    # `callback_timeout_seconds`. A callback that raises is logged as
    # `callback_failed` and never undoes a committed write.
    #
    # `on_probe_changes(callback)` -> callback(previous_stored, new_stored,
    #   changed_paths). Returning `Rejection` vetoes the write before it is stored.
    # `on_after_save(callback)`    -> callback(previous_stored, new_stored,
    #   event.to_dict()), where `event` is a ChangeEvent: `document`,
    #   `changed_paths`, `previous_revision`, `revision`, `application_state`,
    #   `active_revision`. The host uses it to refresh any cache it derived from
    #   the resolved configuration.
    # `on_application(callback)`  -> callback(previous_effective,
    #   new_effective, changed_paths); it is called only for `live` and `reload`
    #   changes and only when the descriptor demands one.
    # `subscribe(document_id, paths, callback)` -> callback(ChangeEvent).

    def on_probe_changes(self, callback: Callable[..., Any]) -> None:
        """Host veto hook, called before a candidate is stored."""
        _require_callback_arity(callback, ("before", "after", "changed_paths"))
        self._probe_changes.append(callback)

    def on_after_save(self, callback: Callable[..., Any]) -> None:
        """Post-commit hook: (previous_stored, new_stored, event)."""
        _require_callback_arity(callback, ("previous", "current", "event"))
        self._after_save.append(callback)

    def on_application(self, callback: Callable[..., Any]) -> None:
        """Apply hook for `live` and `reload` changes: (before, after, paths)."""
        _require_callback_arity(callback, ("previous", "current", "changed_paths"))
        self._application.append(callback)

    def subscribe(
        self,
        document_id: str,
        paths: Sequence[str],
        callback: Callable[[ChangeEvent], Any],
        *,
        principal: Principal | None = None,
    ) -> Subscription:
        self._registration(document_id)
        if principal is not None:
            self._require(principal, "settings_read_effective")
        if not paths:
            raise BadRequest("A subscription requires at least one JSON Pointer")
        subscription = Subscription(document_id, list(paths), callback, self)
        self._subscriptions.append(subscription)
        return subscription

    # -- operations ------------------------------------------------------
    def load(self, document_id: str, *, principal: Principal) -> LoadResult:
        self._require(principal, "settings_read_effective")
        return self._load_state(document_id, force_lkg=False)

    def doctor(
        self,
        document_id: str,
        *,
        principal: Principal,
        fix: bool | Iterable[str] = False,
        expected_revision: str | None = None,
        expected_descriptor_revision: str | None = None,
    ) -> Any:
        """Diagnose one document and optionally repair the fixable part.

        See `aiset/doctor.py`: the report lists every issue with the one fix
        class that could handle it, and `fix` applies the requested classes.
        The file is written only when the repairs make it fully valid.
        """
        from .doctor import doctor as _doctor

        return _doctor(
            self,
            document_id,
            principal=principal,
            fix=fix,
            expected_revision=expected_revision,
            expected_descriptor_revision=expected_descriptor_revision,
        )

    def load_lkg(self, document_id: str, *, principal: Principal) -> LoadResult:
        self._require(principal, "settings_load_lkg")
        result = self._load_state(document_id, force_lkg=True)
        self._audit("load_lkg", {"document": document_id, "revision": result.revision})
        return result

    def reread(self, document_id: str, *, principal: Principal | None = None) -> LoadResult:
        """Explicit re-read; adopts valid external edits (SPEC.md 10.4)."""
        return self._load_state(document_id, force_lkg=False)

    def get(
        self,
        document_id: str,
        path: str,
        *,
        view: str = "source",
        principal: Principal,
    ) -> GetResult:
        if view not in ("source", "effective"):
            raise BadRequest("view must be 'source' or 'effective'")
        self._require(
            principal, "settings_read_source" if view == "source" else "settings_read_effective"
        )
        state = self._state(document_id)
        node = self._node_for(state.registration, path, required=True)
        common: dict[str, Any] = {
            "document": document_id,
            "path": path,
            "view": view,
            "revision": state.revision,
            "descriptor_revision": state.registration.descriptor.revision,
            "etag": self._etag(state),
            "invalid_on_disk": state.invalid_on_disk,
            "field": node.describe(),
            "origin": {"kind": "file", "document": document_id},
        }
        if view == "source":
            cst_node = state.document.find(path)
            if cst_node is None:
                return GetResult(exists=False, **common)
            self._require_secret_subtree(node, principal, path)
            format_ = state.document.format_of(cst_node)
            if not node.env_allowed:
                format_ = "json5"
            return GetResult(
                exists=True,
                value_text=state.document.value_text(cst_node),
                format=format_,
                **common,
            )

        stored = _lookup_stored(state.stored, path)
        provenance: dict[str, Any] = {}
        if stored is MISSING or is_missing(stored):
            if node.has_default:
                return GetResult(
                    exists=False,
                    default_applied=True,
                    value_text=_dump_value(node.default),
                    effective=copy.deepcopy(node.default),
                    provenance={path: {"kind": "default"}},
                    **common,
                )
            return GetResult(exists=False, provenance=provenance, **common)
        effective, issues = effective_at(
            stored, node, state.registration.resolver, path, provenance=provenance
        )
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ValidationError(
                "Effective configuration is invalid", issues=[issue.to_dict() for issue in errors]
            )
        self._require_secret_subtree(node, principal, path)
        return GetResult(
            exists=True,
            effective=copy.deepcopy(effective),
            value_text=_dump_value(effective),
            provenance=provenance,
            **common,
        )

    def validate(
        self,
        document_id: str,
        path: str,
        value_text: str,
        *,
        expected_revision: str | None,
        expected_descriptor_revision: str | None,
        principal: Principal,
    ) -> ValidateResult:
        self._require(principal, "settings_validate")
        state = self._state(document_id)
        self._check_revisions(state, expected_revision, expected_descriptor_revision)
        candidate_text, issues = self._prepare(state, path, value_text, principal)
        preservable = not any(issue.rule == "comment_preservation" for issue in issues)
        return ValidateResult(
            document=document_id,
            valid=not any(issue.severity == "error" for issue in issues),
            preservable=preservable,
            issues=issues,
            revision=state.revision,
            descriptor_revision=state.registration.descriptor.revision,
        )

    def validate_document(
        self, document_id: str, source: str, *, principal: Principal
    ) -> ValidateResult:
        """Validate a candidate document source against its descriptor.

        The candidate is a whole document (for example a file a host wants to
        ship). Nothing is written, no state changes, and the LKG path is not
        consulted: the caller gets the issues the file would produce.
        """
        self._require(principal, "settings_validate")
        registration = self._registration(document_id)
        try:
            _, revision, _ = registration.store.read()
        except AisetError:
            revision = ""
        try:
            candidate = Document(source, origin=registration.store.path.name)
            stored = candidate.stored_value(candidate.root)
        except AisetError as exc:
            return ValidateResult(
                document=document_id,
                valid=False,
                preservable=True,
                issues=[ValueIssue("", "parse", str(exc))],
                revision=revision,
                descriptor_revision=registration.descriptor.revision,
            )
        issues = self._validate_stored(registration, stored, candidate)
        return ValidateResult(
            document=document_id,
            valid=not any(issue.severity == "error" for issue in issues),
            preservable=True,
            issues=issues,
            revision=revision,
            descriptor_revision=registration.descriptor.revision,
        )

    def set(
        self,
        document_id: str,
        path: str,
        value_text: str,
        *,
        expected_revision: str | None,
        expected_descriptor_revision: str | None,
        principal: Principal,
    ) -> SetResult:
        self._require(principal, "settings_write")
        state = self._state(document_id)
        self._check_revisions(state, expected_revision, expected_descriptor_revision)
        candidate_text, issues = self._prepare(state, path, value_text, principal)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ValidationError(
                "Candidate configuration is invalid", issues=[issue.to_dict() for issue in errors]
            )

        previous_state = state
        changed_paths = self._changed_paths(state, candidate_text, path)
        self._probe(previous_state, candidate_text, changed_paths)

        with state.registration.store.lock():
            data, current_revision, current_text = state.registration.store.read()
            if current_revision != state.revision:
                raise RevisionConflict(
                    "The document changed on disk; re-read before saving",
                    detail=f"disk={current_revision} client={state.revision}",
                )
            payload = encode(candidate_text, current_text.startswith(BOM))
            candidate = Document(candidate_text, origin=state.registration.store.path.name)
            self._revalidate_locked(state, candidate, principal)
            report = state.registration.store.write_locked(payload, audit=self._audit)
            if not report.committed:
                raise StorageError("The document could not be persisted", detail=report.detail)

        new_state = self._adopt(state, payload)
        application_state = self._apply_change(previous_state, new_state, changed_paths)
        self._notify(previous_state, new_state, changed_paths, application_state)
        self._audit(
            "set",
            {
                "document": document_id,
                "paths": changed_paths,
                "revision": new_state.revision,
                "application": application_state,
            },
        )
        return SetResult(
            document=document_id,
            stored=True,
            revision=new_state.revision,
            descriptor_revision=state.registration.descriptor.revision,
            application_state=application_state,
            active_revision=new_state.active_revision,
            changed_paths=changed_paths,
            commit_report=report.to_dict(),
        )

    def descriptor(
        self, document_id: str, *, view: str = "authorized", principal: Principal
    ) -> DescriptorResult:
        if view not in ("authorized", "raw"):
            raise BadRequest("view must be 'authorized' or 'raw'")
        if view == "raw":
            self._require(principal, "settings_descriptor_raw")
        descriptor = self._registration(document_id).descriptor
        return DescriptorResult(
            document=document_id,
            descriptor=descriptor.raw if view == "raw" else descriptor.to_authorized_dict(),
            revision=descriptor.revision,
        )

    def validate_descriptor(
        self, descriptor_source: str, *, mode: str = "default", principal: Principal | None = None
    ) -> DescriptorResult:
        """Development operation (SPEC.md 4.5); needs no document or config file."""
        if mode not in ("default", "strict"):
            raise BadRequest("mode must be 'default' or 'strict'")
        diagnostic = validate_descriptor(descriptor_source, mode=mode)
        return DescriptorResult(
            document=None,
            descriptor={"valid": diagnostic.valid, "issues": diagnostic.to_dict()["issues"]},
            revision=revision_of_bytes(descriptor_source.encode("utf-8")),
            valid=diagnostic.valid,
            issues=diagnostic.issues,
        )

    def rollback(self, document_id: str, reason: str, *, principal: Principal) -> SetResult:
        """Host-initiated rollback: shift the backup chain down one level."""
        self._require(principal, "settings_write")
        state = self._state(document_id)
        data = state.registration.store.restore_backup(1)
        new_state = self._adopt(state, data)
        self._audit("rollback", {"document": document_id, "reason": reason})
        return SetResult(
            document=document_id,
            stored=True,
            revision=new_state.revision,
            descriptor_revision=state.registration.descriptor.revision,
            application_state="restart_required",
            active_revision=state.active_revision,
        )

    def list_documents(self, *, principal: Principal) -> list[str]:
        """Registered document ids; the same read permission a read requires."""
        self._require(principal, "settings_read_source")
        return sorted(self.documents)

    def tree(
        self, document_id: str, path: str = "", *, view: str = "source", principal: Principal
    ) -> dict[str, Any]:
        """One consistent, authorized snapshot for a generated editor."""
        from .tree import build_tree

        if view not in ("source", "effective"):
            raise BadRequest("view must be 'source' or 'effective'")
        self._require(
            principal, "settings_read_source" if view == "source" else "settings_read_effective"
        )
        state = self._state(document_id)
        if path:
            self._node_for(state.registration, path, required=True)
        return build_tree(
            state,
            path,
            view=view,
            can_read_secret=principal.has("settings_read_secret"),
            limits=self.settings.limits,
        )

    def env_status(self, document_id: str, names: Sequence[str], *, principal: Principal) -> dict[str, bool]:
        """Which environment variables are set, without ever exposing a value.

        The editor shows this next to a ${VAR} control so the user knows whether
        the file or the inline fallback decides the effective value.
        """
        self._require(principal, "settings_read_source")
        state = self._state(document_id)
        self._node_for(state.registration, "", required=True)
        cleaned = [str(name) for name in names if isinstance(name, str)][:MAX_ENV_NAMES]
        if not cleaned:
            raise BadRequest("At least one variable name is required")
        return state.registration.resolver.presence(cleaned)

    def apply_operations(
        self,
        document_id: str,
        operations: Sequence[dict[str, Any]],
        *,
        expected_revision: str | None,
        expected_descriptor_revision: str | None,
        principal: Principal,
        dry_run: bool = False,
    ) -> OperationsResult:  # noqa: D401
        """Apply one batch of structural operations atomically (SPEC_service.md 21).

        Validation is all-or-nothing: if one operation fails, nothing is written.
        """
        permission = "settings_validate" if dry_run else "settings_write"
        self._require(principal, permission)
        state = self._state(document_id)
        self._check_revisions(state, expected_revision, expected_descriptor_revision)
        operations = [dict(item) for item in operations]
        if not operations:
            raise BadRequest("At least one operation is required")
        candidate_text, issues = self._apply_to_candidate(state, operations, principal)
        errors = [issue for issue in issues if issue.severity == "error"]
        result = OperationsResult(
            document=document_id,
            valid=not errors,
            operations=operations,
            issues=issues,
            revision=state.revision,
            descriptor_revision=state.registration.descriptor.revision,
            dry_run=dry_run,
        )
        if dry_run:
            result.issues = issues
            return result
        if errors:
            raise ValidationError(
                "Staged operations are invalid",
                issues=[issue.to_dict() for issue in errors],
            )

        previous_state = state
        changed_paths = self._batch_changed_paths(state, candidate_text, operations)
        self._probe(previous_state, candidate_text, changed_paths)

        with state.registration.store.lock():
            data, current_revision, current_text = state.registration.store.read()
            if current_revision != state.revision:
                raise RevisionConflict(
                    "The document changed on disk; re-read before saving",
                    detail=f"disk={current_revision} client={state.revision}",
                )
            payload = encode(candidate_text, current_text.startswith(BOM))
            candidate = Document(candidate_text, origin=state.registration.store.path.name)
            self._revalidate_locked(state, candidate, principal)
            report = state.registration.store.write_locked(payload, audit=self._audit)
            if not report.committed:
                raise StorageError("The document could not be persisted", detail=report.detail)

        new_state = self._adopt(state, payload)
        application_state = self._apply_change(previous_state, new_state, changed_paths)
        self._notify(previous_state, new_state, changed_paths, application_state)
        self._audit(
            "operations",
            {
                "document": document_id,
                "operations": [item.get("op") for item in operations],
                "revision": new_state.revision,
                "application": application_state,
            },
        )
        result.stored = True
        result.application_state = application_state
        result.active_revision = new_state.active_revision
        result.changed_paths = changed_paths
        result.revision = new_state.revision
        result.commit_report = report.to_dict()
        return result

    def _apply_to_candidate(
        self, state: DocumentState, operations: Sequence[dict[str, Any]], principal: Principal
    ) -> tuple[str, list[ValueIssue]]:
        """Run every operation against one in-memory candidate document."""
        registration = state.registration
        issues: list[ValueIssue] = []
        text = state.text
        for position, operation in enumerate(operations):
            op = str(operation.get("op") or "")
            target = str(operation.get("path") or "")
            try:
                if op == "set":
                    value = operation.get("value_text")
                    self._check_operation(state, text, target, "set", value, principal)
                    text = Document(text, origin=registration.store.path.name).apply_set(target, value)
                elif op == "add":
                    value = operation.get("value_text")
                    self._check_operation(state, text, target, "add", value, principal)
                    text = Document(text, origin=registration.store.path.name).apply_add(target, value)
                elif op == "remove":
                    self._check_operation(state, text, target, "remove", None, principal)
                    text = Document(text, origin=registration.store.path.name).apply_remove(target)
                elif op == "drop":
                    # The doctor's operation: remove a key the descriptor does not
                    # declare. `remove` cannot do this because it resolves the node
                    # first and answers NotFound for exactly the keys we want gone.
                    self._check_operation(state, text, target, "drop", None, principal)
                    text = Document(text, origin=registration.store.path.name).apply_remove(target)
                elif op == "move":
                    source = str(operation.get("from") or "")
                    self._check_operation(state, text, source, "move", None, principal)
                    self._check_operation(state, text, target, "move_index", None, principal)
                    text = Document(text, origin=registration.store.path.name).apply_move(source, target)
                elif op == "rename":
                    new_key = operation.get("to")
                    self._check_operation(state, text, target, "rename", new_key, principal)
                    text = Document(text, origin=registration.store.path.name).apply_rename(
                        target, "" if new_key is None else str(new_key)
                    )
                else:
                    raise BadRequest(f"Unknown operation {op!r}")
            except (Forbidden, SecretAccessDenied, Unauthorized):
                raise
            except AisetError as exc:
                issues.append(
                    ValueIssue(
                        target or str(operation.get("from") or ""),
                        "operation",
                        f"Operation {position + 1} ({op}) failed: {exc.message}",
                    )
                )
                return state.text, issues
        try:
            candidate = Document(text, origin=registration.store.path.name)
            stored = candidate.stored_value(candidate.root)
        except AisetError as exc:
            return state.text, [ValueIssue("", "parse", str(exc))]
        limit_issues = check_limits(stored, self.settings.limits)
        if limit_issues:
            return text, limit_issues
        issues.extend(self._validate_stored(registration, stored, candidate))
        return text, issues

    def _check_operation(
        self,
        state: DocumentState,
        text: str,
        pointer: str,
        op: str,
        value_text: Any,
        principal: Principal,
    ) -> None:
        """Authorize one operation path against the descriptor and permissions."""
        document = Document(text, origin=state.registration.store.path.name)
        if op == "add" and pointer.endswith("/-"):
            pointer = pointer[:-2]
        elif pointer.endswith("/-"):
            raise BadRequest("The append token is only valid for an add operation")
        parent_pointer, token = "", pointer
        if pointer:
            parent_pointer, _, token = pointer.rpartition("/")
            parent_pointer = parent_pointer or ""
        parent_node = self._node_for(state.registration, parent_pointer, required=False) if parent_pointer else state.registration.descriptor.root
        if parent_node is None:
            raise NotFound(f"Path {pointer!r} is not declared by the descriptor")
        if op == "add":
            if parent_node.type == "array":
                return
            if parent_node.type != "object":
                raise BadRequest(f"Cannot add to {parent_node.type} at {pointer!r}")
            existing = parent_node.children.get(token) if parent_node.children else None
            if existing is None and parent_node.additional_children is None:
                raise BadRequest(f"Key {token!r} is not permitted at {parent_pointer!r}")
            if parent_node.key_enum and token not in parent_node.key_enum:
                raise BadRequest(f"Key {token!r} is not in key_enum")
            if parent_node.key_pattern and not re.match(parent_node.key_pattern, token):
                raise BadRequest(f"Key {token!r} does not match key_pattern")
            return
        if op == "rename":
            if parent_node.type != "object":
                raise BadRequest("Only object keys can be renamed")
            old_node = self._node_for(state.registration, pointer, required=False)
            if old_node is None:
                raise NotFound(f"Path {pointer!r} is not declared by the descriptor")
            if old_node.required:
                raise Forbidden(f"Path {pointer!r} is required and cannot be renamed")
            if old_node.read_only:
                raise Forbidden(f"Path {pointer!r} is read-only")
            if old_node.const is not None:
                raise Forbidden(f"Path {pointer!r} has a fixed value")
            if parent_node.children and token in parent_node.children and parent_node.additional_children is None:
                raise Forbidden(f"Path {pointer!r} is a fixed declared child")
            if old_node.secret and not principal.has("settings_edit_secret"):
                raise SecretAccessDenied(f"Path {pointer!r} is a secret subtree")
            new_key = "" if value_text is None else str(value_text)
            if not new_key:
                raise BadRequest("rename requires a non-empty 'to' key")
            if new_key != token and not (parent_node.children and new_key in parent_node.children):
                if parent_node.additional_children is None:
                    raise BadRequest(f"Key {new_key!r} is not permitted at {parent_pointer!r}")
                if parent_node.key_enum and new_key not in parent_node.key_enum:
                    raise BadRequest(f"Key {new_key!r} is not in key_enum")
                if parent_node.key_pattern and not re.match(parent_node.key_pattern, new_key):
                    raise BadRequest(f"Key {new_key!r} does not match key_pattern")
            return
        if op == "drop":
            if parent_node.type != "object":
                raise BadRequest(f"Cannot drop a key from {parent_node.type} at {pointer!r}")
            if parent_node.read_only:
                raise Forbidden(f"Path {parent_pointer!r} is read-only")
            declared = self._node_for(state.registration, pointer, required=False)
            if declared is not None:
                raise BadRequest(
                    f"Path {pointer!r} is declared; use remove, not drop"
                )
            if self._subtree_has_secret(parent_node) and not principal.has("settings_edit_secret"):
                raise SecretAccessDenied(f"Path {parent_pointer!r} is a secret subtree")
            return
        node = self._node_for(state.registration, pointer, required=False)
        if node is None and parent_node.type == "array" and parent_node.option_nodes:
            # An item beyond the declared options still has a permitted shape.
            node = parent_node.option_nodes[0]
        if node is None:
            raise NotFound(f"Path {pointer!r} is not declared by the descriptor")
        if op == "remove":
            if node.required:
                raise Forbidden(f"Path {pointer!r} is required and cannot be removed")
            if node.read_only:
                raise Forbidden(f"Path {pointer!r} is read-only")
            if node.const is not None:
                raise Forbidden(f"Path {pointer!r} has a fixed value")
            if parent_node.children and token in parent_node.children and parent_node.additional_children is None:
                raise Forbidden(f"Path {pointer!r} is a fixed declared child")
        if op == "move" and parent_node.type != "array":
            raise BadRequest("Only array items can be moved")
        if op == "move_index" and parent_node.type != "array":
            raise BadRequest("A move target must be an array index")
        if node.secret and op in ("set", "remove", "move") and not principal.has(
            "settings_edit_secret"
        ):
            raise SecretAccessDenied(f"Path {pointer!r} is a secret subtree")
        if op == "set":
            existing = document.find(pointer)
            if node.read_only and existing is not None:
                if value_text is not None and document.value_text(existing) != value_text:
                    raise Forbidden(f"Path {pointer!r} is read-only")
        if value_text is not None and str(value_text).strip() == "":
            raise BadRequest("value_text is required")

    # -- candidate pipeline ----------------------------------------------
    def _prepare(
        self, state: DocumentState, path: str, value_text: str, principal: Principal
    ) -> tuple[str, list[ValueIssue]]:
        """Build the source-preserving candidate and validate the exact result."""
        registration = state.registration
        issues: list[ValueIssue] = []
        if path == "":
            return state.text, [ValueIssue(path, "read_only", "The root pointer is read-only in v1")]
        try:
            candidate_text = state.document.apply_set(path, value_text)
        except CommentPreservationConflict as exc:
            return state.text, [ValueIssue(path, "comment_preservation", str(exc))]
        except PathError as exc:
            return state.text, [ValueIssue(path, "path", str(exc))]
        try:
            fragment = parse_fragment(value_text)
            submitted = fragment.stored_value(fragment.root)
        except AisetError as exc:
            return state.text, [ValueIssue(path, "value_text", str(exc))]

        node = self._node_for(registration, path, required=False)
        if node is None:
            return state.text, [
                ValueIssue(path, "undeclared_path", "Path is not declared by the descriptor")
            ]
        try:
            candidate = Document(candidate_text, origin=registration.store.path.name)
        except AisetError as exc:
            return state.text, [ValueIssue(path, "parse", str(exc))]
        self._check_editable(state, path, node, submitted, principal, candidate)
        stored = candidate.stored_value(candidate.root)
        limit_issues = check_limits(stored, self.settings.limits)
        if limit_issues:
            return candidate_text, limit_issues
        issues.extend(self._validate_stored(registration, stored, candidate))
        self._check_hook_capability(state, path, candidate)
        return candidate_text, issues

    def _validate_stored(
        self, registration: DocumentRegistration, stored: Any, candidate: Document
    ) -> list[ValueIssue]:
        """Resolve and validate a stored tree, attaching source positions."""
        issues: list[ValueIssue] = []
        effective, resolve_issues = build_effective(
            stored, registration.descriptor.root, registration.resolver
        )
        issues.extend(resolve_issues)
        if not any(issue.severity == "error" for issue in issues):
            issues.extend(
                validate_document(effective, registration.descriptor.root, limits=self.settings.limits)
            )
        for issue in issues:
            if issue.line is None:
                line, column = _locate(candidate, issue.path)
                issue.line, issue.column = line, column
        return issues

    def _revalidate_locked(
        self, state: DocumentState, candidate: Document, principal: Principal
    ) -> None:
        """Under the lock, reparse and revalidate the exact candidate (SPEC.md 8.1)."""
        stored = candidate.stored_value(candidate.root)
        limit_issues = check_limits(stored, self.settings.limits)
        if limit_issues:
            raise ValidationError(
                "Candidate configuration is invalid", issues=[issue.to_dict() for issue in limit_issues]
            )
        issues = self._validate_stored(state.registration, stored, candidate)
        errors = [issue for issue in issues if issue.severity == "error"]
        if errors:
            raise ValidationError(
                "Candidate configuration is invalid", issues=[issue.to_dict() for issue in errors]
            )

    def _probe(self, state: DocumentState, candidate_text: str, changed_paths: list[str]) -> None:
        """`probe_changes` may veto before persistence (SPEC.md 10.3)."""
        if not self._probe_changes:
            return
        try:
            candidate = Document(candidate_text, origin=state.registration.store.path.name)
            after = candidate.stored_value(candidate.root)
        except AisetError:
            return
        before = copy.deepcopy(state.stored)
        for callback in self._probe_changes:
            outcome = self._call(callback, before, copy.deepcopy(after), changed_paths)
            if isinstance(outcome, Rejection):
                raise ValidationError(outcome.message, issues=[issue.to_dict() for issue in outcome.issues])

    # -- state -----------------------------------------------------------
    def _state(self, document_id: str) -> DocumentState:
        state = self.states.get(document_id)
        if state is None:
            self._load_state(document_id, force_lkg=False)
            state = self.states[document_id]
        return state

    def _load_state(self, document_id: str, *, force_lkg: bool) -> LoadResult:
        registration = self._registration(document_id)
        store = registration.store
        store.check_symlink()
        data, revision, text = store.read()
        if force_lkg:
            return self._load_lkg_state(registration)
        state, issues = self._analyze(registration, revision, text, "file")
        if state is not None:
            previous = self.states.get(document_id)
            store.last_validated = data
            self.states[document_id] = state
            if previous is not None and previous.revision != revision:
                self._audit("external_edit_adopted", {"document": document_id, "revision": revision})
            return self._result(state)

        reason = _issue_summary(issues)
        lkg = self._newest_valid_backup(registration)
        if lkg is not None:
            backup_data, backup_revision = lkg
            state = self._build_state(registration, backup_data, backup_revision, decode(backup_data), "lkg")
            if state is not None:
                self.states[document_id] = state
                result = self._result(state)
                result.reason = reason
                self._audit("lkg_fallback", {"document": document_id, "reason": reason})
                LOGGER.warning("lkg_fallback document=%s reason=%s", document_id, reason)
                return result

        previous = self.states.get(document_id)
        invalid = self._invalid_state(
            registration, data, revision, text, reason, issues,
            restore=previous is not None and registration.store.last_validated is not None,
        )
        self.states[document_id] = invalid
        self._audit("invalid_document", {"document": document_id, "reason": reason})
        LOGGER.error("invalid_document document=%s reason=%s", document_id, reason)
        return self._result(invalid)

    def _load_lkg_state(self, registration: DocumentRegistration) -> LoadResult:
        """Explicit load LKG: newest valid backup, whatever the on-disk state is."""
        lkg = self._newest_valid_backup(registration)
        if lkg is None:
            raise NoValidBackup("No valid backup is available for this document")
        backup_data, backup_revision = lkg
        state = self._analyze(registration, backup_revision, decode(backup_data), "lkg")[0]
        if state is None:
            raise NoValidBackup("No valid backup is available for this document")
        self.states[registration.document_id] = state
        result = self._result(state)
        result.reason = "explicit_lkg_request"
        return result

    def _newest_valid_backup(self, registration: DocumentRegistration) -> tuple[bytes, str] | None:
        for path in registration.store.backup_chain():
            data = path.read_bytes()
            if len(data) > self.settings.limits.max_file_size:
                continue
            state = self._build_state(registration, data, revision_of_bytes(data), decode(data), "file")
            if state is not None:
                return data, revision_of_bytes(data)
        return None

    def _build_state(
        self,
        registration: DocumentRegistration,
        data: bytes,
        revision: str,
        text: str,
        source: str,
    ) -> DocumentState | None:
        state, _ = self._analyze(registration, revision, text, source)
        return state

    def _analyze(
        self, registration: DocumentRegistration, revision: str, text: str, source: str
    ) -> tuple[DocumentState | None, list[ValueIssue]]:
        try:
            document = Document(text, origin=registration.store.path.name)
            stored = document.stored_value(document.root)
        except AisetError as exc:
            return None, [ValueIssue("", "parse", str(exc))]
        provenance: dict[str, Any] = {}
        effective, issues = build_effective(
            stored, registration.descriptor.root, registration.resolver, provenance=provenance
        )
        if not any(issue.severity == "error" for issue in issues):
            issues.extend(
                validate_document(effective, registration.descriptor.root, limits=self.settings.limits)
            )
        if any(issue.severity == "error" for issue in issues):
            return None, issues
        return (
            DocumentState(
                registration=registration,
                revision=revision,
                text=text,
                document=document,
                stored=stored,
                effective=effective,
                provenance=provenance,
                loaded_from=source,
                active_revision=revision,
            ),
            issues,
        )

    def _invalid_state(
        self,
        registration: DocumentRegistration,
        data: bytes,
        revision: str,
        text: str,
        reason: str,
        issues: list[ValueIssue],
        *,
        restore: bool = False,
    ) -> DocumentState:
        try:
            document = Document(text, origin=registration.store.path.name)
            stored = document.stored_value(document.root)
        except AisetError:
            document = Document("{}")
            stored = {}
        state = DocumentState(
            registration=registration,
            revision=revision,
            text=text,
            document=document,
            stored=stored,
            effective={},
            provenance={},
            loaded_from="file",
            invalid_on_disk=True,
            invalid_reason=reason,
            active_revision=revision,
            issues=issues,
        )
        if restore:
            self._preserve_rejected(state)
        return state

    def _preserve_rejected(self, state: DocumentState) -> None:
        """Run-time restore: keep the rejected bytes, then write back the last good one."""
        store = state.registration.store
        try:
            data = store.read_bytes()
        except StorageError:  # pragma: no cover - unreadable file
            return
        conflicted = store.save_conflicted(data)
        self._audit(
            "external_edit_restored",
            {"document": store.document_id, "conflicted": conflicted.name, "reason": state.invalid_reason},
        )
        LOGGER.warning(
            "external_edit_restored document=%s conflicted=%s", store.document_id, conflicted.name
        )
        if store.last_validated:
            try:
                store.write_unchecked(store.last_validated)
                state.text = decode(store.last_validated)
                state.document = Document(state.text)
                state.stored = state.document.stored_value(state.document.root)
            except (StorageError, AisetError) as exc:  # pragma: no cover - defensive
                state.invalid_reason = f"{state.invalid_reason}; restore failed: {exc}"

    def _adopt(self, state: DocumentState, data: bytes) -> DocumentState:
        """Publish a newly stored revision as the current state."""
        registration = state.registration
        text = decode(data)
        document = Document(text, origin=registration.store.path.name)
        stored = document.stored_value(document.root)
        provenance: dict[str, Any] = {}
        effective, _ = build_effective(
            stored, registration.descriptor.root, registration.resolver, provenance=provenance
        )
        new_state = DocumentState(
            registration=registration,
            revision=revision_of_bytes(data),
            text=text,
            document=document,
            stored=stored,
            effective=effective,
            provenance=provenance,
            active_revision=state.active_revision,
        )
        self.states[registration.document_id] = new_state
        registration.store.last_validated = data
        return new_state

    def _result(self, state: DocumentState) -> LoadResult:
        return LoadResult(
            document=state.registration.document_id,
            loaded=state.loaded_from,
            revision=state.revision,
            descriptor_revision=state.registration.descriptor.revision,
            effective=copy.deepcopy(state.effective),
            provenance=copy.deepcopy(state.provenance),
            invalid_on_disk=state.invalid_on_disk,
            reason=state.invalid_reason,
            issues=list(state.issues),
        )

    def _etag(self, state: DocumentState) -> str:
        payload = f"{state.revision}:{state.registration.descriptor.revision}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # -- permissions and checks ------------------------------------------
    def _require(self, principal: Principal | None, permission: str) -> None:
        if principal is None:
            raise Unauthorized("A principal is required")
        if not principal.has(permission):
            raise Forbidden(f"Principal {principal.id!r} lacks {permission}")

    def _check_revisions(
        self, state: DocumentState, source_revision: str | None, descriptor_revision: str | None
    ) -> None:
        if not source_revision or not descriptor_revision:
            raise RevisionRequired("expected_revision and expected_descriptor_revision are required")
        if source_revision != state.revision:
            raise RevisionConflict(
                "Stale source revision; re-read the document before saving",
                detail=f"current={state.revision} client={source_revision}",
            )
        if descriptor_revision != state.registration.descriptor.revision:
            raise RevisionConflict(
                "Stale descriptor revision; reload the descriptor before saving",
                detail=f"current={state.registration.descriptor.revision} client={descriptor_revision}",
            )

    def _node_for(
        self, registration: DocumentRegistration, path: str, *, required: bool
    ) -> Node | None:
        node = node_at(registration.descriptor, path)
        if node is None:
            if required:
                raise NotFound(f"Path {path!r} is not declared by the descriptor")
            return None
        return node

    def _subtree_has_secret(self, node: Node | None) -> bool:
        if node is None:
            return False
        if node.secret:
            return True
        for child in (node.children or {}).values():
            if self._subtree_has_secret(child):
                return True
        if node.additional_children is not None and self._subtree_has_secret(node.additional_children):
            return True
        if node.option_nodes and any(self._subtree_has_secret(option) for option in node.option_nodes):
            return True
        return node.item_node is not None and self._subtree_has_secret(node.item_node)

    def _require_secret_subtree(self, node: Node | None, principal: Principal, path: str) -> None:
        """A fragment containing an inaccessible secret is denied, never redacted."""
        if principal.has("settings_read_secret"):
            return
        if self._subtree_has_secret(node):
            raise SecretAccessDenied(
                f"Path {path!r} contains an inaccessible secret; a redacted fragment is not returned"
            )

    def _check_editable(
        self,
        state: DocumentState,
        path: str,
        node: Node,
        submitted: Any,
        principal: Principal,
        candidate: Document,
    ) -> None:
        """Parent edits cannot bypass descendant read-only/secret protections.

        A read-only descendant blocks the edit only when its source actually
        changes; leaving it untouched is not a modification (SPEC.md 11).
        """
        creating = state.document.find(path) is None
        if node.read_only and not creating:
            raise Forbidden(f"Path {path!r} is read-only")
        if node.secret and not principal.has("settings_edit_secret"):
            raise SecretAccessDenied(f"Path {path!r} is a secret subtree")
        if not isinstance(submitted, (dict, list)):
            return
        for child_path in _submitted_paths(path, submitted):
            if child_path == path or self._creates(state, child_path):
                continue
            child = self._node_for(state.registration, child_path, required=False)
            if child is None:
                continue
            if child.secret and not principal.has("settings_edit_secret"):
                raise SecretAccessDenied(f"Path {child_path!r} is a secret subtree")
            if child.read_only and not self._source_unchanged(state, candidate, child_path):
                raise Forbidden(f"Path {child_path!r} is read-only")

    def _source_unchanged(self, state: DocumentState, candidate: Document, pointer: str) -> bool:
        before = state.document.find(pointer)
        after = candidate.find(pointer)
        if before is None or after is None:
            return False
        return state.document.source_of(before) == candidate.source_of(after)

    def _creates(self, state: DocumentState, path: str) -> bool:
        return state.document.find(path) is None

    def _batch_changed_paths(
        self, state: DocumentState, candidate_text: str, operations: Sequence[dict[str, Any]]
    ) -> list[str]:
        """Changed paths of a batch: every operation target and its subtree."""
        try:
            candidate = Document(candidate_text, origin=state.registration.store.path.name)
        except AisetError:  # pragma: no cover - defensive
            return []
        touched: set[str] = set()
        for operation in operations:
            for key in ("path", "from"):
                pointer = operation.get(key)
                if not isinstance(pointer, str):
                    continue
                if pointer.endswith("/-"):
                    # An appended item changes the container, so report it too.
                    pointer = pointer[:-2]
                base = pointer.rstrip("/")
                touched.update(state.document.paths(base))
                touched.update(candidate.paths(base))
            if operation.get("op") == "rename":
                # The new key is a path too, and it exists only after the batch.
                base = str(operation.get("path") or "")
                parent = base.rsplit("/", 1)[0]
                new_key = operation.get("to")
                if isinstance(new_key, str) and new_key:
                    pointer = parent + "/" + escape(new_key)
                    touched.update(state.document.paths(pointer))
                    touched.update(candidate.paths(pointer))
        return sorted(touched)

    def _changed_paths(self, state: DocumentState, candidate_text: str, pointer: str) -> list[str]:
        """Every pointer present before or after the edit, at or below the target."""
        try:
            candidate = Document(candidate_text, origin=state.registration.store.path.name)
        except AisetError:  # pragma: no cover - defensive
            return [pointer]
        return sorted(set(state.document.paths(pointer)) | set(candidate.paths(pointer)))

    def _check_hook_capability(self, state: DocumentState, path: str, candidate: Document) -> None:
        """Recognized hook bindings are rejected, never silently ignored (SPEC.md 17).

        A change inside a hook-bound subtree triggers the ancestor bindings too,
        exactly as the dispatcher of phase 2 would plan them (SPEC.md 19.2).
        """
        for changed in self._changed_paths(state, candidate.text, path):
            for prefix in _prefixes(changed):
                node = self._node_for(state.registration, prefix, required=False)
                if node is not None and node.hooks:
                    raise UnsupportedCapability(
                        "Descriptor lifecycle hooks are recognized but not executed by this build",
                        detail=f"first binding at {prefix}",
                    )

    # -- application and notification ------------------------------------
    def _apply_change(
        self, state: DocumentState, new_state: DocumentState, changed_paths: list[str]
    ) -> str:
        """Application state of one committed write.

        The most restrictive `apply` policy of the changed paths wins and becomes
        the reported state:

        | state | meaning for the host |
        |---|---|
        | `applied` | every changed node is `live`; the next read already sees the value |
        | `reload_required` | the host must re-read its configuration and re-apply it |
        | `restart_required` | only a process restart picks the change up |
        | `apply_failed` | the `on_application` callback raised; the file is committed but the host did not apply it |

        `live` is also the policy a node without an explicit `apply` must not
        get: the descriptor default is `restart`, so an unmarked node always asks
        for a restart rather than pretending to be live.
        """
        required = "live"
        for changed in changed_paths:
            node = self._node_for(state.registration, changed, required=False)
            if node is not None and node.apply in APPLY_ORDER:
                if APPLY_ORDER[node.apply] > APPLY_ORDER[required]:
                    required = node.apply
        failure: Exception | None = None
        if self._application and required in ("live", "reload"):
            for callback in self._application:
                try:
                    self._call(
                        callback,
                        copy.deepcopy(state.effective),
                        copy.deepcopy(new_state.effective),
                        changed_paths,
                    )
                except Exception as exc:  # noqa: BLE001 - host callback boundary
                    failure = exc
                    break
        if failure is not None:
            LOGGER.error("apply_failed document=%s detail=%s", new_state.registration.document_id, failure)
            return "apply_failed"
        if required == "live":
            new_state.active_revision = new_state.revision
            self.states[new_state.registration.document_id] = new_state
            return "applied"
        return f"{required}_required"

    def _notify(
        self,
        previous: DocumentState,
        new_state: DocumentState,
        changed_paths: list[str],
        application_state: str,
    ) -> None:
        document_id = new_state.registration.document_id
        event = ChangeEvent(
            document=document_id,
            changed_paths=changed_paths,
            previous_revision=previous.revision,
            revision=new_state.revision,
            application_state=application_state,
            active_revision=new_state.active_revision,
        )
        for subscription in list(self._subscriptions):
            if subscription.document_id != document_id or not subscription.active:
                continue
            if not subscription.matches(changed_paths):
                continue
            self._safe_call(subscription.callback, event)
        for callback in self._after_save:
            self._safe_call(
                callback,
                copy.deepcopy(previous.stored),
                copy.deepcopy(new_state.stored),
                event.to_dict(),
            )

    def _safe_call(self, callback: Callable[..., Any], *args: Any) -> Any:
        try:
            return self._call(callback, *args)
        except Exception as exc:  # noqa: BLE001 - notification must not undo a commit
            LOGGER.error("callback_failed callback=%s detail=%s", getattr(callback, "__name__", "?"), exc)
            return None

    # -- helpers ---------------------------------------------------------
    def _audit(self, name: str, payload: dict[str, Any]) -> None:
        if self._audit_sink:
            self._audit_sink(name, payload)
        LOGGER.debug("audit %s %s", name, sorted(payload))

    def _call(self, callback: Callable[..., Any], *args: Any) -> Any:
        """Run a sync or async callback with a bounded timeout, never under the lock."""
        box: dict[str, Any] = {}

        def runner() -> None:
            try:
                result = callback(*args)
                if inspect.isawaitable(result):
                    try:
                        asyncio.get_running_loop()
                        box["error"] = UnsupportedCapability(
                            "An async callback cannot run inside an already running event loop"
                        )
                        return
                    except RuntimeError:
                        result = asyncio.run(_await_value(result))
                box["result"] = result
            except AisetError as exc:
                box["error"] = exc
            except Exception as exc:  # noqa: BLE001 - host callback boundary
                box["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(self.settings.callback_timeout_seconds)
        if thread.is_alive():
            raise CallbackTimeout(f"Callback exceeded {self.settings.callback_timeout_seconds:g}s")
        if "error" in box:
            raise box["error"]
        return box.get("result")


@dataclass
class OperationsResult:
    """Result of one staged batch of structural operations."""

    document: str
    valid: bool
    operations: list[dict[str, Any]]
    issues: list[ValueIssue]
    revision: str
    descriptor_revision: str
    stored: bool = False
    application_state: str | None = None
    active_revision: str | None = None
    changed_paths: list[str] = dataclasses.field(default_factory=list)
    dry_run: bool = False
    commit_report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": True,
            "document": self.document,
            "valid": self.valid,
            "dry_run": self.dry_run,
            "operations": list(self.operations),
            "issues": [issue.to_dict() for issue in self.issues],
            "revision": self.revision,
            "descriptor_revision": self.descriptor_revision,
        }
        if self.stored:
            out["stored"] = True
            out["application"] = {
                "state": self.application_state,
                "active_revision": self.active_revision,
            }
            out["changed_paths"] = list(self.changed_paths)
        if self.commit_report is not None:
            out["commit_report"] = self.commit_report
        return out


@dataclass
class Rejection:
    """Host veto returned by `probe_changes` (SPEC.md 10.3)."""

    issues: list[ValueIssue]
    message: str = "The host rejected this change"


async def _await_value(awaitable: Any) -> Any:
    return await awaitable


def _issue_summary(issues: list[ValueIssue]) -> str:
    for issue in issues:
        if issue.severity == "error":
            return f"{issue.rule} at {issue.path or '/'}: {issue.message}"
    return "configuration is invalid"


def _require_callback_arity(callback: Callable[..., Any], names: tuple[str, ...]) -> None:
    """Reject a host callback whose signature cannot receive the documented arguments.

    The callbacks are invoked positionally after the commit, inside a boundary
    that logs and swallows every exception. A wrong arity would therefore
    surface only as a `callback_failed` log line while the host silently kept
    stale values - the exact failure this check exists to prevent. Callables
    whose signature cannot be inspected (builtins, C callables) are accepted.
    """
    import inspect

    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return
    positional = 0
    variadic = False
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            variadic = True
        elif parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional += 1
    if variadic or positional >= len(names):
        return
    wanted = ", ".join(names)
    raise TypeError(
        f"{getattr(callback, '__qualname__', callback)!r} must accept {wanted}; "
        f"it accepts {positional} positional argument(s)"
    )


def _locate(document: Document, pointer: str) -> tuple[int | None, int | None]:
    node = document.find(pointer) if pointer else document.root
    if node is None:
        return None, None
    return document.line_col(node.start)


def _lookup_stored(stored: Any, path: str) -> Any:
    node = stored
    for token in parse_pointer(path):
        if isinstance(node, dict):
            if token not in node:
                return MISSING
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit() or int(token) >= len(node):
                return MISSING
            node = node[int(token)]
        else:
            return MISSING
    return node


def _dump_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _prefixes(pointer: str) -> list[str]:
    """Every ancestor pointer including the pointer itself (SPEC.md 19.2)."""
    from .pointer import format_pointer, parse_pointer

    tokens = parse_pointer(pointer)
    return [format_pointer(tokens[:index]) for index in range(len(tokens) + 1)]


def _submitted_paths(pointer: str, value: Any) -> list[str]:
    paths = [pointer]
    if isinstance(value, dict):
        for key, item in value.items():
            token = key.replace("~", "~0").replace("/", "~1")
            paths.extend(_submitted_paths(f"{pointer}/{token}", item))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            paths.extend(_submitted_paths(f"{pointer}/{index}", item))
    return paths