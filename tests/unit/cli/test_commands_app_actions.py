"""Unit tests for the hassette app start/stop/reload commands."""

import json
from typing import Any
from unittest.mock import patch

import pytest
from hassette_wire import ActionResponse, AppAction, AppInstance, InstanceOutcome, ResourceStatus

from hassette.cli.commands.app import (
    cmd_app_reload,
    cmd_app_start,
    cmd_app_stop,
)
from hassette.cli.context import CLIContext
from tests.support.web_manifest_helpers import make_app_list_response, make_app_summary
from tests.unit.cli.conftest import (
    APPS_ENDPOINT,
    CLIClientFactory,
    CommandRunner,
    capture_json_stdout,
    make_post_spy,
)

runner = CommandRunner("hassette.cli.commands.app.make_client")

#: (command, action verb, past-tense verb, extra kwargs) for the three action commands.
#: `start` never prompts for confirmation and takes no `yes` kwarg; `stop`/`reload` do.
_ACTION_CASES = [
    pytest.param(cmd_app_start, "start", "started", {}, id="start"),
    pytest.param(cmd_app_stop, "stop", "stopped", {"yes": True}, id="stop"),
    pytest.param(cmd_app_reload, "reload", "reloaded", {"yes": True}, id="reload"),
]


# cmd_app_start / cmd_app_stop / cmd_app_reload


def _action_response(
    app_key: str = "my_app", action: AppAction = "start", instance_name: str | None = None
) -> ActionResponse:
    return ActionResponse(app_key=app_key, action=action, instance_name=instance_name, outcomes=[])


def _instance(name: str, app_key: str = "my_app") -> AppInstance:
    return AppInstance(
        app_key=app_key,
        instance_name=name,
        class_name="MyApp",
        status=ResourceStatus.RUNNING,
    )


def apps_route(instances: list[AppInstance], app_key: str = "my_app") -> tuple[str, str, int, Any]:
    """Route entry for ``GET /api/apps``, used to resolve instance names."""
    app_summary = make_app_summary(app_key=app_key, instances=instances)
    app_list = make_app_list_response([app_summary])
    return ("GET", APPS_ENDPOINT, 200, app_list.model_dump())


def _instance_action_routes(
    action: AppAction,
    *,
    app_key: str = "my_app",
    instances: list[AppInstance] | None = None,
    requested: str = "inst1",
    confirmed: str | None = None,
    apps_status: int = 200,
    apps_detail: str = "",
    action_status: int = 200,
    action_detail: str = "",
) -> list[tuple[str, str, int, Any]]:
    """Route pair for an instance-scoped app action: the app list lookup plus the action POST.

    ``instances`` defaults to a single instance named ``requested``; pass an explicit list to
    exercise multi-instance app lists or a name with no entry. ``confirmed`` is the name the server
    echoes back, defaulting to ``requested`` — pass a different value to exercise the mismatch
    warning. A non-200
    ``apps_status`` or ``action_status`` makes that route fail with the matching
    ``*_detail`` as its error body instead of returning its normal successful payload.
    """
    if instances is None:
        instances = [_instance(requested, app_key=app_key)]
    if confirmed is None:
        confirmed = requested

    if apps_status != 200:
        apps_response_route = ("GET", APPS_ENDPOINT, apps_status, {"detail": apps_detail})
    else:
        apps_response_route = apps_route(instances, app_key=app_key)

    action_path = f"/api/apps/{app_key}/instances/{requested}/{action}"
    if action_status != 200:
        action_route = ("POST", action_path, action_status, {"detail": action_detail})
    else:
        action_route = (
            "POST",
            action_path,
            200,
            _action_response(app_key=app_key, action=action, instance_name=confirmed).model_dump(),
        )

    return [apps_response_route, action_route]


