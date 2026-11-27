"""Tests for bus where= predicate hardening: async rejection and raising-predicate isolation.

Covers:
- normalize_where() rejects async callables at registration time (#1243 part B, #1244)
- compare_value() rejects async callable instances (#1244)
- Listener.matches() catches raising predicates and returns False (#1243 part A)
- wait_for() detects async callable instances (#1244)
"""

import typing

import pytest

from hassette.event_handling import predicates as P
from hassette.event_handling.predicates import compare_value, normalize_where
from hassette.testing import wait_for
from tests.support.factories import make_mock_event
from tests.support.helpers import create_listener
from tests.unit.bus.conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus


async def async_check(_ev: object) -> bool:
    return False


async def noop_handler() -> None:
    pass


class TestNormalizeWhereAsyncRejection:
    """normalize_where() rejects async callable predicates at registration time."""

    def test_async_function_raises_type_error(self) -> None:
        async def pred(_ev: object) -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(pred)  # pyright: ignore[reportArgumentType]

    def test_async_callable_instance_raises_type_error(self) -> None:
        class AsyncPred:
            async def __call__(self, _ev: object) -> bool:
                return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(AsyncPred())  # pyright: ignore[reportArgumentType]

    def test_sequence_with_async_member_raises_type_error(self) -> None:
        def sync_pred(_ev: object) -> bool:
            return True

        async def async_pred(_ev: object) -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where([sync_pred, async_pred])  # pyright: ignore[reportArgumentType]

    def test_sequence_with_async_callable_instance_raises_type_error(self) -> None:
        def sync_pred(_ev: object) -> bool:
            return True

        class AsyncPred:
            async def __call__(self, _ev: object) -> bool:
                return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where([sync_pred, AsyncPred()])  # pyright: ignore[reportArgumentType]

    def test_sync_callable_passes(self) -> None:
        def pred(_ev: object) -> bool:
            return True

        result = normalize_where(pred)
        assert result is pred

    def test_none_passes(self) -> None:
        assert normalize_where(None) is None

    def test_and_composition_with_async_member_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(P.StateTo("on") & async_check)  # pyright: ignore[reportOperatorIssue]

    def test_any_of_nested_in_all_of_with_async_member_raises_type_error(self) -> None:
        nested = P.AllOf((P.StateTo("on"), P.AnyOf((P.StateFrom("off"), async_check))))  # pyright: ignore[reportArgumentType]
        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(nested)

    def test_not_wrapping_async_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(P.Not(async_check))  # pyright: ignore[reportArgumentType]

    def test_guard_wrapping_async_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(P.Guard(async_check))  # pyright: ignore[reportArgumentType]

    def test_sync_composition_passes(self) -> None:
        where = P.StateTo("on") & ~P.StateFrom("off")
        assert normalize_where(where) is where


async def test_on_state_change_where_list_with_async_member_raises_type_error(bus: "Bus") -> None:
    """on_state_change pre-wraps where= lists in AllOf; the async member is still rejected at registration."""
    with mock_add_listener(bus), pytest.raises(TypeError, match="synchronous"):
        await bus.on_state_change(
            "light.kitchen",
            handler=noop_handler,
            name="async_where",
            where=[async_check],  # pyright: ignore[reportArgumentType]
        )


class TestCompareValueAsyncCallableInstance:
    """compare_value() rejects async callable instances, not just async def functions."""

    def test_async_callable_instance_raises_type_error(self) -> None:
        class AsyncCondition:
            async def __call__(self, _value: object) -> bool:
                return True

        with pytest.raises(TypeError, match="Async predicates are not supported"):
            compare_value("x", AsyncCondition())


class TestListenerMatchesRaisingPredicate:
    """Listener.matches() propagates raising predicates to the caller.

    BusService.dispatch() is responsible for isolation, telemetry recording,
    and error-handler routing (#1255).
    """

    def test_raising_predicate_propagates(self) -> None:
        def bad_pred(_ev: object) -> bool:
            raise ValueError("boom")

        listener = create_listener(where=bad_pred)
        ev = make_mock_event()

        with pytest.raises(ValueError, match="boom"):
            listener.matches(ev)

    def test_raising_predicate_preserves_exception_type(self) -> None:
        def bad_pred(_ev: object) -> bool:
            raise RuntimeError("unexpected")

        listener = create_listener(where=bad_pred)
        ev = make_mock_event()

        with pytest.raises(RuntimeError, match="unexpected"):
            listener.matches(ev)

    def test_normal_predicate_still_works(self) -> None:
        def good_pred(_ev: object) -> bool:
            return True

        listener = create_listener(where=good_pred)
        ev = make_mock_event()

        assert listener.matches(ev) is True

    def test_false_predicate_still_works(self) -> None:
        def reject_pred(_ev: object) -> bool:
            return False

        listener = create_listener(where=reject_pred)
        ev = make_mock_event()

        assert listener.matches(ev) is False


class TestWaitForAsyncCallableInstance:
    """wait_for() correctly detects async callable instances."""

    async def test_async_callable_instance_detected(self) -> None:
        call_count = 0

        class AsyncPred:
            async def __call__(self) -> bool:
                nonlocal call_count
                call_count += 1
                return True

        await wait_for(AsyncPred(), timeout=1.0, desc="async callable instance")
        assert call_count >= 1

    async def test_sync_callable_instance_works(self) -> None:
        class SyncPred:
            def __call__(self) -> bool:
                return True

        await wait_for(SyncPred(), timeout=1.0, desc="sync callable instance")
