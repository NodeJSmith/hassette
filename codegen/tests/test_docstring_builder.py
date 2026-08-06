"""Unit tests for the docstring builder and the strings.json description resolver.

These cover the description-threading path directly, independent of a live HA core checkout
(the integration tests in test_services.py skip when HA_CORE_PATH is absent).
"""

import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.extractors.services import _extract_descriptions, _resolve_key_ref
from hassette_codegen.generators.entities import LINE_LENGTH, ServiceParam, build_method_docstring


class TestBuildMethodDocstring:
    def test_no_params_is_summary_only(self) -> None:
        doc = build_method_docstring("Open a cover.", [])
        assert doc.startswith('        """Open a cover.')
        assert "Args:" not in doc
        # No Returns section is ever emitted — the annotation states the return.
        assert "Returns:" not in doc

    def test_documented_params_render_args(self) -> None:
        params = [ServiceParam(name="position", python_type="int", required=True, description="Target position")]
        doc = build_method_docstring("Move the cover to a specific position.", params)
        assert doc.startswith('        """Move the cover to a specific position.')
        assert "        Args:" in doc
        # Trailing period is added when the source description lacks terminal punctuation.
        assert "            position: Target position." in doc
        assert "Returns:" not in doc

    def test_params_without_description_are_omitted_from_args(self) -> None:
        params = [ServiceParam(name="position", python_type="int", required=True, description=None)]
        doc = build_method_docstring("Move the cover.", params)
        assert "Args:" not in doc

    def test_long_summary_wraps_within_line_length(self) -> None:
        summary = "Turns on one or more lights and adjusts their properties, even when they are turned on already."
        doc = build_method_docstring(summary, [])
        assert all(len(line) <= LINE_LENGTH for line in doc.splitlines())

    def test_long_description_wraps_within_line_length(self) -> None:
        long = "Number indicating brightness " * 12
        params = [ServiceParam(name="brightness", python_type="int", required=False, description=long)]
        doc = build_method_docstring("Turn on the light.", params)
        assert all(len(line) <= LINE_LENGTH for line in doc.splitlines())
        # Continuation lines align under the description at a 16-space hanging indent.
        assert [ln for ln in doc.splitlines() if ln.startswith(" " * 16)]

    def test_existing_terminal_punctuation_is_preserved(self) -> None:
        params = [ServiceParam(name="flash", python_type="str", required=False, description="Tell light to flash?")]
        doc = build_method_docstring("Turn on the light.", params)
        assert "flash: Tell light to flash?" in doc
        assert "flash?." not in doc


class TestResolveKeyRef:
    def test_plain_string_passes_through(self, tmp_path: Path) -> None:
        assert _resolve_key_ref("A human-readable color name.", tmp_path) == "A human-readable color name."

    def test_malformed_component_only_ref_returns_none(self, tmp_path: Path) -> None:
        assert _resolve_key_ref("[%key:component%]", tmp_path) is None

    def test_depth_limit_returns_none(self, tmp_path: Path) -> None:
        assert _resolve_key_ref("[%key:component::light::x%]", tmp_path, depth=99) is None

    def test_missing_strings_json_returns_none(self, tmp_path: Path) -> None:
        assert _resolve_key_ref("[%key:component::light::common::brightness%]", tmp_path) is None

    def test_resolves_cross_domain_reference(self, tmp_path: Path) -> None:
        light_dir = tmp_path / "light"
        light_dir.mkdir()
        (light_dir / "strings.json").write_text(
            json.dumps({"common": {"field_brightness": "Number indicating brightness."}}), encoding="utf-8"
        )
        resolved = _resolve_key_ref("[%key:component::light::common::field_brightness%]", tmp_path)
        assert resolved == "Number indicating brightness."

    def test_chained_reference_resolves_recursively(self, tmp_path: Path) -> None:
        light_dir = tmp_path / "light"
        light_dir.mkdir()
        brightness = {"description": "[%key:component::light::common::b%]"}
        (light_dir / "strings.json").write_text(
            json.dumps(
                {
                    "services": {"turn_on": {"fields": {"brightness": brightness}}},
                    "common": {"b": "Resolved brightness text."},
                }
            ),
            encoding="utf-8",
        )
        ref = "[%key:component::light::services::turn_on::fields::brightness::description%]"
        assert _resolve_key_ref(ref, tmp_path) == "Resolved brightness text."

    def test_non_string_leaf_returns_none(self, tmp_path: Path) -> None:
        light_dir = tmp_path / "light"
        light_dir.mkdir()
        (light_dir / "strings.json").write_text(json.dumps({"common": {"x": {"nested": "y"}}}), encoding="utf-8")
        assert _resolve_key_ref("[%key:component::light::common::x%]", tmp_path) is None


