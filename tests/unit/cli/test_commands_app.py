"""Unit tests for hassette app, app health, app activity, app config, and app source commands."""

import json
from unittest.mock import patch

import pytest

from hassette.cli.commands.app import (
    APP_ACTIVITY_COLUMNS,
    APP_HEALTH_COLUMNS,
    APP_LIST_COLUMNS,
    cmd_app,
    cmd_app_activity,
    cmd_app_config,
    cmd_app_health,
    cmd_app_source,
)
from hassette.cli.context import CLIContext
from hassette.test_utils.web_helpers import (
    make_activity_feed_entry,
    make_app_config_response,
    make_app_health_response,
    make_app_source_response,
    make_manifest_list_response,
    make_manifest_response,
)
from hassette.web.models import AppInstanceResponse, AppManifestListResponse
from tests.unit.cli.conftest import CLIClientFactory, capture_stderr, capture_stdout

# cmd_app (bare — list all apps)


class TestCmdApp:
    def test_calls_manifests_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Bare app command fetches from GET /api/apps/manifests."""
        manifest = make_manifest_response()
        data = make_manifest_list_response([manifest])
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app()

        assert "/api/apps/manifests" in called_paths

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """app renders a table with app_key and status columns."""
        manifest = make_manifest_response(app_key="my_app", status="running", display_name="My App")
        data = make_manifest_list_response([manifest])
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app()
        output = buf.getvalue()
        assert "my_app" in output
        assert "running" in output

    def test_json_mode_outputs_manifests_list(self, cli_client_factory: CLIClientFactory) -> None:
        """app --json outputs the manifests list as a JSON array."""
        manifest = make_manifest_response(app_key="my_app")
        data = make_manifest_list_response([manifest])
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.app.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_app(ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["app_key"] == "my_app"

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """app renders a no-results message when manifests list is empty."""
        data = make_manifest_list_response([])
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])
        with (
            capture_stdout(),
            capture_stderr() as err_buf,
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app()
        assert "No results" in err_buf.getvalue()

    def test_app_list_columns_defined(self) -> None:
        """APP_LIST_COLUMNS includes the key per-app fields."""
        field_names = [c.field for c in APP_LIST_COLUMNS]
        assert "app_key" in field_names
        assert "status" in field_names
        assert "display_name" in field_names
        assert "instance_count" in field_names
        assert "autostart" in field_names

    def test_app_list_columns_count_is_compact(self) -> None:
        """APP_LIST_COLUMNS uses at most 8 columns for readability."""
        assert len(APP_LIST_COLUMNS) <= 8


# cmd_app_health


class TestCmdAppHealth:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """app health fetches from GET /api/telemetry/app/{key}/health."""
        health = make_app_health_response()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_health("my-app")

        assert any("/api/telemetry/app/my-app/health" in p for p in called_paths)

    def test_instance_integer_passes_index_param(self, cli_client_factory: CLIClientFactory) -> None:
        """app health --instance 1 passes instance_index=1 as a query param."""
        health = make_app_health_response()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_health("my-app", instance="1")

        health_call = next(r for r in received_params if "health" in r["path"])
        assert health_call["params"] is not None
        assert health_call["params"]["instance_index"] == 1

    def test_instance_name_resolution(self, cli_client_factory: CLIClientFactory) -> None:
        """app health --instance office resolves the name to an index."""
        health = make_app_health_response()
        instance_resp = AppInstanceResponse(
            app_key="my-app",
            index=2,
            instance_name="office",
            class_name="MyApp",
            status="running",  # pyright: ignore[reportArgumentType]
        )
        manifest_resp = make_manifest_response(app_key="my-app", instances=[instance_resp])
        manifest_list = AppManifestListResponse(
            total=1, running=1, failed=0, stopped=0, disabled=0, blocked=0, manifests=[manifest_resp]
        )
        client, _ = cli_client_factory.build_with_routes(
            [
                ("GET", "/api/apps/manifests", 200, manifest_list.model_dump()),
                ("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump()),
            ]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_health("my-app", instance="office")

        health_call = next(r for r in received_params if "health" in r["path"])
        assert health_call["params"] is not None
        assert health_call["params"]["instance_index"] == 2

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """app health renders a key-value detail panel."""
        health = make_app_health_response(health_status="excellent", error_rate=0.05)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_health("my-app")
        output = buf.getvalue()
        assert "health_status" in output
        assert "excellent" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """app health --json outputs a JSON object."""
        health = make_app_health_response(error_rate=0.1)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.app.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_app_health("my-app", ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert parsed["error_rate"] == pytest.approx(0.1)
        assert "health_status" in parsed

    def test_health_columns_defined(self) -> None:
        """APP_HEALTH_COLUMNS includes key health fields."""
        field_names = [c.field for c in APP_HEALTH_COLUMNS]
        assert "health_status" in field_names
        assert "error_rate" in field_names
        assert "last_activity_ts" in field_names


# cmd_app_activity


class TestCmdAppActivity:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """app activity fetches from GET /api/telemetry/app/{key}/activity."""
        entry = make_activity_feed_entry()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/activity", 200, [entry.model_dump()])]
        )
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_activity("my-app")

        assert any("/api/telemetry/app/my-app/activity" in p for p in called_paths)

    def test_no_instance_omits_instance_index(self, cli_client_factory: CLIClientFactory) -> None:
        """app activity with no --instance does NOT pass instance_index param."""
        entry = make_activity_feed_entry()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/activity", 200, [entry.model_dump()])]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_activity("my-app")

        activity_call = next(r for r in received_params if "activity" in r["path"])
        # instance_index must not be present — API returns all instances when absent
        params = activity_call["params"] or {}
        assert "instance_index" not in params

    def test_since_and_limit_passed_as_params(self, cli_client_factory: CLIClientFactory) -> None:
        """app activity --since and --limit are forwarded as query params."""
        entry = make_activity_feed_entry()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/activity", 200, [entry.model_dump()])]
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
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_activity("my-app", since=since_epoch, limit=10)

        activity_call = next(r for r in received_params if "activity" in r["path"])
        assert activity_call["params"] is not None
        assert activity_call["params"]["since"] == since_epoch
        assert activity_call["params"]["limit"] == 10

    def test_instance_integer_passes_index_param(self, cli_client_factory: CLIClientFactory) -> None:
        """app activity --instance 2 passes instance_index=2."""
        entry = make_activity_feed_entry()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/activity", 200, [entry.model_dump()])]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_activity("my-app", instance="2")

        activity_call = next(r for r in received_params if "activity" in r["path"])
        assert activity_call["params"] is not None
        assert activity_call["params"]["instance_index"] == 2

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """app activity renders a table with handler name and status."""
        entry = make_activity_feed_entry(handler_name="on_light_change", app_key="my-app")
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/activity", 200, [entry.model_dump()])]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_activity("my-app")
        output = buf.getvalue()
        # Rich may truncate the handler name in a narrow console — match the prefix
        assert "on_light_c" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """app activity --json outputs entries as a JSON array."""
        entry = make_activity_feed_entry(row_id="h-42")
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/activity", 200, [entry.model_dump()])]
        )
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.app.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_app_activity("my-app", ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["row_id"] == "h-42"

    def test_activity_columns_defined(self) -> None:
        """APP_ACTIVITY_COLUMNS includes key activity fields."""
        field_names = [c.field for c in APP_ACTIVITY_COLUMNS]
        assert "handler_name" in field_names
        assert "status" in field_names
        assert "kind" in field_names
        assert "timestamp" in field_names

    def test_activity_columns_count_is_compact(self) -> None:
        """APP_ACTIVITY_COLUMNS uses at most 8 columns for readability."""
        assert len(APP_ACTIVITY_COLUMNS) <= 8


# cmd_app_config


class TestCmdAppConfig:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """app config fetches from GET /api/apps/{key}/config."""
        cfg = make_app_config_response(app_key="my-app")
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_config("my-app")

        assert any("/api/apps/my-app/config" in p for p in called_paths)

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """app config renders a detail panel with app_key and class_name."""
        cfg = make_app_config_response(app_key="my-app", class_name="MyApp")
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_config("my-app")
        output = buf.getvalue()
        assert "my-app" in output
        assert "MyApp" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """app config --json outputs a JSON object."""
        cfg = make_app_config_response(app_key="my-app", enabled=True)
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.app.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_app_config("my-app", ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert parsed["app_key"] == "my-app"
        assert parsed["enabled"] is True


# cmd_app_source


class TestCmdAppSource:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """app source fetches from GET /api/apps/{key}/source."""
        src = make_app_source_response(app_key="my-app")
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/source", 200, src.model_dump())])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_source("my-app")

        assert any("/api/apps/my-app/source" in p for p in called_paths)

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """app source renders a detail panel showing filename and content."""
        src = make_app_source_response(app_key="my-app", filename="my_app.py", content="class MyApp: pass\n")
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/source", 200, src.model_dump())])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.app.make_client", return_value=client),
        ):
            cmd_app_source("my-app")
        output = buf.getvalue()
        assert "my_app.py" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """app source --json outputs a JSON object with content field."""
        src = make_app_source_response(app_key="my-app", content="class MyApp: pass\n", line_count=1)
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/source", 200, src.model_dump())])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.app.make_client", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_app_source("my-app", ctx=CLIContext(json_mode=True))

        parsed = json.loads("".join(captured))
        assert parsed["app_key"] == "my-app"
        assert "content" in parsed
        assert parsed["line_count"] == 1
