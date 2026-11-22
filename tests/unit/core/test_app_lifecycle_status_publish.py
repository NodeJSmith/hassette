"""``set_app_status`` publishes each change to ``/ws`` clients directly, in write order (spec 160 D4)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from hassette_wire import ResourceStatus

import hassette.core.app_lifecycle_instances as instances_module
from hassette.core.app_lifecycle_service import AppLifecycleService
from hassette.core.app_registry import StatusChange

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