class TestExtractDescriptions:
    def test_returns_service_and_field_descriptions(self, tmp_path: Path) -> None:
        light_dir = tmp_path / "light"
        light_dir.mkdir()
        (light_dir / "strings.json").write_text(
            json.dumps(
                {
                    "services": {
                        "turn_on": {
                            "description": "Turns on one or more lights.",
                            "fields": {"brightness": {"description": "Brightness, 0-255."}},
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        service_descs, field_descs = _extract_descriptions(light_dir)
        assert service_descs["turn_on"] == "Turns on one or more lights."
        assert field_descs["turn_on"]["brightness"] == "Brightness, 0-255."

    def test_missing_strings_json_returns_empty_maps(self, tmp_path: Path) -> None:
        assert _extract_descriptions(tmp_path / "nonexistent") == ({}, {})


class TestDocstringEscaping:
    """A service description is Home Assistant's text inserted at raw statement position.

    Nothing between services.yaml and the generated file quotes it, so the escaping has to happen
    here. Each test parses the result and asserts the method body still contains only what the
    generator put there.
    """

    @staticmethod
    def _parse_method(doc: str) -> ast.FunctionDef:
        """Wrap a built docstring at its native indentation and return the enclosing method."""
        module = ast.parse(f"class C:\n    def m(self) -> None:\n{doc}\n        pass\n")
        cls = module.body[0]
        assert isinstance(cls, ast.ClassDef)
        assert len(module.body) == 1, "text escaped the class body into module scope"
        assert len(cls.body) == 1, "text escaped the method body into class scope"

        method = cls.body[0]
        assert isinstance(method, ast.FunctionDef)
        return method

    @staticmethod
    def _docstring(method: ast.FunctionDef) -> str:
        """The docstring's text, less the indentation its own closing-delimiter line carries."""
        return (ast.get_docstring(method, clean=False) or "").strip()

    def test_triple_quote_in_summary_cannot_reach_executable_position(self) -> None:
        method = self._parse_method(build_method_docstring('Close the cover."""\nimport os\n"""', []))

        # Docstring plus the `pass` the wrapper adds — an injected `import os` would make it three.
        assert len(method.body) == 2
        assert '"""' in self._docstring(method)

    def test_triple_quote_in_param_description_cannot_reach_executable_position(self) -> None:
        params = [ServiceParam(name="position", python_type="int", required=True, description='x"""\nimport os\n"""')]
        method = self._parse_method(build_method_docstring("Move the cover.", params))

        assert len(method.body) == 2
        assert '"""' in self._docstring(method)

    def test_trailing_backslash_does_not_escape_the_closing_delimiter(self) -> None:
        method = self._parse_method(build_method_docstring("Ends with a backslash \\", []))

        assert len(method.body) == 2
        assert self._docstring(method).endswith("backslash \\.")

    def test_windows_path_is_not_read_as_escape_sequences(self) -> None:
        method = self._parse_method(build_method_docstring("Path is C:\\new\\table.", []))

        assert self._docstring(method) == "Path is C:\\new\\table."

    def test_nul_byte_leaves_the_module_compilable(self) -> None:
        # Python refuses to read source containing a literal NUL at all.
        method = self._parse_method(build_method_docstring("Has a \x00 byte.", []))

        assert self._docstring(method) == "Has a \x00 byte."

    def test_whitespace_only_summary_still_opens_the_docstring(self) -> None:
        # textwrap.fill drops initial_indent when the text collapses to nothing, which used to
        # emit a lone closing delimiter that swallowed everything after it.
        method = self._parse_method(build_method_docstring("   ", []))

        assert len(method.body) == 2
        assert self._docstring(method) == ""

    def test_whitespace_only_param_description_is_not_documented(self) -> None:
        params = [ServiceParam(name="position", python_type="int", required=True, description="  ")]
        doc = build_method_docstring("Move the cover.", params)

        assert "Args:" not in doc
