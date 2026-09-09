"""Unit tests for hassette listener and listener <id> commands."""

import pytest

from hassette.cli.client import HassetteCLIClient
from hassette.cli.commands.listener import (
    LISTENER_INVOCATION_COLUMNS,
    LISTENER_LIST_COLUMNS,
    cmd_listener,
)
from tests.support.web_telemetry_helpers import make_execution, make_listener_with_summary
from tests.unit.cli.conftest import SINCE_EPOCH, CLIClientFactory, CommandRunner

runner = CommandRunner("hassette.cli.commands.listener.make_client")
LISTENER_42_EXECUTIONS_ENDPOINT = "/api/telemetry/listener/42/executions"


class TestCmdListener:
    def test_calls_global_listeners_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener (no --app) fetches from GET /api/bus/listeners."""
        listener = make_listener_with_summary()
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        spy = runner.spy(client, cmd_listener)

        assert "/api/bus/listeners" in spy.paths

    def test_app_flag_routes_to_per_app_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --app my-app fetches from /api/telemetry/app/my-app/listeners."""
        listener = make_listener_with_summary(app_key="my-app")
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/listeners", 200, [listener.model_dump()])]
        )
        spy = runner.spy(client, cmd_listener, app="my-app")

        assert any("/api/telemetry/app/my-app/listeners" in p for p in spy.paths)

    def test_app_and_instance_passes_instance_index(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --app my-app --instance 0 passes instance_index=0 as a query param."""
        listener = make_listener_with_summary(app_key="my-app", instance_index=0)
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/listeners", 200, [listener.model_dump()])]
        )
        spy = runner.spy(client, cmd_listener, app="my-app", instance="0")

        assert spy.params_for("listeners")["instance_index"] == 0

    def test_instance_without_app_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --instance 0 (without --app) exits non-zero with usage error."""
        client = cli_client_factory.build_with_routes([])

        code, _stderr = runner.usage_error(client, cmd_listener, instance="0")

        assert code != 0

    def test_source_tier_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --source-tier app passes source_tier=app as a query param."""
        listener = make_listener_with_summary()
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        spy = runner.spy(client, cmd_listener, source_tier="app")

        assert spy.params_for("listeners")["source_tier"] == "app"

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener renders a table with listener_id and target."""
        listener = make_listener_with_summary(listener_id=42, target="light.kitchen")
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        output = runner.stdout(client, cmd_listener)

        assert "42" in output
        assert "light" in output
        assert "test_" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --json outputs the listener list as a JSON array."""
        listener = make_listener_with_summary(listener_id=7)
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])

        parsed = runner.json_output(client, cmd_listener)
        assert isinstance(parsed, list)
        assert parsed[0]["listener_id"] == 7

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener renders a no-results message when no listeners are returned."""
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [])])
        assert "No results" in runner.stderr(client, cmd_listener)

    def test_listener_list_columns_defined(self) -> None:
        """LISTENER_LIST_COLUMNS includes key listener fields."""
        field_names = [c.field for c in LISTENER_LIST_COLUMNS]
        assert "listener_id" in field_names
        assert "app_key" in field_names
        assert "target" in field_names
        assert "handler_method" in field_names
        assert "total_invocations" in field_names

    def test_listener_list_columns_count_is_compact(self) -> None:
        """LISTENER_LIST_COLUMNS uses at most 10 columns for wide terminal fit."""
        assert len(LISTENER_LIST_COLUMNS) <= 10


class TestCmdListenerDetail:
    @pytest.fixture
    def listener_42_client(self, cli_client_factory: CLIClientFactory) -> HassetteCLIClient:
        """A client serving one invocation for listener 42, the id the query-param tests use."""
        invocation = make_execution(kind="handler", listener_id=42)
        return cli_client_factory.build_with_routes(
            [("GET", LISTENER_42_EXECUTIONS_ENDPOINT, 200, [invocation.model_dump()])]
        )

    def test_calls_invocations_endpoint(self, listener_42_client: HassetteCLIClient) -> None:
        """Listener <id> fetches from GET /api/telemetry/listener/{id}/executions."""
        spy = runner.spy(listener_42_client, cmd_listener, listener_id=42)

        assert LISTENER_42_EXECUTIONS_ENDPOINT in spy.paths

    def test_limit_passed_as_param(self, listener_42_client: HassetteCLIClient) -> None:
        """Listener <id> --limit 5 passes limit=5 as a query param."""
        spy = runner.spy(listener_42_client, cmd_listener, listener_id=42, limit=5)

        assert spy.params_for("executions")["limit"] == 5

    def test_since_passed_as_param(self, listener_42_client: HassetteCLIClient) -> None:
        """Listener <id> --since passes since as a query param."""
        since_epoch = SINCE_EPOCH
        spy = runner.spy(listener_42_client, cmd_listener, listener_id=42, since=since_epoch)

        assert spy.params_for("executions")["since"] == since_epoch

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener <id> renders a table with status and duration."""
        invocation = make_execution(kind="handler", listener_id=1, duration_ms=12.5)
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/listener/1/executions", 200, [invocation.model_dump()])]
        )
        output = runner.stdout(client, cmd_listener, listener_id=1)

        assert "success" in output.lower() or "Status" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener <id> --json outputs the invocations as a JSON array."""
        invocation = make_execution(kind="handler", listener_id=1, duration_ms=20.0)
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/listener/1/executions", 200, [invocation.model_dump()])]
        )

        parsed = runner.json_output(client, cmd_listener, listener_id=1)
        assert isinstance(parsed, list)
        assert parsed[0]["duration_ms"] == pytest.approx(20.0)

    def test_invocation_columns_defined(self) -> None:
        """LISTENER_INVOCATION_COLUMNS includes key invocation fields."""
        field_names = [c.field for c in LISTENER_INVOCATION_COLUMNS]
        assert "status" in field_names
        assert "duration_ms" in field_names
        assert "execution_start_ts" in field_names
        assert "error_type" in field_names

    def test_invocation_columns_count_is_compact(self) -> None:
        """LISTENER_INVOCATION_COLUMNS uses at most 7 columns for 80-column fit."""
        assert len(LISTENER_INVOCATION_COLUMNS) <= 7