class TestCmdAppActionRouting:
    """Routing and messaging behavior shared by start/stop/reload.

    Parametrized across all three actions since the underlying logic (``run_app_action``)
    is one shared implementation — confirmation-prompt behavior differs per action (`start`
    never prompts, `stop`/`reload` do, and `reload`'s name-selector prompt wording is its own
    case), so those tests stay in the per-action classes below instead.
    """

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_no_instance_hits_app_level_route(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """Without --instance, sends POST /api/apps/{key}/{action}."""
        client = cli_client_factory.build_with_routes(
            [("POST", f"/api/apps/my_app/{action}", 200, _action_response(action=action).model_dump())]
        )
        spy = make_post_spy(client)
        with patch.object(client, "post", spy):
            runner.stdout(client, cmd, "my_app", **extra)

        spy.assert_called_once_with(f"/api/apps/my_app/{action}", ActionResponse)

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_with_instance_checks_and_hits_instance_route(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """--instance inst1 sends POST /api/apps/{key}/instances/inst1/{action}."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        spy = make_post_spy(client)
        with patch.object(client, "post", spy):
            runner.stdout(client, cmd, "my_app", instance="inst1", **extra)

        spy.assert_called_once_with(f"/api/apps/my_app/instances/inst1/{action}", ActionResponse)

    def test_instance_is_quoted_into_the_route(self, cli_client_factory: CLIClientFactory) -> None:
        """A name that skipped the known-instance check (app list unreadable) still can't change the route."""
        path = "/api/apps/my_app/instances/a%2F..%2Fb/stop"
        client = cli_client_factory.build_with_routes(
            [("POST", path, 200, _action_response(action="stop").model_dump())]
        )
        spy = make_post_spy(client)
        with patch.object(client, "post", spy):
            client.post_with_instance_routing("my_app", "stop", "a/../b")

        spy.assert_called_once_with(path, ActionResponse)

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_success_message_app_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """Success message uses app-level text without --instance."""
        client = cli_client_factory.build_with_routes(
            [("POST", f"/api/apps/my_app/{action}", 200, _action_response(action=action).model_dump())]
        )
        parsed = runner.json_output(client, cmd, "my_app", **extra)
        assert parsed["message"] == f"App 'my_app' {verb}"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_success_message_instance_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """Success message includes the instance name when --instance is provided."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        parsed = runner.json_output(client, cmd, "my_app", instance="inst1", **extra)
        assert parsed["message"] == f"Instance 'inst1' of 'my_app' {verb}"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_json_output_includes_instance_name_app_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """App-level (no --instance) JSON output includes instance_name: null."""
        client = cli_client_factory.build_with_routes(
            [("POST", f"/api/apps/my_app/{action}", 200, _action_response(action=action).model_dump())]
        )
        parsed = runner.json_output(client, cmd, "my_app", **extra)
        assert parsed["instance_name"] is None

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_json_output_includes_instance_name_instance_level(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """Instance-scoped JSON output includes the server-confirmed instance_name."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        parsed = runner.json_output(client, cmd, "my_app", instance="inst1", **extra)
        assert parsed["instance_name"] == "inst1"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_unknown_name_errors_with_the_known_names_and_never_posts(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """A typo, or an old script's digit, is refused before any action runs."""
        client = cli_client_factory.build_with_routes(
            _instance_action_routes(action, instances=[_instance("inst0")], requested="0")
        )
        spy = make_post_spy(client)
        with patch.object(client, "post", spy):
            code, stderr = runner.usage_error(client, cmd, "my_app", instance="0", **extra)
        assert code == 1
        assert "'inst0'" in stderr
        spy.assert_not_called()

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_instance_succeeds_when_app_list_fetch_returns_503(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """--instance still succeeds when /api/apps 503s (telemetry outage).

        The app list lookup is a best-effort name check — the mutating action itself
        has no telemetry dependency, so a degraded telemetry DB must not block it.
        """
        client = cli_client_factory.build_with_routes(
            _instance_action_routes(action, apps_status=503, apps_detail="Telemetry store unavailable")
        )
        parsed = runner.json_output(client, cmd, "my_app", instance="inst1", **extra)
        assert parsed["message"] == f"Instance 'inst1' of 'my_app' {verb}"

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_warns_on_server_instance_name_mismatch(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """A server-confirmed instance_name that disagrees with the requested one prints a warning."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action, confirmed="inst2"))
        stderr = runner.stderr(client, cmd, "my_app", instance="inst1", **extra)
        assert "requested instance 'inst1'" in stderr
        assert "server confirmed instance 'inst2'" in stderr

    @pytest.mark.parametrize(("cmd", "action", "verb", "extra"), _ACTION_CASES)
    def test_no_warning_when_server_instance_name_matches(
        self, cli_client_factory: CLIClientFactory, cmd, action: AppAction, verb: str, extra: dict[str, Any]
    ) -> None:
        """No mismatch warning when the server echoes the same instance_name that was requested."""
        client = cli_client_factory.build_with_routes(_instance_action_routes(action))
        stderr = runner.stderr(client, cmd, "my_app", instance="inst1", **extra)
        assert "requested instance" not in stderr


class TestCmdAppStart:
    def test_does_not_prompt(self, cli_client_factory: CLIClientFactory) -> None:
        """Start never calls input() — no confirmation is required."""
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/start", 200, _action_response().model_dump())]
        )
        with patch("builtins.input", side_effect=AssertionError("start must not prompt")):
            runner.stdout(client, cmd_app_start, "my_app")

    def test_json_output_lists_each_instance_outcome(self, cli_client_factory: CLIClientFactory) -> None:
        outcome = InstanceOutcome(instance_name="kitchen", result="succeeded", reason="already running")
        response = ActionResponse(app_key="my_app", action="start", instance_name=None, outcomes=[outcome])
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/start", 200, response.model_dump(mode="json"))]
        )

        parsed = runner.json_output(client, cmd_app_start, "my_app")

        assert parsed["outcomes"] == [
            {
                "instance_name": "kitchen",
                "result": "succeeded",
                "needs_restart": False,
                "reason": "already running",
            }
        ]

    def test_json_error_carries_the_problem_outcomes(self, cli_client_factory: CLIClientFactory) -> None:
        """A 409/500 problem body's per-instance outcomes reach the --json error document."""
        outcome = {
            "instance_name": "kitchen",
            "result": "refused",
            "needs_restart": True,
            "reason": "needs a hassette restart",
        }
        problem = {"code": "needs_restart", "detail": "kitchen: needs a hassette restart", "outcomes": [outcome]}
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/my_app/start", 409, problem)], json_mode=True
        )

        parsed = runner.json_error(client, cmd_app_start, "my_app")

        assert (parsed["status"], parsed["outcomes"]) == (409, [outcome])

    def test_json_error_without_outcomes_has_no_outcomes_key(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes(
            [("POST", "/api/apps/missing/start", 404, {"detail": "App not found"})], json_mode=True
        )

        assert "outcomes" not in runner.json_error(client, cmd_app_start, "missing")

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

    def test_server_404_surfaces_when_the_app_list_cannot_be_read(self, cli_client_factory: CLIClientFactory) -> None:
        """With no app list to check against, the server answers for the name."""
        client = cli_client_factory.build_with_routes(
            _instance_action_routes(
                "stop",
                requested="nope",
                apps_status=503,
                apps_detail="Telemetry store unavailable",
                action_status=404,
                action_detail="Instance not found",
            )
        )
        code, stderr = runner.usage_error(client, cmd_app_stop, "my_app", instance="nope", yes=True)
        assert code == 1
        assert "Instance not found" in stderr


class TestCmdAppReload:
    def test_prompts_for_confirmation_with_instance_name(self, cli_client_factory: CLIClientFactory) -> None:
        """Reload --instance office prompts with the instance name in the message."""
        client = cli_client_factory.build_with_routes(_instance_action_routes("reload", requested="office"))
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
