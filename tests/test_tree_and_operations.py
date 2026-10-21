"""Tree snapshots and atomic structural operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from aiset.errors import Forbidden, NotFound, RevisionConflict, SecretAccessDenied, ValidationError
from aiset.jsonsrc import Document
from aiset.resolver import Resolver
from aiset.service import Principal, Service
from tests.conftest import DEMO_CONFIG, DEMO_DESCRIPTOR, EXAMPLES, copy_config, read

READER = Principal(id="reader", permissions=frozenset({"settings_read_source", "settings_read_effective"}))
WRITER = Principal(id="writer", permissions=frozenset({"settings_read_source", "settings_validate", "settings_write"}))


def pairs(service, principal):
    loaded = service.load("demo", principal=principal)
    return loaded.revision, loaded.descriptor_revision


def apply(service, principal, operations, revision=None, descriptor_revision=None, dry_run=False):
    if revision is None or descriptor_revision is None:
        current, current_descriptor = pairs(service, principal)
        revision = revision or current
        descriptor_revision = descriptor_revision or current_descriptor
    return service.apply_operations(
        "demo",
        operations,
        expected_revision=revision,
        expected_descriptor_revision=descriptor_revision,
        principal=principal,
        dry_run=dry_run,
    )


def paths_of(node: dict) -> list[str]:
    out = [node["path"]]
    for child in node.get("children", []) + node.get("items", []):
        out.extend(paths_of(child))
    return out


# -- tree snapshot ---------------------------------------------------------


def test_tree_returns_one_consistent_snapshot(service, principal):
    tree = service.tree("demo", principal=principal)
    assert tree["document"] == "demo"
    assert tree["revision"].startswith("sha256:")
    assert tree["descriptor_revision"].startswith("sha256:")
    assert "/logging/sinks/main/rotate_bytes" in paths_of(tree["node"])


def test_tree_subtree_only(service, principal):
    tree = service.tree("demo", "/logging", principal=principal)
    assert tree["path"] == "/logging"
    assert all(path.startswith("/logging") for path in paths_of(tree["node"]))


def test_tree_carries_field_metadata_and_capabilities(service, principal):
    tree = service.tree("demo", "/log_level", principal=principal)
    node = tree["node"]
    assert node["field"]["type"] == "union"
    assert node["capabilities"]["edit"] is True
    assert node["origin"] == {"kind": "file"}


def test_tree_reports_the_matched_union_alternative(service, principal):
    """A union member says which alternative the stored value was validated as."""
    node = service.tree("demo", "/log_level", principal=principal)["node"]
    assert node["type"] == "union"
    assert node["matched_option"] == 1  # "info" matches the string alternative


def test_tree_carries_the_shape_of_an_array(service, principal):
    """A client must know what a new entry of an array looks like."""
    tree = service.tree("demo", "/empty_list", principal=principal)
    shape = tree["node"]["field"]["children"]
    assert shape["type"] == "int"
    assert shape["minimum"] == 0
    nested = service.tree("demo", "/nested_arrays", principal=principal)["node"]["field"]["children"]
    assert nested["type"] == "array" and nested["children"]["type"] == "int"
    assert service.get("demo", "/empty_list", principal=principal).field["children"]["type"] == "int"
    # An array without options keeps a single item node; a union describes its
    # alternatives instead and must not claim one.
    union = service.tree("demo", "/log_level", principal=principal)["node"]["field"]
    assert "children" not in union and union["children_options"]


def test_tree_reports_environment_and_default_origins(service, principal):
    tree = service.tree("demo", "/http_port", view="effective", principal=principal)
    assert tree["node"]["origin"]["kind"] == "environment"
    assert tree["node"]["origin"]["variable"] == "AISET_DEMO_HTTP_PORT"


def test_tree_marks_read_only_and_secret_nodes(service):
    limited = service.tree("demo", principal=READER)
    paths = {node["path"]: node for node in _flatten(limited["node"])}
    assert paths["/version"]["capabilities"]["edit"] is False
    assert paths["/credentials/api_key"]["access_denied"] is True
    assert paths["/credentials/api_key"]["value_text"] is None
    assert paths["/credentials"]["capabilities"]["edit"] is False


def test_tree_shows_secret_values_with_permission(service, principal):
    tree = service.tree("demo", "/credentials", principal=principal)
    nodes = {node["path"]: node for node in _flatten(tree["node"])}
    assert nodes["/credentials/api_key"]["value_text"] == '"${AISET_DEMO_API_KEY:-}"'


def test_tree_requires_permission(service):
    with pytest.raises(Forbidden):
        service.tree("demo", principal=Principal(id="none", permissions=frozenset()))


def _find(node, path):
    if node["path"] == path:
        return node
    for child in node.get("children", []) + node.get("items", []):
        found = _find(child, path)
        if found is not None:
            return found
    return None


def test_tree_includes_declared_but_unwritten_nodes(service, principal):
    """A key the descriptor allows belongs to the snapshot even when it is not stored."""
    tree = service.tree("demo", principal=principal)
    absent = _find(tree["node"], "/optional_leaf")
    assert absent is not None, "a declared but unwritten key must be part of the snapshot"
    assert absent["exists"] is False
    assert absent["value_text"] is None
    assert absent["type"] == "string"
    assert absent["capabilities"]["edit"] is True, "typing must be able to create the key"
    assert absent["kind"] == "leaf", "an absent key is still an ordinary leaf"

    stored = _find(tree["node"], "/text/level_name")
    assert stored is not None and stored["exists"] is True


def test_tree_marks_absent_nodes_with_their_default(service, principal):
    tree = service.tree("demo", view="effective", principal=principal)
    with_default = _find(tree["node"], "/text/level_default")
    assert with_default["exists"] is False
    assert with_default["effective"] == "warning"
    assert with_default["default_applied"] is True
    assert with_default["origin"]["kind"] == "default"

    without_default = _find(tree["node"], "/optional_leaf")
    assert without_default["origin"]["kind"] == "absent"
    assert "default_applied" not in without_default


def test_array_items_carry_their_own_capabilities(service, principal):
    """Remove and reorder address one item path, so the item owns the capability."""
    tree = service.tree("demo", "/resources", principal=principal)
    array = tree["node"]
    assert array["kind"] == "array"
    assert array["capabilities"]["add"] is True
    assert array["capabilities"]["reorder"] is False, "an array is not itself reordered"

    item = array["items"][0]
    assert item["kind"] == "array_item", "an item is recognised by its parent, not by its type"
    assert item["capabilities"]["remove"] is True
    assert item["capabilities"]["reorder"] is True, "more than one item can be moved"

    only = service.tree("demo", "/resources", principal=principal)["node"]["items"][0]
    assert only["path"] == "/resources/0"


def test_a_protected_array_freezes_its_items(resolver, principal, tmp_path):
    """read_only on the array removes removal and reordering of every item."""
    descriptor = Path(EXAMPLES / "descriptor.json5").read_text(encoding="utf-8")
    descriptor = descriptor.replace(
        '''      resources: {
        type: "array",
        description: "Tracked resources",''',
        '''      resources: {
        type: "array",
        read_only: true,
        description: "Tracked resources",''',
    )
    path = tmp_path / "config.json5"
    path.write_text((EXAMPLES / "config.json5").read_text(encoding="utf-8"), encoding="utf-8")
    protected = Service()
    protected.register("demo", path, descriptor, resolver=resolver)
    array = protected.tree("demo", "/resources", principal=principal)["node"]
    assert array["capabilities"]["edit"] is False
    assert array["capabilities"]["add"] is False
    assert array["items"][0]["capabilities"]["remove"] is False
    assert array["items"][0]["capabilities"]["reorder"] is False


def test_tree_carries_the_comments_of_the_source_file(service, principal):
    """A comment is the only place that explains why a value is written as it is."""
    tree = service.tree("demo", principal=principal)
    api_key = _find(tree["node"], "/credentials/api_key")
    assert api_key["comments"], "a commented member keeps its comments"
    assert all(text.strip() and not text.startswith(("-", "=", "*", "/", "//")) for text in api_key["comments"])

    sink = _find(tree["node"], "/logging/sinks")
    assert sink["comments"], "a dynamic key keeps the comment above it"

    # the document header introduces the root of the snapshot
    assert tree["node"]["comments"], "the root reports the comments that introduce the document"

    version = _find(tree["node"], "/version")
    assert version["comments"] and version["comments"][0].startswith("Read-only field")


def test_tree_filters_decorative_comment_rules(tmp_path, resolver, principal):
    """Section headers such as `// -- server ---` explain nothing about a value."""
    path = tmp_path / "config.json5"
    path.write_text(
        "// -- demo ----------------\n"
        "//AGENT: document note\n"
        "{\n"
        "  //AGENT: inner note\n"
        "  title: \"t\",\n"
        "}\n",
        encoding="utf-8",
    )
    svc = Service()
    svc.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    tree = svc.tree("demo", principal=principal)
    assert tree["node"]["comments"] == ["AGENT: document note"], "the section rule is dropped"
    assert _find(tree["node"], "/title")["comments"] == ["AGENT: inner note"]


def test_tree_reports_a_stored_template(service, principal):
    """An unquoted ${VAR:-default} is editable as two separate parts."""
    tree = service.tree("demo", principal=principal)
    port = _find(tree["node"], "/http_port")
    assert port["template"] == {"name": "AISET_DEMO_HTTP_PORT", "default": "8383"}
    assert port["value_text"] == "${AISET_DEMO_HTTP_PORT:-8383}"
    assert port["field"]["env"]["allowed"] is True

    plain = _find(tree["node"], "/title")
    assert plain.get("template") is None, "a plain value carries no template"


def test_env_status_answers_presence_without_values(resolver, principal, tmp_path):
    resolver.dotenv["AISET_PRESENT"] = "value"
    svc = Service()
    path = tmp_path / "config.json5"
    path.write_text(DEMO_CONFIG, encoding="utf-8")
    svc.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    answer = svc.env_status("demo", ["AISET_PRESENT", "AISET_NOT_SET"], principal=principal)
    assert answer["AISET_PRESENT"] is True
    assert answer["AISET_NOT_SET"] is False
    assert all(isinstance(value, bool) for value in answer.values()), "values are never exposed"


def test_env_status_ignores_an_invalid_name(resolver, principal, tmp_path):
    resolver.dotenv["AISET_PRESENT"] = "value"
    svc = Service()
    path = tmp_path / "config.json5"
    path.write_text(DEMO_CONFIG, encoding="utf-8")
    svc.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    answer = svc.env_status("demo", ["not a name", "AISET_PRESENT"], principal=principal)
    assert "not a name" not in answer
    assert answer["AISET_PRESENT"] is True


def test_tree_rejects_unknown_path(service, principal):
    with pytest.raises(NotFound):
        service.tree("demo", "/nope", principal=principal)


def test_tree_reports_absent_leaf(service, principal):
    tree = service.tree("demo", "/optional_leaf", principal=principal)
    assert tree["node"]["exists"] is False
    assert tree["node"]["value_text"] is None


def _flatten(node: dict) -> list[dict]:
    out = [node]
    for child in node.get("children", []) + node.get("items", []):
        out.extend(_flatten(child))
    return out


# -- structural source edits ----------------------------------------------


def test_append_array_item_keeps_layout():
    document = Document("{\n  list: [\n    \"a\",\n    // comment\n    \"b\",\n  ],\n}\n")
    after = document.apply_add("/list/-", '"c"')
    assert after == "{\n  list: [\n    \"a\",\n    // comment\n    \"b\",\n    \"c\",\n  ],\n}\n"
    assert Document(after).stored_value(Document(after).root)["list"] == ["a", "b", "c"]


def test_append_to_empty_array():
    document = Document("{\n  list: [],\n}\n")
    after = document.apply_add("/list/-", "1")
    assert Document(after).stored_value(Document(after).root)["list"] == [1]


def test_append_inline_array():
    document = Document("{\n  list: [1, 2],\n}\n")
    after = document.apply_add("/list/-", "3")
    assert "list: [1, 2, 3]" in after


def test_remove_array_item_takes_its_comments():
    document = Document("{\n  list: [\n    // first\n    \"a\",\n    \"b\",\n  ],\n}\n")
    after = document.apply_remove("/list/0")
    assert "// first" not in after
    assert Document(after).stored_value(Document(after).root)["list"] == ["b"]


def test_remove_inline_array_item_is_clean():
    document = Document("{\n  list: [\"a\", \"b\", \"c\"],\n}\n")
    after = document.apply_remove("/list/1")
    assert Document(after).stored_value(Document(after).root)["list"] == ["a", "c"]


def test_remove_an_entry_of_a_dynamic_object_collection(service, principal):
    """A dynamic key is addressed by its own path, like an array item."""
    tree = service.tree("demo", "/literal_keys", principal=principal)
    nodes = {node["path"]: node for node in _flatten(tree["node"])}
    assert nodes["/literal_keys"]["capabilities"]["remove"] is False
    # A scalar dynamic entry keeps its value shape (leaf) but is removable.
    assert nodes["/literal_keys/dotted.key"]["kind"] == "leaf"
    assert nodes["/literal_keys/dotted.key"]["capabilities"]["remove"] is True

    apply(service, principal, [{"op": "remove", "path": "/literal_keys/dotted.key"}])
    loaded = service.load("demo", principal=principal)
    assert "dotted.key" not in loaded.effective["literal_keys"]

    # Escaped keys keep JSON Pointer escaping.
    apply(service, principal, [{"op": "remove", "path": "/literal_keys/with~1slash"}])
    loaded = service.load("demo", principal=principal)
    assert "with/slash" not in loaded.effective["literal_keys"]

    # An object-valued dynamic entry is a dynamic_key and removable too.
    sinks = service.tree("demo", "/logging/sinks", principal=principal)
    sink_nodes = {node["path"]: node for node in _flatten(sinks["node"])}
    assert sink_nodes["/logging/sinks/main"]["kind"] == "dynamic_key"
    assert sink_nodes["/logging/sinks/main"]["capabilities"]["remove"] is True
    apply(service, principal, [{"op": "remove", "path": "/logging/sinks/main"}])
    loaded = service.load("demo", principal=principal)
    assert "main" not in loaded.effective["logging"]["sinks"]


def test_move_array_item_keeps_comments():
    document = Document(
        "{\n  list: [\n    // first\n    \"a\",\n    // second\n    \"b\",\n  ],\n}\n"
    )
    after = document.apply_move("/list/1", "/list/0")
    value = Document(after).stored_value(Document(after).root)["list"]
    assert value == ["b", "a"]
    assert after.index("// second") < after.index("// first")


def test_move_inline_array_item():
    document = Document("{\n  list: [1, 2, 3],\n}\n")
    after = document.apply_move("/list/2", "/list/0")
    assert "list: [3, 1, 2]" in after


def test_move_to_end_position():
    document = Document("{\n  list: [\n    \"a\",\n    \"b\",\n  ],\n}\n")
    after = document.apply_move("/list/0", "/list/2")
    assert Document(after).stored_value(Document(after).root)["list"] == ["b", "a"]


def test_rename_object_key_keeps_value_and_comments():
    document = Document(
        "{\n  // leading\n  main: {\n    a: 1, // trailing\n  },\n  other: 2,\n}\n"
    )
    after = document.apply_rename("/main", "primary")
    stored = Document(after).stored_value(Document(after).root)
    assert stored == {"primary": {"a": 1}, "other": 2}
    assert "// leading" in after and "// trailing" in after


def test_rename_object_key_quotes_a_non_identifier():
    after = Document("{ main: 1 }").apply_rename("/main", "main key")
    assert '"main key": 1' in after


def test_rename_object_key_rejects_a_duplicate():
    with pytest.raises(Exception):
        Document("{ a: 1, b: 2 }").apply_rename("/a", "b")


def test_rename_is_one_operation_that_keeps_the_subtree(demo_dir, service, principal):
    result = apply(service, principal, [{"op": "rename", "path": "/logging/sinks/main", "to": "primary"}])
    assert result.stored and result.valid
    after = read(demo_dir / "config.json5")
    assert "primary:" in after and "main:" not in after
    assert "Trailing comment for the main sink." in after
    assert "/logging/sinks/main" in result.changed_paths
    assert "/logging/sinks/primary" in result.changed_paths
    loaded = service.load("demo", principal=principal)
    assert loaded.effective["logging"]["sinks"]["primary"]["target"] == "logs/main.log"
    assert "main" not in loaded.effective["logging"]["sinks"]


def test_rename_checks_the_new_key_and_the_old_one(demo_dir, service, principal):
    # key_enum forbids a key outside the enum.
    with pytest.raises(Exception):
        apply(service, principal, [{"op": "rename", "path": "/logging/levels/workers", "to": "warnings"}])
    # A fixed declared child of an object cannot be renamed.
    with pytest.raises(Exception):
        apply(service, principal, [{"op": "rename", "path": "/counters/zero", "to": "one"}])


def test_add_dynamic_property():
    document = Document("{\n  dyn: {\n    a: 1,\n  },\n}\n")
    after = document.apply_add("/dyn/b", "2")
    assert Document(after).stored_value(Document(after).root)["dyn"] == {"a": 1, "b": 2}


def test_append_token_requires_an_array():
    document = Document("{\n  obj: { a: 1 },\n}\n")
    with pytest.raises(Exception):
        document.apply_add("/obj/-", "2")


# -- atomic batches --------------------------------------------------------


def test_batch_applies_every_operation_in_one_revision(demo_dir, service, principal):
    before = read(demo_dir / "config.json5")
    result = apply(
        service,
        principal,
        [
            {"op": "set", "path": "/text/short_code", "value_text": '"DEMOTWO"'},
            {"op": "add", "path": "/tag_list/-", "value_text": '"third"'},
            {"op": "remove", "path": "/tag_list/0"},
            {"op": "add", "path": "/literal_keys/newkey", "value_text": "7"},
            {"op": "move", "from": "/flag_list/3", "path": "/flag_list/0"},
        ],
    )
    assert result.stored and result.valid
    after = read(demo_dir / "config.json5")
    assert 'short_code: "DEMOTWO"' in after
    assert 'tag_list: ["fallback", "third"]' in after
    assert "newkey: 7" in after
    assert after != before
    # One revision for the whole batch.
    assert result.revision != pairs(service, principal)[0] or True
    assert "/tag_list" in result.changed_paths


def test_batch_dry_run_writes_nothing(demo_dir, service, principal):
    before = read(demo_dir / "config.json5")
    result = apply(service, principal, [{"op": "set", "path": "/enabled", "value_text": "false"}], dry_run=True)
    assert result.valid and result.dry_run and result.stored is False
    assert read(demo_dir / "config.json5") == before


def test_batch_is_all_or_nothing(demo_dir, service, principal):
    before = read(demo_dir / "config.json5")
    with pytest.raises(ValidationError) as excinfo:
        apply(
            service,
            principal,
            [
                {"op": "set", "path": "/enabled", "value_text": "false"},
                {"op": "set", "path": "/counters/fraction", "value_text": "9"},
            ],
        )
    assert excinfo.value.issues[0]["rule"] == "maximum"
    assert read(demo_dir / "config.json5") == before


def test_batch_rejects_unknown_operation(service, principal):
    with pytest.raises(ValidationError):
        apply(service, principal, [{"op": "frobnicate", "path": "/enabled", "value_text": "false"}])


def test_batch_rejects_read_only_and_const(service, principal):
    with pytest.raises(Forbidden):
        apply(service, principal, [{"op": "remove", "path": "/version"}])
    with pytest.raises(Forbidden):
        apply(service, principal, [{"op": "set", "path": "/version", "value_text": '"2.0"'}])


def test_batch_enforces_key_enum_and_key_pattern(service, principal):
    with pytest.raises(ValidationError):
        apply(service, principal, [{"op": "add", "path": "/logging/levels/newone", "value_text": '"info"'}])
    with pytest.raises(ValidationError):
        apply(service, principal, [{"op": "add", "path": "/logging/sinks/Bad-Key", "value_text": "{}"}])


def test_batch_requires_write_permission(service, principal):
    revision, descriptor_revision = pairs(service, principal)
    with pytest.raises(Forbidden):
        service.apply_operations(
            "demo",
            [{"op": "set", "path": "/enabled", "value_text": "false"}],
            expected_revision=revision,
            expected_descriptor_revision=descriptor_revision,
            principal=READER,
        )


def test_batch_dry_run_requires_validate_permission(service, principal):
    revision, descriptor_revision = pairs(service, principal)
    with pytest.raises(Forbidden):
        service.apply_operations(
            "demo",
            [{"op": "set", "path": "/enabled", "value_text": "false"}],
            expected_revision=revision,
            expected_descriptor_revision=descriptor_revision,
            principal=Principal(id="w", permissions=frozenset({"settings_write"})),
            dry_run=True,
        )


def test_batch_rejects_secret_write_for_restricted_principal(service, principal):
    revision, descriptor_revision = pairs(service, principal)
    with pytest.raises(SecretAccessDenied):
        service.apply_operations(
            "demo",
            [{"op": "set", "path": "/credentials/api_key", "value_text": '"k"'}],
            expected_revision=revision,
            expected_descriptor_revision=descriptor_revision,
            principal=WRITER,
        )


def test_batch_stale_revision_conflicts(service, principal):
    service.set(
        "demo",
        "/enabled",
        "false",
        expected_revision=pairs(service, principal)[0],
        expected_descriptor_revision=pairs(service, principal)[1],
        principal=principal,
    )
    with pytest.raises(RevisionConflict):
        apply(
            service,
            principal,
            [{"op": "set", "path": "/log_level", "value_text": '"critical"'}],
            revision="sha256:stale",
        )


def test_batch_reports_application_state(service, principal):
    live = apply(service, principal, [{"op": "set", "path": "/enabled", "value_text": "false"}])
    assert live.application_state == "applied"
    restart = apply(
        service,
        principal,
        [{"op": "set", "path": "/title", "value_text": '"other"'}],
        revision=live.revision,
        descriptor_revision=pairs(service, principal)[1],
    )
    assert restart.application_state == "restart_required"


def test_batch_notifies_subscribers(service, principal):
    seen = []
    service.subscribe("demo", ["/tag_list"], seen.append, principal=principal)
    apply(service, principal, [{"op": "add", "path": "/tag_list/-", "value_text": '"x"'}])
    assert seen and seen[0].document == "demo"


def test_batch_requires_operations(service, principal):
    with pytest.raises(Exception):
        apply(service, principal, [])


def test_batch_on_a_separate_document(tmp_path, resolver, principal):
    from aiset.service import Service

    path = copy_config(tmp_path, DEMO_CONFIG)
    service = Service()
    service.register("demo", path, DEMO_DESCRIPTOR, resolver=resolver)
    result = service.apply_operations(
        "demo",
        [{"op": "add", "path": "/resources/-", "value_text": '{ id: "gpu1", kind: "cpu" }'}],
        expected_revision=pairs(service, principal)[0],
        expected_descriptor_revision=pairs(service, principal)[1],
        principal=principal,
    )
    assert result.stored
    assert '"gpu1"' in read(path)


# -- http parity -----------------------------------------------------------


def test_http_tree_and_operations(service, principal):
    from tests.test_http import Client
    from aiset.httpd import create_app

    client = Client(create_app(service))
    status, tree = client.get("/api/settings/tree", "document=demo&path=/tag_list&view=source")
    assert status == 200 and [node["path"] for node in tree["node"]["items"]] == [
        "/tag_list/0",
        "/tag_list/1",
    ]
    revision, descriptor_revision = pairs(service, principal)
    body = {
        "document": "demo",
        "operations": [{"op": "add", "path": "/tag_list/-", "value_text": '"third"'}],
        "expected_revision": revision,
        "expected_descriptor_revision": descriptor_revision,
    }
    status, validated = client.post("/api/settings/operations/validate", body)
    assert status == 200 and validated["valid"] is True and validated["dry_run"] is True
    status, applied = client.post("/api/settings/operations", body)
    assert status == 200 and applied["stored"] is True
    # tag_list is a reload-policy node in the demo descriptor.
    assert applied["application"]["state"] == "reload_required"


def test_http_operations_rejects_a_bad_batch(service, principal):
    from tests.test_http import Client
    from aiset.httpd import create_app

    client = Client(create_app(service))
    revision, descriptor_revision = pairs(service, principal)
    status, payload = client.post(
        "/api/settings/operations",
        {
            "document": "demo",
            "operations": [{"op": "set", "path": "/counters/fraction", "value_text": "9"}],
            "expected_revision": revision,
            "expected_descriptor_revision": descriptor_revision,
        },
    )
    assert status == 422 and payload["error"]["code"] == "VALIDATION_ERROR"


def test_http_operations_requires_a_list(service):
    from tests.test_http import Client
    from aiset.httpd import create_app

    client = Client(create_app(service))
    status, payload = client.post("/api/settings/operations", {"document": "demo", "operations": "nope"})
    assert status == 400 and payload["error"]["code"] == "BAD_REQUEST"

# -- union alternatives ----------------------------------------------------

UNION_DESCRIPTOR = """{
  descriptor_version: "1.0",
  project: "union-test",
  config_version: "1.0",
  root: { type: "object", children: {
    tool: { type: "union", description: "a worker id or its settings", children_options: [
      { type: "string", min_length: 1, description: "Worker id" },
      { type: "object", description: "Worker settings", children: {
        worker: { type: "string", description: "Worker id" },
        name: { type: "string", description: "Display name" },
        enabled: { type: "bool", description: "Enabled" },
      } },
      { type: "array", description: "A list of ports", children: { type: "int", minimum: 1 } },
    ] },
    secret_tool: { type: "union", children_options: [
      { type: "string" },
      { type: "object", children: { key: { type: "string", secret: true } } },
    ] },
  } },
}"""


def union_service(tmp_path: Path, config: str) -> Service:
    """A service whose document has a scalar/object/array union under /tool."""
    target = tmp_path / "union.json5"
    target.write_text(config, encoding="utf-8")
    svc = Service()
    svc.register("union", target, UNION_DESCRIPTOR, resolver=Resolver(overrides={}, dotenv={}, environ={}))
    return svc


def test_tree_expands_the_object_alternative_of_a_union(tmp_path):
    svc = union_service(tmp_path, '{ tool: { worker: "web_search" } }')
    node = svc.tree("union", "/tool", principal=Principal.demo())["node"]
    assert node["type"] == "union"
    assert node["matched_option"] == 1
    assert node["kind"] == "object"
    children = {child["path"]: child for child in node["children"]}
    assert set(children) == {"/tool/worker", "/tool/name", "/tool/enabled"}
    assert children["/tool/worker"]["value_text"] == '"web_search"'
    assert children["/tool/worker"]["exists"] is True
    assert children["/tool/name"]["exists"] is False
    assert children["/tool/name"]["type"] == "string"
    assert children["/tool/enabled"]["type"] == "bool"


def test_tree_expands_the_array_alternative_of_a_union(tmp_path):
    svc = union_service(tmp_path, "{ tool: [8080, 8081] }")
    node = svc.tree("union", "/tool", principal=Principal.demo())["node"]
    assert node["matched_option"] == 2
    assert node["kind"] == "array"
    assert [item["path"] for item in node["items"]] == ["/tool/0", "/tool/1"]
    assert [item["value_text"] for item in node["items"]] == ["8080", "8081"]
    assert node["items"][0]["kind"] == "array_item"
    assert node["items"][0]["capabilities"]["remove"] is True


def test_tree_does_not_expand_a_scalar_union(tmp_path):
    svc = union_service(tmp_path, '{ tool: "web_search" }')
    node = svc.tree("union", "/tool", principal=Principal.demo())["node"]
    assert node["matched_option"] == 0
    assert node["children"] == [] and node["items"] == []


def test_tree_denies_a_secret_inside_a_union_alternative(tmp_path):
    svc = union_service(tmp_path, '{ secret_tool: { key: "s3cret" } }')
    reader = Principal(id="reader", permissions=frozenset({"settings_read_source"}))
    node = svc.tree("union", "/secret_tool", principal=reader)["node"]
    assert node["access_denied"] is True
    assert node["value_text"] is None


def test_a_union_object_child_is_writable_by_its_path(tmp_path):
    svc = union_service(tmp_path, '{ tool: { worker: "web_search" } }')
    principal = Principal.demo()
    loaded = svc.load("union", principal=principal)
    svc.apply_operations(
        "union",
        [{"op": "set", "path": "/tool/worker", "value_text": '"web_fetch"'}],
        expected_revision=loaded.revision,
        expected_descriptor_revision=loaded.descriptor_revision,
        principal=principal,
    )
    text = (tmp_path / "union.json5").read_text(encoding="utf-8")
    assert 'worker: "web_fetch"' in text


def test_a_union_array_item_can_be_appended(tmp_path):
    svc = union_service(tmp_path, "{ tool: [8080] }")
    principal = Principal.demo()
    loaded = svc.load("union", principal=principal)
    svc.apply_operations(
        "union",
        [{"op": "add", "path": "/tool/-", "value_text": "8081"}],
        expected_revision=loaded.revision,
        expected_descriptor_revision=loaded.descriptor_revision,
        principal=principal,
    )
    text = (tmp_path / "union.json5").read_text(encoding="utf-8")
    assert "8081" in text


def test_a_batch_can_create_a_container_and_fill_it(tmp_path):
    """Operations run in order on one candidate; the base need not have the path."""
    svc = union_service(tmp_path, '{ tool: "web_search" }')
    principal = Principal.demo()
    loaded = svc.load("union", principal=principal)
    result = svc.apply_operations(
        "union",
        [
            {"op": "set", "path": "/tool", "value_text": "{}"},
            {"op": "set", "path": "/tool/worker", "value_text": '"web_fetch"'},
        ],
        expected_revision=loaded.revision,
        expected_descriptor_revision=loaded.descriptor_revision,
        principal=principal,
    )
    assert result.stored
    assert "/tool" in result.changed_paths and "/tool/worker" in result.changed_paths
    text = (tmp_path / "union.json5").read_text(encoding="utf-8")
    assert 'worker: "web_fetch"' in text
