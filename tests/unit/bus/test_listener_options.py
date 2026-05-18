"""Unit tests for ListenerOptions sub-struct."""

import pytest

from hassette.bus.listeners import ListenerOptions


class TestListenerOptionsConstruction:
    def test_default_construction(self) -> None:
        """ListenerOptions() with no arguments uses all defaults."""
        opts = ListenerOptions()
        assert opts.once is False
        assert opts.debounce is None
        assert opts.throttle is None
        assert opts.timeout is None
        assert opts.timeout_disabled is False
        assert opts.priority == 0

    def test_set_once(self) -> None:
        opts = ListenerOptions(once=True)
        assert opts.once is True

    def test_set_debounce(self) -> None:
        opts = ListenerOptions(debounce=1.5)
        assert opts.debounce == 1.5

    def test_set_throttle(self) -> None:
        opts = ListenerOptions(throttle=2.0)
        assert opts.throttle == 2.0

    def test_set_timeout(self) -> None:
        opts = ListenerOptions(timeout=30.0)
        assert opts.timeout == 30.0

    def test_set_timeout_disabled(self) -> None:
        opts = ListenerOptions(timeout_disabled=True)
        assert opts.timeout_disabled is True

    def test_set_priority(self) -> None:
        opts = ListenerOptions(priority=5)
        assert opts.priority == 5

    def test_has_slots(self) -> None:
        opts = ListenerOptions()
        assert hasattr(type(opts), "__slots__")


class TestListenerOptionsValidation:
    def test_debounce_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="debounce"):
            ListenerOptions(debounce=0)

    def test_debounce_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="debounce"):
            ListenerOptions(debounce=-1.0)

    def test_debounce_positive_ok(self) -> None:
        opts = ListenerOptions(debounce=0.1)
        assert opts.debounce == 0.1

    def test_throttle_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="throttle"):
            ListenerOptions(throttle=0)

    def test_throttle_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="throttle"):
            ListenerOptions(throttle=-0.5)

    def test_throttle_positive_ok(self) -> None:
        opts = ListenerOptions(throttle=0.5)
        assert opts.throttle == 0.5

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

    def test_timeout_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="timeout"):
            ListenerOptions(timeout=0)

    def test_timeout_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="timeout"):
            ListenerOptions(timeout=-1.0)

    def test_timeout_bool_raises(self) -> None:
        """timeout=True is invalid (it's a bool, not a number)."""
        with pytest.raises(ValueError, match="timeout"):
            ListenerOptions(timeout=True)

    def test_timeout_and_timeout_disabled_conflict(self) -> None:
        with pytest.raises(ValueError, match="timeout"):
            ListenerOptions(timeout=5.0, timeout_disabled=True)

    def test_valid_timeout_ok(self) -> None:
        opts = ListenerOptions(timeout=10.0)
        assert opts.timeout == 10.0
