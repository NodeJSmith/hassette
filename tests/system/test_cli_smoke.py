"""CLI smoke tests against the real hassette web API (Docker HA + demo apps).

These are end-to-end tests — not mocked. They start a hassette instance with
demo apps, instantiate HassetteCLIClient directly, and verify that each API
endpoint deserializes correctly into its expected Pydantic model.

Run via: uv run nox -s system
"""

import asyncio
import contextlib
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hassette.cli.client import HassetteCLIClient
from hassette.core.telemetry_models import JobSummary
from hassette.web.models import (
    AppManifestListResponse,
    ConfigResponse,
    DashboardAppGridResponse,
    EventEntry,
    ListenerWithSummary,
    LogEntryResponse,
    SystemStatusResponse,
    TelemetryStatusResponse,
)

from .conftest import HA_TOKEN, SystemTestConfig, make_web_system_config, startup_context, wait_for_web_server

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYSTEM_APPS_DIR = Path(__file__).parent / "apps"

pytestmark = [pytest.mark.system]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _cli_client(config: SystemTestConfig) -> Iterator[HassetteCLIClient]:
    """Build a non-JSON-mode CLI client pointed at the running server."""
    client = HassetteCLIClient(config, json_mode=False)
    try:
        yield client
    finally:
        client.close()


def _web_config_with_bus_app(ha_url: str, tmp_path: Path) -> tuple[SystemTestConfig, str]:
    """Build a web-enabled config that autodetects apps from the system apps dir.

    BusHandlerApp in tests/system/apps/ registers a listener for
    light.kitchen_lights — gives us an app with real listeners for filter tests.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 0))
        port = sock.getsockname()[1]

    config = SystemTestConfig(
        base_url=ha_url,
        token=HA_TOKEN,
        data_dir=tmp_path / "data",
        apps={"directory": str(SYSTEM_APPS_DIR), "autodetect": True},
        web_api={"run": True, "port": port},
        lifecycle={"startup_timeout_seconds": 30},
    )
    return config, f"http://127.0.0.1:{port}"


# ===========================================================================
# System-status commands
# ===========================================================================


async def test_health_deserializes(ha_container: str, tmp_path: Path) -> None:
    """GET /api/health deserializes to SystemStatusResponse."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            result = await asyncio.to_thread(client.get, "/api/health", SystemStatusResponse)

    assert isinstance(result, SystemStatusResponse)
    assert result.status in ("ok", "degraded", "starting")


async def test_config_deserializes(ha_container: str, tmp_path: Path) -> None:
    """GET /api/config deserializes to ConfigResponse."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            result = await asyncio.to_thread(client.get, "/api/config", ConfigResponse)

    assert isinstance(result, ConfigResponse)
    assert result.web_api.port > 0


async def test_telemetry_status_deserializes(ha_container: str, tmp_path: Path) -> None:
    """GET /api/telemetry/status deserializes to TelemetryStatusResponse."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            result = await asyncio.to_thread(client.get, "/api/telemetry/status", TelemetryStatusResponse)

    assert isinstance(result, TelemetryStatusResponse)


async def test_dashboard_deserializes(ha_container: str, tmp_path: Path) -> None:
    """GET /api/telemetry/dashboard/app-grid deserializes to DashboardAppGridResponse."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            result = await asyncio.to_thread(client.get, "/api/telemetry/dashboard/app-grid", DashboardAppGridResponse)

    assert isinstance(result, DashboardAppGridResponse)
    assert isinstance(result.apps, list)


async def test_events_deserializes_and_respects_limit(ha_container: str, tmp_path: Path) -> None:
    """GET /api/events/recent?limit=5 deserializes to list[EventEntry] with ≤5 entries."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            raw: list[Any] = await asyncio.to_thread(client.get, "/api/events/recent", list, {"limit": 5})

    events = [EventEntry.model_validate(e) for e in raw]
    assert isinstance(events, list)
    assert len(events) <= 5
    for evt in events:
        assert isinstance(evt, EventEntry)


# ===========================================================================
# App commands
# ===========================================================================


