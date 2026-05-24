"""Unit tests for hassette status, telemetry, and dashboard commands."""

import json
from unittest.mock import patch

from hassette.cli.commands.status import (
    DASHBOARD_COLUMNS,
    STATUS_COLUMNS,
    cmd_dashboard,
    cmd_status,
    cmd_telemetry,
)
from hassette.test_utils.web_helpers import (
    make_dashboard_app_grid_response,
    make_system_status_response,
    make_telemetry_status_response,
)
from tests.unit.cli.conftest import CLIClientFactory, capture_stdout

# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------


class TestCmdStatus:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """status command fetches from GET /api/health."""
        status_data = make_system_status_response()
        client, _builder = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_status(json=False)

        assert "/api/health" in called_paths

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """status command produces a key-value panel in human mode."""
        status_data = make_system_status_response(status="ok", version="0.2.0", uptime_seconds=90.0)
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_status(json=False)
        output = buf.getvalue()
        assert "ok" in output
        assert "0.2.0" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """status --json outputs a complete JSON object on stdout."""
        status_data = make_system_status_response()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/health", 200, status_data.model_dump())])
        captured_stdout: list[str] = []

        def capture_write(s: str) -> int:
            captured_stdout.append(s)
            return len(s)

        with (
            patch("hassette.cli.commands.status.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=capture_write),
        ):
            cmd_status(json=True)

        combined = "".join(captured_stdout)
        parsed = json.loads(combined)
        assert parsed["status"] == "ok"
        assert "websocket_connected" in parsed

    def test_status_columns_are_defined(self) -> None:
        """STATUS_COLUMNS defines the expected fields."""
        field_names = [c.field for c in STATUS_COLUMNS]
        assert "status" in field_names
        assert "uptime_seconds" in field_names
        assert "version" in field_names
        assert "boot_issues" in field_names

    def test_uptime_formatted(self, cli_client_factory: CLIClientFactory) -> None:
        """uptime_seconds column uses a human-readable formatter."""
        uptime_col = next(c for c in STATUS_COLUMNS if c.field == "uptime_seconds")
        assert uptime_col.formatter is not None
        # 3661 seconds = 1h 1m 1s
        assert "h" in uptime_col.formatter(3661) or "m" in uptime_col.formatter(3661)

    def test_boot_issues_count(self) -> None:
        """boot_issues formatter shows count for non-empty list."""
        boot_col = next(c for c in STATUS_COLUMNS if c.field == "boot_issues")
        assert boot_col.formatter is not None
        assert boot_col.formatter([{"severity": "err", "label": "x", "detail": "y"}]) == "1"
        assert boot_col.formatter([]) == "—"


# ---------------------------------------------------------------------------
# cmd_telemetry
# ---------------------------------------------------------------------------


class TestCmdTelemetry:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """telemetry command fetches from GET /api/telemetry/status."""
        tel_data = make_telemetry_status_response()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 200, tel_data.model_dump())])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_telemetry(json=False)

        assert "/api/telemetry/status" in called_paths

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """telemetry command produces a key-value panel showing degraded field."""
        tel_data = make_telemetry_status_response(degraded=False)
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 200, tel_data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_telemetry(json=False)
        output = buf.getvalue()
        assert "degraded" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """telemetry --json outputs a complete JSON object."""
        tel_data = make_telemetry_status_response(dropped_overflow=5)
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/telemetry/status", 200, tel_data.model_dump())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.status.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_telemetry(json=True)

        parsed = json.loads("".join(captured))
        assert parsed["dropped_overflow"] == 5


# ---------------------------------------------------------------------------
# cmd_dashboard
# ---------------------------------------------------------------------------


class TestCmdDashboard:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """dashboard command fetches from GET /api/telemetry/dashboard/app-grid."""
        grid = make_dashboard_app_grid_response()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/dashboard/app-grid", 200, grid.model_dump())]
        )
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_dashboard(json=False)

        assert any("/api/telemetry/dashboard/app-grid" in p for p in called_paths)

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """dashboard command renders a table with app rows."""
        grid = make_dashboard_app_grid_response()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/dashboard/app-grid", 200, grid.model_dump())]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.status.make_client", return_value=client),
        ):
            cmd_dashboard(json=False)
        output = buf.getvalue()
        # Table headers must always be visible
        assert "App" in output
        assert "Health" in output
        # app_key value appears (possibly truncated by Rich if terminal is narrow)
        assert "my_app" in output or "my_a" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """dashboard --json outputs the apps list as JSON array."""
        grid = make_dashboard_app_grid_response()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/dashboard/app-grid", 200, grid.model_dump())]
        )
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.status.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_dashboard(json=True)

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["app_key"] == "my_app"

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
