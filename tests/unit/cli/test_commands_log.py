"""Unit tests for hassette log and execution commands."""

import pytest

from hassette.cli.client import HassetteCLIClient
from hassette.cli.commands.log import (
    EXECUTION_LOG_COLUMNS,
    LOG_COLUMNS,
    cmd_execution,
    cmd_log,
)
from tests.support.web_telemetry_helpers import make_log_entry_response, make_logs_by_execution_response
from tests.unit.cli.conftest import SINCE_EPOCH, CLIClientFactory, CommandRunner

runner = CommandRunner("hassette.cli.commands.log.make_client")


class TestCmdLog:
    @pytest.fixture
    def logs_client(self, cli_client_factory: CLIClientFactory) -> HassetteCLIClient:
        """A client serving one default log entry from /api/logs/recent."""
        entry = make_log_entry_response()
        return cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])

    def test_calls_logs_recent_endpoint(self, logs_client: HassetteCLIClient) -> None:
        """Log (no flags) fetches from GET /api/logs/recent."""
        spy = runner.spy(logs_client, cmd_log)

        assert "/api/logs/recent" in spy.paths

    def test_app_flag_passes_app_key_as_query_param(self, logs_client: HassetteCLIClient) -> None:
        """Log --app my-app passes app_key=my-app as a query param (not routing)."""
        spy = runner.spy(logs_client, cmd_log, app="my-app")

        assert spy.params_for("logs/recent")["app_key"] == "my-app"

    def test_app_flag_does_not_route_to_per_app_endpoint(self, logs_client: HassetteCLIClient) -> None:
        """Log --app my-app still uses /api/logs/recent, not a per-app endpoint."""
        spy = runner.spy(logs_client, cmd_log, app="my-app")

        assert all("/api/logs/recent" in p for p in spy.paths)
        assert not any("telemetry/app" in p for p in spy.paths)

    def test_since_and_limit_passed_as_params(self, logs_client: HassetteCLIClient) -> None:
        """Log --since 1h --limit 20 passes since (epoch float) and limit=20."""
        since_epoch = SINCE_EPOCH
        spy = runner.spy(logs_client, cmd_log, since=since_epoch, limit=20)

        params = spy.params_for("logs/recent")
        assert params["since"] == since_epoch
        assert params["limit"] == 20

    def test_source_tier_passed_as_param(self, logs_client: HassetteCLIClient) -> None:
        """Log --source-tier framework passes source_tier=framework as a query param."""
        spy = runner.spy(logs_client, cmd_log, source_tier="framework")

        assert spy.params_for("logs/recent")["source_tier"] == "framework"

    def test_instance_flag_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Log --instance 0 exits non-zero with a usage error (not supported on log)."""
        client = cli_client_factory.build_with_routes([])

        code, stderr = runner.usage_error(client, cmd_log, instance="0")

        assert code != 0
        assert "instance" in stderr.lower()

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Log renders a table with timestamp, level, and message."""
        entry = make_log_entry_response(level="INFO", message="System started", app_key="my_app")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        output = runner.stdout(client, cmd_log)

        assert "INFO" in output or "Level" in output
        assert "my_app" in output or "App" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Log --json outputs the log entries as a JSON array."""
        entry = make_log_entry_response(message="Hello world", level="WARNING")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])

        parsed = runner.json_output(client, cmd_log)
        assert isinstance(parsed, list)
        assert parsed[0]["message"] == "Hello world"
        assert parsed[0]["level"] == "WARNING"

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """Log renders a no-results message when no entries are returned."""
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [])])
        assert "No results" in runner.stderr(client, cmd_log)

    def test_log_columns_defined(self) -> None:
        """LOG_COLUMNS includes key log fields."""
        field_names = [c.field for c in LOG_COLUMNS]
        assert "timestamp" in field_names
        assert "level" in field_names
        assert "app_key" in field_names
        assert "message" in field_names

    def test_log_columns_count_is_compact(self) -> None:
        """LOG_COLUMNS uses at most 8 columns for 80-column fit."""
        assert len(LOG_COLUMNS) <= 8


class TestCmdExecution:
    def test_calls_execution_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution <uuid> fetches from GET /api/executions/{execution_id}."""
        execution_id = "abc-123-def"
        response_obj = make_logs_by_execution_response()
        client = cli_client_factory.build_with_routes(
            [("GET", f"/api/executions/{execution_id}", 200, response_obj.model_dump())]
        )
        spy = runner.spy(client, cmd_execution, uuid="abc-123-def")

        assert f"/api/executions/{execution_id}" in spy.paths

    def test_limit_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution <uuid> --limit 50 passes limit=50 as a query param."""
        response_obj = make_logs_by_execution_response()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/abc-123", 200, response_obj.model_dump())]
        )
        spy = runner.spy(client, cmd_execution, uuid="abc-123", limit=50)

        assert spy.params_for("executions")["limit"] == 50

    def test_extracts_records_from_wrapper(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution renders the records list from the LogsByExecutionResponse wrapper."""
        entry = make_log_entry_response(message="Handler invoked", level="DEBUG")
        response_obj = make_logs_by_execution_response(records=[entry])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-1", 200, response_obj.model_dump())]
        )
        output = runner.stdout(client, cmd_execution, uuid="exec-1")

        # Table output should show log entry data
        assert "DEBUG" in output or "Level" in output

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution renders a table with log entry columns."""
        entry = make_log_entry_response(level="ERROR", message="Something failed")
        response_obj = make_logs_by_execution_response(records=[entry])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-2", 200, response_obj.model_dump())]
        )
        output = runner.stdout(client, cmd_execution, uuid="exec-2")

        assert "ERROR" in output or "Level" in output

    def test_json_mode_outputs_records_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution --json outputs the records list as a JSON array."""
        entry = make_log_entry_response(message="Executed ok", level="INFO")
        response_obj = make_logs_by_execution_response(records=[entry])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-3", 200, response_obj.model_dump())]
        )

        parsed = runner.json_output(client, cmd_execution, uuid="exec-3")
        assert isinstance(parsed, list)
        assert parsed[0]["message"] == "Executed ok"

    def test_empty_execution_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution shows no-results message when records list is empty."""
        response_obj = make_logs_by_execution_response(records=[])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-4", 200, response_obj.model_dump())]
        )
        assert "No results" in runner.stderr(client, cmd_execution, uuid="exec-4")

    def test_execution_columns_defined(self) -> None:
        """EXECUTION_LOG_COLUMNS includes key log entry fields."""
        field_names = [c.field for c in EXECUTION_LOG_COLUMNS]
        assert "timestamp" in field_names
        assert "level" in field_names
        assert "message" in field_names

    def test_execution_columns_count_is_compact(self) -> None:
        """EXECUTION_LOG_COLUMNS uses at most 7 columns for 80-column fit."""
        assert len(EXECUTION_LOG_COLUMNS) <= 7
