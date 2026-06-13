"""Unit tests for the docstring builder and the strings.json description resolver.

These cover the description-threading path directly, independent of a live HA core checkout
(the integration tests in test_services.py skip when HA_CORE_PATH is absent).
"""

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
