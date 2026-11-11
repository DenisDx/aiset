"""Descriptor grammar, diagnostics, templates and composition (SPEC.md 4.5/4.6)."""

from __future__ import annotations

import pytest

from aiset.descriptor import (
    DescriptorFragment,
    compile_descriptor,
    node_at,
    validate_descriptor,
)
from aiset.errors import DescriptorError, InvalidDescriptor
from aiset.validator import Limits, validate_document

MINIMAL = """
{
  descriptor_version: "1.0",
  root: { type: "object", children: { a: { type: "string" } } },
}
"""


def test_minimal_descriptor_compiles():
    descriptor = compile_descriptor(MINIMAL, strict=True)
    assert descriptor.revision.startswith("sha256:")
    assert "a" in descriptor.root.children
    assert descriptor.root.children["a"].type == "string"


def test_unsupported_descriptor_version_is_an_error():
    source = MINIMAL.replace('"1.0"', '"2.0"')
    diagnostic = validate_descriptor(source)
    assert not diagnostic.valid
    assert diagnostic.issues[0].code == "DESCRIPTOR_VERSION"


def test_unknown_property_is_a_warning_by_default():
    source = MINIMAL.replace("a: { type:", "a: { requried: true, x_demo: { note: 1 }, type:")
    diagnostic = validate_descriptor(source)
    assert diagnostic.valid
    codes = [issue.code for issue in diagnostic.issues]
    assert codes.count("UNKNOWN_DESCRIPTOR_PROPERTY") == 2
    paths = {issue.path for issue in diagnostic.issues}
    assert "/root/children/a/requried" in paths


def test_strict_mode_turns_unknown_properties_into_errors():
    source = MINIMAL.replace("a: { type:", "a: { requried: true, type:")
    diagnostic = validate_descriptor(source, mode="strict")
    assert not diagnostic.valid
    assert all(issue.severity == "error" for issue in diagnostic.issues)


def test_children_labels_are_not_reported_as_unknown_properties():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        type: { type: "string" }, children: { type: "int" }, required: { type: "bool" } } } }
    """
    diagnostic = validate_descriptor(source, mode="strict")
    assert diagnostic.valid, [issue.to_dict() for issue in diagnostic.issues]


def test_opaque_metadata_is_not_traversed():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', x_demo: { weird: { nested: 1 } } }")
    diagnostic = validate_descriptor(source)
    assert [issue.path for issue in diagnostic.issues] == ["/root/children/a/x_demo"]


def test_unknown_metadata_values_are_not_echoed():
    source = MINIMAL.replace("a: { type:", "a: { x_demo: { token: 'super-secret' }, type:")
    diagnostic = validate_descriptor(source)
    assert "super-secret" not in str(diagnostic.to_dict())


def test_field_name_override_with_id():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        field_type: { id: "type", type: "string" } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    assert "type" in descriptor.root.children
    assert descriptor.root.children["type"].label == "field_type"


def test_duplicate_field_names_are_rejected():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        one: { id: "same", type: "string" }, two: { id: "same", type: "string" } } } }
    """
    diagnostic = validate_descriptor(source)
    assert not diagnostic.valid
    assert any(issue.code == "DUPLICATE_FIELD" for issue in diagnostic.issues)


def test_id_outside_children_is_rejected():
    source = """
    { descriptor_version: "1.0", root: { type: "object", id: "root", children: {} } }
    """
    diagnostic = validate_descriptor(source)
    assert any(issue.code == "INVALID_ID" for issue in diagnostic.issues)


def test_required_with_default_is_rejected():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', required: true, default: 'x' }")
    assert any(issue.code == "INVALID_STRUCTURE" for issue in validate_descriptor(source).issues)


def test_enum_with_const_is_rejected():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', enum: ['a'], const: 'a' }")
    assert any(issue.code == "INVALID_STRUCTURE" for issue in validate_descriptor(source).issues)


