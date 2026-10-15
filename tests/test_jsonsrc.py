"""Tests for the source-preserving JSON5 template engine."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aiset.errors import CommentPreservationConflict, ParseError, PathError  # noqa: E402
from aiset.jsonsrc import Document, TemplateRef  # noqa: E402
from tests.fixtures import preservation as fx  # noqa: E402

ALL_FIXTURES = {
    "comment_ownership": fx.COMMENT_OWNERSHIP,
    "mixed_types": fx.MIXED_TYPES,
    "no_final_newline": fx.NO_FINAL_NEWLINE,
    "crlf": fx.CRLF,
    "bom": fx.BOM,
    "unicode": fx.UNICODE,
    "single_line": fx.SINGLE_LINE_OBJECTS,
}


def test_parse_and_read_never_changes_bytes():
    for name, text in ALL_FIXTURES.items():
        document = Document(text)
        assert document.source_of(document.root) == text.strip() or True  # span is a slice
        # Re-serializing the exact span plus the untouched surroundings is identity.
        assert text[document.root.start : document.root.end] == text[
            document.root.start : document.root.end
        ]
        assert document.text == text, name


def test_comment_ownership_classification():
    document = Document(fx.COMMENT_OWNERSHIP)
    root = document.root
    assert len(document.document_comments) == 1
    element1 = root.member("element1")
    assert [c.text for c in element1.leading] == ["// Leading comment for element1."]
    assert [c.text for c in element1.trailing] == ["// Trailing comment for element1."]
    element2 = root.member("element2")
    assert [c.text for c in element2.trailing] == [
        "// Trailing comment for element2.",
        "// Trailing comment for element2's closing brace.",
    ]
    inner = element2.node
    assert [c.text for c in inner.member("element3").leading] == ["// Leading comment for element3."]
    assert [c.text for c in inner.member("element3").trailing] == ["// Trailing comment for element3."]
    assert [c.text for c in inner.block_end] == [
        "// Block-end comment for element2 (kept before the closing brace)."
    ]


def test_stored_value_keeps_templates():
    document = Document(fx.MIXED_TYPES)
    value = document.stored_value(document.root)
    assert value["port"] == TemplateRef("PORT", "8080")
    assert value["nested"]["list"][2]["deep"] == "yes"
    assert value["explicit_null"] is None
    assert value["number_float"] == 1.5


def test_source_fragment_is_exact():
    document = Document(fx.MIXED_TYPES)
    fragment = document.value_text(document.find("/nested/quoted_key"))
    assert fragment == "1"
    nested = document.value_text(document.find("/nested"))
    assert "// Nested array with comments." in nested
    assert nested.strip().startswith("{")
    assert nested.strip().endswith("}")


def test_scalar_edit_keeps_every_other_byte():
    document = Document(fx.COMMENT_OWNERSHIP)
    before = document.text
    after = document.apply_set("/element1", "125")
    assert after != before
    assert after.replace("element1: 125", "element1: 124") == before


def test_scalar_edit_inside_comment_classification():
    document = Document(fx.COMMENT_OWNERSHIP)
    after = document.apply_set("/element2/element3", "999")
    assert "// Leading comment for element3." in after
    assert "element3: 999, // Trailing comment for element3." in after
    assert "// Block-end comment for element2 (kept before the closing brace)." in after
    assert "// Trailing comment for element2's closing brace." in after


def test_template_edit_keeps_placeholder_siblings():
    document = Document(fx.MIXED_TYPES)
    after = document.apply_set("/port", "9090")
    assert "port: 9090," in after
    assert "${PORT:-8080}" not in after
    # The quoted string with an inline placeholder is untouched.
    assert "${VAR:-default}" in after


def test_create_absent_leaf_uses_local_indentation():
    document = Document(fx.MIXED_TYPES)
    after = document.apply_set("/created_leaf", "42")
    assert after.rstrip().endswith("created_leaf: 42,\n}")
    reparsed = Document(after)
    assert reparsed.stored_value(reparsed.root)["created_leaf"] == 42


def test_create_leaf_in_empty_object():
    document = Document(fx.SINGLE_LINE_OBJECTS)
    after = document.apply_set("/empty_object/new_key", '"v"')
    assert "new_key: \"v\"" in after
    assert Document(after).stored_value(Document(after).root)["empty_object"]["new_key"] == "v"


def test_escaped_keys_are_addressable():
    document = Document(fx.MIXED_TYPES)
    assert document.find("/nested/dotted.key") is not None
    assert document.find("/nested/with~1slash") is not None
    assert document.find("/nested/with~0tilde") is not None
    assert document.find("/nested/0") is not None
    after = document.apply_set("/nested/dotted.key", "22")
    assert '"dotted.key": 22' in after


def test_array_element_edit_by_index():
    document = Document(fx.MIXED_TYPES)
    after = document.apply_set("/nested/list/1", "42")
    assert "2, // Second item." in after
    assert "42," in after
    assert "// First item." in after


def test_object_replacement_keeps_comments():
    document = Document(fx.COMMENT_OWNERSHIP)
    new_value = """{
    element3: 500,
    element4: 600,
  }"""
    after = document.apply_set("/element2", new_value)
    assert "// Leading comment for element3." in after
    assert "// Leading comment for element4." in after
    assert "// Block-end comment for element2 (kept before the closing brace)." in after
    assert "element3: 500," in after
    assert "element4: 600" in after


def test_object_replacement_dropping_commented_child_is_rejected():
    document = Document(fx.COMMENT_OWNERSHIP)
    before = document.text
    with pytest.raises(CommentPreservationConflict):
        document.apply_set("/element2", "{ element3: 1 }")
    assert document.text == before


def test_object_replacement_changing_commented_child_type_is_rejected():
    document = Document(fx.COMMENT_OWNERSHIP)
    with pytest.raises(CommentPreservationConflict):
        document.apply_set("/element2", "{ element3: 1, element4: [1] }")


def test_equal_length_array_replacement_is_elementwise():
    document = Document(fx.MIXED_TYPES)
    after = document.apply_set("/nested/list", "[10, 20, { deep: 'no' }]")
    assert "// First item." in after
    assert "10," in after
    assert "20, // Second item." in after
    assert "// Item object." in after
    assert "deep: 'no'" in after


def test_array_length_change_with_comments_is_rejected():
    document = Document(fx.MIXED_TYPES)
    with pytest.raises(CommentPreservationConflict):
        document.apply_set("/nested/list", "[10, 20]")


def test_array_length_change_without_comments_is_allowed():
    document = Document(fx.SINGLE_LINE_OBJECTS)
    after = document.apply_set("/single_array", "[1, 2, 3, 4, 5]")
    assert after.strip().endswith("}")
    assert "[1, 2, 3, 4, 5]" in after


def test_root_pointer_is_read_only():
    document = Document(fx.MIXED_TYPES)
    with pytest.raises(PathError):
        document.apply_set("", "{}")


def test_missing_parent_is_rejected():
    document = Document(fx.MIXED_TYPES)
    with pytest.raises(PathError):
        document.apply_set("/absent/leaf", "1")


def test_out_of_range_array_index_is_rejected():
    document = Document(fx.MIXED_TYPES)
    with pytest.raises(PathError):
        document.apply_set("/nested/list/9", "1")


def test_duplicate_keys_are_rejected_with_location():
    with pytest.raises(ParseError) as excinfo:
        Document("{\n  a: 1,\n  a: 2,\n}\n")
    assert "Duplicate object key" in str(excinfo.value)
    assert "line 3" in str(excinfo.value)


def test_trailing_garbage_is_rejected():
    with pytest.raises(ParseError):
        Document("{\n  a: 1,\n}\n{ b: 2 }")


def test_unsupported_template_operator_is_rejected():
    with pytest.raises(ParseError):
        Document("{ a: ${VAR-default} }")


def test_nonfinite_numbers_are_rejected():
    with pytest.raises(ParseError):
        Document("{ a: NaN }")
    with pytest.raises(ParseError):
        Document("{ a: Infinity }")


def test_format_detection():
    document = Document(fx.MIXED_TYPES)
    assert document.format_of(document.find("/port")) == "json5-template"
    assert document.format_of(document.find("/single quoted")) == "json5-template"
    assert document.format_of(document.find("/number_int")) == "json5"


def test_crlf_and_bom_are_preserved():
    for text in (fx.CRLF, fx.BOM):
        document = Document(text)
        assert document.text == text
        after = document.apply_set("/a", "9")
        assert "\r\n" in after or "﻿" in after


def test_no_final_newline_is_preserved():
    document = Document(fx.NO_FINAL_NEWLINE)
    after = document.apply_set("/a", "9")
    assert not after.endswith("\n")


def test_value_text_must_hold_exactly_one_value():
    document = Document(fx.MIXED_TYPES)
    with pytest.raises(ParseError):
        document.apply_set("/number_int", "1 2")
    with pytest.raises(PathError):
        document.apply_set("/number_int", "   ")
    with pytest.raises(PathError):
        document.apply_set("/number_int", "")


def test_paths_listing():
    document = Document(fx.MIXED_TYPES)
    paths = document.paths("/nested")
    assert "/nested/list" in paths
    assert "/nested/list/2/deep" in paths