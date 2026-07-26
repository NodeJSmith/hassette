"""System test: Hassette starts and serves when HA has never been reachable.

Unlike ``test_reconnection.py`` (which restarts a *running* HA container mid-test), this
test never starts the HA Docker container at all — it points Hassette at a closed local
port so REST calls fail with a real connection-refused error. This proves the
dependency-decoupling fix (``design/specs/018-dashboard-without-ha/design.md``) holds at
the process level: the web server serves and apps bootstrap even though HA was never
reachable, not just in the mocked integration test (``test_dashboard_without_ha.py``).
"""

import httpx2 as httpx
import pytest

from .conftest import make_web_system_config, startup_context, wait_for_web_server

pytestmark = [pytest.mark.system]

# Nothing listens here — connect() fails immediately with ECONNREFUSED, no DNS lookup or
# TCP timeout delay. The ApiResource retry loop (5 attempts, exponential backoff) still
# runs against this real refusal, so this test budgets extra time for that retry storm
# rather than mocking it away.
UNREACHABLE_HA_URL = "http://127.0.0.1:1"
STARTUP_TIMEOUT_SECONDS = 60


async def test_starts_and_serves_without_ha(tmp_path, system_app_dir) -> None:
    """WebApiService serves, apps bootstrap, and /api/health reports 'starting' with no HA."""
    config, base_url = make_web_system_config(UNREACHABLE_HA_URL, tmp_path)
    config = config.model_copy(deep=True)
    config.apps.autodetect = True
    config.apps.directory = system_app_dir
    config.lifecycle.startup_timeout_seconds = STARTUP_TIMEOUT_SECONDS

    async with startup_context(config, timeout=STARTUP_TIMEOUT_SECONDS) as hassette:
        assert hassette.websocket_service.is_ready()
        assert hassette.websocket_service.is_connected is False
        assert hassette.websocket_service.has_ever_connected is False

        snapshot = hassette.app_handler.registry.get_full_snapshot()
        app_keys = [manifest.app_key for manifest in snapshot.manifests]
        assert any("TrivialApp" in key for key in app_keys), f"TrivialApp not found in registry: {app_keys}"

        await wait_for_web_server(base_url)
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base_url}/api/health", timeout=10.0)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "starting"
        assert body["websocket_connected"] is False
