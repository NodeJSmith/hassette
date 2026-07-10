"""Tests for source_tier propagation through Resource hierarchy (#547).

Verifies:
- Resource defaults to source_tier='framework'
- App/AppSync override to source_tier='app'
- Bus.on() reads parent.source_tier and passes it to Listener
- Scheduler.schedule() reads parent.source_tier and passes it to ScheduledJob
- Service inherits 'framework' from Resource
"""

import typing
from unittest.mock import Mock

import pytest

from hassette.app.app import App, AppSync
from hassette.resources.base import Resource
from hassette.resources.service import Service
from hassette.scheduler.triggers import After
from hassette.test_utils.factories import make_mock_parent, make_scheduler
from hassette.test_utils.helpers import noop
from hassette.types.enums import ExecutionMode

if typing.TYPE_CHECKING:
    from hassette import HassetteConfig
    from hassette.bus.bus import Bus
    from hassette.test_utils.harness import HassetteHarness


class TestResourceSourceTierDefaults:
    def test_resource_defaults_to_framework(self) -> None:
        assert Resource.source_tier == "framework"

    def test_service_inherits_framework(self) -> None:
        assert Service.source_tier == "framework"

    def test_app_overrides_to_app(self) -> None:
        assert App.source_tier == "app"

    def test_app_sync_inherits_app(self) -> None:
        assert AppSync.source_tier == "app"


class TestResourceAppKey:
    def test_framework_resource_app_key_has_hassette_prefix(self) -> None:
        """Resource.app_key returns __hassette__.<ClassName>."""
        mock = Mock(spec=Resource)
        mock.class_name = "StateProxy"
        assert Resource.app_key.fget(mock) == "__hassette__.StateProxy"  # pyright: ignore[reportOptionalMemberAccess]


@pytest.fixture
async def framework_bus(
    hassette_harness: "typing.Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> "typing.AsyncIterator[Bus]":
    """Bus whose parent is a framework Resource (source_tier='framework').

    The harness's internal bus parent is Hassette, which inherits
    Resource.source_tier='framework' — no mock override needed.
    """
    async with hassette_harness(test_config).with_bus() as harness:
        yield harness.hassette._bus


@pytest.fixture
async def app_bus(
    hassette_harness: "typing.Callable[[HassetteConfig], HassetteHarness]",
    test_config: "HassetteConfig",
) -> "typing.AsyncIterator[Bus]":
    """Bus whose parent is an App (source_tier='app')."""
    async with hassette_harness(test_config).with_bus() as harness:
        bus = harness.hassette._bus
        bus.parent = make_mock_parent(source_tier="app", app_key="my_app", index=0, unique_name="MyApp.0")
        yield bus


async def handler(event: object) -> None:
    pass


class TestBusSourceTierPropagation:
    async def test_framework_bus_creates_framework_listener(self, framework_bus: "Bus") -> None:
        """Bus.on() with a framework parent passes source_tier='framework' to Listener."""
        sub = await framework_bus.on(topic="test.topic", handler=handler, name="framework_tier")
        assert sub.listener.identity.source_tier == "framework"

    async def test_app_bus_creates_app_listener(self, app_bus: "Bus") -> None:
        """Bus.on() with an app parent passes source_tier='app' to Listener."""
        sub = await app_bus.on(topic="test.topic", handler=handler, name="app_tier")
        assert sub.listener.identity.source_tier == "app"

    async def test_convenience_methods_propagate_tier(self, framework_bus: "Bus") -> None:
        """on_state_change and other convenience methods also propagate source_tier."""
        sub = await framework_bus.on_state_change("sensor.test", handler=handler, name="framework_tier_state")
        assert sub.listener.identity.source_tier == "framework"


class TestExecutionModeTierDefault:
    """The tier-aware default for ``mode``: app→single, framework→parallel."""

    async def test_app_registration_without_mode_defaults_to_single(self, app_bus: "Bus") -> None:
        """An app-tier registration without an explicit mode resolves to single."""
        sub = await app_bus.on(topic="test.topic", handler=handler, name="app_default_mode")
        assert sub.listener.options.mode is ExecutionMode.SINGLE

    async def test_framework_registration_without_mode_defaults_to_parallel(self, framework_bus: "Bus") -> None:
        """A framework-tier registration without an explicit mode resolves to parallel."""
        sub = await framework_bus.on(topic="test.topic", handler=handler, name="framework_default_mode")
        assert sub.listener.options.mode is ExecutionMode.PARALLEL

    async def test_explicit_mode_wins_over_tier_default(self, framework_bus: "Bus") -> None:
        """An explicit mode always wins over the tier default, even for framework listeners."""
        sub = await framework_bus.on(topic="test.topic", handler=handler, name="framework_explicit", mode="single")
        assert sub.listener.options.mode is ExecutionMode.SINGLE

    async def test_convenience_method_app_default_single(self, app_bus: "Bus") -> None:
        """on_state_change (typed method, mode via Options) also picks up the app-tier single default."""
        sub = await app_bus.on_state_change("sensor.test", handler=handler, name="app_state_default")
        assert sub.listener.options.mode is ExecutionMode.SINGLE

    async def test_invalid_mode_raises_at_registration(self, app_bus: "Bus") -> None:
        """An invalid mode string is rejected at registration time."""
        with pytest.raises(ValueError, match="Invalid execution mode"):
            await app_bus.on(topic="test.topic", handler=handler, name="bad_mode", mode="bogus")


class TestSchedulerSourceTierPropagation:
    async def test_framework_scheduler_creates_framework_job(self) -> None:
        """Scheduler.schedule() with a framework parent sets source_tier='framework'."""
        scheduler = make_scheduler(source_tier="framework", app_key="")
        job = await scheduler.schedule(noop, After(seconds=10))
        assert job.source_tier == "framework"

    async def test_app_scheduler_creates_app_job(self) -> None:
        """Scheduler.schedule() with an app parent sets source_tier='app'."""
        scheduler = make_scheduler(source_tier="app")
        job = await scheduler.schedule(noop, After(seconds=10))
        assert job.source_tier == "app"
