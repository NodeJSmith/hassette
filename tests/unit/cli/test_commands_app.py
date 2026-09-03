"""Unit tests for hassette app, app health, app activity, app config, and app source commands."""

from typing import Any

import pytest

from hassette.cli.client import HassetteCLIClient
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
from hassette.cli.output import now_epoch
from hassette.web.models import AppInstanceResponse, AppManifestListResponse
from tests.support.web_manifest_helpers import make_manifest_list_response, make_manifest_response
from tests.support.web_response_helpers import (
    make_app_config_response,
    make_app_health_response,
    make_app_source_response,
)
from tests.support.web_telemetry_helpers import make_activity_feed_entry
from tests.unit.cli.conftest import (
    SINCE_EPOCH,
    CLIClientFactory,
    CommandRunner,
)

runner = CommandRunner("hassette.cli.commands.app.make_client")
ACTIVITY_ENDPOINT = "/api/telemetry/app/my-app/activity"

# cmd_app (bare — list all apps)


class TestCmdApp:
    def test_calls_manifests_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Bare app command fetches from GET /api/apps/manifests."""
        manifest = make_manifest_response()
        data = make_manifest_list_response([manifest])
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])
        spy = runner.spy(client, cmd_app)

        assert "/api/apps/manifests" in spy.paths

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """App renders a table with app_key and status columns."""
        manifest = make_manifest_response(app_key="my_app", status="running", display_name="My App")
        data = make_manifest_list_response([manifest])
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])
        output = runner.stdout(client, cmd_app)
        assert "my_app" in output
        assert "running" in output

    def test_json_mode_outputs_manifests_list(self, cli_client_factory: CLIClientFactory) -> None:
        """App --json outputs the manifests list as a JSON array."""
        manifest = make_manifest_response(app_key="my_app")
        data = make_manifest_list_response([manifest])
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])

        parsed = runner.json_output(client, cmd_app)
        assert isinstance(parsed, list)
        assert parsed[0]["app_key"] == "my_app"

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """App renders a no-results message when manifests list is empty."""
        data = make_manifest_list_response([])
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/manifests", 200, data.model_dump())])
        assert "No results" in runner.stderr(client, cmd_app)

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
        """App health fetches from GET /api/telemetry/app/{key}/health."""
        health = make_app_health_response()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        spy = runner.spy(client, cmd_app_health, "my-app")

        assert any("/api/telemetry/app/my-app/health" in p for p in spy.paths)

    def test_instance_integer_passes_index_param(self, cli_client_factory: CLIClientFactory) -> None:
        """App health --instance 1 passes instance_index=1 as a query param."""
        health = make_app_health_response()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        spy = runner.spy(client, cmd_app_health, "my-app", instance="1")

        assert spy.params_for("health")["instance_index"] == 1

    def test_instance_name_resolution(self, cli_client_factory: CLIClientFactory) -> None:
        """App health --instance office resolves the name to an index."""
        health = make_app_health_response()
        instance_resp = AppInstanceResponse(
            app_key="my-app",
            index=2,
            instance_name="office",
            class_name="MyApp",
            status="running",  # pyright: ignore[reportArgumentType]
        )
        manifest_resp = make_manifest_response(app_key="my-app", instances=[instance_resp])
        manifest_list = AppManifestListResponse(total=1, status_counts={"running": 1}, manifests=[manifest_resp])
        client = cli_client_factory.build_with_routes(
            [
                ("GET", "/api/apps/manifests", 200, manifest_list.model_dump()),
                ("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump()),
            ]
        )
        spy = runner.spy(client, cmd_app_health, "my-app", instance="office")

        assert spy.params_for("health")["instance_index"] == 2

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """App health renders a key-value detail panel."""
        health = make_app_health_response(health_status="excellent", error_rate=0.05)
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        output = runner.stdout(client, cmd_app_health, "my-app")
        assert "health_status" in output
        assert "excellent" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """App health --json outputs a JSON object."""
        health = make_app_health_response(error_rate=0.1)
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )

        parsed = runner.json_output(client, cmd_app_health, "my-app")
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
    @pytest.fixture
    def activity_client(self, cli_client_factory: CLIClientFactory) -> HassetteCLIClient:
        """A client serving one default activity entry from my-app's activity feed."""
        entry = make_activity_feed_entry()
        return cli_client_factory.build_with_routes([("GET", ACTIVITY_ENDPOINT, 200, [entry.model_dump()])])

    def test_calls_correct_endpoint(self, activity_client: HassetteCLIClient) -> None:
        """App activity fetches from GET /api/telemetry/app/{key}/activity."""
        spy = runner.spy(activity_client, cmd_app_activity, "my-app")

        assert any(ACTIVITY_ENDPOINT in p for p in spy.paths)

    def test_no_instance_omits_instance_index(self, activity_client: HassetteCLIClient) -> None:
        """App activity with no --instance does NOT pass instance_index param."""
        spy = runner.spy(activity_client, cmd_app_activity, "my-app")

        # Not spy.params_for() — that asserts params were sent at all, and "no params" is one
        # of the passing outcomes here: the API returns all instances when instance_index is absent.
        activity_call = next(r for r in spy.calls if "activity" in r["path"])
        assert "instance_index" not in (activity_call["params"] or {})

    def test_since_and_limit_passed_as_params(self, activity_client: HassetteCLIClient) -> None:
        """App activity --since and --limit are forwarded as query params."""
        since_epoch = SINCE_EPOCH
        spy = runner.spy(activity_client, cmd_app_activity, "my-app", since=since_epoch, limit=10)

        params = spy.params_for("activity")
        assert params["since"] == since_epoch
        assert params["limit"] == 10

    def test_instance_integer_passes_index_param(self, activity_client: HassetteCLIClient) -> None:
        """App activity --instance 2 passes instance_index=2."""
        spy = runner.spy(activity_client, cmd_app_activity, "my-app", instance="2")

        assert spy.params_for("activity")["instance_index"] == 2

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """App activity renders a table with handler name and status."""
        # timestamp is pinned to "now" (not the shared fixed-epoch default) so the "When"
        # column always renders as "just now" — a fixed-epoch default grows by one digit
        # every ~10x days elapsed, stealing column width from Handler and truncating it
        # further than this test expects.
        entry = make_activity_feed_entry(handler_name="on_light_change", app_key="my-app", timestamp=now_epoch())
        client = cli_client_factory.build_with_routes([("GET", ACTIVITY_ENDPOINT, 200, [entry.model_dump()])])
        output = runner.stdout(client, cmd_app_activity, "my-app")
        # Rich may truncate the handler name in a narrow console — match the prefix
        assert "on_light_c" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """App activity --json outputs entries as a JSON array."""
        entry = make_activity_feed_entry(row_id="h-42")
        client = cli_client_factory.build_with_routes([("GET", ACTIVITY_ENDPOINT, 200, [entry.model_dump()])])

        parsed = runner.json_output(client, cmd_app_activity, "my-app")
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
        """App config fetches from GET /api/apps/{key}/config."""
        cfg = make_app_config_response(app_key="my-app")
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])
        spy = runner.spy(client, cmd_app_config, "my-app")

        assert any("/api/apps/my-app/config" in p for p in spy.paths)

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """App config renders a detail panel with app_key and class_name."""
        cfg = make_app_config_response(app_key="my-app", class_name="MyApp")
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])
        output = runner.stdout(client, cmd_app_config, "my-app")
        assert "my-app" in output
        assert "MyApp" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """App config --json outputs a JSON object."""
        cfg = make_app_config_response(app_key="my-app", enabled=True)
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])

        parsed = runner.json_output(client, cmd_app_config, "my-app")
        assert parsed["app_key"] == "my-app"
        assert parsed["enabled"] is True

    def test_renders_config_values_not_schema_blob(self, cli_client_factory: CLIClientFactory) -> None:
        """App config shows masked config values but never dumps the inlined config_schema."""
        cfg = make_app_config_response(
            app_key="my-app",
            app_config={"setting_name": "visible_value"},
            config_schema={"properties": {"setting_name": {"SCHEMA_BLOB_MARKER": True}}},
        )
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])
        output = runner.stdout(client, cmd_app_config, "my-app")
        assert "visible_value" in output
        assert "SCHEMA_BLOB_MARKER" not in output

    @pytest.mark.parametrize(
        "app_config",
        [
            pytest.param({"setting_name": "visible_value"}, id="single-instance-dict"),
            pytest.param([{"setting_name": "first"}, {"setting_name": "second"}], id="multi-instance-list"),
            pytest.param([], id="empty-multi-instance-list"),
        ],
    )
    def test_json_mode_emits_app_config_verbatim_without_schema_blob(
        self, cli_client_factory: CLIClientFactory, app_config: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        """App config --json round-trips app_config as-is and never dumps the config_schema envelope.

        The empty-list case is the interesting one: it must stay ``[]`` rather than falling back
        to the default dict when a multi-instance app has no instances.
        """
        cfg = make_app_config_response(
            app_key="my-app",
            app_config=app_config,
            config_schema={"properties": {"setting_name": {"SCHEMA_BLOB_MARKER": True}}},
        )
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/config", 200, cfg.model_dump())])
        parsed = runner.json_output(client, cmd_app_config, "my-app")
        assert parsed["app_config"] == app_config
        assert "config_schema" not in parsed


# cmd_app_source


class TestCmdAppSource:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """App source fetches from GET /api/apps/{key}/source."""
        src = make_app_source_response(app_key="my-app")
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/source", 200, src.model_dump())])
        spy = runner.spy(client, cmd_app_source, "my-app")

        assert any("/api/apps/my-app/source" in p for p in spy.paths)

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """App source renders a detail panel showing filename and content."""
        src = make_app_source_response(app_key="my-app", filename="my_app.py", content="class MyApp: pass\n")
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/source", 200, src.model_dump())])
        output = runner.stdout(client, cmd_app_source, "my-app")
        assert "my_app.py" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """App source --json outputs a JSON object with content field."""
        src = make_app_source_response(app_key="my-app", content="class MyApp: pass\n", line_count=1)
        client = cli_client_factory.build_with_routes([("GET", "/api/apps/my-app/source", 200, src.model_dump())])

        parsed = runner.json_output(client, cmd_app_source, "my-app")
        assert parsed["app_key"] == "my-app"
        assert "content" in parsed
        assert parsed["line_count"] == 1
