"""Integration tests for ``AppTestHarness.simulate_event`` — arbitrary event dispatch and drain."""

import pytest
from hassette_wire import ResourceStatus

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.events import AppStateChangePayload, HassetteAppStateEvent, HassettePayload
from hassette.testing import AppTestHarness
from hassette.types import Topic


class WatcherConfig(AppConfig):
    """Minimal config for the watcher app."""


class UpstreamWatcher(App[WatcherConfig]):
    """Reacts when a different app, ``upstream``, reaches RUNNING."""

    upstream_ready: list[str]

    async def on_initialize(self) -> None:
        self.upstream_ready = []
        await self.bus.on_app_running(handler=self.on_upstream_running, app_key="upstream", name="upstream_running")

    async def on_upstream_running(self, event: HassetteAppStateEvent) -> None:
        self.upstream_ready.append(event.payload.data.app_key)


def make_app_state_event(app_key: str, status: ResourceStatus) -> HassetteAppStateEvent:
    return HassetteAppStateEvent(
        topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED,
        payload=HassettePayload(data=AppStateChangePayload(app_key=app_key, index=0, status=status)),
    )


async def test_simulate_event_drives_cross_app_lifecycle_listener() -> None:
    """A listener filtered on another app's key fires for a hand-built event, drained before return."""
    async with AppTestHarness(UpstreamWatcher, config={}) as harness:
        event = make_app_state_event("upstream", ResourceStatus.RUNNING)

        returned = await harness.simulate_event(event)

        assert returned is event
        assert harness.app.upstream_ready == ["upstream"]


async def test_simulate_event_ignores_other_app_keys() -> None:
    """The app_key filter still applies to events dispatched through simulate_event."""
    async with AppTestHarness(UpstreamWatcher, config={}) as harness:
        await harness.simulate_event(make_app_state_event("someone_else", ResourceStatus.RUNNING))

        assert harness.app.upstream_ready == []


async def test_simulate_event_outside_context_raises() -> None:
    """Calling simulate_event on a harness that was never entered fails with a clear error."""
    harness = AppTestHarness(UpstreamWatcher, config={})

    with pytest.raises(RuntimeError, match="not active"):
        await harness.simulate_event(make_app_state_event("upstream", ResourceStatus.RUNNING))
