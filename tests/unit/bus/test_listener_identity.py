"""Unit tests for ListenerIdentity sub-struct."""

import pytest

from hassette.bus.listeners import ListenerIdentity


class TestListenerIdentityConstruction:
    def test_required_fields_only(self) -> None:
        """ListenerIdentity can be constructed with only required fields."""
        identity = ListenerIdentity(
            owner_id="test_owner",
            handler_name="my_handler",
            handler_short_name="my_handler",
        )
        assert identity.owner_id == "test_owner"
        assert identity.handler_name == "my_handler"
        assert identity.handler_short_name == "my_handler"

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("app_key", ""),
            ("instance_index", 0),
            ("name", None),
            ("source_tier", "app"),
            ("source_location", ""),
            ("registration_source", ""),
        ],
    )
    def test_optional_field_defaults(self, field: str, expected: object) -> None:
        identity = ListenerIdentity(owner_id="o", handler_name="h", handler_short_name="h")
        assert getattr(identity, field) == expected

    def test_all_fields_set(self) -> None:
        """All 9 fields can be set explicitly."""
        identity = ListenerIdentity(
            owner_id="owner",
            app_key="my_app",
            instance_index=2,
            name="my_listener",
            source_tier="framework",
            handler_name="my_module.MyClass.my_handler",
            handler_short_name="my_handler",
            source_location="bus.py:42",
            registration_source="self.bus.on_state_change(...)",
        )
        assert identity.owner_id == "owner"
        assert identity.app_key == "my_app"
        assert identity.instance_index == 2
        assert identity.name == "my_listener"
        assert identity.source_tier == "framework"
        assert identity.handler_name == "my_module.MyClass.my_handler"
        assert identity.handler_short_name == "my_handler"
        assert identity.source_location == "bus.py:42"
        assert identity.registration_source == "self.bus.on_state_change(...)"

    def test_has_slots(self) -> None:
        """ListenerIdentity uses slots=True."""
        identity = ListenerIdentity(owner_id="o", handler_name="h", handler_short_name="h")
        assert hasattr(type(identity), "__slots__")
