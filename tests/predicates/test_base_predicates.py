# pyright: reportInvalidTypeArguments=none, reportArgumentType=none
import asyncio
from types import SimpleNamespace
from typing import Any

from hassette.core.resources.bus.predicates import Guard
from hassette.core.resources.bus.predicates.base import AllOf, AnyOf, Not
from hassette.core.resources.bus.predicates.utils import normalize_where


async def test_allof_waits_for_all_predicates() -> None:
    """AllOf evaluates every predicate and only succeeds when all succeed."""
    event = SimpleNamespace(flag=True)

    async def async_predicate(evt: Any) -> bool:
        await asyncio.sleep(0)
        return evt.flag

    predicate = AllOf((lambda _: True, async_predicate))
    assert await predicate(event) is True


async def test_allof_is_false_if_any_predicate_fails() -> None:
    """AllOf evaluates every predicate and fails if any fail."""
    event = SimpleNamespace(flag=False)

    async def async_predicate(evt: Any) -> bool:
        await asyncio.sleep(0)
        return evt.flag

    predicate = AllOf((lambda _: True, async_predicate))
    assert await predicate(event) is False


async def test_anyof_passes_when_any_predicate_matches() -> None:
    """AnyOf resolves true as soon as one predicate passes."""
    event = SimpleNamespace(value=2)
    predicate = AnyOf((lambda evt: evt.value == 2, lambda evt: evt.value == 3))
    assert await predicate(event) is True


async def test_anyof_fails_when_no_predicates_match() -> None:
    """AnyOf resolves false when all predicates fail."""
    event = SimpleNamespace(value=1)
    predicate = AnyOf((lambda evt: evt.value == 2, lambda evt: evt.value == 3))
    assert await predicate(event) is False


async def test_not_inverts_predicate_result() -> None:
    """Not negates the wrapped predicate."""
    event = SimpleNamespace(active=False)
    predicate = Not(lambda evt: evt.active)
    assert await predicate(event) is True


async def test_guard_wraps_callable() -> None:
    """Guard wraps arbitrary callables and supports async evaluation."""

    async def async_checker(evt: Any) -> bool:
        await asyncio.sleep(0)
        return evt.status == "ok"

    guard = Guard(async_checker)
    event = SimpleNamespace(status="ok")
    assert await guard(event) is True


def test_normalize_where_handles_sequences() -> None:
    """normalize_where consolidates iterables into AllOf."""
    predicate = normalize_where([lambda _: True, lambda _: False])
    assert isinstance(predicate, AllOf)


def test_normalize_where_handles_single_predicate() -> None:
    """normalize_where returns single predicates as-is."""

    def single(_: Any) -> bool:
        return True

    predicate = normalize_where(single)
    assert predicate is single
