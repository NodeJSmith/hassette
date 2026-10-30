"""Integration tests for core web API endpoints."""

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from hassette_wire import ResourceStatus
from pydantic import BaseModel, TypeAdapter
from pydantic_core import PydanticUndefined

from hassette.config import HassetteConfig
from hassette.core.app_registry import AppRegistry
from hassette.exceptions import AppBlockedError, AppBootstrapNotReleasedError, AppRemovedError
from hassette.schemas.app_outcomes import InstanceOutcome, OutcomeResult
from hassette.web.config_view import MASK_SENTINEL
from tests.integration.conftest import make_manifest_mock
from tests.support.helpers import create_app_manifest
from tests.support.web_manifest_helpers import make_manifest_db_row
from tests.support.web_telemetry_helpers import make_listener_summary_row

from .conftest import (
    APP_PATH,
    APPS_PATH,
    CONFIG_PATH,
    HEALTH_PATH,
    get_json,
    set_app_status_snapshot,
    set_websocket_state,
    telemetry_error,
)

if TYPE_CHECKING:
    from httpx2 import AsyncClient

# Route paths hit by multiple tests below — single source of truth so a route rename only
# needs to change here.
HEALTH_READY_PATH = "/api/health/ready"
APP_START_PATH = "/api/apps/my_app/start"
APP_STOP_PATH = "/api/apps/my_app/stop"
APP_RELOAD_PATH = "/api/apps/my_app/reload"
BUS_LISTENERS_PATH = "/api/bus/listeners"
OPENAPI_PATH = "/api/openapi.json"


def app_action_path(app_key: str, action: str) -> str:
    """Build a full-app-key action URL — single source of truth so a route rename only needs
    to change here.
    """
    return f"/api/apps/{app_key}/{action}"


def instance_action_path(app_key: str, index: int, action: str) -> str:
    """Build a per-instance action URL — single source of truth so a route rename only needs
    to change here.
    """
    return f"/api/apps/{app_key}/instances/{index}/{action}"


def outcome(
    index: int,
    name: str,
    result: OutcomeResult = OutcomeResult.SUCCEEDED,
    reason: str | None = None,
    needs_restart: bool = False,
) -> InstanceOutcome:
    """One instance's outcome, as a mocked ``AppHandler`` action returns it."""
    return InstanceOutcome(
        instance_index=index, instance_name=name, result=result, needs_restart=needs_restart, reason=reason
    )