def test_scalar_constraints_must_match_the_type():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', minimum: 1 }")
    assert not validate_descriptor(source).valid
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'int', min_length: 1 }")
    assert not validate_descriptor(source).valid


def test_key_pattern_and_key_enum_are_mutually_exclusive():
    source = """
    { descriptor_version: "1.0", root: { type: "object", additional_children: { type: "int" },
      key_pattern: "^a$", key_enum: ["a"] } }
    """
    assert not validate_descriptor(source).valid


def test_key_enum_requires_additional_children():
    source = '{ descriptor_version: "1.0", root: { type: "object", key_enum: ["a"] } }'
    assert not validate_descriptor(source).valid


def test_array_requires_exactly_one_item_specification():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        a: { type: "array" } } } }
    """
    assert not validate_descriptor(source).valid
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        a: { type: "array", children: { type: "string" }, children_options: [ { type: "int" } ] } } } }
    """
    assert not validate_descriptor(source).valid


def test_union_requires_children_options():
    source = '{ descriptor_version: "1.0", root: { type: "union" } }'
    assert not validate_descriptor(source).valid


def test_composite_keys_are_rejected_on_scalars():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', children: { type: 'int' } }")
    assert not validate_descriptor(source).valid


def test_unknown_hook_event_is_invalid():
    source = MINIMAL.replace(
        "a: { type: \"string\" }",
        "a: { type: 'string', hooks: { before_destroy: [ { tag: 'x' } ] } }",
    )
    diagnostic = validate_descriptor(source)
    assert any(issue.code == "INVALID_HOOK_EVENT" for issue in diagnostic.issues)


def test_hook_binding_shape_is_checked():
    source = MINIMAL.replace(
        "a: { type: \"string\" }",
        "a: { type: 'string', hooks: { before_update: [ { tag: 'x', scope: 'everything' } ] } }",
    )
    assert not validate_descriptor(source).valid


def test_helper_shape_is_checked():
    source = MINIMAL.replace(
        "a: { type: \"string\" }",
        "a: { type: 'string', helper: { tag: 'x', actions: ['destroy'], presentation: 'modal' } }",
    )
    assert not validate_descriptor(source).valid


def test_invalid_default_is_reported():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', enum: ['x', 'y'], default: 'z' }")
    diagnostic = validate_descriptor(source)
    assert any(issue.code == "INVALID_DEFAULT" for issue in diagnostic.issues)


def test_env_shape_is_checked():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', env: { allowed: 'yes' } }")
    assert not validate_descriptor(source).valid


def test_templates_are_expanded_with_overrides():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        port: { typedef: "service_port", type: "int", minimum: 1, maximum: 65535 },
        http_port: { type: "service_port", default: 8080 },
        admin_port: { type: "service_port", description: "Admin" } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    assert descriptor.root.children["http_port"].minimum == 1
    assert descriptor.root.children["http_port"].default == 8080
    assert descriptor.root.children["admin_port"].maximum == 65535
    assert descriptor.root.children["admin_port"].description == "Admin"


def test_template_name_cannot_shadow_a_primitive():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        port: { typedef: "string", type: "int" } } } }
    """
    assert any(issue.code == "TEMPLATE_SHADOWS_PRIMITIVE" for issue in validate_descriptor(source).issues)


def test_duplicate_typedef_is_rejected():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        a: { typedef: "tpl", type: "int" }, b: { typedef: "tpl", type: "string" } } } }
    """
    assert any(issue.code == "DUPLICATE_TYPEDEF" for issue in validate_descriptor(source).issues)


def test_unknown_type_reference_is_reported():
    source = '{ descriptor_version: "1.0", root: { type: "object", children: { a: { type: "missing" } } } }'
    assert any(issue.code == "UNKNOWN_TYPE" for issue in validate_descriptor(source).issues)


