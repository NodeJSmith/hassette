from hassette import ResourceStatus
from hassette.events import (
    AppStateChangePayload,
    HassetteAppStateEvent,
    HassettePayload,
)
from hassette.testing import AppTestHarness
from hassette.types import Topic

from my_apps.upstream_watcher import UpstreamWatcher


async def test_watcher_reacts_when_upstream_app_starts():
    async with AppTestHarness(
        UpstreamWatcher, config={"instance_name": "upstream_watcher"}
    ) as harness:
        event = HassetteAppStateEvent(
            topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED,
            payload=HassettePayload(
                data=AppStateChangePayload(
                    app_key="upstream", index=0, status=ResourceStatus.RUNNING
                ),
            ),
        )

        await harness.simulate_event(event)

        assert harness.app.upstream_ready == ["upstream"]
