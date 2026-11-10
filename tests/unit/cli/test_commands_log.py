"""Unit tests for hassette log and execution commands."""

from io import StringIO
from unittest.mock import patch

import pytest
from hassette_wire import CausingWrite, ExecutionDetailResponse, ExecutionStatus, ExecutionTrigger
from pydantic import BaseModel, ValidationError
from rich.console import Console

import hassette.cli.output as output_module
from hassette.cli.client import HassetteCLIClient
from hassette.cli.commands.log import (
    API_WRITES_TRUNCATED_MESSAGE,
    EXECUTION_LOG_COLUMNS,
    EXECUTION_NOT_FOUND_MESSAGE,
    LOG_COLUMNS,
    cmd_execution,
    cmd_log,
    execution_summary,
)
from hassette.cli.formatters import fmt_log_message
from hassette.cli.output import Column, render_table
from hassette.utils.exception_utils import get_traceback_string
from tests.support.web_telemetry_helpers import (
    make_api_write,
    make_execution,
    make_execution_detail_response,
    make_log_entry,
)
from tests.unit.cli.conftest import SINCE_EPOCH, CLIClientFactory, CommandRunner

NARROW_CONSOLE_WIDTH = 100
TRACEBACK_MESSAGE = "Job error in demo_stimulator.tick: something went wrong\n" + "\n".join(
    f'  File "/usr/src/app/apps/demo_stimulator/really/long/path/module_{i}.py", line {i}, in handler_{i}'
    for i in range(6)
)

runner = CommandRunner("hassette.cli.commands.log.make_client")


def _detail_client(
    factory: CLIClientFactory, execution_id: str, detail: ExecutionDetailResponse
) -> HassetteCLIClient:
    """A client whose only route is the execution detail read, answering ``detail``."""
    return factory.build_with_routes([("GET", f"/api/executions/{execution_id}", 200, detail.model_dump(mode="json"))])

OFFICE_TRIGGER = ExecutionTrigger(
    topic="hass.event.state_changed",
    entity_id="light.office",
    old_value="off",
    new_value="on",
    context_id="ctx-1",
    origin="LOCAL",
)

# cmd_log — recent log entries


