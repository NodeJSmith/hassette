"""Unit tests for hassette listener and listener <id> commands."""

import pytest
from hassette_wire import ExecutionTrigger

from hassette.cli.client import HassetteCLIClient
from hassette.cli.commands.listener import (
    LISTENER_LIST_COLUMNS,
    cmd_listener,
)
from hassette.cli.formatters import fmt_change
from tests.support.web_telemetry_helpers import make_execution, make_listener_miss, make_listener_summary
from tests.unit.cli.conftest import SINCE_EPOCH, CLIClientFactory, CommandRunner

runner = CommandRunner("hassette.cli.commands.listener.make_client")
LISTENER_42_EXECUTIONS_ENDPOINT = "/api/telemetry/listener/42/executions"
LISTENER_42_MISSES_ENDPOINT = "/api/telemetry/listener/42/misses"

# cmd_listener (bare — list all listeners)


class TestCmdListener:
    def test_calls_global_listeners_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener (no --app) fetches from GET /api/bus/listeners."""
        listener = make_listener_summary()
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        spy = runner.spy(client, cmd_listener)

        assert "/api/bus/listeners" in spy.paths

    def test_app_flag_routes_to_per_app_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --app my-app fetches from /api/telemetry/app/my-app/listeners."""
        listener = make_listener_summary(app_key="my-app")
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/listeners", 200, [listener.model_dump()])]
        )
        spy = runner.spy(client, cmd_listener, app="my-app")

        assert any("/api/telemetry/app/my-app/listeners" in p for p in spy.paths)

    def test_app_and_instance_passes_instance_name(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --app my-app --instance office passes instance_name=office as a query param."""
        listener = make_listener_summary(app_key="my-app")
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/listeners", 200, [listener.model_dump()])]
        )
        spy = runner.spy(client, cmd_listener, app="my-app", instance="office")

        assert spy.params_for("listeners")["instance_name"] == "office"

    def test_instance_without_app_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --instance 0 (without --app) exits non-zero with usage error."""
        client = cli_client_factory.build_with_routes([])

        code, _stderr = runner.usage_error(client, cmd_listener, instance="0")

        assert code != 0

    def test_source_tier_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --source-tier app passes source_tier=app as a query param."""
        listener = make_listener_summary()
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        spy = runner.spy(client, cmd_listener, source_tier="app")

        assert spy.params_for("listeners")["source_tier"] == "app"

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener renders a table with listener_id and target."""
        listener = make_listener_summary(listener_id=42, target="light.kitchen")
        client = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        output = runner.stdout(client, cmd_listener)

        assert "42" in output
        assert "light" in output
        assert "test_" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Listener --json outputs the listener list as a JSON array."""
        listener = make_listener_summary(listener_id=7)
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


class TestCmdListenerMisses:
    @pytest.fixture
    def listener_42_misses_client(self, cli_client_factory: CLIClientFactory) -> HassetteCLIClient:
        """A client serving one near-miss row for listener 42."""
        return cli_client_factory.build_with_routes(
            [("GET", LISTENER_42_MISSES_ENDPOINT, 200, [make_listener_miss().model_dump()])]
        )

    def test_calls_misses_endpoint_with_since_and_limit(self, listener_42_misses_client: HassetteCLIClient) -> None:
        """Listener <id> --misses fetches /misses, not /executions, and passes --since and --limit."""
        spy = runner.spy(
            listener_42_misses_client, cmd_listener, listener_id=42, misses=True, since=SINCE_EPOCH, limit=5
        )

        assert spy.paths == [LISTENER_42_MISSES_ENDPOINT]
        assert spy.params_for("misses") == {"since": SINCE_EPOCH, "limit": 5}

    def test_human_mode_renders_reason_filter_and_change(self, listener_42_misses_client: HassetteCLIClient) -> None:
        output = runner.stdout(listener_42_misses_client, cmd_listener, listener_id=42, misses=True)

        assert "filter" in output
        assert "→ on" in output
        assert "light.kitchen" in output
        assert "off → dim" in output

    def test_json_mode_outputs_the_rows(self, listener_42_misses_client: HassetteCLIClient) -> None:
        parsed = runner.json_output(listener_42_misses_client, cmd_listener, listener_id=42, misses=True)

        assert [(row["reason"], row["count"]) for row in parsed] == [("filter", 3)]

    def test_without_listener_id_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        code, stderr = runner.usage_error(cli_client_factory.build_with_routes([]), cmd_listener, misses=True)

        assert code != 0
        assert "--misses requires a listener ID" in stderr

    def test_change_column_blank_without_values(self) -> None:
        miss = make_listener_miss(trigger=ExecutionTrigger(topic="hassette.event.custom"))

        assert fmt_change(miss) == ""
