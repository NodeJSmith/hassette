"""Unit tests for the hassette blocking command."""

from typing import Any

import pytest
from hassette_wire import (
    BlockingFinding,
    BlockingFrameRef,
    BlockingHandlerRef,
    BlockingInstanceRef,
    UnattributedBlockingResponse,
    UnattributedStall,
)

from hassette.cli.client import HassetteCLIClient
from hassette.cli.commands.blocking import TRUNCATED_NOTE, cmd_blocking
from tests.unit.cli.conftest import NOW_EPOCH, SINCE_EPOCH, CLIClientFactory, CommandRunner, fixed_now

APP_PATH = "/api/telemetry/app/car_climate/blocking"
ALL_PATH = "/api/telemetry/blocking/findings"
UNATTRIBUTED_PATH = "/api/telemetry/blocking/unattributed"

runner = CommandRunner("hassette.cli.commands.blocking.make_client")


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hassette.cli.output.now_epoch", fixed_now)


def frame_ref(display_path: str, lineno: int, function: str) -> BlockingFrameRef:
    return BlockingFrameRef(
        filename=f"/apps/{display_path}", lineno=lineno, function=function, display_path=display_path
    )


def finding(**overrides: Any) -> dict[str, Any]:
    base = BlockingFinding(
        app_key="car_climate",
        tier="watchdog",
        call_site=frame_ref("calendar_service.py", 98, "get_calendar_events"),
        call_site_is_user_code=True,
        callee=frame_ref("gcsa/events.py", 5, "get_events"),
        handlers=[
            BlockingHandlerRef(kind="job", id=7, name="scan_and_schedule", handler_method="scan", instance_index=0)
        ],
        instances=[BlockingInstanceRef(index=0, name="CarClimate.0")],
        event_count=9,
        max_stall_ms=534.0,
        avg_stall_ms=300.0,
        last_seen_ts=NOW_EPOCH - 120,
        latest_stack=[],
    )
    return base.model_copy(update=overrides).model_dump(mode="json")


def findings_body(*items: dict[str, Any], truncated: bool = False) -> dict[str, Any]:
    return {"findings": list(items), "truncated": truncated}


def unattributed_body(**overrides: Any) -> dict[str, Any]:
    return UnattributedBlockingResponse(**{"recent": [], **overrides}).model_dump(mode="json")


class TestPerApp:
    @pytest.fixture
    def client(self, cli_client_factory: CLIClientFactory) -> HassetteCLIClient:
        return cli_client_factory.build_with_routes([("GET", APP_PATH, 200, findings_body(finding()))])

    def test_calls_the_per_app_route_with_window(self, client: HassetteCLIClient) -> None:
        spy = runner.spy(client, cmd_blocking, app="car_climate", since=SINCE_EPOCH)

        assert spy.paths == [APP_PATH]
        assert spy.params_for("car_climate/blocking") == {"since": SINCE_EPOCH}

    def test_renders_one_row_per_finding(self, client: HassetteCLIClient) -> None:
        output = runner.stdout(client, cmd_blocking, app="car_climate")

        assert "calendar_service.py:98 in get_calendar_events" in output
        assert "gcsa/events.py get_events" in output
        assert "534ms" in output
        assert "2m ago" in output
        assert "CarClimate.0" in output

    def test_without_instance_requests_every_instance(self, client: HassetteCLIClient) -> None:
        spy = runner.spy(client, cmd_blocking, app="car_climate")

        assert "instance_index" not in spy.params_for("car_climate/blocking")

    @pytest.mark.parametrize("truncated", [False, True])
    def test_json_mode_outputs_findings_envelope(self, cli_client_factory: CLIClientFactory, truncated: bool) -> None:
        client = cli_client_factory.build_with_routes(
            [("GET", APP_PATH, 200, findings_body(finding(), truncated=truncated))], json_mode=True
        )

        data = runner.json_output(client, cmd_blocking, app="car_climate")

        assert data["truncated"] is truncated
        assert [f["app_key"] for f in data["findings"]] == ["car_climate"]

    def test_truncation_is_reported(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes(
            [("GET", APP_PATH, 200, findings_body(finding(), truncated=True))]
        )

        assert TRUNCATED_NOTE in runner.stderr(client, cmd_blocking, app="car_climate")


class TestRowText:
    @pytest.mark.parametrize(
        ("overrides", "call_site", "calls_into"),
        [
            pytest.param(
                {"call_site": None, "callee": None},
                "call site not captured (scan_and_schedule)",
                "",
                id="no-call-site",
            ),
            pytest.param(
                {
                    "tier": "monkeypatch",
                    "primitive": "socket.connect",
                    "callee": None,
                    "call_site_is_user_code": False,
                    "detected_in_package": "requests",
                    "call_site": frame_ref("requests/api.py", 10, "get"),
                },
                "detected inside requests (requests/api.py:10 in get)",
                "socket.connect",
                id="tier2-library",
            ),
        ],
    )
    def test_row_text(
        self, cli_client_factory: CLIClientFactory, overrides: dict[str, Any], call_site: str, calls_into: str
    ) -> None:
        client = cli_client_factory.build_with_routes([("GET", APP_PATH, 200, findings_body(finding(**overrides)))])

        output = runner.stdout(client, cmd_blocking, app="car_climate")

        assert call_site in output
        assert calls_into in output


class TestAllApps:
    def test_fetches_every_app_and_unattributed_stalls(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes(
            [("GET", ALL_PATH, 200, findings_body(finding())), ("GET", UNATTRIBUTED_PATH, 200, unattributed_body())]
        )

        spy = runner.spy(client, cmd_blocking, since=SINCE_EPOCH)

        assert spy.paths == [ALL_PATH, UNATTRIBUTED_PATH]
        assert spy.params_for("blocking/unattributed") == {"since": SINCE_EPOCH}

    def test_renders_unattributed_stalls_when_present(self, cli_client_factory: CLIClientFactory) -> None:
        stall = UnattributedStall(
            detected_ts=NOW_EPOCH - 60,
            tier="watchdog",
            reason="displaced",
            stall_duration_ms=5000.0,
            app_frame=frame_ref("helper.py", 3, "go"),
            stack=[],
        )
        body = unattributed_body(total_count=1, displaced_count=1, max_stall_ms=5000.0, recent=[stall])
        client = cli_client_factory.build_with_routes(
            [("GET", ALL_PATH, 200, findings_body()), ("GET", UNATTRIBUTED_PATH, 200, body)]
        )

        output = runner.stdout(client, cmd_blocking)

        assert "Loop stalls credited to no app: 1 (1 displaced, 0 framework)" in output
        assert "helper.py:3 in go" in output
        assert "5.0s" in output

    def test_json_mode_outputs_one_document(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes(
            [("GET", ALL_PATH, 200, findings_body(finding())), ("GET", UNATTRIBUTED_PATH, 200, unattributed_body())],
            json_mode=True,
        )

        data = runner.json_output(client, cmd_blocking)

        assert data["findings"]["findings"][0]["app_key"] == "car_climate"
        assert data["unattributed"]["total_count"] == 0

    def test_instance_without_app_is_a_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        code, stderr = runner.usage_error(cli_client_factory.build_with_routes([]), cmd_blocking, instance="0")

        assert code != 0
        assert "--instance requires --app" in stderr
