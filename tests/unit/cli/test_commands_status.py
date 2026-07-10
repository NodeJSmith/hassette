"""Unit tests for hassette status, telemetry, and dashboard commands."""

import json
from unittest.mock import patch

from hassette.cli.commands.status import (
    DASHBOARD_COLUMNS,
    cmd_dashboard,
    cmd_status,
    cmd_telemetry,
)
from hassette.cli.context import CLIContext
from hassette.test_utils.web_helpers import (
    make_dashboard_app_grid_response,
    make_system_status_response,
    make_telemetry_status_response,
)
from tests.unit.cli.conftest import CLIClientFactory, GetSpy, capture_json_stdout, capture_stdout

# cmd_status


class TestCmdStatus:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Status command fetches from GET /api/health."""
        status_data = make_system_status_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_status()

        assert "/api/health" in spy.paths

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """Status command produces a key-value panel in human mode."""
        status_data = make_system_status_response(status="ok", version="0.2.0", uptime_seconds=90.0)
        client = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_status()
        output = buf.getvalue()
        assert "ok" in output
        assert "0.2.0" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """Status --json outputs a complete JSON object on stdout."""
        status_data = make_system_status_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])

        with (
            patch("hassette.cli.commands.status.make_client", return_value=client),
            capture_json_stdout() as captured,
        ):
            cmd_status(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert parsed["status"] == "ok"
        assert "websocket_connected" in parsed

    def test_uptime_formatted_in_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """uptime_seconds renders as human-readable via CliFormat annotation."""
        status_data = make_system_status_response(uptime_seconds=3661.0)
        client = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_status()
        output = buf.getvalue()
        assert "1h 1m 1s" in output

    def test_status_degraded_prints_status_not_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Status command prints status body (not an error) when instance is 'degraded' (200)."""
        status_data = make_system_status_response(status="degraded", websocket_connected=False)
        client = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_status()
        output = buf.getvalue()
        assert "degraded" in output

    def test_status_starting_prints_status_not_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Status command prints status body (not an error) when instance is 'starting' (200)."""
        status_data = make_system_status_response(status="starting", websocket_connected=False)
        client = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_status()
        output = buf.getvalue()
        assert "starting" in output


# cmd_telemetry


class TestCmdTelemetry:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Telemetry command fetches from GET /api/telemetry/status."""
        tel_data = make_telemetry_status_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 200, tel_data.model_dump())])
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_telemetry()

        assert "/api/telemetry/status" in spy.paths

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """Telemetry command produces a key-value panel showing degraded field."""
        tel_data = make_telemetry_status_response(degraded=False)
        client = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 200, tel_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_telemetry()
        output = buf.getvalue()
        assert "degraded" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """Telemetry --json outputs a complete JSON object."""
        tel_data = make_telemetry_status_response(dropped_overflow=5)
        client = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 200, tel_data.model_dump())])

        with (
            patch("hassette.cli.commands.status.make_client", return_value=client),
            capture_json_stdout() as captured,
        ):
            cmd_telemetry(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert parsed["dropped_overflow"] == 5

    def test_503_renders_degraded_status_human_mode(self, cli_client_factory: CLIClientFactory) -> None:
        """A 503 (degraded DB) prints the status body, not an error, and does not exit."""
        tel_data = make_telemetry_status_response(degraded=True)
        client = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 503, tel_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_telemetry()
        assert "degraded" in buf.getvalue()

    def test_503_outputs_status_json_mode_exit_zero(self, cli_client_factory: CLIClientFactory) -> None:
        """A 503 in json mode emits the deserialized status (no error doc) and exits 0."""
        tel_data = make_telemetry_status_response(degraded=True)
        client = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 503, tel_data.model_dump())])

        with (
            patch("hassette.cli.commands.status.make_client", return_value=client),
            capture_json_stdout() as captured,
        ):
            cmd_telemetry(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert parsed["degraded"] is True
        assert "error" not in parsed


# cmd_dashboard


class TestCmdDashboard:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Dashboard command fetches from GET /api/telemetry/dashboard/app-grid."""
        grid = make_dashboard_app_grid_response()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/dashboard/app-grid", 200, grid.model_dump())]
        )
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_dashboard()

        assert any("/api/telemetry/dashboard/app-grid" in p for p in spy.paths)

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Dashboard command renders a table with app rows."""
        grid = make_dashboard_app_grid_response()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/dashboard/app-grid", 200, grid.model_dump())]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_dashboard()
        output = buf.getvalue()
        # Table headers must always be visible
        assert "App" in output
        assert "Health" in output
        # app_key value appears (possibly truncated by Rich if terminal is narrow)
        assert "test_app" in output or "test_a" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Dashboard --json outputs the apps list as JSON array."""
        grid = make_dashboard_app_grid_response()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/dashboard/app-grid", 200, grid.model_dump())]
        )

        with (
            patch("hassette.cli.commands.status.make_client", return_value=client),
            capture_json_stdout() as captured,
        ):
            cmd_dashboard(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["app_key"] == "test_app"

    def test_dashboard_columns_defined(self) -> None:
        """DASHBOARD_COLUMNS includes the core per-app fields."""
        field_names = [c.field for c in DASHBOARD_COLUMNS]
        assert "app_key" in field_names
        assert "health_status" in field_names
        assert "avg_duration_ms" in field_names
        assert "last_activity_ts" in field_names

    def test_dashboard_columns_count_is_compact(self) -> None:
        """Dashboard uses at most 8 columns for readability in 80-col terminals."""
        assert len(DASHBOARD_COLUMNS) <= 8, f"Too many columns: {len(DASHBOARD_COLUMNS)}"
