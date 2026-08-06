"""Unit tests for rendering upstream-derived values into generated source.

The failure mode these guard against is "valid syntax, wrong structure" — an input that changes
how many literals or statements the generated module contains while still compiling. String
equality does not catch that, so the assertions here parse the rendered text and check its shape.
"""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.rendering import (
    UnsafeGeneratedValueError,
    escape_docstring_text,
    py_literal,
    require_identifier,
)

# Each of these breaks at least one of the hand-quoting sites the generators used to have.
HOSTILE_STRINGS = [
    'has "double" quotes',
    "has 'single' quotes",
    'closes the list", "and opens another',
    "trailing backslash \\",
    "back\\slash",
    'triple """ quote',
    "new\nline",
    "carriage\rreturn",
    "tab\there",
    "nul\x00byte",
    "non-ascii é ☃",
    '"""\nimport os\n"""',
]


class TestPyLiteral:
    @pytest.mark.parametrize("value", HOSTILE_STRINGS)
    def test_string_renders_as_exactly_one_literal(self, value: str) -> None:
        node = ast.parse(py_literal(value), mode="eval").body
        assert isinstance(node, ast.Constant)
        assert node.value == value

    @pytest.mark.parametrize("value", HOSTILE_STRINGS)
    def test_string_does_not_smuggle_extra_statements(self, value: str) -> None:
        module = ast.parse(f"X = {py_literal(value)}")
        assert len(module.body) == 1

    def test_prefers_double_quotes(self) -> None:
        # Matches what ruff format settles on, so unformatted generated output reads the same.
        assert py_literal("plain") == '"plain"'

    @pytest.mark.parametrize(("value", "expected"), [(0, "0"), (4, "4"), (-1, "-1"), (True, "True")])
    def test_int_renders_verbatim(self, value: int, expected: str) -> None:
        assert py_literal(value) == expected

    @pytest.mark.parametrize("value", [None, 1.5, ["a"], {"a": 1}, object()])
    def test_rejects_types_codegen_never_emits(self, value: object) -> None:
        with pytest.raises(UnsafeGeneratedValueError):
            py_literal(value)


# Python's tokenizer normalizes a lone carriage return in source to a newline, so those inputs
# survive structurally but not byte-for-byte. Covered separately below.
DOCSTRING_ROUND_TRIP_STRINGS = [text for text in HOSTILE_STRINGS if "\r" not in text]


class TestEscapeDocstringText:
    @pytest.mark.parametrize("text", DOCSTRING_ROUND_TRIP_STRINGS)
    def test_escaped_text_survives_a_docstring_round_trip(self, text: str) -> None:
        source = f'def f():\n    """{escape_docstring_text(text)}"""\n'
        module = ast.parse(source)

        assert len(module.body) == 1, "text escaped the docstring into executable position"
        assert ast.get_docstring(module.body[0], clean=False) == text  # pyright: ignore[reportArgumentType]

    def test_backslashes_are_escaped_before_the_quotes_they_introduce(self) -> None:
        # Escaping quotes first would leave the added backslashes to be doubled by the second pass.
        assert escape_docstring_text('"""') == '\\"\\"\\"'

    def test_carriage_return_stays_inside_the_docstring(self) -> None:
        # Python normalizes it to a newline rather than preserving it, but nothing escapes.
        escaped = escape_docstring_text("carriage\rreturn")
        module = ast.parse(f'def f():\n    """{escaped}"""\n')

        assert len(module.body) == 1
        assert ast.get_docstring(module.body[0], clean=False) == "carriage\nreturn"  # pyright: ignore[reportArgumentType]


class TestRequireIdentifier:
    @pytest.mark.parametrize("name", ["turn_on", "_private", "café", "match", "type"])
    def test_accepts_usable_names(self, name: str) -> None:
        assert require_identifier(name, kind="test") == name

    @pytest.mark.parametrize("name", ["", "turn on", "turn-on", "2fast", "foo.bar", "foo()", "os.system('x')"])
    def test_rejects_non_identifiers(self, name: str) -> None:
        with pytest.raises(UnsafeGeneratedValueError):
            require_identifier(name, kind="test")

    @pytest.mark.parametrize("name", ["class", "import", "None", "lambda"])
    def test_rejects_keywords(self, name: str) -> None:
        # Keywords pass str.isidentifier() but are not usable as names.
        with pytest.raises(UnsafeGeneratedValueError):
            require_identifier(name, kind="test")
