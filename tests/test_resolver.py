"""Resolver policy and effective snapshots (SPEC.md section 6)."""

from __future__ import annotations

from aiset.descriptor import compile_descriptor, node_at
from aiset.jsonsrc import Document, TemplateRef
from aiset.resolver import MISSING, Resolver, build_effective, effective_at
from aiset.validator import validate_document

DESCRIPTOR = """
{
  descriptor_version: "1.0",
  root: {
    type: "object",
    children: {
      plain: { type: "string" },
      templated: { type: "string", env: { allowed: true, convert: "string" } },
      number: { type: "int", env: { allowed: true, convert: "int" } },
      real: { type: "number", env: { allowed: true, convert: "number" } },
      flag: { type: "bool", env: { allowed: true, convert: "bool" } },
      not_allowed: { type: "string" },
      with_default: { type: "string", default: "fallback" },
      nested: {
        type: "object",
        children: { inner: { type: "int", default: 7 } },
      },
    },
  },
}
"""


def resolve(config_text: str, **kwargs):
    descriptor = compile_descriptor(DESCRIPTOR, strict=True)
    document = Document(config_text)
    stored = document.stored_value(document.root)
    resolver = Resolver(
        overrides=kwargs.get("overrides", {}),
        dotenv=kwargs.get("dotenv", {}),
        environ=kwargs.get("environ", {}),
    )
    return build_effective(stored, descriptor.root, resolver)


def test_inline_default_is_used_when_unset():
    effective, issues = resolve('{ templated: "${MISSING:-fallback}" }')
    assert effective["templated"] == "fallback"
    assert not [issue for issue in issues if issue.severity == "error"]


def test_empty_value_falls_back_to_the_inline_default():
    effective, _ = resolve('{ templated: "${VAR:-fallback}" }', environ={"VAR": ""})
    assert effective["templated"] == "fallback"


def test_plain_placeholder_is_empty_when_unset():
    effective, _ = resolve('{ templated: "${MISSING}" }')
    assert effective["templated"] == ""


def test_process_environment_wins_over_dotenv():
    effective, _ = resolve('{ templated: "${VAR}" }', environ={"VAR": "from-env"}, dotenv={"VAR": "from-dotenv"})
    assert effective["templated"] == "from-env"


def test_dotenv_wins_over_inline_default():
    effective, _ = resolve('{ templated: "${VAR:-inline}" }', environ={}, dotenv={"VAR": "from-dotenv"})
    assert effective["templated"] == "from-dotenv"


def test_overrides_win_over_the_process_environment():
    effective, _ = resolve(
        '{ templated: "${VAR}" }', overrides={"VAR": "override"}, environ={"VAR": "from-env"}
    )
    assert effective["templated"] == "override"


def test_config_default_is_the_last_resort():
    """An absent field falls back to the config default, never to the environment."""
    effective, _ = resolve("{}")
    assert effective["with_default"] == "fallback"
    # A present value wins over the default, even when it resolves to empty.
    effective, _ = resolve('{ templated: "${UNSET}" }')
    assert effective["templated"] == ""


def test_defaults_do_not_create_absent_parents():
    effective, _ = resolve("{}")
    assert "nested" not in effective
    effective, _ = resolve("{ nested: {} }")
    assert effective["nested"]["inner"] == 7


def test_absent_optional_field_gets_the_config_default():
    effective, _ = resolve("{}")
    assert effective["with_default"] == "fallback"


def test_numeric_conversion():
    effective, issues = resolve('{ number: ${NUM} }', environ={"NUM": "42"})
    assert effective["number"] == 42 and isinstance(effective["number"], int)
    assert not [issue for issue in issues if issue.severity == "error"]


def test_numeric_conversion_rejects_non_numbers():
    _, issues = resolve('{ number: ${NUM} }', environ={"NUM": "abc"})
    assert any(issue.rule == "env_conversion" for issue in issues)


def test_numeric_conversion_rejects_out_of_range_values():
    _, issues = resolve('{ number: ${NUM} }', environ={"NUM": "9007199254740992"})
    assert any(issue.rule == "env_conversion" for issue in issues)


def test_boolean_conversion_accepts_only_true_and_false():
    effective, issues = resolve('{ flag: ${FLAG} }', environ={"FLAG": "true"})
    assert effective["flag"] is True
    _, issues = resolve('{ flag: ${FLAG} }', environ={"FLAG": "yes"})
    assert any(issue.rule == "env_conversion" for issue in issues)


def test_number_conversion():
    effective, issues = resolve('{ real: ${REAL} }', environ={"REAL": "1.5"})
    assert effective["real"] == 1.5
    _, issues = resolve('{ real: ${REAL} }', environ={"REAL": "inf"})
    assert any(issue.rule == "env_conversion" for issue in issues)


def test_unquoted_placeholder_requires_env_allowed():
    _, issues = resolve('{ not_allowed: ${VAR} }', environ={"VAR": "x"})
    assert any(issue.rule == "env_not_allowed" for issue in issues)


def test_disabled_placeholder_inside_a_string_stays_literal():
    effective, issues = resolve('{ not_allowed: "${VAR}" }', environ={"VAR": "x"})
    assert effective["not_allowed"] == "${VAR}"
    assert not [issue for issue in issues if issue.severity == "error"]


def test_environment_cannot_inject_structure():
    document = Document('{ templated: "${VAR}" }')
    stored = document.stored_value(document.root)
    assert isinstance(stored["templated"], str)
    effective, _ = build_effective(
        stored, compile_descriptor(DESCRIPTOR, strict=True).root,
        Resolver(overrides={"VAR": '{"injected": true}'}, dotenv={}, environ={}),
    )
    assert effective["templated"] == '{"injected": true}'
    assert "injected" not in effective


def test_substitution_is_single_pass():
    effective, _ = resolve('{ templated: "${VAR}" }', overrides={"VAR": "${OTHER}"}, dotenv={}, environ={})
    assert effective["templated"] == "${OTHER}"


def test_provenance_reports_the_variable_name_only():
    descriptor = compile_descriptor(DESCRIPTOR, strict=True)
    document = Document('{ templated: "${SECRET_NAME:-x}", with_default: "y" }')
    stored = document.stored_value(document.root)
    provenance: dict = {}
    build_effective(stored, descriptor.root, Resolver(environ={}, dotenv={}, overrides={}), provenance=provenance)
    assert provenance["/templated"] == {"kind": "environment", "variable": "SECRET_NAME", "source": "inline_default"}
    assert "/with_default" in provenance


def test_effective_at_returns_default_for_absent_leaves():
    descriptor = compile_descriptor(DESCRIPTOR, strict=True)
    value, issues = effective_at(MISSING, node_at(descriptor, "/with_default"), Resolver(environ={}), "/x")
    assert value == "fallback" and not issues


def test_effective_snapshot_passes_validation():
    effective, issues = resolve('{ number: 1, nested: { inner: 2 } }', environ={})
    assert not validate_document(effective, compile_descriptor(DESCRIPTOR, strict=True).root)


def test_template_reference_is_kept_in_the_stored_tree():
    document = Document("{ number: ${NUM} }")
    stored = document.stored_value(document.root)
    assert stored["number"] == TemplateRef("NUM", None)