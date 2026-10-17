"""Service pipeline: reads, writes, revisions, permissions, callbacks, recovery."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from aiset.errors import (
    Forbidden,
    NoValidBackup,
    NotFound,
    RevisionConflict,
    RevisionRequired,
    SecretAccessDenied,
    UnsupportedCapability,
    ValidationError,
)
from aiset.jsonsrc import Document
from aiset.resolver import Resolver
from aiset.service import ChangeEvent, Principal, Rejection, Service
from aiset.store import Settings
from aiset.validator import ValueIssue
from tests.conftest import DEMO_DESCRIPTOR, DEMO_CONFIG, copy_config, read

LIMITED = Principal(id="reader", permissions=frozenset({"settings_read_source", "settings_read_effective"}))


def _object_source(text: str, key: str) -> str:
    """Exact source of an object member value, without its key."""
    document = Document(text)
    node = document.find("/logging/" + key)
    return text[node.start : node.end]


def revisions(service, principal):
    loaded = service.load("demo", principal=principal)
    return loaded.revision, loaded.descriptor_revision


# -- loading ---------------------------------------------------------------


def test_load_returns_revision_and_effective_snapshot(service, principal):
    loaded = service.load("demo", principal=principal)
    assert loaded.loaded == "file"
    assert loaded.invalid_on_disk is False
    assert loaded.effective["title"] == "aiset demo"
    assert loaded.provenance["/title"]["kind"] == "environment"


def test_load_reports_unknown_document(service, principal):
    with pytest.raises(NotFound):
        service.load("nope", principal=principal)


# -- reading ---------------------------------------------------------------


def test_get_source_returns_the_exact_fragment(service, principal):
    result = service.get("demo", "/logging/levels/workers", principal=principal)
    assert result.exists and result.value_text == '"debug"'
    assert result.format == "json5"
    assert result.etag


def test_get_source_returns_comments_for_an_object(service, principal):
    result = service.get("demo", "/logging", principal=principal)
    assert "// Dynamic keys restricted by key_enum." in result.value_text


def test_get_reports_template_format(service, principal):
    result = service.get("demo", "/title", principal=principal)
    assert result.format == "json5-template"


def test_absent_optional_leaf_has_no_value_text(service, principal):
    result = service.get("demo", "/optional_leaf", principal=principal)
    assert result.exists is False and result.value_text is None


def test_absent_optional_leaf_reports_the_effective_default(service, principal):
    result = service.get("demo", "/text/level_default", principal=principal)
    assert result.exists is False and result.default_applied is False
    effective = service.get("demo", "/text/level_default", view="effective", principal=principal)
    assert effective.exists is False and effective.default_applied is True
    assert effective.value_text == '"warning"'


def test_explicit_null_is_present(service, principal):
    result = service.get("demo", "/nullable_field", principal=principal)
    assert result.exists is True and result.value_text == "null"


def test_effective_view_resolves_placeholders(service, principal):
    result = service.get("demo", "/http_port", view="effective", principal=principal)
    assert result.effective == 8383


def test_root_is_readable_but_not_writable(service, principal, revisions):
    assert service.get("demo", "", principal=principal).exists
    source, descriptor = revisions
    result = service.validate("demo", "", "{}", expected_revision=source,
                              expected_descriptor_revision=descriptor, principal=principal)
    assert not result.valid


def test_undeclared_path_is_not_found(service, principal):
    with pytest.raises(NotFound):
        service.get("demo", "/not_declared", principal=principal)


def test_secret_requires_permission(service):
    with pytest.raises(SecretAccessDenied):
        service.get("demo", "/credentials/api_key", principal=LIMITED)
    assert service.get("demo", "/credentials/api_key", principal=Principal.demo()).exists


def test_secret_parent_read_is_denied(service):
    with pytest.raises(SecretAccessDenied):
        service.get("demo", "/credentials", principal=LIMITED)


def test_read_requires_permission(service):
    with pytest.raises(Forbidden):
        service.get("demo", "/title", principal=Principal(id="none", permissions=frozenset()))


# -- validation ------------------------------------------------------------


def test_validate_accepts_a_good_candidate(service, principal, revisions):
    source, descriptor = revisions
    result = service.validate("demo", "/log_level", '"debug"', expected_revision=source,
                              expected_descriptor_revision=descriptor, principal=principal)
    assert result.valid and result.preservable and result.issues == []


def test_validate_reports_issues_with_line_and_column(service, principal, revisions):
    source, descriptor = revisions
    result = service.validate("demo", "/counters/fraction", "9", expected_revision=source,
                              expected_descriptor_revision=descriptor, principal=principal)
    assert not result.valid
    issue = result.issues[0]
    assert issue.rule == "maximum" and issue.line and issue.column


def test_validate_reports_comment_conflicts(service, principal, revisions):
    source, descriptor = revisions
    # Dropping a commented dynamic key cannot preserve its comment attachment.
    result = service.validate("demo", "/logging/sinks", "{ other: { target: 'x' } }",
                              expected_revision=source, expected_descriptor_revision=descriptor,
                              principal=principal)
    assert not result.valid
    assert result.preservable is False
    assert result.issues[0].rule == "comment_preservation"


def test_missing_revisions_are_rejected(service, principal):
    with pytest.raises(RevisionRequired):
        service.validate("demo", "/title", '"x"', expected_revision=None,
                         expected_descriptor_revision=None, principal=principal)


def test_stale_revision_is_a_conflict(service, principal, revisions):
    source, descriptor = revisions
    service.set("demo", "/enabled", "false", expected_revision=source,
                expected_descriptor_revision=descriptor, principal=principal)
    with pytest.raises(RevisionConflict):
        service.set("demo", "/enabled", "true", expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=principal)


def test_stale_descriptor_revision_is_a_conflict(service, principal, revisions):
    source, _ = revisions
    with pytest.raises(RevisionConflict):
        service.set("demo", "/enabled", "true", expected_revision=source,
                    expected_descriptor_revision="sha256:other", principal=principal)


# -- writing ---------------------------------------------------------------


def test_set_preserves_every_other_byte(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    before = read(demo_dir / "config.json5")
    service.set("demo", "/log_level", '"debug"', expected_revision=source,
                expected_descriptor_revision=descriptor, principal=principal)
    after = read(demo_dir / "config.json5")
    assert after != before
    assert after.replace('log_level: "debug"', 'log_level: "info"') == before


def test_set_reports_the_application_state_from_the_apply_policy(service, principal, revisions):
    source, descriptor = revisions
    live = service.set("demo", "/enabled", "false", expected_revision=source,
                       expected_descriptor_revision=descriptor, principal=principal)
    assert live.application_state == "applied"
    restart = service.set("demo", "/title", '"other"', expected_revision=live.revision,
                          expected_descriptor_revision=descriptor, principal=principal)
    assert restart.application_state == "restart_required"
    reload_ = service.set("demo", "/counters/zero", "7", expected_revision=restart.revision,
                          expected_descriptor_revision=descriptor, principal=principal)
    assert reload_.application_state == "reload_required"


def test_failed_set_leaves_the_file_unchanged(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    before = read(demo_dir / "config.json5")
    with pytest.raises(ValidationError):
        service.set("demo", "/counters/fraction", "5", expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=principal)
    assert read(demo_dir / "config.json5") == before


def test_read_only_field_is_rejected(service, principal, revisions):
    source, descriptor = revisions
    with pytest.raises(Forbidden):
        service.set("demo", "/version", '"2.0"', expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=principal)


def test_read_only_descendant_blocks_a_parent_edit(service, principal, revisions):
    source, descriptor = revisions
    text = read(service.documents["demo"].store.path)
    document = Document(text)
    node = document.find("/resources/0")
    current = text[node.start : node.end]
    with pytest.raises(Forbidden):
        service.set("demo", "/resources/0", current.replace('"gpu0"', '"gpu9"'),
                    expected_revision=source, expected_descriptor_revision=descriptor,
                    principal=principal)


def test_unchanged_read_only_descendant_is_allowed(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    text = read(demo_dir / "config.json5")
    document = Document(text)
    node = document.find("/resources/0")
    current = text[node.start : node.end]
    result = service.set("demo", "/resources/0", current.replace("vram_bytes: 24576000000",
                                                                 "vram_bytes: 24576000001"),
                         expected_revision=source, expected_descriptor_revision=descriptor,
                         principal=principal)
    assert result.stored
    assert 'id: "gpu0"' in read(demo_dir / "config.json5")


def test_secret_write_requires_permission(service, principal, revisions):
    source, descriptor = revisions
    writer = Principal(id="writer", permissions=frozenset({"settings_write"}))
    with pytest.raises(SecretAccessDenied):
        service.set("demo", "/credentials/api_key", '"x"', expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=writer)


def test_write_requires_permission(service, revisions):
    source, descriptor = revisions
    with pytest.raises(Forbidden):
        service.set("demo", "/title", '"x"', expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=LIMITED)


def test_creating_an_absent_leaf(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    result = service.set("demo", "/optional_leaf", '"created"', expected_revision=source,
                         expected_descriptor_revision=descriptor, principal=principal)
    assert result.stored
    assert 'optional_leaf: "created"' in read(demo_dir / "config.json5")


def test_creating_a_dynamic_key(service, principal, revisions):
    source, descriptor = revisions
    result = service.set("demo", "/logging/levels/http", '"info"', expected_revision=source,
                         expected_descriptor_revision=descriptor, principal=principal)
    assert result.stored


def test_dynamic_key_outside_key_enum_is_rejected(service, principal, revisions):
    source, descriptor = revisions
    with pytest.raises(ValidationError):
        service.set("demo", "/logging/levels/unknown", '"info"', expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=principal)


def test_array_element_edit(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    service.set("demo", "/flag_list/1", "7", expected_revision=source,
                expected_descriptor_revision=descriptor, principal=principal)
    assert "7" in read(demo_dir / "config.json5")


def test_array_index_must_exist(service, principal, revisions):
    source, descriptor = revisions
    with pytest.raises(ValidationError):
        service.set("demo", "/flag_list/99", "7", expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=principal)


def test_object_replacement_keeps_comments(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    text = read(demo_dir / "config.json5")
    original = _object_source(text, "sinks")
    service.set("demo", "/logging/sinks", original.replace("1048576", "2048"),
                expected_revision=source, expected_descriptor_revision=descriptor, principal=principal)
    after = read(demo_dir / "config.json5")
    assert "// Trailing comment for the main sink." in after
    assert "rotate_bytes: 2048" in after


def test_changed_paths_include_descendants(service, principal, revisions):
    source, descriptor = revisions
    text = read(service.documents["demo"].store.path)
    original = _object_source(text, "sinks")
    result = service.set("demo", "/logging/sinks", original.replace("1048576", "4096"),
                         expected_revision=source, expected_descriptor_revision=descriptor,
                         principal=principal)
    assert "/logging/sinks/main/rotate_bytes" in result.changed_paths


# -- hooks, callbacks, subscriptions ---------------------------------------


def test_hooks_are_rejected_with_an_unsupported_capability(tmp_path, principal):
    descriptor = DEMO_DESCRIPTOR.replace(
        "      enabled: {",
        """      guarded: {
        type: "object",
        hooks: { before_update: [ { tag: "check", scope: "node" } ] },
        children: { value: { type: "int" } },
      },
      enabled: {""",
    )
    config = DEMO_CONFIG.replace("  enabled: true,", "  guarded: { value: 1 },\n  enabled: true,")
    path = copy_config(tmp_path, config)
    service = Service()
    service.register("demo", path, descriptor, resolver=Resolver(environ={}, dotenv={}, overrides={}))
    loaded = service.load("demo", principal=principal)
    with pytest.raises(UnsupportedCapability):
        service.set("demo", "/guarded/value", "2", expected_revision=loaded.revision,
                    expected_descriptor_revision=loaded.descriptor_revision, principal=principal)


def test_probe_changes_can_reject_a_save(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    service.on_probe_changes(lambda before, after, paths: Rejection(
        [ValueIssue("/log_level", "host_rule", "not allowed at this time")]))
    with pytest.raises(ValidationError) as excinfo:
        service.set("demo", "/log_level", '"debug"', expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=principal)
    assert excinfo.value.issues[0]["rule"] == "host_rule"
    assert 'log_level: "info"' in read(demo_dir / "config.json5")


def test_application_callback_failure_keeps_the_commit(service, principal, revisions):
    source, descriptor = revisions
    service.on_application(lambda before, after, paths: (_ for _ in ()).throw(RuntimeError("boom")))
    result = service.set("demo", "/enabled", "false", expected_revision=source,
                         expected_descriptor_revision=descriptor, principal=principal)
    assert result.stored is True
    assert result.application_state == "apply_failed"


def test_async_application_callback(service, principal, revisions):
    source, descriptor = revisions

    async def apply(before, after, paths):
        return None

    service.on_application(apply)
    result = service.set("demo", "/enabled", "false", expected_revision=source,
                         expected_descriptor_revision=descriptor, principal=principal)
    assert result.application_state == "applied"


def test_callback_timeout_is_reported(service, principal, revisions):
    source, descriptor = revisions
    service.settings.callback_timeout_seconds = 0.2
    service.on_probe_changes(lambda before, after, paths: __import__("time").sleep(1))
    from aiset.errors import CallbackTimeout

    with pytest.raises(CallbackTimeout):
        service.set("demo", "/enabled", "false", expected_revision=source,
                    expected_descriptor_revision=descriptor, principal=principal)


def test_after_save_and_subscriptions_receive_the_event(service, principal, revisions):
    source, descriptor = revisions
    seen: list[ChangeEvent] = []
    saved: list[dict] = []
    subscription = service.subscribe("demo", ["/logging"], seen.append, principal=principal)
    service.on_after_save(lambda before, after, event: saved.append(event))
    service.set("demo", "/logging/levels/workers", '"info"', expected_revision=source,
                expected_descriptor_revision=descriptor, principal=principal)
    assert seen and seen[0].changed_paths == ["/logging/levels/workers"]
    assert saved and saved[0]["document"] == "demo"
    subscription.unsubscribe()
    service.set("demo", "/logging/levels/workers", '"debug"', expected_revision=seen[0].revision,
                expected_descriptor_revision=descriptor, principal=principal)
    assert len(seen) == 1


# -- descriptor access -----------------------------------------------------


def test_descriptor_authorized_view_omits_metadata(service, principal):
    result = service.descriptor("demo", principal=principal)
    assert "x_demo" not in str(result.descriptor["root"])
    assert result.descriptor["root"]["type"] == "object"


def test_descriptor_raw_view_requires_permission(service):
    with pytest.raises(Forbidden):
        service.descriptor("demo", view="raw", principal=LIMITED)
    result = service.descriptor("demo", view="raw", principal=Principal.demo())
    assert result.descriptor["x_demo"]["owner"] == "aiset"


def test_validate_descriptor_service_operation(principal):
    service = Service()
    result = service.validate_descriptor("{ descriptor_version: '1.0', root: { type: 'object' } }",
                                         principal=principal)
    assert result.valid
    invalid = service.validate_descriptor("{ descriptor_version: '9.9', root: {} }")
    assert not invalid.valid


# -- recovery --------------------------------------------------------------


def test_lkg_fallback_on_load(tmp_path, resolver, principal):
    path = copy_config(tmp_path, DEMO_CONFIG)
    service = Service(Settings(backup_depth=3))
    service.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    loaded = service.load("demo", principal=principal)
    service.set("demo", "/enabled", "false", expected_revision=loaded.revision,
                expected_descriptor_revision=loaded.descriptor_revision, principal=principal)
    copy_config(tmp_path, DEMO_CONFIG.replace("  enabled: true,", "  enabled: 5,"))
    service.states.clear()
    recovered = service.load("demo", principal=principal)
    assert recovered.loaded == "lkg"
    assert "validation" in recovered.reason or recovered.reason


def test_explicit_load_lkg(tmp_path, resolver, principal):
    path = copy_config(tmp_path, DEMO_CONFIG)
    service = Service(Settings(backup_depth=3))
    service.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    loaded = service.load("demo", principal=principal)
    service.set("demo", "/enabled", "false", expected_revision=loaded.revision,
                expected_descriptor_revision=loaded.descriptor_revision, principal=principal)
    result = service.load_lkg("demo", principal=principal)
    assert result.loaded == "lkg" and result.reason == "explicit_lkg_request"
    # read-only: the file on disk is untouched
    assert "enabled: false" in read(path)


def test_load_lkg_without_backups(tmp_path, resolver, principal):
    path = copy_config(tmp_path, DEMO_CONFIG)
    service = Service()
    service.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    with pytest.raises(NoValidBackup):
        service.load_lkg("demo", principal=principal)


def test_valid_external_edit_is_adopted(tmp_path, resolver, principal):
    path = copy_config(tmp_path, DEMO_CONFIG)
    service = Service()
    service.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    loaded = service.load("demo", principal=principal)
    copy_config(tmp_path, DEMO_CONFIG.replace("  enabled: true,", "  enabled: false,"))
    reread = service.reread("demo", principal=principal)
    assert reread.effective["enabled"] is False
    assert reread.revision != loaded.revision


def test_invalid_external_edit_is_restored_and_preserved(tmp_path, resolver, principal):
    path = copy_config(tmp_path, DEMO_CONFIG)
    service = Service()
    service.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    service.load("demo", principal=principal)
    copy_config(tmp_path, DEMO_CONFIG.replace("  enabled: true,", "  enabled: not-a-bool,"))
    reread = service.reread("demo", principal=principal)
    assert reread.invalid_on_disk is True
    conflicts = list(tmp_path.glob("config.json5.conflicted.*.back"))
    assert len(conflicts) == 1
    assert b"not-a-bool" in conflicts[0].read_bytes()
    assert "enabled: true" in read(path)


def test_rollback_restores_the_previous_content(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    service.set("demo", "/enabled", "false", expected_revision=source,
                expected_descriptor_revision=descriptor, principal=principal)
    result = service.rollback("demo", "regression", principal=principal)
    assert result.application_state == "restart_required"
    assert "enabled: true" in read(demo_dir / "config.json5")


def test_revision_survives_restart(demo_dir, resolver, principal):
    descriptor_source = DEMO_DESCRIPTOR
    path = demo_dir / "config.json5"
    first = Service()
    first.register("demo", path, descriptor_source, resolver=resolver)
    loaded = first.load("demo", principal=principal)
    first.set("demo", "/log_level", '"critical"', expected_revision=loaded.revision,
              expected_descriptor_revision=loaded.descriptor_revision, principal=principal)
    second = Service()
    second.register("demo", path, descriptor_source, resolver=resolver)
    assert second.load("demo", principal=principal).effective["log_level"] == "critical"


def test_symlink_policy_can_be_disabled(tmp_path, resolver, principal):
    real = tmp_path / "real.json5"
    real.write_text(DEMO_CONFIG, encoding="utf-8")
    link = tmp_path / "config.json5"
    link.symlink_to(real)
    service = Service(Settings(symlinks_allowed=False))
    with pytest.raises(Exception):
        service.register("demo", link, DEMO_DESCRIPTOR, resolver=resolver)


def test_tracked_examples_are_never_modified(tmp_path, resolver, principal):
    examples = tmp_path / "examples"
    shutil.copytree(Path("examples"), examples)
    state = tmp_path / "state"
    state.mkdir()
    shutil.copyfile(examples / "config.json5", state / "config.json5")
    before = (examples / "config.json5").read_bytes()
    service = Service()
    service.register("demo", state / "config.json5", DEMO_DESCRIPTOR, resolver=resolver)
    loaded = service.load("demo", principal=principal)
    service.set("demo", "/log_level", '"critical"', expected_revision=loaded.revision,
                expected_descriptor_revision=loaded.descriptor_revision, principal=principal)
    assert (examples / "config.json5").read_bytes() == before
    assert "critical" not in (examples / "config.json5").read_text()


def test_document_source_is_a_valid_document_after_every_write(demo_dir, service, principal, revisions):
    source, descriptor = revisions
    for pointer, value in (("/log_level", '"critical"'), ("/counters/zero", "5"), ("/title", '"t"')):
        result = service.set("demo", pointer, value, expected_revision=source,
                             expected_descriptor_revision=descriptor, principal=principal)
        source = result.revision
    Document(read(demo_dir / "config.json5"))

# --------------------------------------------------------------------------
# the opaque `any` type end to end
# --------------------------------------------------------------------------

ANY_DOCUMENT = """{
  descriptor_version: "1.0",
  root: {
    type: "object",
    children: {
      tools: {
        type: "object",
        additional_children: { type: "any", description: "One free-form declaration" },
      },
    },
  },
}
"""


def _any_service(tmp_path, config_text):
    from aiset.resolver import Resolver
    from aiset.service import Service

    target = tmp_path / "config.json5"
    target.write_text(config_text, encoding="utf-8")
    service = Service()
    service.register("any", target, ANY_DOCUMENT, resolver=Resolver(overrides={}, dotenv={}, environ={}))
    return service


def test_free_form_region_loads_and_keeps_arbitrary_json(tmp_path):
    config = """
    {
      tools: {
        builtin: { description: "Run a command", parameters: { type: "object", properties: { cmd: { type: "string" } } } },
        counter: 3,
        flag: true,
        nothing: null,
        list: [1, "two", { three: 3 }],
      },
    }
    """
    service = _any_service(tmp_path, config)
    loaded = service.load("any", principal=Principal.demo())
    assert loaded.invalid_on_disk is False
    assert loaded.effective["tools"]["counter"] == 3
    assert loaded.effective["tools"]["flag"] is True
    assert loaded.effective["tools"]["nothing"] is None


def test_free_form_region_is_written_as_source_text(tmp_path):
    service = _any_service(tmp_path, "{ tools: {} }\n")
    loaded = service.load("any", principal=Principal.demo())
    result = service.apply_operations(
        "any",
        [{"op": "add", "path": "/tools/new", "value_text": '{ a: [1, 2], b: "x" }'}],
        expected_revision=loaded.revision,
        expected_descriptor_revision=loaded.descriptor_revision,
        principal=Principal.demo(),
    )
    assert result.stored is True
    reread = service.load("any", principal=Principal.demo())
    assert reread.invalid_on_disk is False
    assert reread.effective["tools"]["new"] == {"a": [1, 2], "b": "x"}


def test_free_form_region_is_one_leaf_in_a_snapshot(tmp_path):
    service = _any_service(tmp_path, '{ tools: { a: { deep: [1] } } }')
    service.load("any", principal=Principal.demo())
    snapshot = service.tree("any", "/tools/a", principal=Principal.demo())
    node = snapshot["node"]
    assert node["kind"] == "leaf"
    assert node["type"] == "any"
    assert node["capabilities"]["edit"] is True


# --------------------------------------------------------------------------
# host callback signatures
# --------------------------------------------------------------------------


def test_a_callback_with_the_wrong_arity_is_refused_at_registration(service):
    """Regression: a wrong arity used to be swallowed at commit time as callback_failed."""
    with pytest.raises(TypeError) as caught:
        service.on_after_save(lambda previous: None)
    assert "event" in str(caught.value)


@pytest.mark.parametrize("register", ["on_probe_changes", "on_after_save", "on_application"])
def test_every_callback_accepts_the_documented_three_arguments(service, register):
    getattr(service, register)(lambda previous, current, third: None)
    getattr(service, register)(lambda *args: None)
    getattr(service, register)(lambda previous, current, third, extra: None)


def test_a_method_with_the_documented_signature_is_accepted(service):
    class Host:
        def on_after_save(self, previous, current, event):
            return None

    host = Host()
    service.on_after_save(host.on_after_save)


def test_a_callback_without_an_inspectable_signature_is_accepted(service):
    service.on_after_save(print)
