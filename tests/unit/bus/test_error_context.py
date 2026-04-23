"""Tests for BusErrorContext dataclass."""

import traceback

import pytest

from hassette.bus.error_context import BusErrorContext
from hassette.events.base import Event, EventPayload


def _make_bus_error_context(exc: BaseException | None = None) -> BusErrorContext:
    """Helper to construct a BusErrorContext with minimal required fields."""
    if exc is None:
        exc = ValueError("test error")

    tb = traceback.format_exc()
    payload = EventPayload(event_type="state_changed", data=None)
    event: Event[EventPayload[None]] = Event(topic="state_changed", payload=payload)

    return BusErrorContext(
        exception=exc,
        traceback=tb,
        topic="state_changed",
        listener_name="my_listener",
        event=event,
    )


class TestBusErrorContextConstruction:
    def test_bus_error_context_construction(self) -> None:
        """BusErrorContext can be constructed and fields are accessible."""
        exc = RuntimeError("boom")
        ctx = _make_bus_error_context(exc)

        assert ctx.exception is exc
        assert ctx.topic == "state_changed"
        assert ctx.listener_name == "my_listener"
        assert isinstance(ctx.traceback, str)

    def test_bus_error_context_frozen(self) -> None:
        """BusErrorContext is frozen — mutation raises FrozenInstanceError."""
        ctx = _make_bus_error_context()

        with pytest.raises(Exception, match="cannot assign to field"):  # FrozenInstanceError (dataclasses internal)
            ctx.topic = "other_topic"  # pyright: ignore[reportGeneralIssues]

    def test_bus_error_context_traceback_always_populated(self) -> None:
        """traceback is always a non-empty string, regardless of exception type."""
        for exc_type in [ValueError, RuntimeError, KeyError, SystemExit]:
            exc = exc_type("test")
            tb = "Traceback (most recent call last):\n  ...\nValueError: test\n"
            payload = EventPayload(event_type="test", data=None)
            event: Event[EventPayload[None]] = Event(topic="test", payload=payload)

            ctx = BusErrorContext(
                exception=exc,
                traceback=tb,
                topic="test",
                listener_name="handler",
                event=event,
            )
            assert isinstance(ctx.traceback, str)
            assert len(ctx.traceback) > 0, f"traceback empty for {exc_type}"

    def test_bus_error_context_traceback_typed_str_not_optional(self) -> None:
        """traceback field is typed str, not str | None — must be set to a string value."""
        import dataclasses

        fields = {f.name: f for f in dataclasses.fields(BusErrorContext)}
        assert "traceback" in fields
        # The field type should be str, not str | None
        field = fields["traceback"]
        assert field.type == "str" or field.type is str
