"""Unit tests for hassette log and execution commands."""

import json
from unittest.mock import patch

import pytest

from hassette.cli.commands.log import (
    EXECUTION_LOG_COLUMNS,
    LOG_COLUMNS,
    cmd_execution,
    cmd_log,
)
from hassette.cli.context import CLIContext
from hassette.test_utils.web_helpers import make_log_entry_response, make_logs_by_execution_response
from tests.unit.cli.conftest import CLIClientFactory, GetSpy, capture_json_stdout, capture_stderr, capture_stdout

# cmd_log — recent log entries


class TestCmdLog:
    def test_calls_logs_recent_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """log (no flags) fetches from GET /api/logs/recent."""
        entry = make_log_entry_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_log()

        assert "/api/logs/recent" in spy.paths

    def test_app_flag_passes_app_key_as_query_param(self, cli_client_factory: CLIClientFactory) -> None:
        """log --app my-app passes app_key=my-app as a query param (not routing)."""
        entry = make_log_entry_response(app_key="my-app")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_log(app="my-app")

        logs_call = next(r for r in spy.calls if "logs/recent" in r["path"])
        assert logs_call["params"] is not None
        assert logs_call["params"]["app_key"] == "my-app"

    def test_app_flag_does_not_route_to_per_app_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """log --app my-app still uses /api/logs/recent, not a per-app endpoint."""
        entry = make_log_entry_response(app_key="my-app")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_log(app="my-app")

        assert all("/api/logs/recent" in p for p in spy.paths)
        assert not any("telemetry/app" in p for p in spy.paths)

    def test_since_and_limit_passed_as_params(self, cli_client_factory: CLIClientFactory) -> None:
        """log --since 1h --limit 20 passes since (epoch float) and limit=20."""
        entry = make_log_entry_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        spy = GetSpy(client)

        since_epoch = 1_700_000_000.0
        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_log(since=since_epoch, limit=20)

        logs_call = next(r for r in spy.calls if "logs/recent" in r["path"])
        assert logs_call["params"] is not None
        assert logs_call["params"]["since"] == since_epoch
        assert logs_call["params"]["limit"] == 20

    def test_source_tier_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """log --source-tier framework passes source_tier=framework as a query param."""
        entry = make_log_entry_response()
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_log(source_tier="framework")

        logs_call = next(r for r in spy.calls if "logs/recent" in r["path"])
        assert logs_call["params"] is not None
        assert logs_call["params"]["source_tier"] == "framework"

    def test_instance_flag_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """log --instance 0 exits non-zero with a usage error (not supported on log)."""
        client = cli_client_factory.build_with_routes([])

        with (
            capture_stderr() as err_buf,
            patch("hassette.cli.commands.log.make_client", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_log(instance="0")

        assert exc_info.value.code != 0
        assert "instance" in err_buf.getvalue().lower()

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """log renders a table with timestamp, level, and message."""
        entry = make_log_entry_response(level="INFO", message="System started", app_key="my_app")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_log()

        output = buf.getvalue()
        assert "INFO" in output or "Level" in output
        assert "my_app" in output or "App" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """log --json outputs the log entries as a JSON array."""
        entry = make_log_entry_response(message="Hello world", level="WARNING")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])

        with (
            patch("hassette.cli.commands.log.make_client", return_value=client),
            capture_json_stdout() as captured,
        ):
            cmd_log(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["message"] == "Hello world"
        assert parsed[0]["level"] == "WARNING"

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """log renders a no-results message when no entries are returned."""
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [])])
        with (
            capture_stdout(),
            capture_stderr() as err_buf,
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_log()

        assert "No results" in err_buf.getvalue()

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


# cmd_execution — logs for a specific execution context


class TestCmdExecution:
    def test_calls_execution_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """execution <uuid> fetches from GET /api/executions/{execution_id}."""
        execution_id = "abc-123-def"
        response_obj = make_logs_by_execution_response()
        client = cli_client_factory.build_with_routes(
            [("GET", f"/api/executions/{execution_id}", 200, response_obj.model_dump())]
        )
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_execution(uuid="abc-123-def")

        assert f"/api/executions/{execution_id}" in spy.paths

    def test_limit_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """execution <uuid> --limit 50 passes limit=50 as a query param."""
        response_obj = make_logs_by_execution_response()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/abc-123", 200, response_obj.model_dump())]
        )
        spy = GetSpy(client)

        with (
            patch.object(client, "get", side_effect=spy),
            capture_stdout(),
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_execution(uuid="abc-123", limit=50)

        exec_call = next(r for r in spy.calls if "executions" in r["path"])
        assert exec_call["params"] is not None
        assert exec_call["params"]["limit"] == 50

    def test_extracts_records_from_wrapper(self, cli_client_factory: CLIClientFactory) -> None:
        """execution renders the records list from the LogsByExecutionResponse wrapper."""
        entry = make_log_entry_response(message="Handler invoked", level="DEBUG")
        response_obj = make_logs_by_execution_response(records=[entry])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-1", 200, response_obj.model_dump())]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_execution(uuid="exec-1")

        output = buf.getvalue()
        # Table output should show log entry data
        assert "DEBUG" in output or "Level" in output

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """execution renders a table with log entry columns."""
        entry = make_log_entry_response(level="ERROR", message="Something failed")
        response_obj = make_logs_by_execution_response(records=[entry])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-2", 200, response_obj.model_dump())]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_execution(uuid="exec-2")

        output = buf.getvalue()
        assert "ERROR" in output or "Level" in output

    def test_json_mode_outputs_records_list(self, cli_client_factory: CLIClientFactory) -> None:
        """execution --json outputs the records list as a JSON array."""
        entry = make_log_entry_response(message="Executed ok", level="INFO")
        response_obj = make_logs_by_execution_response(records=[entry])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-3", 200, response_obj.model_dump())]
        )

        with (
            patch("hassette.cli.commands.log.make_client", return_value=client),
            capture_json_stdout() as captured,
        ):
            cmd_execution(uuid="exec-3", ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["message"] == "Executed ok"

    def test_empty_execution_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """execution shows no-results message when records list is empty."""
        response_obj = make_logs_by_execution_response(records=[])
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/executions/exec-4", 200, response_obj.model_dump())]
        )
        with (
            capture_stdout(),
            capture_stderr() as err_buf,
            patch("hassette.cli.commands.log.make_client", return_value=client),
        ):
            cmd_execution(uuid="exec-4")

        assert "No results" in err_buf.getvalue()

    def test_execution_columns_defined(self) -> None:
        """EXECUTION_LOG_COLUMNS includes key log entry fields."""
        field_names = [c.field for c in EXECUTION_LOG_COLUMNS]
        assert "timestamp" in field_names
        assert "level" in field_names
        assert "message" in field_names

    def test_execution_columns_count_is_compact(self) -> None:
        """EXECUTION_LOG_COLUMNS uses at most 7 columns for 80-column fit."""
        assert len(EXECUTION_LOG_COLUMNS) <= 7
