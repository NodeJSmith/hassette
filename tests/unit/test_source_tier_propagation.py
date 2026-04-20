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
from hassette.resources.base import Resource, Service
from hassette.scheduler.triggers import After

if typing.TYPE_CHECKING:
    from hassette import HassetteConfig
    from hassette.bus.bus import Bus
    from hassette.scheduler.scheduler import Scheduler
    from hassette.test_utils.harness import HassetteHarness


# ---------------------------------------------------------------------------
# Resource hierarchy — ClassVar defaults
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Bus.on() propagation
# ---------------------------------------------------------------------------


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
        mock_parent = Mock()
        mock_parent.source_tier = "app"
        mock_parent.app_key = "my_app"
        mock_parent.index = 0
        mock_parent.unique_name = "MyApp.0"
        bus.parent = mock_parent
        yield bus


async def _handler(event: object) -> None:
    pass


class TestBusSourceTierPropagation:
    async def test_framework_bus_creates_framework_listener(self, framework_bus: "Bus") -> None:
        """Bus.on() with a framework parent passes source_tier='framework' to Listener."""
        sub = framework_bus.on(topic="test.topic", handler=_handler)
        assert sub.listener.source_tier == "framework"

    async def test_app_bus_creates_app_listener(self, app_bus: "Bus") -> None:
        """Bus.on() with an app parent passes source_tier='app' to Listener."""
        sub = app_bus.on(topic="test.topic", handler=_handler)
        assert sub.listener.source_tier == "app"

    async def test_convenience_methods_propagate_tier(self, framework_bus: "Bus") -> None:
        """on_state_change and other convenience methods also propagate source_tier."""
        sub = framework_bus.on_state_change("sensor.test", handler=_handler)
        assert sub.listener.source_tier == "framework"


# ---------------------------------------------------------------------------
# Scheduler.schedule() propagation
# ---------------------------------------------------------------------------


def _make_scheduler_with_parent(source_tier: str) -> "Scheduler":
    """Create a minimal Scheduler with a mocked parent at the given source_tier."""
    from hassette.scheduler.scheduler import Scheduler

    _TestScheduler = type("_TestScheduler", (Scheduler,), {})  # noqa: N806

    mock_parent = Mock()
    mock_parent.source_tier = source_tier
    mock_parent.app_key = "test_app" if source_tier == "app" else ""
    mock_parent.index = 0
    mock_parent.unique_name = "TestParent"

    _TestScheduler.owner_id = property(lambda _self: "test_owner")  # pyright: ignore[reportAttributeAccessIssue]
    _TestScheduler.parent = property(lambda _self: mock_parent)  # pyright: ignore[reportAttributeAccessIssue]

    scheduler = _TestScheduler.__new__(_TestScheduler)
    mock_service = Mock()
    mock_service.register_removal_callback = Mock()
    mock_service.dequeue_job = Mock(side_effect=lambda job: setattr(job, "_dequeued", True) or True)
    scheduler.scheduler_service = mock_service
    scheduler._jobs_by_name = {}
    scheduler._jobs_by_group = {}
    return scheduler


async def _job_fn() -> None:
    pass


class TestSchedulerSourceTierPropagation:
    def test_framework_scheduler_creates_framework_job(self) -> None:
        """Scheduler.schedule() with a framework parent sets source_tier='framework'."""
        scheduler = _make_scheduler_with_parent("framework")
        job = scheduler.schedule(_job_fn, After(seconds=10))
        assert job.source_tier == "framework"

    def test_app_scheduler_creates_app_job(self) -> None:
        """Scheduler.schedule() with an app parent sets source_tier='app'."""
        scheduler = _make_scheduler_with_parent("app")
        job = scheduler.schedule(_job_fn, After(seconds=10))
        assert job.source_tier == "app"
