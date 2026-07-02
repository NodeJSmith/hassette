"""Unit tests for ListenerOptions sub-struct."""

import pytest

from hassette.bus.listeners import ListenerOptions


class TestListenerOptionsConstruction:
    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("once", False),
            ("debounce", None),
            ("throttle", None),
            ("timeout", None),
            ("timeout_disabled", False),
            ("priority", 0),
        ],
    )
    def test_default_values(self, field: str, expected: object) -> None:
        opts = ListenerOptions()
        assert getattr(opts, field) == expected

    @pytest.mark.parametrize(
        ("field", "value", "expected"),
        [
            ("once", True, True),
            ("debounce", 1.5, 1.5),
            ("throttle", 2.0, 2.0),
            ("timeout", 30.0, 30.0),
            ("timeout_disabled", True, True),
            ("priority", 5, 5),
        ],
    )
    def test_set_field(self, field: str, value: object, expected: object) -> None:
        opts = ListenerOptions(**{field: value})
        assert getattr(opts, field) == expected

    def test_has_slots(self) -> None:
        opts = ListenerOptions()
        assert hasattr(type(opts), "__slots__")


class TestListenerOptionsValidation:
    @pytest.mark.parametrize(
        ("field", "invalid_value"),
        [
            ("debounce", 0),
            ("debounce", -1.0),
            ("throttle", 0),
            ("throttle", -0.5),
            ("timeout", 0),
            ("timeout", -1.0),
        ],
    )
    def test_rate_limit_and_timeout_must_be_positive(self, field: str, invalid_value: float) -> None:
        with pytest.raises(ValueError, match=field):
            ListenerOptions(**{field: invalid_value})

    @pytest.mark.parametrize(
        ("field", "valid_value"),
        [
            ("debounce", 0.1),
            ("throttle", 0.5),
            ("timeout", 10.0),
        ],
    )
    def test_positive_values_accepted(self, field: str, valid_value: float) -> None:
        opts = ListenerOptions(**{field: valid_value})
        assert getattr(opts, field) == valid_value

    def test_debounce_and_throttle_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError, match=r"debounce.*throttle|throttle.*debounce|both"):
            ListenerOptions(debounce=1.0, throttle=1.0)

    def test_once_with_debounce_raises(self) -> None:
        with pytest.raises(ValueError, match="once"):
            ListenerOptions(once=True, debounce=1.0)

    def test_once_with_throttle_raises(self) -> None:
        with pytest.raises(ValueError, match="once"):
            ListenerOptions(once=True, throttle=1.0)

    def test_once_without_rate_limiting_ok(self) -> None:
        opts = ListenerOptions(once=True)
        assert opts.once is True

    def test_timeout_bool_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout"):
            ListenerOptions(timeout=True)

    def test_timeout_and_timeout_disabled_conflict(self) -> None:
        with pytest.raises(ValueError, match="timeout"):
            ListenerOptions(timeout=5.0, timeout_disabled=True)

    def test_invalid_mode_string_raises_value_error(self) -> None:
        """An unknown mode string raises ValueError listing the valid execution modes."""
        with pytest.raises(ValueError, match="bogus_mode") as exc_info:
            ListenerOptions(mode="bogus_mode")
        error_msg = str(exc_info.value)
        assert "single" in error_msg
        assert "restart" in error_msg
        assert "queued" in error_msg
        assert "parallel" in error_msg
