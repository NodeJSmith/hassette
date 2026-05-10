"""Unit tests for AST extractors — features, properties, and base class."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.extractors.base_class import determine_base_class
from hassette_codegen.extractors.features import extract_features
from hassette_codegen.extractors.properties import extract_properties

_HA_CORE = Path("~/source/core").expanduser()
_HAS_HA_CORE = _HA_CORE.exists()
_COMPONENTS = _HA_CORE / "homeassistant" / "components"


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestFeatureExtraction:
    def test_light_features_in_const_py(self) -> None:
        enums = extract_features(_COMPONENTS / "light")
        assert len(enums) >= 1
        light_enum = next(e for e in enums if e.name == "LightEntityFeature")
        member_names = {m[0] for m in light_enum.members}
        assert "EFFECT" in member_names
        assert "FLASH" in member_names
        assert "TRANSITION" in member_names

    def test_fan_features_in_init_py(self) -> None:
        enums = extract_features(_COMPONENTS / "fan")
        assert len(enums) >= 1
        fan_enum = next(e for e in enums if e.name == "FanEntityFeature")
        member_names = {m[0] for m in fan_enum.members}
        assert "SET_SPEED" in member_names
        assert "OSCILLATE" in member_names
        assert "DIRECTION" in member_names

    def test_enum_values_are_ints(self) -> None:
        enums = extract_features(_COMPONENTS / "fan")
        fan_enum = next(e for e in enums if e.name == "FanEntityFeature")
        for _name, value in fan_enum.members:
            assert isinstance(value, int)

    def test_domain_without_features_returns_empty(self) -> None:
        enums = extract_features(_COMPONENTS / "number")
        feature_enums = [e for e in enums if e.name.endswith("EntityFeature")]
        assert len(feature_enums) == 0


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestPropertyExtraction:
    def test_fan_properties(self) -> None:
        props = extract_properties(_COMPONENTS / "fan" / "__init__.py")
        names = {p.name for p in props}
        assert "current_direction" in names
        assert "oscillating" in names
        assert "percentage" in names

    def test_fan_excludes_supported_features(self) -> None:
        props = extract_properties(_COMPONENTS / "fan" / "__init__.py")
        names = {p.name for p in props}
        assert "supported_features" not in names

    def test_field_without_default_gets_none_widened(self) -> None:
        props = extract_properties(_COMPONENTS / "fan" / "__init__.py")
        for prop in props:
            if not prop.has_default:
                assert "None" in prop.python_type, f"{prop.name} should be widened to include None"

    def test_field_with_default_preserves_type(self) -> None:
        props = extract_properties(_COMPONENTS / "fan" / "__init__.py")
        percentage = next((p for p in props if p.name == "percentage"), None)
        assert percentage is not None
        assert percentage.has_default is True


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestBaseClassDetermination:
    def test_light_is_bool(self) -> None:
        result = determine_base_class(_COMPONENTS / "light" / "__init__.py")
        assert result == "BoolBaseState"

    def test_fan_is_bool(self) -> None:
        result = determine_base_class(_COMPONENTS / "fan" / "__init__.py")
        assert result == "BoolBaseState"

    def test_number_is_numeric(self) -> None:
        result = determine_base_class(_COMPONENTS / "number" / "__init__.py")
        assert result == "NumericBaseState"

    def test_climate_is_string(self) -> None:
        result = determine_base_class(_COMPONENTS / "climate" / "__init__.py")
        assert result == "StringBaseState"