class TestCmdLog:
    @pytest.fixture
    def logs_client(self, cli_client_factory: CLIClientFactory) -> HassetteCLIClient:
        """A client serving one default log entry from /api/logs/recent."""
        entry = make_log_entry()
        return cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])

    def test_calls_logs_recent_endpoint(self, logs_client: HassetteCLIClient) -> None:
        """Log (no flags) fetches from GET /api/logs/recent."""
        spy = runner.spy(logs_client, cmd_log)

        assert "/api/logs/recent" in spy.paths

    def test_app_flag_passes_app_key_as_query_param(self, logs_client: HassetteCLIClient) -> None:
        """Log --app my-app passes app_key=my-app as a query param (not routing)."""
        spy = runner.spy(logs_client, cmd_log, app="my-app")

        assert spy.params_for("logs/recent")["app_key"] == "my-app"

    def test_app_flag_does_not_route_to_per_app_endpoint(self, logs_client: HassetteCLIClient) -> None:
        """Log --app my-app still uses /api/logs/recent, not a per-app endpoint."""
        spy = runner.spy(logs_client, cmd_log, app="my-app")

        assert all("/api/logs/recent" in p for p in spy.paths)
        assert not any("telemetry/app" in p for p in spy.paths)

    def test_since_and_limit_passed_as_params(self, logs_client: HassetteCLIClient) -> None:
        """Log --since 1h --limit 20 passes since (epoch float) and limit=20."""
        since_epoch = SINCE_EPOCH
        spy = runner.spy(logs_client, cmd_log, since=since_epoch, limit=20)

        params = spy.params_for("logs/recent")
        assert params["since"] == since_epoch
        assert params["limit"] == 20

    def test_author_passed_as_param(self, logs_client: HassetteCLIClient) -> None:
        """Log --author framework passes author=framework as a query param."""
        spy = runner.spy(logs_client, cmd_log, author="framework")

        assert spy.params_for("logs/recent")["author"] == "framework"

    def test_author_omitted_by_default(self, logs_client: HassetteCLIClient) -> None:
        """Without --author the server's default view applies, so no author param is sent."""
        spy = runner.spy(logs_client, cmd_log)

        assert "author" not in spy.params_for("logs/recent")

    def test_level_passed_as_param(self, logs_client: HassetteCLIClient) -> None:
        """Log --level error forwards level=error unchanged; the server uppercases and validates it."""
        spy = runner.spy(logs_client, cmd_log, level="error")

        assert spy.params_for("logs/recent")["level"] == "error"

    def test_level_omitted_by_default(self, logs_client: HassetteCLIClient) -> None:
        """Without --level no level param is sent, so every level comes back."""
        spy = runner.spy(logs_client, cmd_log)

        assert "level" not in spy.params_for("logs/recent")

    def test_invalid_level_exits_with_http_error(self, cli_client_factory: CLIClientFactory) -> None:
        """A 422 for an invalid --level exits through the CLI's HTTP error path, not a traceback."""
        detail = {"detail": "Invalid level 'loud'"}
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 422, detail)])

        code, stderr = runner.usage_error(client, cmd_log, level="loud")

        assert code == 1
        assert "Invalid level 'loud'" in stderr

    def test_instance_flag_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Log --instance 0 exits non-zero with a usage error (not supported on log)."""
        client = cli_client_factory.build_with_routes([])

        code, stderr = runner.usage_error(client, cmd_log, instance="0")

        assert code != 0
        assert "instance" in stderr.lower()

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Log renders a table with timestamp, level, and message."""
        entry = make_log_entry(level="INFO", message="System started", app_key="my_app")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])
        output = runner.stdout(client, cmd_log)

        assert "INFO" in output or "Level" in output
        assert "my_app" in output or "App" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Log --json outputs the log entries as a JSON array."""
        entry = make_log_entry(message="Hello world", level="WARNING")
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [entry.model_dump()])])

        parsed = runner.json_output(client, cmd_log)
        assert isinstance(parsed, list)
        assert parsed[0]["message"] == "Hello world"
        assert parsed[0]["level"] == "WARNING"

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """Log renders a no-results message when no entries are returned."""
        client = cli_client_factory.build_with_routes([("GET", "/api/logs/recent", 200, [])])
        assert "No results" in runner.stderr(client, cmd_log)

    def test_log_columns_defined(self) -> None:
        """LOG_COLUMNS includes key log fields."""
        field_names = [c.field for c in LOG_COLUMNS]
        assert "timestamp" in field_names
        assert "level" in field_names
        assert "app_key" in field_names
        assert "message" in field_names

    def test_log_columns_count_is_compact(self) -> None:
        """LOG_COLUMNS uses at most 8 columns for 80-column fit."""
        assert len(LOG_COLUMNS) <= 8


# cmd_execution — logs for a specific execution context


class TestCmdExecution:
    def test_calls_execution_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution <uuid> reads only GET /api/executions/{execution_id}."""
        execution_id = "abc-123-def"
        client = _detail_client(cli_client_factory, execution_id, make_execution_detail_response())
        spy = runner.spy(client, cmd_execution, uuid="abc-123-def")

        assert spy.paths == [f"/api/executions/{execution_id}"]

    def test_limit_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution <uuid> --limit 50 passes limit=50 as a query param."""
        client = _detail_client(cli_client_factory, "abc-123", make_execution_detail_response())
        spy = runner.spy(client, cmd_execution, uuid="abc-123", limit=50)

        assert spy.params_for("executions")["limit"] == 50

    def test_author_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution <uuid> --author all passes author=all as a query param."""
        client = _detail_client(cli_client_factory, "abc-123", make_execution_detail_response())
        spy = runner.spy(client, cmd_execution, uuid="abc-123", author="all")

        assert spy.params_for("executions")["author"] == "all"

    def test_marks_framework_lines_only(self, cli_client_factory: CLIClientFactory) -> None:
        """The Author column reads ``framework`` on framework lines and stays blank on app lines."""
        logs = [
            make_log_entry(message="first line", author="app"),
            make_log_entry(id=2, seq=2, message="second line", author="framework"),
        ]
        client = _detail_client(cli_client_factory, "exec-1", make_execution_detail_response(logs=logs))
        output = runner.stdout(client, cmd_execution, uuid="exec-1")

        app_row = next(line for line in output.splitlines() if "first line" in line)
        framework_row = next(line for line in output.splitlines() if "second line" in line)
        assert "framework" not in app_row
        assert "framework" in framework_row

    def test_human_mode_renders_log_table(self, cli_client_factory: CLIClientFactory) -> None:
        entry = make_log_entry(level="ERROR", message="Something failed")
        client = _detail_client(cli_client_factory, "exec-2", make_execution_detail_response(logs=[entry]))
        output = runner.stdout(client, cmd_execution, uuid="exec-2")

        assert "Something failed" in output

    def test_json_mode_prints_detail_as_served(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution --json prints the detail response unchanged: record, writes and logs."""
        detail = make_execution_detail_response(
            execution=make_execution(execution_id="exec-3", trigger=OFFICE_TRIGGER),
            api_writes=[make_api_write(execution_id="exec-3")],
            logs=[make_log_entry(message="Executed ok", level="INFO")],
        )
        client = _detail_client(cli_client_factory, "exec-3", detail)

        parsed = runner.json_output(client, cmd_execution, uuid="exec-3")
        assert parsed == detail.model_dump(mode="json")

    def test_human_mode_missing_record_names_batching_and_retention(self, cli_client_factory: CLIClientFactory) -> None:
        client = _detail_client(cli_client_factory, "exec-7", make_execution_detail_response(execution=None))

        assert EXECUTION_NOT_FOUND_MESSAGE in runner.stderr(client, cmd_execution, uuid="exec-7")

    def test_failed_request_fails_the_command(self, cli_client_factory: CLIClientFactory) -> None:
        client = cli_client_factory.build_with_routes([("GET", "/api/executions/exec-6", 500, {"detail": "boom"})])

        with pytest.raises(SystemExit) as exc_info:
            runner.stdout(client, cmd_execution, uuid="exec-6")
        assert exc_info.value.code != 0

    def test_human_mode_shows_trigger_block_above_logs(self, cli_client_factory: CLIClientFactory) -> None:
        detail = make_execution_detail_response(
            execution=make_execution(execution_id="exec-8", trigger=OFFICE_TRIGGER),
            logs=[make_log_entry(message="handler ran")],
        )
        output = runner.stdout(_detail_client(cli_client_factory, "exec-8", detail), cmd_execution, uuid="exec-8")

        assert "light.office" in output
        assert "off → on" in output
        assert output.index("light.office") < output.index("handler ran")

    def test_human_mode_shows_writes_between_summary_and_logs(self, cli_client_factory: CLIClientFactory) -> None:
        """The writes table lists kind, operation, target, outcome and error code, but not data."""
        write = make_api_write(
            operation="light.turn_on",
            target={"entity_id": ["light.porch"], "area_id": ["garden"]},
            data='{"brightness":200}',
            outcome="rejected",
            error_code="not_found",
        )
        detail = make_execution_detail_response(
            execution=make_execution(execution_id="exec-11"),
            api_writes=[write],
            logs=[make_log_entry(message="handler ran")],
        )
        output = runner.stdout(_detail_client(cli_client_factory, "exec-11", detail), cmd_execution, uuid="exec-11")

        write_row = next(line for line in output.splitlines() if "light.turn_on" in line)
        assert "light.porch; area_id: garden" in write_row
        assert "rejected" in write_row
        assert "not_found" in write_row
        assert "brightness" not in output
        assert output.index("light.turn_on") < output.index("handler ran")

    def test_truncated_writes_print_a_notice(self, cli_client_factory: CLIClientFactory) -> None:
        detail = make_execution_detail_response(api_writes=[make_api_write()], api_writes_truncated=True)
        client = _detail_client(cli_client_factory, "exec-12", detail)

        assert API_WRITES_TRUNCATED_MESSAGE.format(shown=1) in runner.stderr(client, cmd_execution, uuid="exec-12")

    def test_caused_by_names_the_writing_app(self) -> None:
        trigger = ExecutionTrigger(
            context_id="ctx-1",
            caused_by=CausingWrite(
                app_key="porch", instance_name="main", execution_id="exec-0", kind="call_service", operation="light.on"
            ),
        )
        summary = execution_summary(make_execution(trigger=trigger))

        assert summary["trigger"]["caused_by"] == "porch/main call_service light.on (execution exec-0)"

    def test_bracketed_values_render_literally(self, cli_client_factory: CLIClientFactory) -> None:
        """A state like "[Live] Show" or "[/x]" is shown as-is, not parsed as Rich markup."""
        trigger = ExecutionTrigger(entity_id="media_player.tv", old_value="[Live] Show", new_value="[/x]")
        detail = make_execution_detail_response(execution=make_execution(execution_id="exec-9", trigger=trigger))

        output = runner.stdout(_detail_client(cli_client_factory, "exec-9", detail), cmd_execution, uuid="exec-9")
        assert "[Live] Show → [/x]" in output

    def test_bracketed_error_renders_literally(self, cli_client_factory: CLIClientFactory) -> None:
        """An exception message like "[/dev/ttyUSB0]" is shown as-is, without escape backslashes."""
        execution = make_execution(
            execution_id="exec-10",
            status=ExecutionStatus.ERROR,
            error_type="OSError",
            error_message="open [/dev/ttyUSB0] failed",
        )
        detail = make_execution_detail_response(execution=execution)

        output = runner.stdout(_detail_client(cli_client_factory, "exec-10", detail), cmd_execution, uuid="exec-10")
        assert "OSError: open [/dev/ttyUSB0] failed" in output

    def test_error_without_message_shows_type_only(self) -> None:
        summary = execution_summary(make_execution(status=ExecutionStatus.ERROR, error_type="TimeoutError"))
        assert summary["error"] == "TimeoutError"

    def test_empty_string_value_is_distinct_from_missing(self) -> None:
        trigger = ExecutionTrigger(old_value="", new_value="hello")
        summary = execution_summary(make_execution(trigger=trigger))
        assert summary["trigger"]["change"] == '"" → hello'

    def test_job_summary_has_no_trigger_section(self) -> None:
        summary = execution_summary(make_execution(kind="job", job_id=1))
        assert "trigger" not in summary
        assert summary["kind"] == "job"

    def test_empty_execution_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """Execution shows no-results message when records list is empty."""
        client = _detail_client(cli_client_factory, "exec-4", make_execution_detail_response(logs=[]))
        assert "No results" in runner.stderr(client, cmd_execution, uuid="exec-4")

    def test_execution_columns_defined(self) -> None:
        """EXECUTION_LOG_COLUMNS includes key log entry fields."""
        field_names = [c.field for c in EXECUTION_LOG_COLUMNS]
        assert "timestamp" in field_names
        assert "level" in field_names
        assert "message" in field_names

    def test_execution_columns_count_is_compact(self) -> None:
        """EXECUTION_LOG_COLUMNS uses at most 7 columns for 80-column fit."""
        assert len(EXECUTION_LOG_COLUMNS) <= 7


# Column allocation at narrow widths


@pytest.mark.parametrize("columns", [LOG_COLUMNS, EXECUTION_LOG_COLUMNS], ids=["log", "execution"])
def test_multiline_message_does_not_collapse_columns(columns: list[Column]) -> None:
    """A long multi-line message wraps in the Message column instead of starving the other columns."""
    entry = make_log_entry(
        level="ERROR",
        message=TRACEBACK_MESSAGE,
        app_key="demo_app",
        instance_name="primary",
        func_name="tick",
        lineno=314,
    )
    buf = StringIO()
    console = Console(file=buf, highlight=False, no_color=True, width=NARROW_CONSOLE_WIDTH)

    with patch.object(output_module, "stdout_console", console):
        render_table([entry], columns, json_mode=False)

    lines = buf.getvalue().splitlines()
    header_line, first_row_line = lines[1], lines[3]
    for col in columns:
        assert col.header in header_line
    identity_values = {
        "level": "ERROR",
        "app_key": "demo_app",
        "instance_name": "primary",
        "func_name": "tick",
        "lineno": "314",
    }
    for col in columns:
        if col.field in identity_values:
            assert identity_values[col.field] in first_row_line, f"{col.header} value clipped: {first_row_line!r}"


@pytest.mark.parametrize("columns", [LOG_COLUMNS, EXECUTION_LOG_COLUMNS], ids=["log", "execution"])
def test_exception_final_line_follows_message(columns: list[Column]) -> None:
    """A record's exception shows as its final line under the message; the full traceback stays out of the table."""
    entry = make_log_entry(
        level="ERROR",
        message="Handler failed",
        exc_info='Traceback (most recent call last):\n  File "apps/door.py", line 12, in on_door\nValueError: kaboom\n',
    )
    buf = StringIO()
    console = Console(file=buf, highlight=False, no_color=True, width=NARROW_CONSOLE_WIDTH * 2)

    with patch.object(output_module, "stdout_console", console):
        render_table([entry], columns, json_mode=False)

    output = buf.getvalue()
    assert "Handler failed" in output, output
    assert "ValueError: kaboom" in output, output
    assert "Traceback" not in output, output


@pytest.mark.parametrize(
    ("exc_info", "expected"),
    [
        pytest.param(None, "Handler failed", id="no-exception"),
        pytest.param("  \n", "Handler failed", id="whitespace-only"),
        pytest.param(
            'Traceback (most recent call last):\n  File "apps/door.py", line 12, in on_door\n'
            "    raise ValueError(msg)\nValueError: first line\nsecond line\n",
            "Handler failed\nValueError: first line",
            id="multi-line-exception-message",
        ),
        pytest.param("ValueError: no traceback\n", "Handler failed\nValueError: no traceback", id="no-frames"),
    ],
)
def test_fmt_log_message_picks_the_exception_line(exc_info: str | None, expected: str) -> None:
    """The message gains the exception's ``Type: message`` line, never a frame or a continuation line."""
    assert fmt_log_message(make_log_entry(message="Handler failed", exc_info=exc_info)) == expected


def test_fmt_log_message_picks_the_exception_group_header() -> None:
    """An exception group's traceback is indented throughout; the group's own header line is picked."""
    try:
        raise ExceptionGroup("handlers failed", [ValueError("x"), TypeError("y")])
    except ExceptionGroup as exc:
        exc_info = get_traceback_string(exc)

    entry = make_log_entry(message="Handler failed", exc_info=exc_info)

    assert fmt_log_message(entry) == "Handler failed\nExceptionGroup: handlers failed (2 sub-exceptions)"


def test_fmt_log_message_skips_indented_exception_message_lines() -> None:
    """An exception message's indented continuation lines (Pydantic's per-field errors) aren't mistaken for frames."""

    class Model(BaseModel):
        name: str

    try:
        Model.model_validate({})
    except ValidationError as exc:
        exc_info = get_traceback_string(exc)

    entry = make_log_entry(message="Handler failed", exc_info=exc_info)
    expected_line = "pydantic_core._pydantic_core.ValidationError: 1 validation error for Model"

    assert fmt_log_message(entry) == f"Handler failed\n{expected_line}"


def recurse_forever(depth: int) -> int:
    return recurse_forever(depth + 1)


def test_fmt_log_message_skips_the_repeated_frame_marker() -> None:
    """A recursive traceback's ``[Previous line repeated N more times]`` marker isn't taken for the exception line."""
    try:
        recurse_forever(0)
    except RecursionError as exc:
        exc_info = get_traceback_string(exc)

    entry = make_log_entry(message="Handler failed", exc_info=exc_info)

    assert fmt_log_message(entry) == "Handler failed\nRecursionError: maximum recursion depth exceeded"


def test_fmt_log_message_picks_the_last_exception_in_a_chain() -> None:
    """A chained traceback lists the earlier exception first; the logged (last) one's line is picked."""
    try:
        try:
            raise ValueError("original")
        except ValueError:
            raise ExceptionGroup("handlers failed", [TypeError("bad")])  # noqa: B904 - the implicit chain is the case under test
    except ExceptionGroup as exc:
        exc_info = get_traceback_string(exc)

    entry = make_log_entry(message="Handler failed", exc_info=exc_info)

    assert fmt_log_message(entry) == "Handler failed\nExceptionGroup: handlers failed (1 sub-exception)"
