"""``set_app_status`` publishes each change to ``/ws`` clients directly, in write order (spec 160 D4)."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from hassette_wire import ResourceStatus

import hassette.core.app_lifecycle_instances as instances_module
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import AppRegistry, StatusChange
from hassette.core.runtime_query_service import RuntimeQueryService
from tests.support.web_mocks import create_mock_runtime_query_service

from .conftest import make_app_instance

APP_KEY = "porch"


@pytest.fixture
def steps(real_registry_service: AppLifecycleService, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    """Each publish, lifecycle row and bus send, in call order."""
    order: list[tuple[str, object]] = []
    runtime = MagicMock()
    runtime.publish_app_status.side_effect = lambda change: order.append(("publish", change))
    real_registry_service.hassette._runtime_query_service = runtime
    monkeypatch.setattr(instances_module, "record_app_change", lambda _h, change: order.append(("row", change)))
    real_registry_service.hassette.send_event = AsyncMock(side_effect=lambda event: order.append(("send", event)))
    return order


async def test_publishes_each_change_before_the_row_and_the_bus_send(
    real_registry_service: AppLifecycleService, steps: list[tuple[str, object]]
) -> None:
    app = make_app_instance(APP_KEY, "main")
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.NOT_STARTED, app=app)
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)  # no change, no publish
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.RUNNING)

    assert [step for step, _ in steps] == ["publish", "row", "send"] * 2
    published = [change for step, change in steps if step == "publish" and isinstance(change, StatusChange)]
    revisions = [change.status_revision for change in published]
    assert len(revisions) == 2
    assert revisions[0] < revisions[1]


async def test_a_publish_failure_is_logged_and_the_change_still_lands(
    real_registry_service: AppLifecycleService, steps: list[tuple[str, object]], caplog: pytest.LogCaptureFixture
) -> None:
    real_registry_service.hassette._runtime_query_service = MagicMock(
        publish_app_status=MagicMock(side_effect=RuntimeError("publish broke"))
    )
    app = make_app_instance(APP_KEY, "main")

    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.NOT_STARTED, app=app)
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)

    assert real_registry_service.registry.get_status(APP_KEY, "main") is ResourceStatus.STARTING
    assert [step for step, _ in steps] == ["row", "send"]
    assert "Failed to publish the starting change" in caplog.text


async def test_no_runtime_query_service_sends_nothing_to_clients(
    real_registry_service: AppLifecycleService, steps: list[tuple[str, object]]
) -> None:
    real_registry_service.hassette._runtime_query_service = None
    app = make_app_instance(APP_KEY, "main")

    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.NOT_STARTED, app=app)
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)

    assert [step for step, _ in steps] == ["row", "send"]


def fail_on_stale_publish(runtime: RuntimeQueryService, registry: AppRegistry) -> list[int]:
    """Wrap ``runtime.publish_app_status`` to record each change published after a later write already landed.

    The registry's revision at publish time equals the change's only if nothing ran between ``set_status`` and the
    publish, which is D4's guarantee; an await added there lets the other writer's write land in between.
    """
    stale: list[int] = []
    real_publish = runtime.publish_app_status

    def publish(change: StatusChange) -> None:
        if registry.status_revision != change.status_revision:
            stale.append(change.status_revision)
        real_publish(change)

    runtime.publish_app_status = publish
    return stale


async def test_interleaved_writers_reach_a_client_queue_in_revision_order(
    real_registry_service: AppLifecycleService,
) -> None:
    """D4's guarantee is structural: no await between ``set_status`` and the publish, so no writer can overtake."""
    hassette = cast("MagicMock", real_registry_service.hassette)
    runtime = create_mock_runtime_query_service(hassette)
    hassette.integration_service.boot_id = "boot"
    queue = await runtime.register_ws_client()
    stale_publishes = fail_on_stale_publish(runtime, real_registry_service.registry)

    async def yielding_send(_event: object) -> None:
        await asyncio.sleep(0)  # every bus send suspends, so the two writers interleave

    hassette.send_event = AsyncMock(side_effect=yielding_send)

    async def writer(instance_name: str) -> None:
        # Registration onto a missing entry bumps the revision but returns no change, so it publishes nothing;
        # each writer publishes STARTING, then RUNNING.
        app = make_app_instance(APP_KEY, instance_name)
        await real_registry_service.set_app_status(APP_KEY, instance_name, ResourceStatus.NOT_STARTED, app=app)
        await real_registry_service.set_app_status(APP_KEY, instance_name, ResourceStatus.STARTING)
        await real_registry_service.set_app_status(APP_KEY, instance_name, ResourceStatus.RUNNING)

    await asyncio.gather(writer("a"), writer("b"))

    assert stale_publishes == [], "another write landed between set_status and its publish"
    messages = []
    while not queue.empty():
        messages.append(queue.get_nowait())
    deltas = [message["data"] for message in messages if message["type"] == "app_status_changed"]
    assert [delta["instance_name"] for delta in deltas] == ["a", "b", "a", "b"], "the writers did not interleave"
    revisions = [delta["status_revision"] for delta in deltas]
    assert revisions == sorted(set(revisions))
