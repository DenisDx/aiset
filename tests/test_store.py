"""Durable storage: revisions, locking, atomic writes, backups, recovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aiset.errors import LockTimeout, PayloadTooLarge, StorageError
from aiset.store import Settings, Store, decode, encode, revision_of_bytes


def make_store(tmp_path: Path, text: str = "{ a: 1 }\n", **settings_kwargs) -> Store:
    path = tmp_path / "config.json5"
    path.write_text(text, encoding="utf-8")
    return Store("main", path, Settings(**settings_kwargs))


def test_read_returns_bytes_revision_and_text(tmp_path):
    store = make_store(tmp_path)
    data, revision, text = store.read()
    assert revision == revision_of_bytes(data)
    assert text == "{ a: 1 }\n"


def test_revision_changes_on_any_byte_including_comments(tmp_path):
    store = make_store(tmp_path)
    _, first, _ = store.read()
    store.path.write_text("{ a: 1 } // comment\n", encoding="utf-8")
    _, second, _ = store.read()
    assert first != second


def test_write_is_atomic_and_updates_the_revision(tmp_path):
    store = make_store(tmp_path)
    report = store.write_unchecked(b"{ a: 2 }\n")
    assert report.committed and report.revision == revision_of_bytes(b"{ a: 2 }\n")
    assert store.path.read_bytes() == b"{ a: 2 }\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_stale_revision_is_rejected(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(StorageError):
        store.write(b"{ a: 3 }\n", expected_revision="sha256:stale")


def test_missing_revision_writes_anyway(tmp_path):
    store = make_store(tmp_path)
    report = store.write(b"{ a: 4 }\n", expected_revision=None)
    assert report.committed


def test_lock_is_exclusive(tmp_path):
    store = make_store(tmp_path, lock_timeout_seconds=0.2)
    with store.lock():
        other = Store("main", store.path, Settings(lock_timeout_seconds=0.2))
        with pytest.raises(LockTimeout):
            with other.lock():
                pass


def test_lock_file_is_a_sidecar(tmp_path):
    store = make_store(tmp_path)
    with store.lock():
        assert store.lock_path().name == "config.json5.lock"
        assert not store.lock_path().is_symlink()
        assert store.path.exists()


def test_backup_chain_rotates_once_per_session(tmp_path):
    store = make_store(tmp_path, "{ a: 1 }\n", backup_depth=3)
    store.write_unchecked(b"{ a: 2 }\n")
    store.write_unchecked(b"{ a: 3 }\n")
    store.write_unchecked(b"{ a: 4 }\n")
    assert store.path.read_text() == "{ a: 4 }\n"
    # One backup per editing session: the chain holds the session-start content.
    assert store.backup_path(1).read_text() == "{ a: 1 }\n"
    assert not store.backup_path(2).exists()


def test_backup_depth_is_bounded(tmp_path):
    store = make_store(tmp_path, "{ a: 1 }\n", backup_depth=2)
    for index in range(2, 8):
        store.backup_done = False  # each iteration is a new editing session
        store.write_unchecked(f"{{ a: {index} }}\n".encode())
    assert store.backup_path(1).exists()
    assert store.backup_path(2).exists()
    assert not store.backup_path(3).exists()


def test_new_session_rotates_again(tmp_path):
    store = make_store(tmp_path, "{ a: 1 }\n", backup_depth=2)
    store.write_unchecked(b"{ a: 2 }\n")
    assert store.backup_path(1).read_text() == "{ a: 1 }\n"
    store.backup_done = False  # a reload starts a new editing session
    store.write_unchecked(b"{ a: 3 }\n")
    assert store.backup_path(1).read_text() == "{ a: 2 }\n"


def test_backup_rotation_preserves_bytes_exactly(tmp_path):
    original = "{\n  // comment\n  a: 1, // trailing\n}\n"
    store = make_store(tmp_path, original, backup_depth=2)
    store.write_unchecked(b"{ a: 9 }\n")
    assert store.backup_path(1).read_text(encoding="utf-8") == original


def test_zero_depth_disables_backups(tmp_path):
    store = make_store(tmp_path, backup_depth=0)
    store.write_unchecked(b"{ a: 2 }\n")
    assert not store.backup_path(1).exists()


def test_conflicted_copy_is_preserved_with_a_timestamp(tmp_path):
    store = make_store(tmp_path, conflicted_retention=2)
    path = store.save_conflicted(b"{ broken")
    assert path.exists()
    assert path.name.startswith("config.json5.conflicted.")
    assert path.name.endswith(".back")
    assert path.read_bytes() == b"{ broken"


def test_conflicted_retention_is_bounded(tmp_path):
    store = make_store(tmp_path, conflicted_retention=1)
    for _ in range(3):
        store.save_conflicted(b"{ broken")
    copies = list(tmp_path.glob("config.json5.conflicted.*.back"))
    assert len(copies) == 1


def test_restore_backup_shifts_the_chain(tmp_path):
    store = make_store(tmp_path, "{ a: 1 }\n", backup_depth=2)
    for index in (2, 3, 4):
        store.backup_done = False
        store.write_unchecked(f"{{ a: {index} }}\n".encode())
    restored = store.restore_backup(1)
    assert restored == b"{ a: 3 }\n"
    assert store.path.read_bytes() == b"{ a: 3 }\n"
    assert store.backup_path(1).read_bytes() == b"{ a: 2 }\n"
    assert not store.backup_path(2).exists()


def test_file_size_limit_is_checked_before_writing(tmp_path):
    store = make_store(tmp_path)
    store.settings.limits.max_file_size = 10
    with pytest.raises(PayloadTooLarge):
        store.write_unchecked(b"{ a: 1 }\n" * 100)


def test_commit_report_marks_uncertain_failures(tmp_path, monkeypatch):
    store = make_store(tmp_path, write_attempts=2)

    def failing_replace(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", failing_replace)
    report = store.write_unchecked(b"{ a: 5 }\n")
    assert report.committed is False
    assert report.uncertain is True
    assert "2 attempts" in report.detail


def test_bom_and_crlf_round_trip(tmp_path):
    text = decode(b"\xef\xbb\xbf{\r\n  a: 1,\r\n}\r\n")
    assert decode(encode(text, True)) == text
    assert encode(text, True).startswith(b"\xef\xbb\xbf")


def test_symlink_policy(tmp_path):
    real = tmp_path / "real.json5"
    real.write_text("{ a: 1 }\n", encoding="utf-8")
    link = tmp_path / "config.json5"
    link.symlink_to(real)
    store = Store("main", link, Settings(symlinks_allowed=False))
    with pytest.raises(StorageError):
        store.check_symlink()
    Store("main", link, Settings(symlinks_allowed=True)).check_symlink()

def test_commit_report_serialises_its_own_fields():
    """Regression: the method lived at module level and named a field that does not exist."""
    from aiset.store import CommitReport

    report = CommitReport(document="demo", committed=True, revision="sha256:abc")
    assert report.to_dict() == {
        "document": "demo",
        "committed": True,
        "revision": "sha256:abc",
        "uncertain": False,
        "detail": "",
    }


def test_a_successful_write_returns_a_serialisable_report(tmp_path):
    from aiset.store import Store

    target = tmp_path / "config.json5"
    target.write_text('{"a": 1}', encoding="utf-8")
    store = Store("demo", target, Settings())
    report = store.write_unchecked(b'{"a": 2}')
    assert report.committed is True
    assert report.to_dict()["document"] == "demo"
    assert target.read_text(encoding="utf-8") == '{"a": 2}'
