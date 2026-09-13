"""Unit tests for service extraction and type mapping."""

from pathlib import Path
from textwrap import dedent

import pytest

from hassette_codegen.extractors.services import SupportsResponseValue, extract_services
from hassette_codegen.generators.entities import ServiceForTemplate
from hassette_codegen.type_mapping import map_selector_to_type

from .conftest import HA_CORE as _HA_CORE
from .conftest import HAS_HA_CORE as _HAS_HA_CORE

_COMPONENTS = _HA_CORE / "homeassistant" / "components"


def _write_component(tmp_path: Path, services_yaml: str, init_py: str | None = None) -> Path:
    """Create a synthetic component directory with services.yaml and optional __init__.py."""
    comp = tmp_path / "test_domain"
    comp.mkdir()
    (comp / "services.yaml").write_text(dedent(services_yaml))
    if init_py is not None:
        (comp / "__init__.py").write_text(dedent(init_py))
    return comp


class TestSupportsResponseExtraction:
    def test_keyword_supports_response(self, tmp_path: Path) -> None:
        comp = _write_component(
            tmp_path,
            """\
            get_forecasts:
              fields: {}
            """,
            """\
            from homeassistant.components.weather import SupportsResponse

            async def async_setup(hass):
                platform.async_register_entity_service(
                    "get_forecasts",
                    {},
                    "async_get_forecasts",
                    supports_response=SupportsResponse.ONLY,
                )
            """,
        )
        services = extract_services(comp)
        svc = next(s for s in services if s.name == "get_forecasts")
        assert svc.supports_response == "ONLY"

    def test_positional_supports_response(self, tmp_path: Path) -> None:
        comp = _write_component(
            tmp_path,
            """\
            search_media:
              fields: {}
            """,
            """\
            from homeassistant.components.media_player import SupportsResponse

            async def async_setup(hass):
                platform.async_register_entity_service(
                    "search_media",
                    {},
                    "async_search_media",
                    None,
                    SupportsResponse.OPTIONAL,
                )
            """,
        )
        services = extract_services(comp)
        svc = next(s for s in services if s.name == "search_media")
        assert svc.supports_response == "OPTIONAL"

    def test_missing_supports_response_defaults_to_none(self, tmp_path: Path) -> None:
        comp = _write_component(
            tmp_path,
            """\
            turn_on:
              fields: {}
            """,
            """\
            async def async_setup(hass):
                platform.async_register_entity_service(
                    "turn_on",
                    {},
                    "async_turn_on",
                )
            """,
        )
        services = extract_services(comp)
        svc = next(s for s in services if s.name == "turn_on")
        assert svc.supports_response == "NONE"

    def test_no_init_py_defaults_to_none(self, tmp_path: Path) -> None:
        comp = _write_component(
            tmp_path,
            """\
            turn_on:
              fields: {}
            """,
        )
        services = extract_services(comp)
        svc = next(s for s in services if s.name == "turn_on")
        assert svc.supports_response == "NONE"

    def test_service_constant_fuzzy_match(self, tmp_path: Path) -> None:
        comp = _write_component(
            tmp_path,
            """\
            browse_media:
              fields: {}
            """,
            """\
            from homeassistant.components.media_player import SupportsResponse

            SERVICE_BROWSE_MEDIA = "browse_media"

            async def async_setup(hass):
                platform.async_register_entity_service(
                    SERVICE_BROWSE_MEDIA,
                    {},
                    "async_browse_media",
                    supports_response=SupportsResponse.ONLY,
                )
            """,
        )
        services = extract_services(comp)
        svc = next(s for s in services if s.name == "browse_media")
        assert svc.supports_response == "ONLY"

    def test_enum_member_fuzzy_match(self, tmp_path: Path) -> None:
        comp = _write_component(
            tmp_path,
            """\
            get_items:
              fields: {}
            """,
            """\
            from homeassistant.components.todo import SupportsResponse

            class TodoServices:
                GET_ITEMS = "get_items"

            async def async_setup(hass):
                platform.async_register_entity_service(
                    TodoServices.GET_ITEMS,
                    {},
                    "async_get_items",
                    supports_response=SupportsResponse.ONLY,
                )
            """,
        )
        services = extract_services(comp)
        svc = next(s for s in services if s.name == "get_items")
        assert svc.supports_response == "ONLY"


class TestServiceForTemplateHasResponse:
    def _make(self, supports_response: SupportsResponseValue) -> ServiceForTemplate:
        return ServiceForTemplate(
            name="test",
            method_name="test",
            params=[],
            doc='"""Test."""',
            supports_response=supports_response,
        )

    def test_optional_has_response(self) -> None:
        assert self._make("OPTIONAL").has_response is True

    def test_only_has_response(self) -> None:
        assert self._make("ONLY").has_response is True

    def test_none_has_no_response(self) -> None:
        assert self._make("NONE").has_response is False


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