class TestHealthEndpoints:
    async def test_health_returns_200_when_ok(self, client: "AsyncClient") -> None:
        """GET /api/health returns 200 with status 'ok' when WebSocket is connected."""
        data = await get_json(client, HEALTH_PATH)
        assert data["status"] == "ok"
        assert data["websocket_connected"] is True
        assert "entity_count" in data
        assert "app_count" in data

    async def test_health_returns_200_when_degraded(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health returns 200 with status 'degraded' when WebSocket is not connected."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=True)
        data = await get_json(client, HEALTH_PATH)
        assert data["status"] == "degraded"
        assert data["websocket_connected"] is False

    async def test_health_returns_200_when_starting(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health returns 200 (not 503) with status 'starting' during startup."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        data = await get_json(client, HEALTH_PATH)
        assert data["status"] == "starting"

    async def test_health_live_returns_200_regardless_of_ws_state(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health/live returns 200 even when WS is disconnected and never connected."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        data = await get_json(client, "/api/health/live")
        assert data["status"] == "live"

    async def test_health_ready_returns_200_when_ok(self, client: "AsyncClient") -> None:
        """GET /api/health/ready returns 200 when status is 'ok'."""
        data = await get_json(client, HEALTH_READY_PATH)
        assert data["ready"] is True
        assert data["status"] == "ok"

    async def test_health_ready_returns_503_when_degraded(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health/ready returns 503 when status is 'degraded'."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=True)
        data = await get_json(client, HEALTH_READY_PATH, expect_status=503)
        assert data["ready"] is False
        assert data["status"] == "degraded"

    async def test_health_ready_returns_503_when_starting(self, client: "AsyncClient", mock_hassette) -> None:
        """GET /api/health/ready returns 503 when status is 'starting'."""
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        data = await get_json(client, HEALTH_READY_PATH, expect_status=503)
        assert data["ready"] is False
        assert data["status"] == "starting"

    async def test_healthz_returns_404(self, client: "AsyncClient") -> None:
        """GET /api/healthz returns 404 after endpoint removal."""
        response = await client.get("/api/healthz")
        assert response.status_code == 404

    async def test_health_reports_zero_apps_and_starting_before_bootstrap(
        self, client: "AsyncClient", mock_hassette
    ) -> None:
        """The dashboard serves with app_count=0 while apps have not bootstrapped.

        RuntimeQueryService no longer depends on AppHandler, so this must not require any
        AppHandler readiness — only a cold WebSocket (never connected) and an empty live snapshot.
        """
        set_websocket_state(mock_hassette, connected=False, ever_connected=False)
        set_app_status_snapshot(mock_hassette, running=[], failed=[])
        data = await get_json(client, HEALTH_PATH)
        assert data["status"] == "starting"
        assert data["app_count"] == 0


class TestSPACatchAll:
    async def test_path_traversal_returns_404_or_spa(self, client: "AsyncClient") -> None:
        """Path traversal attempts must not serve files outside the SPA directory."""
        response = await client.get("/../../etc/passwd")
        # Either 404 (static-looking path) or 200 with SPA index.html — never the actual file
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            # SPA fallback — should be HTML, not /etc/passwd content
            assert "root:" not in response.text

    async def test_api_path_returns_404(self, client: "AsyncClient") -> None:
        """Paths under /api/ that don't match a route return 404, not SPA index.html."""
        response = await client.get("/api/nonexistent")
        assert response.status_code == 404


class TestAppEndpoints:
    async def test_start_app(self, client: "AsyncClient") -> None:
        response = await client.post(APP_START_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "start"
        assert data["instance_index"] is None

    async def test_start_app_returns_retryable_conflict_before_release(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.start_app = AsyncMock(side_effect=AppBootstrapNotReleasedError("not released"))

        response = await client.post(APP_START_PATH)

        assert response.status_code == 409

    async def test_start_app_returns_conflict_for_blocked_app(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """A blocked app's start must surface as a rejected request, not a 200 for an action
        the registry silently no-op'd.
        """
        mock_hassette.app_handler.start_app = AsyncMock(
            side_effect=AppBlockedError("App 'my_app' is blocked by the --app filter")
        )

        response = await client.post(APP_START_PATH)

        assert response.status_code == 409

    async def test_stop_app(self, client: "AsyncClient") -> None:
        response = await client.post(APP_STOP_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "stop"

    async def test_reload_app(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Reload returns 200 and forces a fresh re-import from disk.

        The force_reload=True assertion guards #1005: without it the endpoint reused the
        cached (failed) class, so a fix on disk never took effect.
        """
        response = await client.post(APP_RELOAD_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "reload"
        mock_hassette.app_handler.reload_app.assert_awaited_once_with("my_app", force_reload=True)

    async def test_reload_app_returns_retryable_conflict_before_release(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.reload_app = AsyncMock(side_effect=AppBootstrapNotReleasedError("not released"))

        response = await client.post(APP_RELOAD_PATH)

        assert response.status_code == 409

    async def test_reload_app_returns_conflict_for_blocked_app(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """A blocked app's reload must surface as a rejected request (reload is
        stop-then-start, so the same block applies).
        """
        mock_hassette.app_handler.reload_app = AsyncMock(
            side_effect=AppBlockedError("App 'my_app' is blocked by the --app filter")
        )

        response = await client.post(APP_RELOAD_PATH)

        assert response.status_code == 409

    async def test_app_management_works_without_dev_mode(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.config.dev_mode = False
        mock_hassette.config.allow_reload_in_prod = False
        assert (await client.post(APP_START_PATH)).status_code == 200
        assert (await client.post(APP_STOP_PATH)).status_code == 200
        assert (await client.post(APP_RELOAD_PATH)).status_code == 200

    async def test_failed_instance_returns_500_listing_every_outcome(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Any failed instance makes the action a 500 whose body lists every instance's outcome."""
        mock_hassette.app_handler.start_app = AsyncMock(
            return_value=(outcome(0, "kitchen"), outcome(1, "hall", OutcomeResult.FAILED, "on_initialize blew up"))
        )

        response = await client.post(APP_START_PATH)

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "action_failed"
        assert body["detail"] == "Started 1 of 2 instances of app 'my_app'; 'hall' failed: on_initialize blew up"
        assert [(o["instance_index"], o["result"]) for o in body["outcomes"]] == [(0, "succeeded"), (1, "failed")]

    async def test_refused_instance_returns_409_needs_restart(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """A refusal with no failure answers 409 ``needs_restart``; the refused entry carries the flag."""
        refused = outcome(1, "hall", OutcomeResult.REFUSED, "needs a hassette restart (flagged at 12:00: hung)", True)
        mock_hassette.app_handler.stop_app = AsyncMock(return_value=(outcome(0, "kitchen"), refused))

        response = await client.post(APP_STOP_PATH)

        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "needs_restart"
        assert body["detail"] == (
            "Stopped 1 of 2 instances of app 'my_app'; 'hall' needs a hassette restart (flagged at 12:00: hung)"
        )
        assert body["outcomes"][1]["needs_restart"] is True

    async def test_failure_outranks_refusal(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Worst outcome wins: a failure and a refusal together answer 500, not 409."""
        mock_hassette.app_handler.reload_app = AsyncMock(
            return_value=(
                outcome(0, "kitchen", OutcomeResult.REFUSED, "needs a hassette restart", True),
                outcome(1, "hall", OutcomeResult.FAILED, "stop timed out", True),
            )
        )

        response = await client.post(APP_RELOAD_PATH)

        assert response.status_code == 500
        assert response.json()["detail"].endswith("'hall' failed: stop timed out; it needs a hassette restart")

    async def test_success_body_lists_outcomes_with_reasons(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.start_app = AsyncMock(return_value=(outcome(0, "kitchen", reason="already running"),))

        response = await client.post(APP_START_PATH)

        assert response.status_code == 200
        data = response.json()

        assert "status" not in data
        assert data["outcomes"] == [
            {
                "instance_index": 0,
                "instance_name": "kitchen",
                "result": "succeeded",
                "needs_restart": False,
                "reason": "already running",
            }
        ]

    async def test_blocked_reload_carries_its_stop_outcomes(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """A reload of a ``--app``-blocked app has already stopped it, so the 409 body says so."""
        mock_hassette.app_handler.reload_app = AsyncMock(
            side_effect=AppBlockedError("blocked", outcomes=(outcome(0, "kitchen"),))
        )

        response = await client.post(APP_RELOAD_PATH)

        assert response.status_code == 409
        assert response.json()["code"] == "app_blocked"
        assert response.json()["outcomes"][0]["instance_name"] == "kitchen"

    async def test_removed_app_maps_to_not_found_with_outcomes(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.reload_app = AsyncMock(
            side_effect=AppRemovedError("gone", outcomes=(outcome(0, "kitchen"),))
        )

        response = await client.post(APP_RELOAD_PATH)

        assert response.status_code == 404
        assert response.json()["code"] == "app_not_found"
        assert len(response.json()["outcomes"]) == 1

    async def test_pre_check_error_has_no_outcomes_member(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.app_handler.start_app = AsyncMock(side_effect=AppBlockedError("blocked"))

        response = await client.post(APP_START_PATH)

        assert response.status_code == 409
        assert "outcomes" not in response.json()


class TestAppInstanceEndpoints:
    """Per-instance HTTP endpoints: POST /apps/{app_key}/instances/{index}/start|stop|reload (#796)."""

    def _seed_manifest(self, mock_hassette: MagicMock, instance_count: int = 2) -> None:
        """Wire a manifest mock with ``instance_count`` app_config entries onto the registry."""
        mock_hassette._app_handler.registry.get_manifest.return_value = make_manifest_mock(
            app_config=[{"instance_name": f"inst_{i}"} for i in range(instance_count)]
        )

    async def test_start_instance(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        self._seed_manifest(mock_hassette)

        response = await client.post(instance_action_path("my_app", 0, "start"))

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "start"
        assert data["instance_index"] == 0
        mock_hassette.app_handler.start_instance.assert_awaited_once_with("my_app", 0)

    async def test_stop_instance(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        self._seed_manifest(mock_hassette)

        response = await client.post(instance_action_path("my_app", 1, "stop"))

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "stop"
        assert data["instance_index"] == 1
        mock_hassette.app_handler.stop_instance.assert_awaited_once_with("my_app", 1)

    async def test_reload_instance(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        self._seed_manifest(mock_hassette)

        response = await client.post(instance_action_path("my_app", 0, "reload"))

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "reload"
        assert data["instance_index"] == 0
        mock_hassette.app_handler.reload_instance.assert_awaited_once_with("my_app", 0, force_reload=True)

    async def test_failed_instance_detail_names_only_that_instance(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """A single-target action has no "N of M" count in its detail."""
        self._seed_manifest(mock_hassette)
        mock_hassette.app_handler.reload_instance = AsyncMock(
            return_value=(outcome(0, "inst_0", OutcomeResult.FAILED, "instance reload blew up"),)
        )

        response = await client.post(instance_action_path("my_app", 0, "reload"))

        assert response.status_code == 500
        assert response.json()["detail"] == "'inst_0' failed: instance reload blew up"

    async def test_start_instance_out_of_range_returns_404(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        self._seed_manifest(mock_hassette, instance_count=1)

        response = await client.post(instance_action_path("my_app", 5, "start"))

        assert response.status_code == 404

    async def test_stop_instance_out_of_range_returns_404(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        self._seed_manifest(mock_hassette, instance_count=1)

        response = await client.post(instance_action_path("my_app", 5, "stop"))

        assert response.status_code == 404

    async def test_reload_instance_out_of_range_returns_404(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        self._seed_manifest(mock_hassette, instance_count=1)

        response = await client.post(instance_action_path("my_app", 5, "reload"))

        assert response.status_code == 404

    async def test_start_instance_unknown_app_returns_404(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        mock_hassette._app_handler.registry.get_instances.return_value = {}

        response = await client.post(instance_action_path("unknown_app", 0, "start"))

        assert response.status_code == 404

    @pytest.mark.parametrize("action", ["start", "reload"])
    @pytest.mark.parametrize(
        "error",
        [
            AppBootstrapNotReleasedError("not released"),
            # A blocked app's instance start or reload (reload is stop-then-start, so the same block applies)
            # must surface as a rejected request, not a 200 for an action the registry silently no-op'd.
            AppBlockedError("App 'my_app' is blocked by the --app filter"),
        ],
        ids=["before_release", "blocked_app"],
    )
    async def test_instance_action_returns_conflict(
        self, client: "AsyncClient", mock_hassette: MagicMock, action: str, error: Exception
    ) -> None:
        self._seed_manifest(mock_hassette)
        setattr(mock_hassette.app_handler, f"{action}_instance", AsyncMock(side_effect=error))

        response = await client.post(instance_action_path("my_app", 0, action))

        assert response.status_code == 409

    async def test_stop_instance_orphaned_app_reaches_service_layer(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """An app removed from config but still running can be stopped via per-instance endpoint."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        mock_hassette._app_handler.registry.get_instances.return_value = {0: MagicMock()}

        response = await client.post(instance_action_path("orphan_app", 0, "stop"))

        assert response.status_code == 200
        mock_hassette.app_handler.stop_instance.assert_awaited_once_with("orphan_app", 0)

    async def test_stop_instance_tracked_orphan_index_reaches_service_layer(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """The configured instance count shrank to 1 while index 2 was still running. That orphan
        is still reported in the manifest's ``instances`` and must stay stoppable, even though it
        now sits outside the configured range.
        """
        self._seed_manifest(mock_hassette, instance_count=1)
        mock_hassette._app_handler.registry.get_instances.return_value = {0: MagicMock(), 2: MagicMock()}

        response = await client.post(instance_action_path("my_app", 2, "stop"))

        assert response.status_code == 200
        mock_hassette.app_handler.stop_instance.assert_awaited_once_with("my_app", 2)

    @pytest.mark.parametrize("action", ["start", "reload"])
    async def test_tracked_orphan_index_start_or_reload_still_returns_404(
        self, client: "AsyncClient", mock_hassette: MagicMock, action: str
    ) -> None:
        """Only stop gets the orphan-index permissiveness, mirroring the orphaned-app rule:
        start/reload report an out-of-range index as a failed outcome in the service layer, so
        admitting them would swap a clear 404 for a 500.
        """
        self._seed_manifest(mock_hassette, instance_count=1)
        mock_hassette._app_handler.registry.get_instances.return_value = {0: MagicMock(), 2: MagicMock()}

        response = await client.post(instance_action_path("my_app", 2, action))

        assert response.status_code == 404

    async def test_stop_app_orphaned_app_reaches_service_layer(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Full-key stop also works for an orphaned app with running instances but no manifest."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        mock_hassette._app_handler.registry.get_instances.return_value = {0: MagicMock()}

        response = await client.post(app_action_path("orphan_app", "stop"))

        assert response.status_code == 200
        mock_hassette.app_handler.stop_app.assert_awaited_once_with("orphan_app")

    @pytest.mark.parametrize(
        "path",
        [
            instance_action_path("orphan_app", 0, "start"),
            instance_action_path("orphan_app", 0, "reload"),
            app_action_path("orphan_app", "start"),
            app_action_path("orphan_app", "reload"),
        ],
        ids=["start_instance", "reload_instance", "start_app", "reload_app"],
    )
    async def test_orphaned_app_start_or_reload_still_returns_404(
        self, client: "AsyncClient", mock_hassette: MagicMock, path: str
    ) -> None:
        """Unlike stop, start/reload do not get orphan permissiveness -- the service layer raises
        ``AppRemovedError`` for a missing manifest, so admitting the request would only delay the
        same 404. Covers both the full-app-key and per-instance routes.
        """
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        mock_hassette._app_handler.registry.get_instances.return_value = {0: MagicMock()}

        response = await client.post(path)

        assert response.status_code == 404


class TestGetAppEndpoint:
    async def test_get_app_returns_single_app(self, client: "AsyncClient", mock_hassette) -> None:
        """A DB-only app (no matching in-memory manifest) returns 200, not 404."""
        mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(
            return_value=make_manifest_db_row(app_key="my_app", display_name="My App")
        )

        response = await client.get(APP_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["app_key"] == "my_app"
        assert data["display_name"] == "My App"
        # No matching in-memory manifest on the stub registry -> stopped, not in current config.
        assert data["status"] == "stopped"
        assert data["in_current_config"] is False

    async def test_get_app_returns_404_for_unknown_app(self, client: "AsyncClient", mock_hassette) -> None:
        """A genuinely unknown app_key (no DB row at all) still 404s."""
        mock_hassette.telemetry_query_service.get_app_manifest = AsyncMock(return_value=None)

        response = await client.get("/api/apps/unknown_app")
        assert response.status_code == 404

    async def test_get_app_returns_400_for_invalid_key(self, client: "AsyncClient") -> None:
        response = await client.get("/api/apps/!!invalid")
        assert response.status_code == 400

    async def test_get_app_returns_503_when_db_unavailable(self, client: "AsyncClient", mock_hassette) -> None:
        """A DB failure on the spine query itself returns 503, not 404."""
        mock_hassette.telemetry_query_service.get_app_manifest = telemetry_error(message="db down")

        response = await client.get(APP_PATH)
        assert response.status_code == 503


class TestAppListEndpoint:
    async def test_get_apps_includes_db_only_apps(self, client: "AsyncClient", mock_hassette) -> None:
        """A DB-only app (no matching in-memory manifest) appears in the app list."""
        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            return_value=[make_manifest_db_row(app_key="orphan_app", display_name="Orphan App")]
        )

        response = await client.get(APPS_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["status_counts"]["stopped"] == 1
        app_keys = {m["app_key"] for m in data["apps"]}
        assert "orphan_app" in app_keys
        orphan = next(m for m in data["apps"] if m["app_key"] == "orphan_app")
        assert orphan["display_name"] == "Orphan App"
        assert orphan["status"] == "stopped"
        assert orphan["in_current_config"] is False

    async def test_get_apps_shows_degraded_status_for_mixed_running_and_failed_instances(
        self, client: "AsyncClient", mock_hassette, tmp_path: Path
    ) -> None:
        """Full-chain check for a degraded app: a real AppRegistry with one running and one failed
        instance for the same app_key must surface as ``status: "degraded"`` in the actual
        HTTP response body from /api/apps -- not just at the registry or mapper
        level (see design/specs/096-registry-instance-unification/known-issues.md).
        """
        registry = AppRegistry()
        manifest = create_app_manifest("half_broken", tmp_path)
        registry.set_manifests({manifest.app_key: manifest})

        running_app = MagicMock()
        running_app.app_config.instance_name = f"{manifest.class_name}.0"
        running_app.class_name = manifest.class_name
        running_app.status = ResourceStatus.RUNNING
        running_app.unique_name = f"{manifest.class_name}.{manifest.app_key}.0"
        registry.register_app(manifest.app_key, 0, running_app)
        registry.record_failure(manifest.app_key, 1, RuntimeError("instance 1 blew up"))
        mock_hassette._app_handler.registry = registry

        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            return_value=[make_manifest_db_row(app_key=manifest.app_key, display_name="Half Broken")]
        )

        response = await client.get(APPS_PATH)

        assert response.status_code == 200
        data = response.json()
        entry = next(m for m in data["apps"] if m["app_key"] == manifest.app_key)
        assert entry["status"] == "degraded"
        assert data["status_counts"]["degraded"] == 1


class TestSchedulerEndpoints:
    async def test_scheduler_jobs_endpoint_exists(self, client: "AsyncClient") -> None:
        """GET /api/scheduler/jobs returns 200."""
        response = await client.get("/api/scheduler/jobs")
        assert response.status_code == 200
        assert response.json() == []


class TestConfigEndpoint:
    async def test_get_config(self, client: "AsyncClient") -> None:
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        assert "config_schema" in data
        assert "config_values" in data


class TestBusEndpoints:
    async def test_get_bus_listeners_empty(self, client: "AsyncClient") -> None:
        # Returns empty when no app_key is provided (TelemetryDep stubs return [])
        response = await client.get(BUS_LISTENERS_PATH)
        assert response.status_code == 200
        assert response.json() == []

    async def test_get_bus_listeners_with_app_key_returns_empty_stub(self, client: "AsyncClient") -> None:
        # TelemetryQueryService stubs return [] for all app_key queries
        response = await client.get(f"{BUS_LISTENERS_PATH}?app_key=my_app")
        assert response.status_code == 200
        assert response.json() == []

    async def test_bus_metrics_endpoint_removed(self, client: "AsyncClient") -> None:
        response = await client.get("/api/bus/metrics")
        assert response.status_code == 404

    async def test_get_listener_metrics_returns_listener_summary(
        self, mock_hassette: MagicMock, client: "AsyncClient"
    ) -> None:
        """Endpoint returns ListenerSummary schema with once as int and handler_summary populated."""
        sample = make_listener_summary_row(
            once=1,
            source_location="test_app.py:10",
            total_invocations=5,
            successful=4,
            failed=1,
            total_duration_ms=100.0,
            avg_duration_ms=20.0,
            min_duration_ms=10.0,
            max_duration_ms=30.0,
            last_invoked_at=1700000000.0,
            last_error_type="ValueError",
            last_error_message="bad value",
        )
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(return_value=[sample])

        response = await client.get(f"{BUS_LISTENERS_PATH}?app_key=test_app")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        entry = data[0]
        # once must be int, not bool
        assert entry["once"] == 1
        assert isinstance(entry["once"], int)
        # handler_summary must be populated by listener_summary_from
        assert "handler_summary" in entry
        assert entry["handler_summary"] != ""
        # ListenerSummary-specific fields present
        assert "source_location" in entry
        assert "human_description" in entry
        # timed_out is tracked separately from failed (not aggregated into it)
        assert "timed_out" in entry
        assert entry["timed_out"] == 0
        assert "listener_kind" in entry
        # Verify key fields are correct
        assert entry["listener_id"] == 1
        assert entry["app_key"] == "test_app"
        assert entry["topic"] == "state_changed.light.kitchen"
        assert entry["total_invocations"] == 5


def expected_defaults(model: type[BaseModel]) -> dict[str, object]:
    """Build the expected ``config_defaults`` from a model's own field definitions."""
    expected: dict[str, object] = {}
    for name, field in model.model_fields.items():
        if field.default is not PydanticUndefined:
            expected[name] = TypeAdapter(field.annotation).dump_python(field.default, mode="json")
        elif isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            expected[name] = expected_defaults(field.annotation)
    return expected


class TestConfigEndpointExpanded:
    async def test_config_defaults_match_model_defaults(self, client: "AsyncClient") -> None:
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        config_defaults = response.json()["config_defaults"]
        assert config_defaults == expected_defaults(HassetteConfig)
        assert "port" in config_defaults["web_api"]

    async def test_response_has_nested_groups(self, client: "AsyncClient", mock_hassette) -> None:
        """Response envelope contains standard config groups in config_values, including previously-omitted ones."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        config_values = data["config_values"]
        assert "web_api" in config_values
        assert "logging" in config_values
        assert "lifecycle" in config_values
        assert "apps" in config_values
        assert "scheduler" in config_values
        assert "file_watcher" in config_values
        # Groups that the old endpoint omitted are now present
        assert "database" in config_values
        assert "websocket" in config_values
        assert "blocking_io" in config_values

    async def test_token_not_in_response(self, client: "AsyncClient", mock_hassette) -> None:
        """Token is present in config_values as None or masked; plaintext is never returned."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        config_values = data["config_values"]
        # Token key is present in config_values (not omitted)
        assert "token" in config_values
        # Value is None (not set) or the mask sentinel — never a plaintext secret
        token_val = config_values["token"]
        assert token_val is None or token_val == MASK_SENTINEL
        # Plaintext token never appears anywhere in the response body
        assert "test-token" not in response.text

    async def test_set_token_is_masked_not_plaintext(self, client: "AsyncClient", mock_hassette) -> None:
        """A token with a value is returned as the mask sentinel — proves the full endpoint
        masking flow (the schema marks token secret, the view builder replaces the value).
        """
        secret = "super-secret-plaintext-xyz"
        mock_hassette.config.model_dump.return_value["token"] = secret
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["config_values"]["token"] == MASK_SENTINEL
        assert secret not in response.text

    async def test_dev_mode_present_at_root(self, client: "AsyncClient", mock_hassette) -> None:
        """dev_mode is present in config_values."""
        response = await client.get(CONFIG_PATH)
        data = response.json()
        assert "dev_mode" in data["config_values"]
        assert isinstance(data["config_values"]["dev_mode"], bool)

    async def test_dir_fields_present_as_strings(self, client: "AsyncClient", mock_hassette) -> None:
        """data_dir and config_dir are present in config_values; apps.directory is under the apps group."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        config_values = data["config_values"]
        assert isinstance(config_values["apps"]["directory"], str)
        assert isinstance(config_values["data_dir"], str)
        assert isinstance(config_values["config_dir"], str)

    async def test_web_api_fields_nested(self, client: "AsyncClient", mock_hassette) -> None:
        """web_api group in config_values contains host and port fields."""
        response = await client.get(CONFIG_PATH)
        assert response.status_code == 200
        data = response.json()
        web_api = data["config_values"]["web_api"]
        assert "host" in web_api
        assert "port" in web_api


class TestOpenApiDocs:
    async def test_openapi_json(self, client: "AsyncClient") -> None:
        response = await client.get(OPENAPI_PATH)
        assert response.status_code == 200
        data = response.json()
        assert data["info"]["title"] == "Hassette Web API"

    async def test_instance_index_has_description_on_telemetry_health(self, client: "AsyncClient") -> None:
        """instance_index parameter on telemetry app health route has a description."""
        response = await client.get(OPENAPI_PATH)
        spec = response.json()
        paths = spec.get("paths", {})
        # Find the app health route
        health_path = "/api/telemetry/app/{app_key}/health"
        assert health_path in paths, f"health route missing; got {list(paths)}"
        params = paths[health_path]["get"].get("parameters", [])
        instance_params = [p for p in params if p.get("name") == "instance_index"]
        assert instance_params, "instance_index parameter must be present on health route"
        assert instance_params[0].get("description"), "instance_index must have a non-empty description"

    async def test_instance_index_has_description_on_bus_listeners(self, client: "AsyncClient") -> None:
        """instance_index parameter on bus listeners route has a description."""
        response = await client.get(OPENAPI_PATH)
        spec = response.json()
        paths = spec.get("paths", {})
        assert BUS_LISTENERS_PATH in paths
        params = paths[BUS_LISTENERS_PATH]["get"].get("parameters", [])
        instance_params = [p for p in params if p.get("name") == "instance_index"]
        assert instance_params, "instance_index parameter must be present on bus/listeners route"
        assert instance_params[0].get("description"), "instance_index must have a non-empty description"