async def test_app_manifests_non_empty(ha_container: str, tmp_path: Path) -> None:
    """GET /api/apps/manifests deserializes and has a non-empty manifests list."""
    config, base_url = _web_config_with_bus_app(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            result = await asyncio.to_thread(client.get, "/api/apps/manifests", AppManifestListResponse)

    assert isinstance(result, AppManifestListResponse)
    assert len(result.manifests) > 0


# ===========================================================================
# Listener commands
# ===========================================================================


async def test_listeners_deserializes(ha_container: str, tmp_path: Path) -> None:
    """GET /api/bus/listeners deserializes to list[ListenerWithSummary]."""
    config, base_url = _web_config_with_bus_app(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            raw: list[Any] = await asyncio.to_thread(client.get, "/api/bus/listeners", list)

    listeners = [ListenerWithSummary.model_validate(e) for e in raw]
    assert isinstance(listeners, list)
    for listener in listeners:
        assert isinstance(listener, ListenerWithSummary)


async def test_listener_app_filter_returns_subset(ha_container: str, tmp_path: Path) -> None:
    """Per-app listener endpoint returns only listeners belonging to that app (AC#4)."""
    config, base_url = _web_config_with_bus_app(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            all_raw: list[Any] = await asyncio.to_thread(client.get, "/api/bus/listeners", list)
            all_listeners = [ListenerWithSummary.model_validate(e) for e in all_raw]

            if not all_listeners:
                pytest.skip("No listeners registered — BusHandlerApp may not have started in time")

            app_key = all_listeners[0].app_key

            filtered_raw: list[Any] = await asyncio.to_thread(
                client.get,
                f"/api/telemetry/app/{app_key}/listeners",
                list,
            )
            filtered = [ListenerWithSummary.model_validate(e) for e in filtered_raw]

    assert len(filtered) > 0
    assert len(filtered) <= len(all_listeners)
    for listener in filtered:
        assert listener.app_key == app_key


async def test_listener_instance_filter(ha_container: str, tmp_path: Path) -> None:
    """Per-app listener endpoint with instance_index=0 returns a valid subset (AC#11)."""
    config, base_url = _web_config_with_bus_app(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            all_raw: list[Any] = await asyncio.to_thread(client.get, "/api/bus/listeners", list)
            all_listeners = [ListenerWithSummary.model_validate(e) for e in all_raw]

            if not all_listeners:
                pytest.skip("No listeners registered — BusHandlerApp may not have started in time")

            app_key = all_listeners[0].app_key

            instance_raw: list[Any] = await asyncio.to_thread(
                client.get,
                f"/api/telemetry/app/{app_key}/listeners",
                list,
                {"instance_index": 0},
            )
            instance_listeners = [ListenerWithSummary.model_validate(e) for e in instance_raw]

    assert isinstance(instance_listeners, list)
    for listener in instance_listeners:
        assert listener.app_key == app_key


# ===========================================================================
# Job commands
# ===========================================================================


async def test_jobs_deserializes(ha_container: str, tmp_path: Path) -> None:
    """GET /api/scheduler/jobs deserializes to list[JobSummary]."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            raw: list[Any] = await asyncio.to_thread(client.get, "/api/scheduler/jobs", list)

    jobs = [JobSummary.model_validate(e) for e in raw]
    assert isinstance(jobs, list)
    for job in jobs:
        assert isinstance(job, JobSummary)


# ===========================================================================
# Log commands
# ===========================================================================


async def test_logs_respects_limit(ha_container: str, tmp_path: Path) -> None:
    """GET /api/logs/recent?limit=10 returns ≤10 entries and deserializes to LogEntryResponse (AC#5)."""
    config, base_url = make_web_system_config(ha_container, tmp_path)
    async with startup_context(config):
        await wait_for_web_server(base_url)
        with _cli_client(config) as client:
            raw: list[Any] = await asyncio.to_thread(client.get, "/api/logs/recent", list, {"limit": 10})

    entries = [LogEntryResponse.model_validate(e) for e in raw]
    assert isinstance(entries, list)
    assert len(entries) <= 10
    for entry in entries:
        assert isinstance(entry, LogEntryResponse)


# ===========================================================================
# Error handling
# ===========================================================================


def test_wrong_port_exits_with_code_2(tmp_path: Path) -> None:
    """Querying a non-existent server exits with code 2 (AC#8)."""
    config = SystemTestConfig(
        base_url="http://localhost:18123",
        token="dummy",
        data_dir=tmp_path / "data",
        apps={"directory": str(tmp_path / "apps"), "autodetect": False},
        web_api={"run": False, "port": 19999},
        lifecycle={"startup_timeout_seconds": 30},
    )
    with _cli_client(config) as client, pytest.raises(SystemExit) as exc_info:
        client.get("/api/health", SystemStatusResponse)

    assert exc_info.value.code == 2
