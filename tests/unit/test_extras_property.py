"""Tests for the `extras` property and `extra()` method on AttributesBase and BaseState."""

from hassette.models.states.light import LightAttributes, LightState
from hassette.test_utils import make_light_state_dict


class TestAttributesBaseExtras:
    """Tests for AttributesBase.extras and .extra()."""

    def test_extras_returns_extra_fields(self) -> None:
        attrs = LightAttributes(friendly_name="Kitchen", is_hue_group=True, preset=5)
        assert attrs.extras == {"is_hue_group": True, "preset": 5}

    def test_extras_returns_empty_dict_when_no_extras(self) -> None:
        attrs = LightAttributes(friendly_name="Kitchen")
        assert attrs.extras == {}

    def test_extra_returns_value_when_present(self) -> None:
        attrs = LightAttributes(friendly_name="Kitchen", is_hue_group=True)
        assert attrs.extra("is_hue_group") is True

    def test_extra_returns_none_when_missing(self) -> None:
        attrs = LightAttributes(friendly_name="Kitchen")
        assert attrs.extra("is_hue_group") is None

    def test_extra_returns_custom_default_when_missing(self) -> None:
        attrs = LightAttributes(friendly_name="Kitchen")
        assert attrs.extra("is_hue_group", False) is False


class TestBaseStateExtras:
    """Tests for BaseState.extras and .extra()."""

    def test_extras_returns_extra_fields(self) -> None:
        data = make_light_state_dict(is_hue_group=True, preset=5)
        # Add an extra field at the state level (not attributes)
        data["custom_state_field"] = "hello"
        state = LightState(**data)
        assert state.extras == {"custom_state_field": "hello"}

    def test_extras_returns_empty_dict_when_no_extras(self) -> None:
        data = make_light_state_dict()
        state = LightState(**data)
        assert state.extras == {}

    def test_extra_returns_value_when_present(self) -> None:
        data = make_light_state_dict()
        data["custom_state_field"] = 42
        state = LightState(**data)
        assert state.extra("custom_state_field") == 42

    def test_extra_returns_none_when_missing(self) -> None:
        data = make_light_state_dict()
        state = LightState(**data)
        assert state.extra("custom_state_field") is None

    def test_extra_returns_custom_default_when_missing(self) -> None:
        data = make_light_state_dict()
        state = LightState(**data)
        assert state.extra("custom_state_field", "fallback") == "fallback"


class TestExtrasViaInheritance:
    """Verify extras work correctly through concrete subclasses."""

    def test_light_attributes_extras_via_state(self) -> None:
        data = make_light_state_dict(is_hue_group=True, preset=5)
        state = LightState(**data)
        assert state.attributes.extras == {"is_hue_group": True, "preset": 5}
        assert state.attributes.extra("is_hue_group") is True
        assert state.attributes.extra("preset") == 5
        assert state.attributes.extra("nonexistent") is None
