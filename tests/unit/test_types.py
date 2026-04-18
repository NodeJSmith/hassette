"""Unit tests for framework key helpers in hassette.types.types."""

from hassette.types.types import FRAMEWORK_APP_KEY_PREFIX, framework_display_name, is_framework_key


class TestIsFrameworkKey:
    def test_is_framework_key_prefixed(self) -> None:
        """Keys starting with __hassette__. prefix are framework keys."""
        assert is_framework_key("__hassette__.service_watcher") is True

    def test_is_framework_key_bare(self) -> None:
        """The legacy bare key __hassette__ is a framework key."""
        assert is_framework_key("__hassette__") is True

    def test_is_framework_key_app(self) -> None:
        """Regular app keys are not framework keys."""
        assert is_framework_key("my_app") is False

    def test_is_framework_key_none(self) -> None:
        """None is not a framework key."""
        assert is_framework_key(None) is False

    def test_is_framework_key_empty_string(self) -> None:
        """Empty string is not a framework key."""
        assert is_framework_key("") is False

    def test_is_framework_key_prefix_only(self) -> None:
        """The prefix constant itself matches (starts with __hassette__)."""
        assert is_framework_key(FRAMEWORK_APP_KEY_PREFIX) is True

    def test_is_framework_key_similar_but_not_matching(self) -> None:
        """Keys that contain but don't start with the prefix are not framework keys."""
        assert is_framework_key("user__hassette__") is False

    def test_is_framework_key_sub_component(self) -> None:
        """Multiple dotted sub-keys with framework prefix are framework keys."""
        assert is_framework_key("__hassette__.bus.on_event") is True


class TestFrameworkDisplayName:
    def test_framework_display_name_prefixed(self) -> None:
        """Prefixed keys return the slug after the prefix."""
        assert framework_display_name("__hassette__.service_watcher") == "service_watcher"

    def test_framework_display_name_bare(self) -> None:
        """Bare __hassette__ key returns 'framework'."""
        assert framework_display_name("__hassette__") == "framework"

    def test_framework_display_name_sub_component(self) -> None:
        """Multiple dotted sub-keys return full suffix after prefix."""
        assert framework_display_name("__hassette__.bus.on_event") == "bus.on_event"