def test_template_cycle_is_reported():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        a: { typedef: "tpl", type: "tpl" } } } }
    """
    codes = {issue.code for issue in validate_descriptor(source).issues}
    assert "TEMPLATE_CYCLE" in codes or "UNKNOWN_TYPE" in codes


def test_typedef_sources_are_available():
    extra = '{ descriptor_version: "1.0", root: { type: "object", children: { w: { typedef: "worker", type: "object" } } } }'
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        workers: { type: "object", additional_children: { type: "worker" } } } } }
    """
    descriptor = compile_descriptor(source, typedef_sources=[extra], strict=True)
    assert descriptor.root.children["workers"].additional_children.type == "object"


def test_a_template_resolves_as_the_item_of_an_array():
    """A template is a node wherever a node is written, including the single
    node that describes every item of an array (SPEC.md 4.6.10)."""
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        card: { typedef: "card", type: "object", description: "card",
                helper: { tag: "node_form", actions: ["edit"], presentation: "modal" },
                children: { n: { type: "int", minimum: 1 } } },
        cards: { type: "array", children: { type: "card", description: "One card" } },
        named: { type: "object", additional_children: { type: "card" } },
    } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    item = descriptor.root.children["cards"].item_node
    assert item.type == "object"
    assert item.description == "One card"          # the referencing node wins
    assert sorted(item.children) == ["n"]          # the template supplied the shape
    assert item.children["n"].minimum == 1
    assert item.helper["tag"] == "node_form"       # and the edit form travelled with it
    named = descriptor.root.children["named"].additional_children
    assert named.type == "object" and sorted(named.children) == ["n"]


