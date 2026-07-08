"""Tests for bus where= predicate hardening: async rejection and raising-predicate isolation.

Covers:
- normalize_where() rejects async callables at registration time (#1243 part B, #1244)
- compare_value() rejects async callable instances (#1244)
- Listener.matches() catches raising predicates and returns False (#1243 part A)
- wait_for() detects async callable instances (#1244)
"""

from types import SimpleNamespace

import pytest

from hassette.event_handling.predicates import compare_value, normalize_where
from hassette.test_utils.harness import wait_for
from hassette.test_utils.helpers import create_listener


class TestNormalizeWhereAsyncRejection:
    """normalize_where() rejects async callable predicates at registration time."""

    def test_async_function_raises_type_error(self) -> None:
        async def pred(_ev: object) -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(pred)

    def test_async_callable_instance_raises_type_error(self) -> None:
        class AsyncPred:
            async def __call__(self, _ev: object) -> bool:
                return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where(AsyncPred())

    def test_sequence_with_async_member_raises_type_error(self) -> None:
        def sync_pred(_ev: object) -> bool:
            return True

        async def async_pred(_ev: object) -> bool:
            return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where([sync_pred, async_pred])

    def test_sequence_with_async_callable_instance_raises_type_error(self) -> None:
        def sync_pred(_ev: object) -> bool:
            return True

        class AsyncPred:
            async def __call__(self, _ev: object) -> bool:
                return True

        with pytest.raises(TypeError, match="synchronous"):
            normalize_where([sync_pred, AsyncPred()])

    def test_sync_callable_passes(self) -> None:
        def pred(_ev: object) -> bool:
            return True

        result = normalize_where(pred)
        assert result is pred

    def test_none_passes(self) -> None:
        assert normalize_where(None) is None


class TestCompareValueAsyncCallableInstance:
    """compare_value() rejects async callable instances, not just async def functions."""

    def test_async_callable_instance_raises_type_error(self) -> None:
        class AsyncCondition:
            async def __call__(self, _value: object) -> bool:
                return True

        with pytest.raises(TypeError, match="Async predicates are not supported"):
            compare_value("x", AsyncCondition())


class TestListenerMatchesRaisingPredicate:
    """Listener.matches() catches raising predicates and returns False."""

    def test_raising_predicate_returns_false(self) -> None:
        def bad_pred(_ev: object) -> bool:
            raise ValueError("boom")

        listener = create_listener(where=bad_pred)
        ev = SimpleNamespace(payload=SimpleNamespace())

        assert listener.matches(ev) is False

    def test_raising_predicate_does_not_propagate(self) -> None:
        def bad_pred(_ev: object) -> bool:
            raise RuntimeError("unexpected")

        listener = create_listener(where=bad_pred)
        ev = SimpleNamespace(payload=SimpleNamespace())

        # Should not raise — exception is caught and logged
        listener.matches(ev)

    def test_normal_predicate_still_works(self) -> None:
        def good_pred(_ev: object) -> bool:
            return True

        listener = create_listener(where=good_pred)
        ev = SimpleNamespace(payload=SimpleNamespace())

        assert listener.matches(ev) is True

    def test_false_predicate_still_works(self) -> None:
        def reject_pred(_ev: object) -> bool:
            return False

        listener = create_listener(where=reject_pred)
        ev = SimpleNamespace(payload=SimpleNamespace())

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
