"""Durable, revision-checked file storage (SPEC.md sections 7.3, 10.4, 14.8).

Registered documents are plain files. Writers cooperate through a sidecar lock,
replace the target atomically, keep a bounded `.back` chain for Last Known Good
recovery, and preserve rejected external bytes as conflicted copies.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .errors import LockTimeout, PayloadTooLarge, StorageError
from .validator import Limits


@dataclass
class Settings:
    """aiset's own configuration defaults (SPEC.md section 3.6)."""

    backup_depth: int = 5
    conflicted_retention: int = 5
    symlinks_allowed: bool = True
    reread_interval_seconds: float = 0.0
    callback_timeout_seconds: float = 30.0
    lock_timeout_seconds: float = 5.0
    write_attempts: int = 3
    logging_level: str = "info"
    demo_port: int = 8383
    demo_host: str = "0.0.0.0"
    limits: Limits = field(default_factory=Limits)

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "Settings":
        """Build settings from an aiset settings document, ignoring unknown keys.

        The document layout follows examples/aiset.json5: `aiset`, `storage`,
        `runtime` and `logging_level`. Flat keys are accepted as well, which
        keeps programmatic use simple.
        """
        settings = cls()
        data = data or {}

        def read(path: str) -> Any:
            node: Any = data
            for token in path.split("."):
                if not isinstance(node, dict) or token not in node:
                    return None
                node = node[token]
            return node

        for path, name, cast in (
            ("storage.backup_depth", "backup_depth", int),
            ("storage.conflicted_retention", "conflicted_retention", int),
            ("storage.write_attempts", "write_attempts", int),
            ("aiset.port", "demo_port", int),
            ("aiset.host", "demo_host", str),
            ("storage.reread_interval_seconds", "reread_interval_seconds", float),
            ("storage.lock_timeout_seconds", "lock_timeout_seconds", float),
            ("runtime.callback_timeout_seconds", "callback_timeout_seconds", float),
            ("storage.symlinks_allowed", "symlinks_allowed", bool),
            ("logging_level", "logging_level", str),
        ):
            for candidate in (path, name):
                value = read(candidate)
                if value is None and candidate != path:
                    value = data.get(name)
                if value is None:
                    continue
                if cast is bool:
                    if isinstance(value, bool):
                        setattr(settings, name, value)
                elif cast is int and isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    setattr(settings, name, value)
                elif cast is float and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                    setattr(settings, name, float(value))
                elif cast is str and isinstance(value, str) and value:
                    setattr(settings, name, value)
                break

        limits = data.get("runtime", {}).get("limits") if isinstance(data.get("runtime"), dict) else None
        if isinstance(limits, dict):
            for name in (
                "max_file_size",
                "max_body_size",
                "max_depth",
                "max_collection_size",
                "max_string_length",
                "max_pattern_length",
                "regex_timeout_ms",
            ):
                value = limits.get(name)
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    setattr(settings.limits, name, value)
            settings.limits.max_body_bytes = settings.limits.max_body_size
        return settings


@dataclass
class CommitReport:
    """Explicit commit state after a durable write (SPEC.md 7.3)."""

    document: str
    committed: bool
    revision: str | None
    uncertain: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "committed": self.committed,
            "revision": self.revision,
            "uncertain": self.uncertain,
            "detail": self.detail,
        }


def revision_of_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()[:32]


