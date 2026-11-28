"""Unit tests for ``hassette app reload --all`` (spec 162 D10)."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hassette_wire import AppReloadResult, InstanceOutcome, ReloadAllCounts, ReloadAllResponse

from hassette.cli.client import RELOAD_ALL_READ_TIMEOUT_SECONDS
from hassette.cli.commands.app import cmd_app_reload
from hassette.cli.context import CLIContext
from tests.unit.cli.conftest import (
    CLIClientFactory,
    CommandRunner,
    MockTransportBuilder,
    capture_json_stdout,
    capture_stdout,
)

runner = CommandRunner("hassette.cli.commands.app.make_client")

RELOAD_ALL = "/api/apps/reload"


def reload_all_body(*, failed: bool = False) -> dict[str, Any]:
    apps = [
        AppReloadResult(
            app_key="lights", result="succeeded", outcomes=[InstanceOutcome(instance_name="lights", result="succeeded")]
        )
    ]
    if failed:
        apps.append(
            AppReloadResult(
                app_key="door",
                result="failed",
                outcomes=[InstanceOutcome(instance_name="door", result="failed", reason="ImportError: no VALUE")],
            )
        )
    counts = ReloadAllCounts(succeeded=1, failed=int(failed), refused=0)
    return ReloadAllResponse(apps=apps, counts=counts).model_dump(mode="json")


def problem(code: str, detail: str) -> dict[str, Any]:
    return {"type": "about:blank", "title": "Conflict", "status": 409, "code": code, "detail": detail}


class TestReloadAllUsage:
    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"key": "my_app", "all_apps": True}, "don't name one"),
            ({"all_apps": True, "instance": "0"}, "don't pass --instance"),
            ({}, "Name an app to reload, or pass --all"),
            ({"key": "my_app", "wait": True}, "--wait only applies with --all"),
        ],
        ids=["all-with-key", "all-with-instance", "neither", "wait-without-all"],
    )
    def test_usage_errors_never_post(
        self, cli_client_factory: CLIClientFactory, kwargs: dict[str, Any], message: str
    ) -> None:
        builder = MockTransportBuilder()
        client = cli_client_factory.build(builder.build())

        code, stderr = runner.usage_error(client, cmd_app_reload, yes=True, **kwargs)

        assert code == 1
        assert message in stderr
        assert builder.captured_paths == []


class TestReloadAll:
    def test_prints_the_counts(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes([("POST", RELOAD_ALL, 200, reload_all_body())])

        output = runner.stdout(client, cmd_app_reload, all_apps=True, yes=True)

        assert "Reloaded 1 apps: 1 succeeded, 0 failed, 0 refused" in output

    def test_a_failed_app_exits_1_and_is_named_with_its_reason(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes([("POST", RELOAD_ALL, 200, reload_all_body(failed=True))])

        with (
            capture_stdout() as buf,
            patch(runner.make_client_path, return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_app_reload(all_apps=True, yes=True)

        assert exc_info.value.code == 1
        assert "door failed: door: ImportError: no VALUE" in buf.getvalue()

    def test_json_output_is_the_response(self, cli_client_factory: CLIClientFactory) -> None:
        body = reload_all_body()
        client = cli_client_factory.build_with_routes([("POST", RELOAD_ALL, 200, body)], json_mode=True)

        parsed = runner.json_output(client, cmd_app_reload, all_apps=True, yes=True)

        assert parsed == body

    def test_json_mode_without_yes_never_prompts(self, cli_client_factory: CLIClientFactory) -> None:
        builder = MockTransportBuilder()
        client = cli_client_factory.build(builder.build(), json_mode=True)
        with (
            patch("builtins.input", side_effect=AssertionError("must not prompt in --json mode")),
            patch(runner.make_client_path, return_value=client),
            capture_json_stdout() as captured,
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_app_reload(all_apps=True, ctx=CLIContext(json_mode=True))

        assert exc_info.value.code == 1
        assert "--yes" in json.loads("".join(captured))["detail"]
        assert builder.captured_paths == []

    def test_prompts_and_declining_never_posts(self, cli_client_factory: CLIClientFactory) -> None:
        builder = MockTransportBuilder()
        client = cli_client_factory.build(builder.build())
        with (
            patch("builtins.input", return_value="n") as mock_input,
            patch(runner.make_client_path, return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_app_reload(all_apps=True)

        assert exc_info.value.code == 0
        assert "Reload every app?" in mock_input.call_args[0][0]
        assert builder.captured_paths == []

    @pytest.mark.parametrize(
        ("code", "detail"),
        [
            ("reload_syntax_error", "helpers/notify.py:12: invalid syntax"),
            ("reload_config_invalid", "The configuration is invalid: apps.door.filename: Field required"),
            ("action_in_progress", "Another reload is still running"),
        ],
    )
    def test_a_refusal_exits_1_with_its_detail(
        self, cli_client_factory: CLIClientFactory, code: str, detail: str
    ) -> None:
        client = cli_client_factory.build_with_routes([("POST", RELOAD_ALL, 409, problem(code, detail))])

        exit_code, stderr = runner.usage_error(client, cmd_app_reload, all_apps=True, yes=True)

        assert exit_code == 1
        assert detail in stderr


class TestReloadAllTimeouts:
    @pytest.mark.parametrize(
        ("wait", "read_timeout", "expected_params"),
        [(False, RELOAD_ALL_READ_TIMEOUT_SECONDS, None), (True, None, {"wait": "true"})],
        ids=["no-wait", "wait"],
    )
    def test_read_timeout_and_query(
        self,
        cli_client_factory: CLIClientFactory,
        wait: bool,
        read_timeout: float | None,
        expected_params: dict[str, str] | None,
    ) -> None:
        client = cli_client_factory.build_with_routes([("POST", RELOAD_ALL, 200, reload_all_body())])
        post = MagicMock(wraps=client._client.post)

        with patch.object(client._client, "post", post):
            runner.stdout(client, cmd_app_reload, all_apps=True, wait=wait, yes=True)

        timeout = post.call_args.kwargs["timeout"]
        assert timeout.read == read_timeout
        assert timeout.connect == client.timeout
        assert post.call_args.kwargs["params"] == expected_params