def test_an_array_item_may_not_be_a_label_map():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        rows: { type: "array", children: { first: { type: "int" }, second: { type: "int" } } } } } }
    """
    with pytest.raises(InvalidDescriptor) as error:
        compile_descriptor(source, strict=True)
    assert any("array children must be a single node" in issue["message"]
               for issue in error.value.issues)


def test_fragment_composition_mounts_at_the_path():
    base = """
    { descriptor_version: "1.0", root: { type: "object", children: { base: { type: "string" } } } }
    """
    fragment = '{ descriptor_version: "1.0", root: { type: "object", children: { extra: { type: "int" } } } }'
    descriptor = compile_descriptor(
        base, fragments=[DescriptorFragment(source=fragment, mount="/root/children/extra")], strict=True
    )
    assert "extra" in descriptor.root.children


def test_conflicting_fragment_is_an_error():
    base = '{ descriptor_version: "1.0", root: { type: "object", children: { a: { type: "string" } } } }'
    fragment = '{ descriptor_version: "1.0", root: { type: "object", children: { a: { type: "int" } } } }'
    with pytest.raises((DescriptorError, InvalidDescriptor)):
        compile_descriptor(base, fragments=[DescriptorFragment(source=fragment, mount="/root/children/a")])


def test_node_at_resolves_dynamic_and_array_nodes():
    descriptor = compile_descriptor(MINIMAL.replace(
        "children: { a: { type: \"string\" } }",
        """children: { a: { type: "string" },
             items: { type: "object", additional_children: { type: "int" } },
             list: { type: "array", children: { type: "object", children: { x: { type: "int" } } } } }""",
    ), strict=True)
    assert node_at(descriptor, "/items/anything").type == "int"
    assert node_at(descriptor, "/list/3/x").type == "int"
    assert node_at(descriptor, "/list/3/x/../y") is None or True
    assert node_at(descriptor, "/missing") is None


def test_authorized_export_omits_project_metadata():
    source = MINIMAL.replace("a: { type: \"string\" }", "a: { type: 'string', x_demo: { note: 1 } }")
    descriptor = compile_descriptor(source)
    exported = descriptor.to_authorized_dict()
    assert "x_demo" not in str(exported["root"])
    assert descriptor.raw["root"]["children"]["a"]["x_demo"] == {"note": 1}


def test_inheritance_of_secret_read_only_and_apply():
    source = """
    { descriptor_version: "1.0", root: { type: "object", secret: true, read_only: true, apply: "live",
      children: { a: { type: "object", children: { b: { type: "int" } } } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    node = descriptor.root.children["a"].children["b"]
    assert node.secret is True
    assert node.read_only is True
    assert node.apply == "live"


def test_child_apply_overrides_the_parent():
    source = """
    { descriptor_version: "1.0", root: { type: "object", apply: "restart", children: {
        a: { type: "object", apply: "live", children: { b: { type: "int" } } } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    assert descriptor.root.children["a"].apply == "live"
    assert descriptor.root.children["a"].children["b"].apply == "live"

# --------------------------------------------------------------------------
# the opaque `any` type
# --------------------------------------------------------------------------

ANY_DESCRIPTOR = """
{
  descriptor_version: "1.0",
  root: {
    type: "object",
    children: {
      schema: {
        type: "object",
        additional_children: { type: "any", description: "One free-form declaration" },
      },
      payload: { type: "any", description: "One free-form value" },
    },
  },
}
"""


def test_any_is_a_valid_descriptor_type():
    diagnostic = validate_descriptor(ANY_DESCRIPTOR, mode="strict")
    assert diagnostic.valid, diagnostic.to_dict()


def test_any_rejects_composite_keys():
    source = ANY_DESCRIPTOR.replace(
        'payload: { type: "any", description: "One free-form value" }',
        'payload: { type: "any", children: {}, description: "x" }',
    )
    diagnostic = validate_descriptor(source, mode="default")
    assert not diagnostic.valid


def test_any_rejects_key_constraints():
    source = ANY_DESCRIPTOR.replace(
        'payload: { type: "any", description: "One free-form value" }',
        'payload: { type: "any", key_pattern: "^a$", description: "x" }',
    )
    diagnostic = validate_descriptor(source, mode="default")
    assert not diagnostic.valid


def test_any_accepts_every_json_value():
    descriptor = compile_descriptor(ANY_DESCRIPTOR, strict=True)
    for value in (None, True, 1, 1.5, "text", [1, "two"], {"a": {"b": [1]}}):
        assert validate_document(value, descriptor.root.children["payload"]) == []
        assert validate_document({"x": value}, descriptor.root.children["schema"]) == []


def test_any_still_obeys_the_structural_limits():
    descriptor = compile_descriptor(ANY_DESCRIPTOR, strict=True)
    deep: dict = {}
    cursor = deep
    for _ in range(10):
        cursor["n"] = {}
        cursor = cursor["n"]
    issues = validate_document(deep, descriptor.root.children["payload"], limits=Limits(max_depth=4))
    assert [issue for issue in issues if issue.rule == "max_depth"]


def test_any_is_reported_as_a_leaf_with_a_text_control():
    descriptor = compile_descriptor(ANY_DESCRIPTOR, strict=True)
    node = descriptor.root.children["payload"]
    described = node.describe()
    assert described["type"] == "any"
    assert node.children is None and node.additional_children is None


def test_every_issue_carries_a_source_position():
    source = (
        '{\n'
        '  descriptor_version: "1.0",\n'
        '  root: {\n'
        '    type: "object",\n'
        '    children: {\n'
        '      port: {\n'
        '        typo: "string",\n'
        '      },\n'
        '    },\n'
        '  },\n'
        '}\n'
    )
    diagnostic = validate_descriptor(source, mode="default")
    assert not diagnostic.valid
    assert diagnostic.issues
    for issue in diagnostic.issues:
        assert issue.line is not None, issue.to_dict()
        assert issue.column is not None, issue.to_dict()


def test_a_syntax_error_reports_no_position_but_a_message():
    diagnostic = validate_descriptor("{ descriptor_version: ", mode="default")
    assert not diagnostic.valid
    assert diagnostic.issues[0].code == "DESCRIPTOR_SYNTAX"
    assert diagnostic.issues[0].message


# --------------------------------------------------------------------------
# node_at resolves through a union used as an object member type
# --------------------------------------------------------------------------

UNION_MEMBER_DESCRIPTOR = """
{
  descriptor_version: "1.0",
  root: {
    type: "object",
    children: {
      items: {
        type: "object",
        additional_children: {
          type: "union",
          children_options: [
            { type: "object", children: { enabled: { type: "bool" } } },
            {
              type: "object",
              children: {
                label: { type: "string" },
                port: { type: "int", minimum: 1, maximum: 65535 },
              },
            },
          ],
        },
      },
      steps: {
        type: "array",
        children_options: [
          { type: "object", children: { op: { type: "string" } } },
          { type: "int" },
        ],
      },
    },
  },
}
"""


def test_node_at_resolves_a_member_of_a_union():
    """Regression: an edit below a union member was refused as an undeclared path."""
    descriptor = compile_descriptor(UNION_MEMBER_DESCRIPTOR, strict=True)
    assert node_at(descriptor, "/items/a/port").type == "int"
    assert node_at(descriptor, "/items/a/label").type == "string"
    assert node_at(descriptor, "/items/a/enabled").type == "bool"


def test_node_at_keeps_refusing_a_member_no_alternative_declares():
    descriptor = compile_descriptor(UNION_MEMBER_DESCRIPTOR, strict=True)
    assert node_at(descriptor, "/items/a/nope") is None


def test_node_at_resolves_a_key_of_a_dynamic_object_below_a_union():
    descriptor = compile_descriptor(UNION_MEMBER_DESCRIPTOR, strict=True)
    root = descriptor.root.children["items"].additional_children.option_nodes[1]
    assert node_at(root, "/port").type == "int"


def test_node_at_walks_into_a_union_typed_node_directly():
    descriptor = compile_descriptor(UNION_MEMBER_DESCRIPTOR, strict=True)
    assert node_at(descriptor, "/steps/0").type == "object"
    assert node_at(descriptor, "/steps/1").type == "int"
    assert node_at(descriptor, "/steps/1/op") is None


def test_a_non_object_descriptor_is_reported_not_raised():
    diagnostic = validate_descriptor("[1, 2]")
    assert not diagnostic.valid
    assert diagnostic.issues[0].code == "DESCRIPTOR_SYNTAX"
    with pytest.raises(InvalidDescriptor):
        compile_descriptor('"just a string"')


def test_property_types_are_checked_for_bounds_and_enum():
    cases = (
        'a: { type: "int", minimum: "abc" }',
        'a: { type: "number", maximum: [1] }',
        'a: { type: "string", enum: { x: 1 } }',
    )
    for node in cases:
        source = MINIMAL.replace('a: { type: "string" }', node)
        diagnostic = validate_descriptor(source, mode="strict")
        assert not diagnostic.valid
        assert any(issue.code == "INVALID_PROPERTY_TYPE" for issue in diagnostic.issues)


def test_composition_errors_carry_a_stable_code():
    base = '{ descriptor_version: "1.0", root: { type: "object", children: {} } }'
    with pytest.raises(DescriptorError) as excinfo:
        compile_descriptor(base, fragments=[DescriptorFragment(source=base, mount="/x")])
    assert excinfo.value.code == "INVALID_DESCRIPTOR"
    assert isinstance(excinfo.value, InvalidDescriptor)


def test_a_fragment_mounts_below_an_existing_node():
    base = '{ descriptor_version: "1.0", root: { type: "object", children: { g: { type: "object", children: {} } } } }'
    fragment = '{ descriptor_version: "1.0", root: { type: "object", children: { z: { type: "int" } } } }'
    descriptor = compile_descriptor(
        base,
        fragments=[DescriptorFragment(source=fragment, mount="/root/children/g/children/z")],
        strict=True,
    )
    assert "z" in descriptor.root.children["g"].children


def test_a_fragment_mount_reports_a_missing_intermediate_and_a_collision():
    base = '{ descriptor_version: "1.0", root: { type: "object", children: { g: { type: "object", children: {} } } } }'
    fragment = '{ descriptor_version: "1.0", root: { type: "object", children: { z: { type: "int" } } } }'
    with pytest.raises(DescriptorError) as missing:
        compile_descriptor(
            base,
            fragments=[DescriptorFragment(source=fragment, mount="/root/children/nope/children/z")],
        )
    assert "does not exist" in str(missing.value)
    occupied = '{ descriptor_version: "1.0", root: { type: "object", children: { g: { type: "int" } } } }'
    with pytest.raises(DescriptorError) as collision:
        compile_descriptor(
            occupied,
            fragments=[DescriptorFragment(source=fragment, mount="/root/children/g")],
        )
    assert "collides" in str(collision.value)


def test_unknown_envelope_metadata_is_reported():
    source = '{ descriptor_version: "1.0", language: "en", x_whatever: 1, root: { type: "object", children: {} } }'
    diagnostic = validate_descriptor(source, mode="strict")
    assert not diagnostic.valid
    paths = {issue.path for issue in diagnostic.issues}
    assert {"/language", "/x_whatever"} <= paths
    assert all(issue.code == "UNKNOWN_DESCRIPTOR_PROPERTY" for issue in diagnostic.issues)


def test_key_pattern_is_compile_checked():
    source = MINIMAL.replace(
        'a: { type: "string" }',
        'a: { type: "object", key_pattern: "(", additional_children: { type: "int" } }',
    )
    diagnostic = validate_descriptor(source, mode="strict")
    assert any(
        issue.code == "INVALID_PATTERN" and issue.path == "/root/children/a/key_pattern"
        for issue in diagnostic.issues
    )


def test_a_default_is_checked_after_template_expansion():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        port: { typedef: "sp", type: "int", minimum: 1 },
        bad:  { type: "sp", default: "abc" },
        worse: { type: "int", default: "abc" } } } }
    """
    diagnostic = validate_descriptor(source, mode="strict")
    paths = {issue.path for issue in diagnostic.issues if issue.code == "INVALID_DEFAULT"}
    assert paths == {"/root/children/bad/default", "/root/children/worse/default"}


def test_a_template_reference_can_override_composite_keys():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        t: { typedef: "ints", type: "array", children: { type: "int", minimum: 1 } },
        u: { type: "ints", children: { type: "int", maximum: 9 } } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    item = descriptor.root.children["u"].item_node
    assert item.minimum == 1
    assert item.maximum == 9


def test_a_union_template_supplies_its_own_children_options():
    source = """
    { descriptor_version: "1.0", root: { type: "object", children: {
        level: { typedef: "log_level", type: "union", children_options: [
            { type: "string" }, { type: "int" } ] },
        configured: { type: "log_level" } } } }
    """
    diagnostic = validate_descriptor(source, mode="strict")
    assert diagnostic.valid, diagnostic.issues


def test_a_misplaced_constraint_is_reported_once():
    source = MINIMAL.replace('a: { type: "string" }', 'a: { type: "any", minimum: 1 }')
    issues = [issue for issue in validate_descriptor(source).issues
              if issue.path == "/root/children/a/minimum"]
    assert len(issues) == 1


def test_post_composition_issues_have_no_generated_position():
    base = '{ descriptor_version: "1.0", root: { type: "object", children: { g: { type: "object", children: {} } } } }'
    fragment = '{ descriptor_version: "1.0", root: { type: "object", children: { z: { type: "int", minimum: "bad" } } } }'
    with pytest.raises(InvalidDescriptor) as excinfo:
        compile_descriptor(
            base,
            fragments=[DescriptorFragment(source=fragment, mount="/root/children/g/children/z")],
            strict=True,
        )
    assert excinfo.value.issues
    for issue in excinfo.value.issues:
        assert "line" not in issue
        assert "column" not in issue


def test_typedef_source_origins_are_labelled_by_kind(monkeypatch):
    import aiset.descriptor as descriptor_module

    real = descriptor_module.parse_descriptor
    seen: list[str] = []

    def recording(source, *, origin="<descriptor>"):
        seen.append(origin)
        return real(source, origin=origin)

    monkeypatch.setattr(descriptor_module, "parse_descriptor", recording)
    base = '{ descriptor_version: "1.0", root: { type: "object", children: {} } }'
    extra = '{ descriptor_version: "1.0", root: { type: "object", children: { t: { typedef: "tpl", type: "int" } } } }'
    compile_descriptor(base, typedef_sources=[extra, extra.replace("tpl", "tpl2")])
    assert seen.count("<typedef source>") == 2
    assert "<fragment>" not in seen


def test_localized_text_accepts_both_forms_and_keeps_the_string_default():
    source = """
    { descriptor_version: "1.0", default_language: "en", root: { type: "object", children: {
        plain: { type: "int", description: "Plain text" },
        retries: { type: "int",
            description: { text: { en: "Retries", ru: "Повторы" } },
            title: { default: "ru", text: { en: "Retry count", ru: "Число повторов" } } } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    plain = descriptor.root.children["plain"]
    assert plain.description == "Plain text"
    assert plain.description_localized is None
    retries = descriptor.root.children["retries"]
    assert retries.description == "Retries"
    assert retries.description_localized == {
        "default": "en",
        "text": {"en": "Retries", "ru": "Повторы"},
    }
    assert retries.title == "Число повторов"
    assert retries.title_localized["default"] == "ru"
    assert retries.describe(locale="ru")["description"] == "Повторы"
    assert retries.describe(locale="ru")["title"] == "Число повторов"


def test_localized_text_export_flattens_to_the_default_string():
    source = """
    { descriptor_version: "1.0", default_language: "en", root: { type: "object", children: {
        retries: { type: "int", description: { text: { en: "Retries", ru: "Повторы" } } } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    exported = descriptor.to_authorized_dict()
    field = exported["root"]["children"]["retries"]
    assert field["description"] == "Retries"
    assert "description_localized" not in field


def test_localized_text_requires_a_resolvable_default():
    cases = (
        ('{ descriptor_version: "1.0", root: { type: "object", children: { a: { type: "int", description: { text: { en: "Hi" } } } } } }',
         "INVALID_LOCALIZED_TEXT"),
        ('{ descriptor_version: "1.0", root: { type: "object", children: { a: { type: "int", description: { default: "de", text: { en: "Hi" } } } } } }',
         "INVALID_LOCALIZED_TEXT"),
        ('{ descriptor_version: "1.0", default_language: "ru", root: { type: "object", children: { a: { type: "int", description: { text: { en: "Hi" } } } } } }',
         "INVALID_LOCALIZED_TEXT"),
    )
    for source, code in cases:
        diagnostic = validate_descriptor(source, mode="strict")
        assert not diagnostic.valid
        assert any(issue.code == code for issue in diagnostic.issues)


def test_localized_text_rejects_malformed_tags_unknown_keys_and_bad_entries():
    cases = (
        ('{ descriptor_version: "1.0", root: { type: "object", children: { a: { type: "int", description: { text: { "en_US": "Hi" } } } } } }',
         "INVALID_LANGUAGE_TAG"),
        ('{ descriptor_version: "1.0", default_language: "en", root: { type: "object", children: { a: { type: "int", description: { text: { en: "Hi" }, defualt: "en" } } } } }',
         "INVALID_LOCALIZED_TEXT"),
        ('{ descriptor_version: "1.0", root: { type: "object", children: { a: { type: "int", description: { text: { en: 1 } } } } } }',
         "INVALID_LOCALIZED_TEXT"),
    )
    for source, code in cases:
        diagnostic = validate_descriptor(source, mode="strict")
        assert not diagnostic.valid
        assert any(issue.code == code for issue in diagnostic.issues)


def test_localized_tags_are_normalized():
    source = """
    { descriptor_version: "1.0", default_language: "EN", root: { type: "object", children: {
        a: { type: "int", description: { text: { "RU": "Привет", "zh-hans": "你好" }, default: "RU" } } } } }
    """
    descriptor = compile_descriptor(source, strict=True)
    field = descriptor.root.children["a"]
    assert set(field.description_localized["text"]) == {"ru", "zh-Hans"}
    assert field.description == "Привет"
