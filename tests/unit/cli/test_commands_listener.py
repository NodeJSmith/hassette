"""Unit tests for hassette listener and listener <id> commands."""

import json
from unittest.mock import patch

import pytest

from hassette.cli.commands.listener import (
    LISTENER_INVOCATION_COLUMNS,
    LISTENER_LIST_COLUMNS,
    cmd_listener,
)
from hassette.cli.context import CLIContext
from hassette.test_utils.web_helpers import make_execution, make_listener_with_summary
from tests.unit.cli.conftest import CLIClientFactory, capture_stderr, capture_stdout

# cmd_listener (bare — list all listeners)


class TestCmdListener:
    def test_calls_global_listeners_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """listener (no --app) fetches from GET /api/bus/listeners."""
        listener = make_listener_with_summary()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener()

        assert "/api/bus/listeners" in called_paths

    def test_app_flag_routes_to_per_app_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """listener --app my-app fetches from /api/telemetry/app/my-app/listeners."""
        listener = make_listener_with_summary(app_key="my-app")
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/listeners", 200, [listener.model_dump()])]
        )
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener(app="my-app")

        assert any("/api/telemetry/app/my-app/listeners" in p for p in called_paths)

    def test_app_and_instance_passes_instance_index(self, cli_client_factory: CLIClientFactory) -> None:
        """listener --app my-app --instance 0 passes instance_index=0 as a query param."""
        listener = make_listener_with_summary(app_key="my-app", instance_index=0)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/listeners", 200, [listener.model_dump()])]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener(app="my-app", instance="0")

        listeners_call = next(r for r in received_params if "listeners" in r["path"])
        assert listeners_call["params"] is not None
        assert listeners_call["params"]["instance_index"] == 0

    def test_instance_without_app_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """listener --instance 0 (without --app) exits non-zero with usage error."""
        client, _ = cli_client_factory.build_with_routes([])

        with (
            capture_stderr(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_listener(instance="0")

        assert exc_info.value.code != 0

    def test_source_tier_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """listener --source-tier app passes source_tier=app as a query param."""
        listener = make_listener_with_summary()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener(source_tier="app")

        listeners_call = next(r for r in received_params if "listeners" in r["path"])
        assert listeners_call["params"] is not None
        assert listeners_call["params"]["source_tier"] == "app"

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """listener renders a table with listener_id and entity_id."""
        listener = make_listener_with_summary(listener_id=42, entity_id="light.kitchen")
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener()

        output = buf.getvalue()
        assert "42" in output
        assert "test_" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """listener --json outputs the listener list as a JSON array."""
        listener = make_listener_with_summary(listener_id=7)
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [listener.model_dump()])])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.listener.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_listener(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["listener_id"] == 7

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """listener renders a no-results message when no listeners are returned."""
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/bus/listeners", 200, [])])
        with (
            capture_stdout(),
            capture_stderr() as err_buf,
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener()

        assert "No results" in err_buf.getvalue()

    def test_listener_list_columns_defined(self) -> None:
        """LISTENER_LIST_COLUMNS includes key listener fields."""
        field_names = [c.field for c in LISTENER_LIST_COLUMNS]
        assert "listener_id" in field_names
        assert "app_key" in field_names
        assert "entity_id" in field_names
        assert "handler_method" in field_names
        assert "total_invocations" in field_names

    def test_listener_list_columns_count_is_compact(self) -> None:
        """LISTENER_LIST_COLUMNS uses at most 10 columns for wide terminal fit."""
        assert len(LISTENER_LIST_COLUMNS) <= 10


class TestCmdListenerDetail:
    def test_calls_invocations_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """listener <id> fetches from GET /api/telemetry/listener/{id}/executions."""
        invocation = make_execution(kind="handler", listener_id=42)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/listener/42/executions", 200, [invocation.model_dump()])]
        )
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener(listener_id=42)

        assert "/api/telemetry/listener/42/executions" in called_paths

    def test_limit_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """listener <id> --limit 5 passes limit=5 as a query param."""
        invocation = make_execution(kind="handler", listener_id=42)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/listener/42/executions", 200, [invocation.model_dump()])]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener(listener_id=42, limit=5)

        executions_call = next(r for r in received_params if "executions" in r["path"])
        assert executions_call["params"] is not None
        assert executions_call["params"]["limit"] == 5

    def test_since_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """listener <id> --since passes since as a query param."""
        invocation = make_execution(kind="handler", listener_id=42)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/listener/42/executions", 200, [invocation.model_dump()])]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        since_epoch = 1_700_000_000.0
        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener(listener_id=42, since=since_epoch)

        executions_call = next(r for r in received_params if "executions" in r["path"])
        assert executions_call["params"] is not None
        assert executions_call["params"]["since"] == since_epoch

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """listener <id> renders a table with status and duration."""
        invocation = make_execution(kind="handler", listener_id=1, duration_ms=12.5)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/listener/1/executions", 200, [invocation.model_dump()])]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.listener.make_client", return_value=client),
        ):
            cmd_listener(listener_id=1)

        output = buf.getvalue()
        assert "success" in output.lower() or "Status" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """listener <id> --json outputs the invocations as a JSON array."""
        invocation = make_execution(kind="handler", listener_id=1, duration_ms=20.0)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/listener/1/executions", 200, [invocation.model_dump()])]
        )
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.listener.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_listener(listener_id=1, ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
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
