"""Unit tests for AST extractors — features, properties, and base class."""

from pathlib import Path

import pytest

from hassette_codegen.extractors._common import parse_module_or_none
from hassette_codegen.extractors.base_class import determine_base_class
from hassette_codegen.extractors.constants import _extract_enum_ref_set, extract_numeric_state_expected_source
from hassette_codegen.extractors.features import extract_features
from hassette_codegen.extractors.properties import extract_properties
from hassette_codegen.ha_source import find_entity_module

from .conftest import HA_CORE as _HA_CORE
from .conftest import HAS_HA_CORE as _HAS_HA_CORE

_COMPONENTS = _HA_CORE / "homeassistant" / "components"


def _entity_module(domain: str) -> Path:
    """The file defining ``domain``'s entity class, which HA moved from ``__init__.py`` to ``entity.py`` for some."""
    module = find_entity_module(_COMPONENTS / domain)
    assert module is not None, f"no entity module found for {domain}"
    return module


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
        props = extract_properties(_entity_module("fan"))
        names = {p.name for p in props}
        assert "current_direction" in names
        assert "oscillating" in names
        assert "percentage" in names

    def test_fan_excludes_supported_features(self) -> None:
        props = extract_properties(_entity_module("fan"))
        names = {p.name for p in props}
        assert "supported_features" not in names

    def test_field_without_default_gets_none_widened(self) -> None:
        props = extract_properties(_entity_module("fan"))
        for prop in props:
            if not prop.has_default:
                assert "None" in prop.python_type, f"{prop.name} should be widened to include None"

    def test_field_with_default_preserves_type(self) -> None:
        props = extract_properties(_entity_module("fan"))
        percentage = next((p for p in props if p.name == "percentage"), None)
        assert percentage is not None
        assert percentage.has_default is True


class TestDeprecatedAttrAliases:
    def test_deprecated_attr_alias_is_skipped(self, tmp_path: Path) -> None:
        """HA 2026.11 keeps a renamed `_attr_*` as a `Final` alias; only the real attribute is a field."""
        module = tmp_path / "entity.py"
        module.write_text(
            "class ClimateEntity(Entity):\n"
            "    _attr_native_current_temperature: float | None = None\n"
            "    _attr_current_temperature: Final = DeprecatedEntityAttr[float | None](\n"
            '        "_attr_native_current_temperature", "2027.11"\n'
            "    )\n"
        )

        props = extract_properties(module)

        assert [(p.name, p.python_type) for p in props] == [("native_current_temperature", "float | None")]


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestBaseClassDetermination:
    def test_light_is_bool(self) -> None:
        result = determine_base_class(_entity_module("light"))
        assert result == "BoolBaseState"

    def test_fan_is_bool(self) -> None:
        result = determine_base_class(_entity_module("fan"))
        assert result == "BoolBaseState"

    def test_number_is_numeric(self) -> None:
        result = determine_base_class(_entity_module("number"))
        assert result == "NumericBaseState"

    def test_climate_is_string(self) -> None:
        result = determine_base_class(_entity_module("climate"))
        assert result == "StringBaseState"


