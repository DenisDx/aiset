"""`doctor`: report every issue, repair only what is mechanically safe.

The classes under test: `clamp`, `coerce` and `drop_unknown`. Everything else is
report-only, and the file is written only when the repairs make it fully valid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiset.doctor import FIX_CLAMP, FIX_COERCE, FIX_DROP_UNKNOWN, SAFE_CLASSES
from aiset.errors import RevisionConflict
from aiset.resolver import Resolver
from aiset.service import Principal, Service
from tests.conftest import DEMO_CONFIG, DEMO_DESCRIPTOR

READ_ONLY = Principal(
    id="reader",
    permissions=frozenset({"settings_read_source", "settings_read_effective"}),
)


def _service(tmp_path: Path, text: str, descriptor: str = DEMO_DESCRIPTOR) -> Service:
    target = tmp_path / "config.json5"
    target.write_text(text, encoding="utf-8")
    service = Service()
    service.register(
        "doc",
        target,
        descriptor,
        resolver=Resolver(overrides={}, dotenv={}, environ={}),
    )
    return service


def _issues(report) -> dict[str, tuple[str, str | None]]:
    """Path to (rule, fix class) for a compact assertion."""
    return {issue.path: (issue.rule, issue.fix) for issue in report.issues}


# -- report ----------------------------------------------------------------


def test_the_report_lists_every_issue_with_its_fix_class(tmp_path):
    text = DEMO_CONFIG.replace("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")
    text = text.replace("  version: \"1.0\",", "  version: \"1.0\",\n  stale_key: 1,")
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo())

    issues = _issues(report)
    assert issues["/http_port"] == ("maximum", FIX_CLAMP)
    assert issues["/stale_key"] == ("undeclared_field", FIX_DROP_UNKNOWN)
    assert report.valid is False
    assert report.applied is False


def test_a_report_does_not_write(tmp_path):
    text = DEMO_CONFIG.replace("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")
    service = _service(tmp_path, text)
    before = (tmp_path / "config.json5").read_text(encoding="utf-8")
    revision = service.load("doc", principal=Principal.demo()).revision

    service.doctor("doc", principal=Principal.demo())

    assert (tmp_path / "config.json5").read_text(encoding="utf-8") == before
    assert service.load("doc", principal=Principal.demo()).revision == revision


def test_an_unfixable_rule_is_reported_without_a_class(tmp_path):
    text = DEMO_CONFIG.replace('version: "1.0",', 'version: "2.0",')
    service = _service(tmp_path, text)

    issues = _issues(service.doctor("doc", principal=Principal.demo()))

    assert issues["/version"] == ("const", None)


# -- clamp -----------------------------------------------------------------


def test_fix_true_clamps_into_range_and_preserves_comments(tmp_path):
    text = DEMO_CONFIG.replace(
        "http_port: ${AISET_DEMO_HTTP_PORT:-8383},",
        "http_port: 70000, // keep this note",
    )
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo(), fix=True)

    assert report.applied is True
    assert report.valid is True
    assert [fix.path for fix in report.fixes] == ["/http_port"]
    written = (tmp_path / "config.json5").read_text(encoding="utf-8")
    assert "http_port: 65535" in written
    assert "// keep this note" in written


def test_a_clamp_does_not_touch_a_minimum_it_satisfies(tmp_path):
    text = DEMO_CONFIG.replace("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 8080,")
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo(), fix=True)

    assert report.fixes == []


# -- drop_unknown ----------------------------------------------------------


def test_fix_true_does_not_delete_an_undeclared_key(tmp_path):
    text = DEMO_CONFIG.replace("  version: \"1.0\",", "  version: \"1.0\",\n  stale_key: 1,")
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo(), fix=True)

    assert report.applied is False
    assert any("class not requested" in item.reason for item in report.skipped)
    assert "stale_key" in (tmp_path / "config.json5").read_text(encoding="utf-8")


def test_drop_unknown_removes_the_key_when_named(tmp_path):
    text = DEMO_CONFIG.replace("  version: \"1.0\",", "  version: \"1.0\",\n  stale_key: 1,")
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo(), fix=[FIX_DROP_UNKNOWN])

    assert report.applied is True
    assert report.valid is True
    written = (tmp_path / "config.json5").read_text(encoding="utf-8")
    assert "stale_key" not in written
    assert "// aiset demo configuration" in written


def test_the_report_suggests_a_rename_for_a_near_miss(tmp_path):
    text = DEMO_CONFIG.replace("  version: \"1.0\",", "  version: \"1.0\",\n  titel: \"typo\",")
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo())

    issue = next(item for item in report.issues if item.path == "/titel")
    assert issue.suggestion and "title" in issue.suggestion


# -- coerce ----------------------------------------------------------------


def test_coerce_accepts_an_unambiguous_literal(tmp_path):
    text = DEMO_CONFIG.replace("admin_port: 8384,", 'admin_port: "8384",')
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo(), fix=[FIX_COERCE])

    assert report.applied is True
    assert "admin_port: 8384" in (tmp_path / "config.json5").read_text(encoding="utf-8")


def test_coerce_never_touches_a_placeholder(tmp_path):
    text = DEMO_CONFIG.replace("admin_port: 8384,", 'admin_port: "${ADMIN_PORT}",')
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo(), fix=[FIX_COERCE])

    assert report.applied is False
    assert report.fixes == []


# -- refusals --------------------------------------------------------------


def test_a_required_key_without_a_default_needs_a_human(tmp_path):
    descriptor = """
    {
      descriptor_version: "1.0",
      root: { type: "object", children: {
        needed: { type: "string", required: true },
      } },
    }
    """
    service = _service(tmp_path, "{\n}\n", descriptor=descriptor)

    report = service.doctor("doc", principal=Principal.demo(), fix=True)

    issue = next(item for item in report.issues if item.path == "/needed")
    assert issue.rule == "required"
    assert issue.fix is None
    assert "no default" in (issue.suggestion or "")
    assert report.applied is False


def test_a_secret_value_is_neither_reported_nor_fixed(tmp_path):
    descriptor = """
    {
      descriptor_version: "1.0",
      root: { type: "object", children: {
        token: { type: "int", maximum: 10, secret: true },
      } },
    }
    """
    service = _service(tmp_path, "{\n  token: 99,\n}\n", descriptor=descriptor)

    report = service.doctor("doc", principal=Principal.demo(), fix=[FIX_CLAMP, FIX_COERCE])

    issue = next(item for item in report.issues if item.path == "/token")
    assert issue.fix is None
    assert issue.before is None and issue.after is None
    assert report.applied is False
    assert "99" not in json.dumps(report.to_dict())


def test_a_read_only_node_is_not_fixed(tmp_path):
    text = DEMO_CONFIG.replace('version: "1.0",', 'version: "2.0",')
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=Principal.demo(), fix=[FIX_COERCE, FIX_CLAMP])

    assert report.applied is False
    assert 'version: "2.0"' in (tmp_path / "config.json5").read_text(encoding="utf-8")


def test_reading_is_enough_for_a_report_but_not_for_a_repair(tmp_path):
    text = DEMO_CONFIG.replace("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")
    service = _service(tmp_path, text)

    report = service.doctor("doc", principal=READ_ONLY)
    assert report.valid is False
    assert report.fixes == []

    report = service.doctor("doc", principal=READ_ONLY, fix=True)
    assert report.applied is False
    assert any("forbidden" in item.reason for item in report.skipped)


# -- lifecycle -------------------------------------------------------------


def test_the_result_is_idempotent(tmp_path):
    text = DEMO_CONFIG.replace("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")
    text = text.replace("  version: \"1.0\",", "  version: \"1.0\",\n  stale_key: 1,")
    service = _service(tmp_path, text)
    classes = [FIX_CLAMP, FIX_DROP_UNKNOWN]

    first = service.doctor("doc", principal=Principal.demo(), fix=classes)
    second = service.doctor("doc", principal=Principal.demo(), fix=classes)

    assert first.applied is True and first.valid is True
    assert second.applied is False
    assert second.fixes == []
    assert second.valid is True


def test_a_stale_revision_is_refused(tmp_path):
    text = DEMO_CONFIG.replace("http_port: ${AISET_DEMO_HTTP_PORT:-8383},", "http_port: 70000,")
    service = _service(tmp_path, text)

    with pytest.raises(RevisionConflict):
        service.doctor(
            "doc", principal=Principal.demo(), fix=True, expected_revision="sha256:stale"
        )


def test_a_file_that_does_not_parse_reports_and_applies_nothing(tmp_path):
    service = _service(tmp_path, "{\n  broken: \n")

    report = service.doctor("doc", principal=Principal.demo(), fix=True)

    assert report.valid is False
    assert [issue.rule for issue in report.issues] == ["parse"]
    assert report.applied is False


def test_the_safe_classes_are_exactly_the_clamp():
    assert SAFE_CLASSES == (FIX_CLAMP,)
