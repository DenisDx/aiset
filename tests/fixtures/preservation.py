"""Fixture corpus for source-preservation tests (SPEC.md section 7.1)."""

from __future__ import annotations

# The classification example of SPEC.md 7.1, a required fixture.
COMMENT_OWNERSHIP = """\
// Document comment (belongs to the whole document).
{
  // Leading comment for element1.
  element1: 124, // Trailing comment for element1.
  element2: { // Trailing comment for element2.
    // Leading comment for element3.
    element3: 123, // Trailing comment for element3.
    // Leading comment for element4.
    element4: 111 // Trailing comment for element4.
    // Block-end comment for element2 (kept before the closing brace).
  } // Trailing comment for element2's closing brace.
}
"""

MIXED_TYPES = """\
// Mixed-type fixture with quotes, trailing commas and templates.
{
  // A quoted string with a placeholder and escapes.
  'single quoted': "value with ${VAR:-default} and \\"escaped\\" quotes",
  number_int: 42,
  number_negative: -7,
  number_float: 1.5,
  flag_true: true,
  flag_false: false,
  explicit_null: null,
  // An unquoted whole-value template.
  port: ${PORT:-8080},
  nested: {
    // Nested array with comments.
    list: [
      // First item.
      1,
      2, // Second item.
      {
        // Item object.
        deep: 'yes',
      },
    ],
    /* block comment inside an object */
    quoted_key: 1,
    "dotted.key": 2,
    "with/slash": 3,
    "with~tilde": 4,
    "0": "numeric object key",
  },
}
"""

# No trailing newline, CRLF line endings, and a BOM in separate fixtures.
NO_FINAL_NEWLINE = "{\n  a: 1,\n  b: 2\n}"

CRLF = "{\r\n  a: 1,\r\n  b: 2,\r\n}\r\n"

BOM = "\ufeff{\n  a: 1,\n}\n"

UNICODE = """\
{
  // Комментарий на русском.
  "ключ": "значение — ✓ ünïcøde",
  "multiline": "first\\nsecond",
}
"""

SINGLE_LINE_OBJECTS = """\
{
  compact: { a: 1, b: 2 },
  empty_object: {},
  empty_array: [],
  single_array: [1, 2, 3],
}
"""