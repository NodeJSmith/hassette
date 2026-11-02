"""An app removed from config keeps its history browsable through the per-app routes."""

from collections.abc import AsyncIterator

import pytest
from httpx2 import ASGITransport, AsyncClient

from hassette.core.app_registry import AppRegistry
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.types.types import FRAMEWORK_APP_KEY
from hassette.web.app import create_fastapi_app
from tests.support.web_mocks import create_hassette_stub, create_mock_runtime_query_service

from .helpers import DbFixture, insert_invocation, insert_listener

REMOVED_APP = "removed_app"
QUIET_APP = "quiet_app"


async def insert_manifest_row(db: DbFixture, app_key: str) -> None:
    """Insert the ``app_manifests`` row an app keeps after it leaves the config while telemetry references it."""
    db_svc, _ = db
    await db_svc.db.execute(
        "INSERT INTO app_manifests (app_key, class_name, display_name, filename) VALUES (?, ?, ?, ?)",
        (app_key, "RemovedApp", "Removed App", "removed_app.py"),
    )
    await db_svc.db.commit()


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
    await insert_manifest_row(db, REMOVED_APP)
    for name in ("upstairs", "downstairs"):
        listener_id = await insert_listener(db_svc, app_key=REMOVED_APP, instance_name=name, handler_method=name)
        await insert_invocation(db_svc, listener_id, session_id)

    health = await client.get(f"/api/telemetry/app/{REMOVED_APP}/health?instance_index=0")
    activity = await client.get(f"/api/telemetry/app/{REMOVED_APP}/activity?instance_index=0")

    assert health.status_code == 200, health.text
    assert health.json()["handler_avg_duration_ms"] is not None
    assert activity.status_code == 200, activity.text
    assert len(activity.json()) == 2


async def test_app_health_answers_404_for_a_key_with_no_manifest_row(client: AsyncClient) -> None:
    health = await client.get("/api/telemetry/app/no_such_app/health")

    assert health.status_code == 404, health.text
    assert health.json()["code"] == "app_not_found"


async def test_app_health_reports_a_quiet_known_app_as_excellent(client: AsyncClient, db: DbFixture) -> None:
    await insert_manifest_row(db, QUIET_APP)

    health = await client.get(f"/api/telemetry/app/{QUIET_APP}/health")

    assert health.status_code == 200, health.text
    assert health.json()["health_status"] == "excellent"


async def test_app_health_needs_no_manifest_row_for_the_framework_key(client: AsyncClient) -> None:
    health = await client.get(f"/api/telemetry/app/{FRAMEWORK_APP_KEY}/health")

    assert health.status_code == 200, health.text
