"""Unit tests for hassette app, app health, app activity, app config, app source, and app
start/stop/reload commands.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest
from hassette_wire import ActionResponse, AppGridEntry, AppInstanceResponse, AppListResponse, AppStatus

from hassette.cli.client import HassetteCLIClient
from hassette.cli.commands.app import (
    APP_ACTIVITY_COLUMNS,
    APP_HEALTH_COLUMNS,
    APP_LIST_COLUMNS,
    cmd_app,
    cmd_app_activity,
    cmd_app_config,
    cmd_app_health,
    cmd_app_reload,
    cmd_app_source,
    cmd_app_start,
    cmd_app_stop,
)
from hassette.cli.context import CLIContext
from hassette.cli.output import now_epoch
from hassette.const.misc import SECONDS_PER_HOUR
from tests.support.web_manifest_helpers import make_app_list_response, make_app_summary
from tests.support.web_response_helpers import (
    make_app_activity,
    make_app_config_response,
    make_app_grid_entry,
    make_app_grid_response,
    make_app_health,
    make_app_source_response,
)
from tests.support.web_telemetry_helpers import make_activity_feed_entry
from tests.unit.cli.conftest import (
    NOW_EPOCH,
    SINCE_EPOCH,
    CLIClientFactory,
    CommandRunner,
    capture_json_stdout,
    fixed_now,
    make_post_spy,
    resolve_path,
)

runner = CommandRunner("hassette.cli.commands.app.make_client")
ACTIVITY_ENDPOINT = "/api/telemetry/app/my-app/activity"
APP_GRID_ENDPOINT = "/api/telemetry/app-grid"

#: (command, action verb, past-tense verb, extra kwargs) for the three action commands.
#: `start` never prompts for confirmation and takes no `yes` kwarg; `stop`/`reload` do.
_ACTION_CASES = [
    pytest.param(cmd_app_start, "start", "started", {}, id="start"),
    pytest.param(cmd_app_stop, "stop", "stopped", {"yes": True}, id="stop"),
    pytest.param(cmd_app_reload, "reload", "reloaded", {"yes": True}, id="reload"),
]


# cmd_app (bare — list all apps)


def _grid_body(entries: list[AppGridEntry] | None = None) -> dict[str, Any]:
    """JSON body for a mocked ``GET /api/telemetry/app-grid`` response."""
    return make_app_grid_response(entries).model_dump(mode="json")


def _grid_body_missing(*parts: str) -> dict[str, Any]:
    """Grid body with one row whose ``activity`` parts named in ``parts`` are ``None``."""
    activity = make_app_activity(total_invocations=42).model_copy(update=dict.fromkeys(parts))
    return _grid_body([make_app_grid_entry(activity=activity)])


class TestCmdApp:
    def test_reads_grid_over_the_last_hour(self, cli_client_factory: CLIClientFactory) -> None:
        """Bare app command reads GET /api/telemetry/app-grid with since = now - 1h on the CLI's clock."""
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, _grid_body())])
        with patch("hassette.cli.output.now_epoch", fixed_now):
            spy = runner.spy(client, cmd_app)

        assert spy.params_for("app-grid")["since"] == pytest.approx(NOW_EPOCH - SECONDS_PER_HOUR)

    def test_human_mode_renders_app_and_hour_invocations(self, cli_client_factory: CLIClientFactory) -> None:
        """The table shows app fields and activity.total_invocations under Invoc/1h."""
        entry = make_app_grid_entry(
            app=make_app_summary(app_key="my_app", status=AppStatus.RUNNING, display_name="My App"),
            activity=make_app_activity(total_invocations=42),
        )
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, _grid_body([entry]))])
        output = runner.stdout(client, cmd_app)
        assert "my_app" in output
        assert "running" in output
        assert "42" in output

    def test_json_mode_outputs_app_activity_rows(self, cli_client_factory: CLIClientFactory) -> None:
        """App --json outputs the grid rows as a JSON array of {app, activity}."""
        entry = make_app_grid_entry(app=make_app_summary(app_key="my_app"))
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, _grid_body([entry]))])

        parsed = runner.json_output(client, cmd_app)
        assert isinstance(parsed, list)
        assert set(parsed[0]) == {"app", "activity"}
        assert parsed[0]["app"]["app_key"] == "my_app"

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """App renders a no-results message when the grid is empty."""
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, _grid_body([]))])
        assert "No results" in runner.stderr(client, cmd_app)

    def test_null_stats_renders_a_blank_invocations_cell(self, cli_client_factory: CLIClientFactory) -> None:
        """A row whose stats didn't compute shows a blank Invoc/1h cell, never a count."""
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, _grid_body_missing("stats"))])
        output = runner.stdout(client, cmd_app)
        assert "test_app" in output
        assert "42" not in output
        assert " 0 " not in output

    def test_missing_parts_warn_on_stderr_by_field_name(self, cli_client_factory: CLIClientFactory) -> None:
        """Every null part is named, windowed ones included, since the command sends a since."""
        body = _grid_body_missing("stats", "last_error", "blocking_event_count")
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, body)])

        # Two runs on purpose: the runner captures one stream per invocation.
        assert "stats, last_error, blocking_event_count" in runner.stderr(client, cmd_app)
        assert "last_error" not in runner.stdout(client, cmd_app)

    def test_missing_parts_warn_in_json_mode_without_touching_stdout(
        self, cli_client_factory: CLIClientFactory
    ) -> None:
        client = cli_client_factory.build_with_routes(
            [("GET", APP_GRID_ENDPOINT, 200, _grid_body_missing("activity_buckets"))]
        )
        assert "activity_buckets" in runner.stderr(client, cmd_app, ctx=CLIContext(json_mode=True))
        assert runner.json_output(client, cmd_app)[0]["activity"]["activity_buckets"] is None

    def test_fully_successful_grid_prints_no_warning(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, _grid_body())])
        assert "Warning" not in runner.stderr(client, cmd_app)

    def test_empty_grid_prints_no_warning(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes([("GET", APP_GRID_ENDPOINT, 200, _grid_body([]))])
        assert "Warning" not in runner.stderr(client, cmd_app)

    def test_app_list_columns_defined(self) -> None:
        """APP_LIST_COLUMNS reads app fields from `app` and the hour's invocations from `activity`."""
        field_names = [c.field for c in APP_LIST_COLUMNS]
        assert "app.app_key" in field_names
        assert "app.status" in field_names
        assert "app.display_name" in field_names
        assert "app.instance_count" in field_names
        assert "app.autostart" in field_names
        assert "activity.stats.total_invocations" in field_names

    def test_app_list_column_paths_resolve_on_a_populated_row(self) -> None:
        """No column is blank because its path is stale: each one reads a value from a full row."""
        row = make_app_grid_entry().model_dump(mode="json")
        assert {c.field for c in APP_LIST_COLUMNS if resolve_path(row, c.field) is None} == set()

    def test_app_list_columns_count_is_compact(self) -> None:
        """APP_LIST_COLUMNS uses at most 8 columns for readability."""
        assert len(APP_LIST_COLUMNS) <= 8


# cmd_app_health


class TestCmdAppHealth:
    def test_calls_correct_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """App health fetches from GET /api/telemetry/app/{key}/health."""
        health = make_app_health()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        spy = runner.spy(client, cmd_app_health, "my-app")

        assert any("/api/telemetry/app/my-app/health" in p for p in spy.paths)

    def test_instance_integer_passes_index_param(self, cli_client_factory: CLIClientFactory) -> None:
        """App health --instance 1 passes instance_index=1 as a query param."""
        health = make_app_health()
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        spy = runner.spy(client, cmd_app_health, "my-app", instance="1")

        assert spy.params_for("health")["instance_index"] == 1

    def test_instance_name_resolution(self, cli_client_factory: CLIClientFactory) -> None:
        """App health --instance office resolves the name to an index."""
        health = make_app_health()
        instance_resp = AppInstanceResponse(
            app_key="my-app",
            index=2,
            instance_name="office",
            class_name="MyApp",
            status="running",  # pyright: ignore[reportArgumentType]
        )
        manifest_resp = make_app_summary(app_key="my-app", instances=[instance_resp])
        manifest_list = AppListResponse(total=1, status_counts={"running": 1}, apps=[manifest_resp])
        client = cli_client_factory.build_with_routes(
            [
                ("GET", "/api/apps", 200, manifest_list.model_dump()),
                ("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump()),
            ]
        )
        spy = runner.spy(client, cmd_app_health, "my-app", instance="office")

        assert spy.params_for("health")["instance_index"] == 2

    def test_human_mode_renders_panel(self, cli_client_factory: CLIClientFactory) -> None:
        """App health renders a key-value detail panel."""
        health = make_app_health(health_status="excellent", error_rate=0.05)
        client = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/health", 200, health.model_dump())]
        )
        output = runner.stdout(client, cmd_app_health, "my-app")
        assert "health_status" in output
        assert "excellent" in output

    def test_json_mode_outputs_valid_json(self, cli_client_factory: CLIClientFactory) -> None:
        """App health --json outputs a JSON object."""
        health = make_app_health(error_rate=0.1)
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


# cmd_app_start / cmd_app_stop / cmd_app_reload


def _action_response(
    app_key: str = "my_app", action: str = "start", instance_index: int | None = None
) -> ActionResponse:
    return ActionResponse(app_key=app_key, action=action, instance_index=instance_index)


def _instance(index: int, name: str, app_key: str = "my_app") -> AppInstanceResponse:
    return AppInstanceResponse(
        app_key=app_key,
        index=index,
        instance_name=name,
        class_name="MyApp",
        status="running",  # pyright: ignore[reportArgumentType]
    )


def _manifest_route(instances: list[AppInstanceResponse], app_key: str = "my_app") -> tuple[str, str, int, Any]:
    """Route entry for ``GET /api/apps``, used to resolve instance names."""
    manifest_resp = make_app_summary(app_key=app_key, instances=instances)
    manifest_list = make_app_list_response([manifest_resp])
    return ("GET", "/api/apps", 200, manifest_list.model_dump())


def _instance_action_routes(
    action: str,
    *,
    app_key: str = "my_app",
    instances: list[AppInstanceResponse] | None = None,
    requested_index: int = 1,
    confirmed_index: int | None = None,
    manifest_status: int = 200,
    manifest_detail: str = "",
    action_status: int = 200,
    action_detail: str = "",
) -> list[tuple[str, str, int, Any]]:
    """Route pair for an instance-scoped app action: the manifest lookup plus the action POST.

    ``instances`` defaults to a single instance at ``requested_index`` named ``inst{index}``;
    pass an explicit list to exercise multi-instance manifests or an index that resolves to no
    entry. ``confirmed_index`` is the index the server echoes back, defaulting to
    ``requested_index`` — pass a different value to exercise the mismatch warning. A non-200
    ``manifest_status`` or ``action_status`` makes that route fail with the matching
    ``*_detail`` as its error body instead of returning its normal successful payload.
    """
    if instances is None:
        instances = [_instance(requested_index, f"inst{requested_index}", app_key=app_key)]
    if confirmed_index is None:
        confirmed_index = requested_index

    if manifest_status != 200:
        manifest_route = ("GET", "/api/apps", manifest_status, {"detail": manifest_detail})
    else:
        manifest_route = _manifest_route(instances, app_key=app_key)

    action_path = f"/api/apps/{app_key}/instances/{requested_index}/{action}"
    if action_status != 200:
        action_route = ("POST", action_path, action_status, {"detail": action_detail})
    else:
        action_route = (
            "POST",
            action_path,
            200,
            _action_response(app_key=app_key, action=action, instance_index=confirmed_index).model_dump(),
        )

    return [manifest_route, action_route]


class TestCmdAppActionRouting:
    """Routing and messaging behavior shared by start/stop/reload.

    Parametrized across all three actions since the underlying logic (``_run_app_action``)
    is one shared implementation — confirmation-prompt behavior differs per action (`start`
    never prompts, `stop`/`reload` do, and `reload`'s name-selector prompt wording is its own
    case), so those tests stay in the per-action classes below instead.
    """

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_no_instance_hits_app_level_route(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """Without --instance, sends POST /api/apps/{key}/{action}."""
        client = cli_client_factory.build_with_routes(
            [("POST", f"/api/apps/my_app/{action}", 200, _action_response(action=action).model_dump())]
        )
        spy = make_post_spy(client)
        with patch.object(client, "post", spy):
            runner.stdout(client, cmd, "my_app", **extra)

        spy.assert_called_once_with(f"/api/apps/my_app/{action}")

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_with_instance_resolves_and_hits_instance_route(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """--instance 1 resolves the index and sends POST /api/apps/{key}/instances/1/{action}."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        spy = make_post_spy(client)
        with patch.object(client, "post", spy):
            runner.stdout(client, cmd, "my_app", instance="1", **extra)

        spy.assert_called_once_with(f"/api/apps/my_app/instances/1/{action}")

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_success_message_app_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """Success message uses app-level text without --instance."""
        client = cli_client_factory.build_with_routes(
            [("POST", f"/api/apps/my_app/{action}", 200, _action_response(action=action).model_dump())]
        )
        parsed = runner.json_output(client, cmd, "my_app", **extra)
        assert parsed["message"] == f"App 'my_app' {verb}"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_success_message_instance_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """Success message includes the resolved instance name when --instance is provided."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        parsed = runner.json_output(client, cmd, "my_app", instance="1", **extra)
        assert parsed["message"] == f"Instance 'inst1' of 'my_app' {verb}"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_json_output_includes_instance_index_app_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """App-level (no --instance) JSON output includes instance_index: null."""
        client = cli_client_factory.build_with_routes(
            [("POST", f"/api/apps/my_app/{action}", 200, _action_response(action=action).model_dump())]
        )
        parsed = runner.json_output(client, cmd, "my_app", **extra)
        assert parsed["instance_index"] is None

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_json_output_includes_instance_index_instance_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """Instance-scoped JSON output includes the server-confirmed instance_index."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        parsed = runner.json_output(client, cmd, "my_app", instance="1", **extra)
        assert parsed["instance_index"] == 1

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_success_message_falls_back_to_raw_selector_when_instance_unresolvable(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """A numeric --instance with no matching manifest entry falls back to the raw selector."""
        client = cli_client_factory.build_with_routes(
            _instance_action_routes(action, instances=[_instance(0, "inst0")], requested_index=5)
        )
        parsed = runner.json_output(client, cmd, "my_app", instance="5", **extra)
        assert parsed["message"] == f"Instance '5' of 'my_app' {verb}"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_numeric_instance_succeeds_when_manifest_fetch_returns_503(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """A numeric --instance still succeeds when /api/apps 503s (telemetry outage).

        The manifest lookup is a best-effort name resolution — the mutating action itself
        has no telemetry dependency, so a degraded telemetry DB must not block it.
        """
        client = cli_client_factory.build_with_routes(
            _instance_action_routes(action, manifest_status=503, manifest_detail="Telemetry store unavailable")
        )
        parsed = runner.json_output(client, cmd, "my_app", instance="1", **extra)
        assert parsed["message"] == f"Instance '1' of 'my_app' {verb}"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_warns_on_server_instance_index_mismatch(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """A server-confirmed instance_index that disagrees with the requested one prints a warning."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action, confirmed_index=2))
        stderr = runner.stderr(client, cmd, "my_app", instance="1", **extra)
        assert "requested instance 1" in stderr
        assert "server confirmed instance 2" in stderr

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_no_warning_when_server_instance_index_matches(
        self, cli_client_factory: CLIClientFactory, cmd, action: str, verb: str, extra: dict[str, Any]
    ) -> None:
        """No mismatch warning when the server echoes the same instance_index that was requested."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        stderr = runner.stderr(client, cmd, "my_app", instance="1", **extra)
        assert "requested instance" not in stderr


class TestCmdAppStart:
    def test_does_not_prompt(self, cli_client_factory: CLIClientFactory) -> None:
        """Start never calls input() — no confirmation is required."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/start", 200, _action_response().model_dump())]
        )
        with patch("builtins.input", side_effect=AssertionError("start must not prompt")):
            runner.stdout(client, cmd_app_start, "my_app")

    def test_error_on_404_surfaces_via_http_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Start against a non-existent app surfaces the 404 via the standard HTTP error path."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/missing/start", 404, {"detail": "App not found"})]
        )
        code, stderr = runner.usage_error(client, cmd_app_start, "missing")
        assert code == 1
        assert "App not found" in stderr


