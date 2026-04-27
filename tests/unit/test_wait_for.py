"""Unit tests for the wait_for polling utility."""

import asyncio

import pytest

from hassette.test_utils.harness import wait_for


class TestWaitForSync:
    async def test_returns_when_predicate_is_true(self) -> None:
        await wait_for(lambda: True, timeout=1.0, desc="always true")

    async def test_raises_on_timeout(self) -> None:
        with pytest.raises(TimeoutError, match="never true"):
            await wait_for(lambda: False, timeout=0.05, desc="never true")

    async def test_polls_until_predicate_becomes_true(self) -> None:
        counter = {"n": 0}

        def predicate() -> bool:
            counter["n"] += 1
            return counter["n"] >= 3

        await wait_for(predicate, timeout=1.0, interval=0.01, desc="counter")


class TestWaitForAsync:
    async def test_accepts_async_predicate(self) -> None:
        async def predicate() -> bool:
            return True

        await wait_for(predicate, timeout=1.0, desc="async true")

    async def test_async_predicate_timeout(self) -> None:
        async def predicate() -> bool:
            return False

        with pytest.raises(TimeoutError, match="async never"):
            await wait_for(predicate, timeout=0.05, desc="async never")

    async def test_async_predicate_polls_until_true(self) -> None:
        counter = {"n": 0}

        async def predicate() -> bool:
            await asyncio.sleep(0)
            counter["n"] += 1
            return counter["n"] >= 3

        await wait_for(predicate, timeout=1.0, interval=0.01, desc="async counter")
