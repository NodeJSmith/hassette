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
def runtime(real_registry_service: AppLifecycleService) -> RuntimeQueryService:
    """A real ``RuntimeQueryService`` wired to the registry service's hassette."""
    hassette = cast("MagicMock", real_registry_service.hassette)
    hassette.integration_service.boot_id = "boot"
    return create_mock_runtime_query_service(hassette)


@pytest.fixture
def steps(
    real_registry_service: AppLifecycleService, runtime: RuntimeQueryService, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[str, object]]:
    """Each publish, lifecycle row and bus send, in call order; publishes still reach the real client queues."""
    order: list[tuple[str, object]] = []
    real_publish = runtime.publish_app_status

    def publish(change: StatusChange) -> None:
        order.append(("publish", change))
        real_publish(change)

    runtime.publish_app_status = publish
    monkeypatch.setattr(instances_module, "record_app_change", lambda _h, change: order.append(("row", change)))
    real_registry_service.hassette.send_event = AsyncMock(side_effect=lambda event: order.append(("send", event)))
    return order


def drain(queue: asyncio.Queue) -> list[dict]:
    messages = []
    while not queue.empty():
        messages.append(queue.get_nowait())
    return messages


async def test_publishes_each_change_before_the_row_and_the_bus_send(
    real_registry_service: AppLifecycleService, runtime: RuntimeQueryService, steps: list[tuple[str, object]]
) -> None:
    queue = await runtime.register_ws_client()
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
    deltas = [message["data"] for message in drain(queue) if message["type"] == "app_status_changed"]
    assert [(delta["status"], delta["status_revision"]) for delta in deltas] == [
        (ResourceStatus.STARTING, revisions[0]),
        (ResourceStatus.RUNNING, revisions[1]),
    ]


async def test_a_publish_failure_does_not_stop_the_change_landing(
    real_registry_service: AppLifecycleService, steps: list[tuple[str, object]]
) -> None:
    real_registry_service.hassette._runtime_query_service = MagicMock(
        publish_app_status=MagicMock(side_effect=RuntimeError("publish broke"))
    )
    app = make_app_instance(APP_KEY, "main")

    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.NOT_STARTED, app=app)
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)

    assert real_registry_service.registry.get_status(APP_KEY, "main") is ResourceStatus.STARTING
    assert [step for step, _ in steps] == ["row", "send"]


async def test_no_runtime_query_service_sends_nothing_to_clients(
    real_registry_service: AppLifecycleService, steps: list[tuple[str, object]]
) -> None:
    real_registry_service.hassette._runtime_query_service = None
    app = make_app_instance(APP_KEY, "main")

    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.NOT_STARTED, app=app)
    await real_registry_service.set_app_status(APP_KEY, "main", ResourceStatus.STARTING)

    assert [step for step, _ in steps] == ["row", "send"]


def record_stale_publishes(runtime: RuntimeQueryService, registry: AppRegistry) -> list[int]:
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
    real_registry_service: AppLifecycleService, runtime: RuntimeQueryService
) -> None:
    """D4's guarantee is structural: no await between ``set_status`` and the publish, so no writer can overtake."""
    hassette = cast("MagicMock", real_registry_service.hassette)
    queue = await runtime.register_ws_client()
    stale_publishes = record_stale_publishes(runtime, real_registry_service.registry)

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
    deltas = [message["data"] for message in drain(queue) if message["type"] == "app_status_changed"]
    assert [delta["instance_name"] for delta in deltas] == ["a", "b", "a", "b"], "the writers did not interleave"
    revisions = [delta["status_revision"] for delta in deltas]
    assert revisions == sorted(set(revisions))