def decode(data: bytes) -> str:
    """Decode file bytes without newline translation; bytes must survive unchanged."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    return data.decode("utf-8")


def encode(text: str, had_bom: bool) -> bytes:
    return ("﻿" + text if had_bom else text).encode("utf-8")


class _FileLock:
    """Bounded cross-process lock on a stable sidecar lock file."""

    def __init__(self, path: Path, timeout: float) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self) -> "_FileLock":
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._fd = fd
                return self
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN):
                    os.close(fd)
                    raise StorageError(f"Cannot lock {self.path.name}: {exc.strerror}") from exc
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise LockTimeout(
                        f"Could not acquire the store lock within {self.timeout:g}s"
                    ) from exc
                time.sleep(0.05)

    def __exit__(self, *exc_info: Any) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


class Store:
    """One registered configuration document on disk."""

    def __init__(self, document_id: str, path: str | os.PathLike[str], settings: Settings) -> None:
        self.document_id = document_id
        self.path = Path(path)
        self.settings = settings
        self.backup_done = False
        self.last_validated: bytes | None = None

    # -- reading ---------------------------------------------------------
    def exists(self) -> bool:
        return self.path.exists()

    def read_bytes(self) -> bytes:
        try:
            return self.path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"Document {self.document_id!r} does not exist") from exc
        except OSError as exc:
            raise StorageError(f"Cannot read {self.path.name}: {exc.strerror}") from exc

    def read(self) -> tuple[bytes, str, str]:
        """Return (bytes, revision, text) with the limit check applied first."""
        data = self.read_bytes()
        if len(data) > self.settings.limits.max_file_size:
            raise PayloadTooLarge(
                f"Document exceeds {self.settings.limits.max_file_size} bytes"
            )
        return data, revision_of_bytes(data), decode(data)

    def check_symlink(self) -> None:
        if self.settings.symlinks_allowed:
            return
        if self.path.is_symlink() or any(
            parent.is_symlink() for parent in self.path.parents if str(parent) not in ("/", "")
        ):
            raise StorageError("Registered path resolves through a symlink; disabled by policy")

    # -- locking ---------------------------------------------------------
    def lock(self) -> _FileLock:
        return _FileLock(self.lock_path(), self.settings.lock_timeout_seconds)

    def lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    # -- backups ---------------------------------------------------------
    def backup_path(self, level: int) -> Path:
        return self.path.with_name(self.path.name + ".back" * level)

    def backup_chain(self) -> list[Path]:
        """Backup paths, newest first, limited by the configured depth."""
        return [
            self.backup_path(level)
            for level in range(1, max(self.settings.backup_depth, 0) + 1)
            if self.backup_path(level).exists()
        ]

    def rotate_backups(self, current: bytes) -> None:
        """Shift the chain down one level; only renames, never a rewrite."""
        depth = self.settings.backup_depth
        if depth <= 0:
            return
        deepest = self.backup_path(depth)
        if deepest.exists():
            deepest.unlink()
        for level in range(depth - 1, 0, -1):
            source = self.backup_path(level)
            if source.exists():
                os.replace(source, self.backup_path(level + 1))
        self.backup_path(1).write_bytes(current)

    def conflicted_path(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        return self.path.with_name(f"{self.path.name}.conflicted.{stamp}.back")

    def save_conflicted(self, data: bytes) -> Path:
        """Preserve rejected bytes; never overwrite them if the copy fails."""
        target = self.conflicted_path()
        try:
            with open(target, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise StorageError(
                f"Cannot preserve the rejected configuration in {target.name}: {exc.strerror}"
            ) from exc
        self._rotate_conflicted()
        return target

    def _rotate_conflicted(self) -> None:
        retention = max(self.settings.conflicted_retention, 1)
        pattern = f"{self.path.name}.conflicted.*.back"
        copies = sorted(self.path.parent.glob(pattern), key=lambda item: item.name)
        for stale in copies[:-retention]:
            try:
                stale.unlink()
            except OSError:  # pragma: no cover - best effort cleanup
                pass

    # -- writing ---------------------------------------------------------
    def write(
        self,
        data: bytes,
        *,
        expected_revision: str | None,
        audit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> CommitReport:
        """Durably replace the document under the store lock."""
        if len(data) > self.settings.limits.max_file_size:
            raise PayloadTooLarge(f"Document exceeds {self.settings.limits.max_file_size} bytes")
        with self.lock():
            current = self.read_bytes() if self.path.exists() else None
            if expected_revision is not None and current is not None:
                if revision_of_bytes(current) != expected_revision:
                    raise StorageError("Source revision changed while the lock was held")
            return self.write_locked(data, audit=audit)

    def write_unchecked(
        self, data: bytes, *, audit: Callable[[str, dict[str, Any]], None] | None = None
    ) -> CommitReport:
        """Replace the document without a revision check (recovery paths only)."""
        with self.lock():
            return self.write_locked(data, audit=audit)

    def write_locked(
        self, data: bytes, *, audit: Callable[[str, dict[str, Any]], None] | None = None
    ) -> CommitReport:
        """Atomically replace the document; the caller must already hold the lock."""
        if len(data) > self.settings.limits.max_file_size:
            raise PayloadTooLarge(f"Document exceeds {self.settings.limits.max_file_size} bytes")
        return self._atomic_write(data, audit=audit)

    def _atomic_write(
        self, data: bytes, *, audit: Callable[[str, dict[str, Any]], None] | None = None
    ) -> CommitReport:
        current = self.read_bytes() if self.path.exists() else b""
        if not self.backup_done and current:
            self.rotate_backups(current)
            self.backup_done = True
        new_revision = revision_of_bytes(data)
        attempts = max(self.settings.write_attempts, 1)
        detail = ""
        for attempt in range(1, attempts + 1):
            tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.{attempt}.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp_path, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, self.path)
                self._sync_directory()
                return CommitReport(
                    document=self.document_id, committed=True, revision=new_revision
                )
            except OSError as exc:
                detail = f"{exc.strerror or exc}"
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                if attempt < attempts:
                    if audit:
                        audit("write_retry", {"document": self.document_id, "attempt": attempt})
                    time.sleep(0.05 * attempt)
        return CommitReport(
            document=self.document_id,
            committed=False,
            revision=None,
            uncertain=True,
            detail=f"write failed after {attempts} attempts: {detail}",
        )

    def _sync_directory(self) -> None:
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        except OSError:  # pragma: no cover - not supported on every filesystem
            pass
        finally:
            os.close(directory)

    def restore_backup(self, level: int = 1) -> bytes:
        """Restore the newest valid backup as the current file (rollback).

        The consumed entry is removed and the rest of the chain shifts up one
        level, so the last change is undone as if it had never happened.
        """
        source = self.backup_path(level)
        if not source.exists():
            raise StorageError("No backup is available for rollback")
        data = source.read_bytes()
        self.backup_done = True  # a rollback does not start a new editing session
        source.unlink()
        for deeper in range(level + 1, self.settings.backup_depth + 1):
            candidate = self.backup_path(deeper)
            if candidate.exists():
                os.replace(candidate, self.backup_path(deeper - 1))
        self.write_unchecked(data)
        return data

    def copy_example(self, example: Path, target: Path) -> bool:
        """Seed an editable file from a tracked example only when it is absent."""
        if target.exists():
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, target)
        return True