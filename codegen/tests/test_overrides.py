"""Unit tests for the TOML override system."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.overrides import DomainOverride, get_override, load_overrides, validate_overrides


class TestLoadOverrides:
    def test_loads_from_default_dir(self) -> None:
        overrides = load_overrides()
        assert "light" in overrides
        assert "media_player" in overrides

    def test_light_has_extra_imports(self) -> None:
        overrides = load_overrides()
        light = overrides["light"]
        assert "entity" in light.extra_imports
        assert any("Color" in imp for imp in light.extra_imports["entity"])

    def test_light_has_param_type_override(self) -> None:
        overrides = load_overrides()
        light = overrides["light"]
        assert "color_name" in light.param_type_overrides

    def test_media_player_has_renames(self) -> None:
        overrides = load_overrides()
        mp = overrides["media_player"]
        assert mp.service_param_renames.get("media_content_type") == "media_type"

    def test_state_base_class_override(self, tmp_path: Path) -> None:
        toml = tmp_path / "sensor.toml"
        toml.write_text('state_base_class = "NumericBaseState"\n')
        overrides = load_overrides(tmp_path)
        assert overrides["sensor"].state_base_class == "NumericBaseState"

    def test_get_override_returns_none_for_unknown(self) -> None:
        overrides = load_overrides()
        assert get_override(overrides, "nonexistent_domain") is None

    def test_loads_from_custom_dir(self, tmp_path: Path) -> None:
        toml = tmp_path / "test.toml"
        toml.write_text('state_base_class = "BoolBaseState"\n')
        overrides = load_overrides(tmp_path)
        assert "test" in overrides
        assert overrides["test"].state_base_class == "BoolBaseState"


class TestValidateOverrides:
    def test_warns_on_unknown_domain(self, capsys: object) -> None:
        overrides = {"fake_domain": DomainOverride(domain="fake_domain")}
        validate_overrides(overrides, {"light", "fan"})
