import pytest

from hassette import TYPE_REGISTRY
from hassette.conversion.type_registry import TypeRegistry
from hassette.exceptions import UnableToConvertValueError


def test_type_already_in_desired_state_not_converted_again() -> None:
    """Test that a state already in the desired type is not converted again."""
    desired_value = 12.1
    desired_type = float

    output = TYPE_REGISTRY.convert(desired_value, desired_type)
    assert output == desired_value
    assert type(output) is desired_type


def test_type_conversion_idempotent() -> None:
    """Test that a state already in the desired type is not converted again."""
    original_value = "12.1"
    desired_value = 12.1
    desired_type = float

    output = TYPE_REGISTRY.convert(original_value, desired_type)
    assert output == desired_value
    assert type(output) is desired_type

    output_two = TYPE_REGISTRY.convert(output, desired_type)
    assert output_two == output
    assert type(output_two) is desired_type


class TestConstructorFallbackCache:
    """Verify that constructor fallback auto-registers into conversion_map."""

    @pytest.fixture(autouse=True)
    def _isolate_registry(self):
        snapshot = TypeRegistry.snapshot()
        yield
        TypeRegistry.restore(snapshot)

    def test_constructor_fallback_auto_registers(self) -> None:
        """First successful constructor fallback adds entry to conversion_map."""

        class Custom:
            def __init__(self, val: str) -> None:
                self.val = val

        key = (str, Custom)
        assert key not in TypeRegistry.conversion_map

        result = TYPE_REGISTRY.convert("hello", Custom)

        assert isinstance(result, Custom)
        assert result.val == "hello"
        assert key in TypeRegistry.conversion_map

    def test_auto_registered_converter_used_on_subsequent_calls(self) -> None:
        """Second call for the same type pair uses the registered converter, not fallback."""

        class Custom:
            def __init__(self, val: int) -> None:
                self.val = val

        key = (int, Custom)
        TYPE_REGISTRY.convert(42, Custom)
        assert key in TypeRegistry.conversion_map

        entry = TypeRegistry.conversion_map[key]
        assert entry.func is Custom

        result = TYPE_REGISTRY.convert(99, Custom)
        assert isinstance(result, Custom)
        assert result.val == 99

    def test_snapshot_restore_clears_auto_registered_entries(self) -> None:
        """snapshot/restore removes auto-registered entries."""

        class Custom:
            def __init__(self, val: str) -> None:
                self.val = val

        snapshot = TypeRegistry.snapshot()
        TYPE_REGISTRY.convert("test", Custom)
        assert (str, Custom) in TypeRegistry.conversion_map

        TypeRegistry.restore(snapshot)
        assert (str, Custom) not in TypeRegistry.conversion_map

    def test_constructor_fallback_raises_for_unconvertible_types(self) -> None:
        """Constructor fallback still raises UnableToConvertValueError on failure."""

        class Strict:
            def __init__(self, val: str) -> None:
                raise TypeError("nope")

        with pytest.raises(UnableToConvertValueError):
            TYPE_REGISTRY.convert("hello", Strict)

        assert (str, Strict) not in TypeRegistry.conversion_map
