"""An app removed from config keeps its history browsable through the per-app routes."""

from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from hassette.core.app_registry import AppRegistry
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.web.app import create_fastapi_app
from tests.support.web_mocks import create_hassette_stub, create_mock_runtime_query_service

from .helpers import DbFixture, insert_invocation, insert_listener

REMOVED_APP = "removed_app"


@pytest.fixture
async def client(query_service: TelemetryQueryService) -> AsyncIterator[AsyncClient]:
    """A client whose routes read the real telemetry database and a real registry that knows no apps."""
    hassette = create_hassette_stub(run_web_ui=False)
    hassette.telemetry_query_service = query_service
    hassette.app_handler.registry = AppRegistry()
    create_mock_runtime_query_service(hassette)
    async with AsyncClient(transport=ASGITransport(app=create_fastapi_app(hassette)), base_url="http://test") as ac:
        yield ac


async def test_removed_app_health_and_activity_return_its_stored_runs(client: AsyncClient, db: DbFixture) -> None:
    """The Apps page always sends index 0; a removed app has no instance to name, so that covers every former one."""
    db_svc, session_id = db
    for name in ("upstairs", "downstairs"):
        listener_id = await insert_listener(db_svc, app_key=REMOVED_APP, instance_name=name, handler_method=name)
        await insert_invocation(db_svc, listener_id, session_id)

    health = await client.get(f"/api/telemetry/app/{REMOVED_APP}/health?instance_index=0")
    activity = await client.get(f"/api/telemetry/app/{REMOVED_APP}/activity?instance_index=0")

    assert health.status_code == 200, health.text
    assert health.json()["handler_avg_duration_ms"] is not None
    assert activity.status_code == 200, activity.text
    assert len(activity.json()) == 2