class TestCmdAppStop:
    def test_prompts_for_confirmation(self, cli_client_factory: CLIClientFactory) -> None:
        """Stop without --yes prompts for confirmation before posting."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/stop", 200, _action_response(action="stop").model_dump())]
        )
        with patch("builtins.input", return_value="y") as mock_input:
            runner.stdout(client, cmd_app_stop, "my_app")

        mock_input.assert_called_once()
        assert "Stop app 'my_app'?" in mock_input.call_args[0][0]

    @pytest.mark.parametrize("response", ["n", "", "no"], ids=["n", "empty", "no"])
    def test_declining_confirmation_exits_without_posting(
        self, cli_client_factory: CLIClientFactory, response: str
    ) -> None:
        """Answering anything but 'y' aborts before POSTing."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/stop", 200, _action_response(action="stop").model_dump())]
        )
        spy = make_post_spy(client)
        with (
            patch("builtins.input", return_value=response),
            patch.object(client, "post", spy),
            patch(runner.make_client_path, return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_app_stop("my_app")

        assert exc_info.value.code == 0
        spy.assert_not_called()

    def test_yes_flag_skips_prompt(self, cli_client_factory: CLIClientFactory) -> None:
        """Stop --yes skips the confirmation prompt entirely."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/stop", 200, _action_response(action="stop").model_dump())]
        )
        with patch("builtins.input", side_effect=AssertionError("must not prompt with --yes")):
            runner.stdout(client, cmd_app_stop, "my_app", yes=True)

    def test_json_mode_without_yes_requires_yes_flag(self, cli_client_factory: CLIClientFactory) -> None:
        """Stop --json without --yes never calls input() and exits via the JSON usage-error path."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/stop", 200, _action_response(action="stop").model_dump())],
            json_mode=True,
        )
        spy = make_post_spy(client)
        with (
            patch("builtins.input", side_effect=AssertionError("must not prompt in --json mode")),
            patch.object(client, "post", spy),
            patch(runner.make_client_path, return_value=client),
            capture_json_stdout() as captured,
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_app_stop("my_app", ctx=CLIContext(json_mode=True))

        assert exc_info.value.code == 1
        spy.assert_not_called()
        doc = json.loads("".join(captured))
        assert doc["error"] is True
        assert "--yes" in doc["detail"]

    def test_error_on_instance_out_of_range(self, cli_client_factory: CLIClientFactory) -> None:
        """Stop against an out-of-range instance index surfaces the 404 via the HTTP error path.

        The out-of-range index (9) has no matching manifest entry, so name resolution falls back
        to the raw selector rather than blocking client-side — range validation stays the
        server's authoritative job (see ``_require_valid_instance_index``).
        """
        client = cli_client_factory.build_with_routes(
            _instance_action_routes(
                "stop",
                instances=[_instance(0, "inst0"), _instance(1, "inst1")],
                requested_index=9,
                action_status=404,
                action_detail="Instance not found",
            )
        )
        code, stderr = runner.usage_error(client, cmd_app_stop, "my_app", instance="9", yes=True)
        assert code == 1
        assert "Instance not found" in stderr


class TestCmdAppReload:
    def test_prompts_for_confirmation_with_instance_name(self, cli_client_factory: CLIClientFactory) -> None:
        """Reload --instance office prompts with the instance name in the message."""
        client = cli_client_factory.build_with_routes(
            _instance_action_routes("reload", instances=[_instance(1, "office")])
        )
        with patch("builtins.input", return_value="y") as mock_input:
            runner.stdout(client, cmd_app_reload, "my_app", instance="office")

        assert "Reload instance 'office' of 'my_app'?" in mock_input.call_args[0][0]

    def test_json_mode_without_yes_requires_yes_flag(self, cli_client_factory: CLIClientFactory) -> None:
        """Reload --json without --yes never calls input() and exits via the JSON usage-error path."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/reload", 200, _action_response(action="reload").model_dump())],
            json_mode=True,
        )
        spy = make_post_spy(client)
        with (
            patch("builtins.input", side_effect=AssertionError("must not prompt in --json mode")),
            patch.object(client, "post", spy),
            patch(runner.make_client_path, return_value=client),
            capture_json_stdout() as captured,
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_app_reload("my_app", ctx=CLIContext(json_mode=True))

        assert exc_info.value.code == 1
        spy.assert_not_called()
        doc = json.loads("".join(captured))
        assert doc["error"] is True
        assert "--yes" in doc["detail"]

    def test_declining_confirmation_exits_without_posting(self, cli_client_factory: CLIClientFactory) -> None:
        """Declining the reload confirmation aborts before POSTing."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/reload", 200, _action_response(action="reload").model_dump())]
        )
        spy = make_post_spy(client)
        with (
            patch("builtins.input", return_value="n"),
            patch.object(client, "post", spy),
            patch(runner.make_client_path, return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_app_reload("my_app")

        assert exc_info.value.code == 0
        spy.assert_not_called()
