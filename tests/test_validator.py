"""Value validation rules (SPEC.md sections 4.2, 4.6.7, 11)."""

from __future__ import annotations

import pytest

from aiset.descriptor import compile_descriptor
from aiset.validator import (
    MAX_EXACT_INT,
    Limits,
    ValidationContext,
    check_limits,
    validate_document,
    validate_value,
)

DESCRIPTOR = """
{
  descriptor_version: "1.0",
  root: { type: "object", children: {
    text: { type: "string", min_length: 2, max_length: 8, pattern: "^[a-z]+$" },
    count: { type: "int", minimum: 1, maximum: 10 },
    ratio: { type: "number", minimum: 0, maximum: 1 },
    flag: { type: "bool" },
    exact: { type: "int" },
    version: { type: "string", const: "1.0" },
    level: { type: "string", enum: ["a", "b"] },
    items: { type: "array", children: { type: "int" }, min_items: 1, max_items: 3, unique_items: true },
    uniq: { type: "array", children: { type: "string" }, unique_items: true },
    mixed: { type: "array", children_options: [ { type: "string" }, { type: "int" } ] },
    either: { type: "union", children_options: [ { type: "int", maximum: 7 }, { type: "string" } ] },
    required_child: { type: "object", children: { a: { type: "int", required: true }, b: { type: "int" } } },
    optional_child: { type: "object", nullable: true, children: { a: { type: "int" } } },
    dynamic: { type: "object", additional_children: { type: "int" }, key_pattern: "^[a-z]+$" },
    listed: { type: "object", additional_children: { type: "int" }, key_enum: ["ok"] },
    nulls: { type: "null" },
    closed: { type: "object", children: { a: { type: "int" } } },
  } },
}
"""


@pytest.fixture(scope="module")
def descriptor():
    return compile_descriptor(DESCRIPTOR, strict=True)


def check(descriptor, path, value, limits=None):
    node = _node(descriptor, path)
    context = ValidationContext(limits=limits or Limits())
    return validate_value(value, node, path, context)


def _node(descriptor, path):
    from aiset.descriptor import node_at

    return node_at(descriptor, path)


def rules(issues):
    return {issue.rule for issue in issues}


def test_bool_is_not_int(descriptor):
    assert rules(check(descriptor, "/count", True)) == {"type"}
    assert check(descriptor, "/count", 5) == []


def test_int_rejects_fractions(descriptor):
    assert rules(check(descriptor, "/count", 1.5)) == {"type"}


def test_number_accepts_int_and_float(descriptor):
    assert check(descriptor, "/ratio", 1) == []
    assert check(descriptor, "/ratio", 0.5) == []


def test_non_finite_values_are_rejected(descriptor):
    assert rules(check(descriptor, "/ratio", float("nan"))) == {"type"}
    assert rules(check(descriptor, "/ratio", float("inf"))) == {"type"}


def test_numeric_bounds(descriptor):
    assert "minimum" in rules(check(descriptor, "/count", 0))
    assert "maximum" in rules(check(descriptor, "/count", 11))
    assert "minimum" in rules(check(descriptor, "/ratio", -0.1))


def test_exact_integer_range(descriptor):
    assert check(descriptor, "/exact", MAX_EXACT_INT) == []
    assert "exact_range" in rules(check(descriptor, "/exact", MAX_EXACT_INT + 2))


def test_string_constraints(descriptor):
    assert "min_length" in rules(check(descriptor, "/text", "a"))
    assert "max_length" in rules(check(descriptor, "/text", "abcdefghi"))
    assert "pattern" in rules(check(descriptor, "/text", "AB"))
    assert check(descriptor, "/text", "abc") == []


def test_string_length_counts_code_points(descriptor):
    assert check(descriptor, "/text", "абвгд") != []
    assert "max_length" not in rules(check(descriptor, "/text", "абвгд"))


def test_enum_and_const_ignore_no_implicit_conversion(descriptor):
    assert check(descriptor, "/level", "a") == []
    assert "enum" in rules(check(descriptor, "/level", "c"))
    assert "type" in rules(check(descriptor, "/level", 1))
    assert check(descriptor, "/version", "1.0") == []
    assert "const" in rules(check(descriptor, "/version", "2.0"))


def test_array_constraints(descriptor):
    assert "min_items" in rules(check(descriptor, "/items", []))
    assert "max_items" in rules(check(descriptor, "/items", [1, 2, 3, 4]))
    assert "unique_items" in rules(check(descriptor, "/items", [1, 1]))
    assert check(descriptor, "/uniq", ["a", "b"]) == []
    assert "unique_items" in rules(check(descriptor, "/uniq", ["a", "a"]))


def test_array_items_are_validated(descriptor):
    assert rules(check(descriptor, "/items", ["x"])) == {"type"}


def test_children_options_accept_alternatives(descriptor):
    assert check(descriptor, "/mixed", ["a", 1, "b"]) == []
    assert "union" in rules(check(descriptor, "/mixed", [1.5]))


def test_union_matches_any_alternative(descriptor):
    assert check(descriptor, "/either", 3) == []
    assert check(descriptor, "/either", "text") == []
    assert "union" in rules(check(descriptor, "/either", 99))


def test_required_child_is_reported(descriptor):
    issues = check(descriptor, "/required_child", {})
    assert any(issue.rule == "required" for issue in issues)


def test_missing_and_null_are_different(descriptor):
    assert check(descriptor, "/optional_child", None) == []
    issues = check(descriptor, "/optional_child", {})
    assert issues == []  # an absent optional object is fine


def test_non_nullable_field_rejects_null(descriptor):
    assert "nullable" in rules(check(descriptor, "/text", None))


def test_undeclared_field_is_rejected(descriptor):
    assert "undeclared_field" in rules(check(descriptor, "/closed", {"a": 1, "b": 2}))
    assert check(descriptor, "/closed", {"a": 1}) == []


def test_dynamic_key_constraints(descriptor):
    assert check(descriptor, "/dynamic", {"abc": 1}) == []
    assert "key_pattern" in rules(check(descriptor, "/dynamic", {"Abc": 1}))
    assert check(descriptor, "/listed", {"ok": 1}) == []
    assert "key_enum" in rules(check(descriptor, "/listed", {"no": 1}))
    assert "type" in rules(check(descriptor, "/dynamic", {"abc": "x"}))


def test_null_type(descriptor):
    assert check(descriptor, "/nulls", None) == []
    assert "type" in rules(check(descriptor, "/nulls", 1))


def test_check_limits_depth():
    limits = Limits(max_depth=2)
    deep = {"a": {"b": {"c": {"d": 1}}}}
    assert [issue.rule for issue in check_limits(deep, limits)] == ["max_depth"]


def test_check_limits_collection_size():
    limits = Limits(max_collection_size=2)
    assert [issue.rule for issue in check_limits([1, 2, 3], limits)] == ["max_collection_size"]


def test_check_limits_string_length():
    limits = Limits(max_string_length=3)
    assert [issue.rule for issue in check_limits({"k": "abcd"}, limits)] == ["max_string_length"]


def test_validate_document_reports_paths(descriptor):
    issues = validate_document({"count": 99}, descriptor.root)
    assert issues[0].path == "/count"
    assert issues[0].rule == "maximum"


def test_portable_pattern_subset_is_enforced(descriptor):
    source = DESCRIPTOR.replace("pattern: \"^[a-z]+$\"", "pattern: \"(?=x)[a-z]+\"")
    other = compile_descriptor(source, strict=True)
    assert "pattern" in rules(check(other, "/text", "abc"))