"""Unit tests for service extraction and type mapping."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.extractors.services import extract_services
from hassette_codegen.type_mapping import map_selector_to_type

_HA_CORE = Path("~/source/core").expanduser()
_HAS_HA_CORE = _HA_CORE.exists()
_COMPONENTS = _HA_CORE / "homeassistant" / "components"


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestServiceExtraction:
    def test_fan_services(self) -> None:
        services = extract_services(_COMPONENTS / "fan")
        names = {s.name for s in services}
        assert "turn_on" in names
        assert "turn_off" in names
        assert "set_percentage" in names
        assert "oscillate" in names

    def test_fan_set_percentage_has_required_field(self) -> None:
        services = extract_services(_COMPONENTS / "fan")
        set_pct = next(s for s in services if s.name == "set_percentage")
        pct_field = next(f for f in set_pct.fields if f.name == "percentage")
        assert pct_field.required is True
        assert pct_field.selector_type == "number"

    def test_light_advanced_fields_flattened(self) -> None:
        services = extract_services(_COMPONENTS / "light")
        turn_on = next(s for s in services if s.name == "turn_on")
        field_names = {f.name for f in turn_on.fields}
        assert "brightness" in field_names or "brightness_pct" in field_names
        assert len(turn_on.fields) >= 5

    def test_domain_with_no_services_yaml(self) -> None:
        services = extract_services(_COMPONENTS / "sensor")
        assert services == []

    def test_fan_turn_off_has_no_fields(self) -> None:
        services = extract_services(_COMPONENTS / "fan")
        turn_off = next(s for s in services if s.name == "turn_off")
        assert turn_off.fields == []


class TestTypeMapping:
    def test_number_int(self) -> None:
        assert map_selector_to_type("number", {"min": 0, "max": 100}) == "int"

    def test_number_float(self) -> None:
        assert map_selector_to_type("number", {"step": 0.1}) == "float"

    def test_boolean(self) -> None:
        assert map_selector_to_type("boolean", {}) == "bool"

    def test_text(self) -> None:
        assert map_selector_to_type("text", {}) == "str"

    def test_select_with_options(self) -> None:
        result = map_selector_to_type("select", {"options": ["a", "b", "c"]})
        assert result == 'Literal["a", "b", "c"]'

    def test_color_rgb(self) -> None:
        assert map_selector_to_type("color_rgb", {}) == "tuple[int, int, int]"

    def test_color_temp(self) -> None:
        assert map_selector_to_type("color_temp", {}) == "int"

    def test_object(self) -> None:
        assert map_selector_to_type("object", {}) == "Any"

    def test_state(self) -> None:
        assert map_selector_to_type("state", {}) == "str"

    def test_entity(self) -> None:
        assert map_selector_to_type("entity", {}) == "str"

    def test_area(self) -> None:
        assert map_selector_to_type("area", {}) == "str"

    def test_media(self) -> None:
        assert map_selector_to_type("media", {}) == "dict[str, Any]"

    def test_unknown_returns_any(self) -> None:
        assert map_selector_to_type("totally_unknown", {}) == "Any"
