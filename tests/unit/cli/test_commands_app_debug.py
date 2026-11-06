"""Unit tests for ``hassette app debug`` (spec 148 D3)."""

import json

import httpx2 as httpx
import pytest
from hassette_wire import AppInstance, DebugCaptureResponse, InstanceDebugCapture, ResourceStatus

from hassette.cli.commands.app import cmd_app_debug
from tests.support.web_manifest_helpers import make_app_list_response, make_app_summary
from tests.unit.cli.conftest import CLIClientFactory, CommandRunner

runner = CommandRunner("hassette.cli.commands.app.make_client")


class RecordingTransport:
    """Answers the app list with ``instances`` and every PUT with ``response``, recording each PUT."""

    def __init__(self, response: DebugCaptureResponse, instances: tuple[str, ...] = ("alpha",)) -> None:
        self.response = response
        self.app_list = make_app_list_response(
            [
                make_app_summary(
                    app_key="my_app",
                    instances=[
                        AppInstance(
                            app_key="my_app", instance_name=n, class_name="MyApp", status=ResourceStatus.RUNNING
                        )
                        for n in instances
                    ],
                )
            ]
        )
        self.puts: list[tuple[str, object]] = []

    def build(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                body = self.app_list.model_dump_json()
            else:
                self.puts.append((request.url.path, json.loads(request.content)))
                body = self.response.model_dump_json()
            return httpx.Response(200, content=body, headers={"content-type": "application/json"})

        return httpx.MockTransport(handler)


def capture_response(*captured: tuple[str, bool], instance: str | None = None) -> DebugCaptureResponse:
    return DebugCaptureResponse(
        app_key="my_app",
        instance_name=instance,
        instances=[InstanceDebugCapture(instance_name=name, debug_capture=on) for name, on in captured],
    )


@pytest.mark.parametrize(
    ("state", "instance", "path", "enabled"),
    [
        pytest.param("on", None, "/api/apps/my_app/debug", True, id="app-on"),
        pytest.param("off", None, "/api/apps/my_app/debug", False, id="app-off"),
        pytest.param("on", "alpha", "/api/apps/my_app/instances/alpha/debug", True, id="instance-on"),
    ],
)
def test_puts_the_requested_state(
    cli_client_factory: CLIClientFactory, state: str, instance: str | None, path: str, enabled: bool
) -> None:
    transport = RecordingTransport(capture_response(("alpha", enabled), instance=instance))
    client = cli_client_factory.build(transport.build())

    runner.stdout(client, cmd_app_debug, "my_app", state, instance)

    assert transport.puts == [(path, {"enabled": enabled})]


def test_human_output_names_the_captured_instances(cli_client_factory: CLIClientFactory) -> None:
    transport = RecordingTransport(capture_response(("alpha", True), ("beta", True)))
    client = cli_client_factory.build(transport.build())

    output = runner.stdout(client, cmd_app_debug, "my_app", "on")

    assert "Debug capture on for app 'my_app' (instances: alpha, beta)" in output


def test_unknown_instance_fails_before_any_put(cli_client_factory: CLIClientFactory) -> None:
    transport = RecordingTransport(capture_response(("alpha", True), instance="alpha"))
    client = cli_client_factory.build(transport.build())

    code, stderr = runner.usage_error(client, cmd_app_debug, "my_app", "on", "gamma")

    assert code != 0
    assert "gamma" in stderr
    assert transport.puts == []


def test_json_output_is_the_response(cli_client_factory: CLIClientFactory) -> None:
    response = capture_response(("alpha", False), instance="alpha")
    client = cli_client_factory.build(RecordingTransport(response).build(), json_mode=True)

    parsed = runner.json_output(client, cmd_app_debug, "my_app", "off", "alpha")

    assert parsed == response.model_dump(mode="json")
