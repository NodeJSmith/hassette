"""Concurrency tests for AppTestHarness (#567).

Verifies that two harnesses for the same App class can run concurrently
via asyncio.gather without deadlock, manifest corruption, or app_key
cross-contamination.
"""

import asyncio
from typing import Any

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.test_utils.app_harness import AppTestHarness


class ConcurrencyConfig(AppConfig):
    test_entity: str = "sensor.test"


class ConcurrencyApp(App[ConcurrencyConfig]):
    async def on_initialize(self) -> None:
        pass


class AltConfig(AppConfig):
    alt_entity: str = "sensor.alt"


class AltApp(App[AltConfig]):
    async def on_initialize(self) -> None:
        pass


async def test_concurrent_same_class_no_deadlock():
    """Two harnesses for the same App class complete via asyncio.gather without deadlock."""

    async def run_harness() -> str:
        async with AppTestHarness(ConcurrencyApp, config={}) as harness:
            return harness.app.app_key

    results = await asyncio.wait_for(asyncio.gather(run_harness(), run_harness()), timeout=15)
    assert len(results) == 2
    assert all(r == "concurrency_app" for r in results)


async def test_concurrent_same_class_manifest_restored():
    """app_manifest is restored after concurrent harnesses exit."""
    original = getattr(ConcurrencyApp, "app_manifest", AppTestHarness._UNSET)

    async def run_harness() -> None:
        async with AppTestHarness(ConcurrencyApp, config={}):
            pass

    await asyncio.wait_for(asyncio.gather(run_harness(), run_harness()), timeout=15)

    restored = getattr(ConcurrencyApp, "app_manifest", AppTestHarness._UNSET)
    assert restored is original


async def test_concurrent_same_class_app_key_isolation():
    """Each concurrent harness gets the correct app_key for its class."""
    keys: list[str] = []

    async def run_harness() -> None:
        async with AppTestHarness(ConcurrencyApp, config={}) as harness:
            keys.append(harness.app.app_key)

    await asyncio.wait_for(asyncio.gather(run_harness(), run_harness()), timeout=15)
    assert all(k == "concurrency_app" for k in keys)


async def test_concurrent_different_classes_no_conflict():
    """Two harnesses for different App classes run concurrently without conflict."""
    results: dict[str, str] = {}

    async def run_a() -> None:
        async with AppTestHarness(ConcurrencyApp, config={}) as h:
            results["a"] = h.app.app_key

    async def run_b() -> None:
        async with AppTestHarness(AltApp, config={}) as h:
            results["b"] = h.app.app_key

    await asyncio.wait_for(asyncio.gather(run_a(), run_b()), timeout=15)
    assert results["a"] == "concurrency_app"
    assert results["b"] == "alt_app"


async def test_sequential_then_concurrent_no_leak():
    """Sequential harness followed by concurrent harnesses — no state leak between runs."""
    async with AppTestHarness(ConcurrencyApp, config={}) as h1:
        assert h1.app.app_key == "concurrency_app"

    captured: list[Any] = []

    async def run_harness() -> None:
        async with AppTestHarness(ConcurrencyApp, config={}) as h:
            captured.append(h.app.app_key)

    await asyncio.wait_for(asyncio.gather(run_harness(), run_harness()), timeout=15)
    assert len(captured) == 2
    assert all(k == "concurrency_app" for k in captured)

    assert "app_manifest" not in ConcurrencyApp.__dict__