class TestEnumRefSetExtraction:
    """``_extract_enum_ref_set`` handles a set of enum *attribute references*

    (``{Color.RED, Color.GREEN}``), not string constants — the shape ``NON_NUMERIC_DEVICE_CLASSES``
    is written in upstream, which ``_extract_strenum_members`` cannot parse.
    """

    def test_extracts_set_of_enum_attribute_refs(self, tmp_path: Path) -> None:
        src = tmp_path / "const.py"
        src.write_text(
            "from enum import StrEnum\n\n\n"
            "class Color(StrEnum):\n"
            '    RED = "red"\n'
            '    BLUE = "blue"\n'
            '    GREEN = "green"\n\n\n'
            "NON_PRIMARY = {Color.GREEN, Color.RED}\n",
            encoding="utf-8",
        )
        values = _extract_enum_ref_set(src, "NON_PRIMARY", "Color")
        assert set(values) == {"red", "green"}

    def test_resolves_via_enum_value_not_lowercased_attribute_name(self, tmp_path: Path) -> None:
        """A member whose value diverges from its lowercased name must still resolve correctly —

        this is the failure mode of a naive ``member.attr.lower()`` shortcut.
        """
        src = tmp_path / "const.py"
        src.write_text(
            'from enum import StrEnum\n\n\nclass Weird(StrEnum):\n    FOO = "not_foo"\n\n\nTARGET = {Weird.FOO}\n',
            encoding="utf-8",
        )
        values = _extract_enum_ref_set(src, "TARGET", "Weird")
        assert values == ["not_foo"]

    def test_missing_target_name_returns_empty(self, tmp_path: Path) -> None:
        src = tmp_path / "const.py"
        src.write_text("X = 1\n", encoding="utf-8")
        assert _extract_enum_ref_set(src, "MISSING", "Whatever") == []

    def test_syntax_error_returns_empty(self, tmp_path: Path) -> None:
        src = tmp_path / "const.py"
        src.write_text("def broken(:\n", encoding="utf-8")
        assert _extract_enum_ref_set(src, "X", "Y") == []

    @pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
    def test_non_numeric_device_classes_against_real_ha_core(self) -> None:
        sensor_const = _COMPONENTS / "sensor" / "const.py"
        values = _extract_enum_ref_set(sensor_const, "NON_NUMERIC_DEVICE_CLASSES", "SensorDeviceClass")
        # Declaration order in upstream const.py — a cross-check that the extractor resolved the
        # right enum members rather than, say, every member.
        assert values == ["date", "enum", "timestamp", "uptime"]


class TestNumericStateExpectedSourceExtraction:
    """``extract_numeric_state_expected_source`` feeds the drift guard in ``pipeline.py``."""

    @pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
    def test_extracts_module_level_function(self) -> None:
        source = extract_numeric_state_expected_source(_HA_CORE)
        assert source is not None
        assert source.startswith("def _numeric_state_expected(")
        assert "NON_NUMERIC_DEVICE_CLASSES" in source

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert extract_numeric_state_expected_source(tmp_path) is None

    def test_function_not_present_returns_none(self, tmp_path: Path) -> None:
        sensor_dir = tmp_path / "homeassistant" / "components" / "sensor"
        sensor_dir.mkdir(parents=True)
        (sensor_dir / "__init__.py").write_text("def other_function():\n    pass\n", encoding="utf-8")
        assert extract_numeric_state_expected_source(tmp_path) is None

    def test_syntax_error_returns_none(self, tmp_path: Path) -> None:
        sensor_dir = tmp_path / "homeassistant" / "components" / "sensor"
        sensor_dir.mkdir(parents=True)
        (sensor_dir / "__init__.py").write_text("def broken(:\n", encoding="utf-8")
        assert extract_numeric_state_expected_source(tmp_path) is None

    def test_ignores_same_named_nested_method(self, tmp_path: Path) -> None:
        """Only the module-level function is matched — HA also has a same-named compat *method*

        on the entity class, which must not be picked up instead.
        """
        sensor_dir = tmp_path / "homeassistant" / "components" / "sensor"
        sensor_dir.mkdir(parents=True)
        (sensor_dir / "__init__.py").write_text(
            "class SensorEntity:\n    def _numeric_state_expected(self) -> bool:\n        return True\n",
            encoding="utf-8",
        )
        assert extract_numeric_state_expected_source(tmp_path) is None


class TestParseModuleOrNone:
    def test_parses_valid_source(self, tmp_path: Path) -> None:
        src = tmp_path / "mod.py"
        src.write_text("X = 1\n", encoding="utf-8")
        tree = parse_module_or_none(src)
        assert tree is not None
        assert len(tree.body) == 1

    def test_syntax_error_returns_none(self, tmp_path: Path) -> None:
        src = tmp_path / "mod.py"
        src.write_text("def broken(:\n", encoding="utf-8")
        assert parse_module_or_none(src) is None

    def test_unreadable_path_returns_none(self, tmp_path: Path) -> None:
        # A directory raises IsADirectoryError (an OSError) on read_text, on every platform.
        assert parse_module_or_none(tmp_path) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert parse_module_or_none(tmp_path / "absent.py") is None


class TestEntityModuleReadFailures:
    """An unreadable entity module degrades to the extractor's empty default instead of raising."""

    def test_determine_base_class_falls_back_to_string(self, tmp_path: Path) -> None:
        assert determine_base_class(tmp_path / "absent.py") == "StringBaseState"

    def test_extract_properties_returns_empty(self, tmp_path: Path) -> None:
        assert extract_properties(tmp_path / "absent.py") == []
