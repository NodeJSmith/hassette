"""Unit tests for hassette job and job <id> commands."""

import pytest

from hassette.cli.client import HassetteCLIClient
from hassette.cli.commands.job import (
    _SCHEDULE_STATUS_TEXT,
    JOB_EXECUTION_COLUMNS,
    JOB_LIST_COLUMNS,
    _next_run_display,
    cmd_job,
)
from tests.support.web_job_helpers import make_job_summary
from tests.support.web_telemetry_helpers import make_execution
from tests.unit.cli.conftest import SINCE_EPOCH, CLIClientFactory, CommandRunner

runner = CommandRunner("hassette.cli.commands.job.make_client")
JOBS_ENDPOINT = "/api/scheduler/jobs"
MY_APP_JOBS_ENDPOINT = "/api/telemetry/app/my-app/jobs"
JOB_5_EXECUTIONS_ENDPOINT = "/api/telemetry/job/5/executions"
JOB_1_EXECUTIONS_ENDPOINT = "/api/telemetry/job/1/executions"


class TestCmdJob:
    def test_calls_global_jobs_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Job (no --app) fetches from GET /api/scheduler/jobs."""
        job = make_job_summary()
        client = cli_client_factory.build_with_routes([("GET", JOBS_ENDPOINT, 200, [job.model_dump()])])
        spy = runner.spy(client, cmd_job)

        assert JOBS_ENDPOINT in spy.paths

    def test_app_flag_routes_to_per_app_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """Job --app my-app fetches from /api/telemetry/app/my-app/jobs."""
        job = make_job_summary(app_key="my-app")
        client = cli_client_factory.build_with_routes([("GET", MY_APP_JOBS_ENDPOINT, 200, [job.model_dump()])])
        spy = runner.spy(client, cmd_job, app="my-app")

        assert any(MY_APP_JOBS_ENDPOINT in p for p in spy.paths)

    def test_app_and_instance_passes_instance_index(self, cli_client_factory: CLIClientFactory) -> None:
        """Job --app my-app --instance 0 passes instance_index=0 as a query param."""
        job = make_job_summary(app_key="my-app", instance_index=0)
        client = cli_client_factory.build_with_routes([("GET", MY_APP_JOBS_ENDPOINT, 200, [job.model_dump()])])
        spy = runner.spy(client, cmd_job, app="my-app", instance="0")

        assert spy.params_for("jobs")["instance_index"] == 0

    def test_instance_without_app_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """Job --instance 0 (without --app) exits non-zero with usage error."""
        client = cli_client_factory.build_with_routes([])

        code, _stderr = runner.usage_error(client, cmd_job, instance="0")

        assert code != 0

    def test_source_tier_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """Job --source-tier app passes source_tier=app as a query param."""
        job = make_job_summary()
        client = cli_client_factory.build_with_routes([("GET", JOBS_ENDPOINT, 200, [job.model_dump()])])
        spy = runner.spy(client, cmd_job, source_tier="app")

        assert spy.params_for("jobs")["source_tier"] == "app"

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Job renders a table with job_id, app_key, and mode columns."""
        job = make_job_summary(job_id=99, handler_method="check_lights")
        client = cli_client_factory.build_with_routes([("GET", JOBS_ENDPOINT, 200, [job.model_dump()])])
        output = runner.stdout(client, cmd_job)

        assert "99" in output
        assert "test" in output
        assert "Mode" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Job --json outputs the job list as a JSON array."""
        job = make_job_summary(job_id=3)
        client = cli_client_factory.build_with_routes([("GET", JOBS_ENDPOINT, 200, [job.model_dump()])])

        parsed = runner.json_output(client, cmd_job)
        assert isinstance(parsed, list)
        assert parsed[0]["job_id"] == 3

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """Job renders a no-results message when no jobs are returned."""
        client = cli_client_factory.build_with_routes([("GET", JOBS_ENDPOINT, 200, [])])
        assert "No results" in runner.stderr(client, cmd_job)

    @pytest.mark.parametrize(
        ("schedule_status", "schedule_status_reason", "expected_text"),
        [
            ("scheduled", None, "Timing unavailable."),
            ("scheduled", "legacy_unknown", "Legacy status unknown."),
            ("waiting", None, "Waiting for entity time."),
            ("completed", None, "Schedule completed."),
            ("completed", "trigger_error", "Schedule stopped after trigger error."),
            ("manual", None, "Manual only."),
        ],
    )
    def test_null_next_run_renders_status_aware_text(
        self,
        schedule_status: str,
        schedule_status_reason: str | None,
        expected_text: str,
    ) -> None:
        """A null next_run renders truthful, status-aware text instead of generic 'done'.

        Exercises ``_next_run_display`` directly rather than through the rendered table —
        the table's fixed capture width can ellipsis-truncate the longer status strings,
        which is a display artifact of column width, not a correctness signal for the text
        the row_formatter produces.
        """
        job = make_job_summary(
            job_id=1, next_run=None, schedule_status=schedule_status, schedule_status_reason=schedule_status_reason
        )

        assert _next_run_display(job) == expected_text

    def test_concrete_next_run_renders_relative_time(self) -> None:
        """A concrete next_run still renders via fmt_relative_time, not status text."""
        job = make_job_summary(job_id=1, next_run=SINCE_EPOCH, schedule_status="scheduled")

        assert _next_run_display(job) != ""
        assert _next_run_display(job) not in _SCHEDULE_STATUS_TEXT.values()

    def test_job_list_columns_defined(self) -> None:
        """JOB_LIST_COLUMNS includes key job fields."""
        field_names = [c.field for c in JOB_LIST_COLUMNS]
        assert "job_id" in field_names
        assert "app_key" in field_names
        assert "job_name" in field_names
        assert "trigger_type" in field_names
        assert "total_executions" in field_names
        assert "mode" in field_names

    def test_job_list_columns_count_is_compact(self) -> None:
        """JOB_LIST_COLUMNS uses at most 11 columns for wide terminal fit."""
        assert len(JOB_LIST_COLUMNS) <= 11

    def test_job_list_columns_includes_schedule_status(self) -> None:
        """JOB_LIST_COLUMNS includes a schedule_status column."""
        field_names = [c.field for c in JOB_LIST_COLUMNS]
        assert "schedule_status" in field_names


class TestCmdJobDetail:
    @pytest.fixture
    def job_5_client(self, cli_client_factory: CLIClientFactory) -> HassetteCLIClient:
        """A client serving one execution from job 5's endpoint, the id the query-param tests use.

        The execution body's own ``job_id`` is incidental — these tests assert on the request
        the CLI made, never on the payload it got back.
        """
        execution = make_execution(kind="job", job_id=1)
        return cli_client_factory.build_with_routes([("GET", JOB_5_EXECUTIONS_ENDPOINT, 200, [execution.model_dump()])])

    def test_calls_executions_endpoint(self, job_5_client: HassetteCLIClient) -> None:
        """Job <id> fetches from GET /api/telemetry/job/{id}/executions."""
        spy = runner.spy(job_5_client, cmd_job, job_id=5)

        assert JOB_5_EXECUTIONS_ENDPOINT in spy.paths

    def test_limit_passed_as_param(self, job_5_client: HassetteCLIClient) -> None:
        """Job <id> --limit 5 passes limit=5 as a query param."""
        spy = runner.spy(job_5_client, cmd_job, job_id=5, limit=5)

        assert spy.params_for("executions")["limit"] == 5

    def test_since_passed_as_param(self, job_5_client: HassetteCLIClient) -> None:
        """Job <id> --since passes since as a query param."""
        since_epoch = SINCE_EPOCH
        spy = runner.spy(job_5_client, cmd_job, job_id=5, since=since_epoch)

        assert spy.params_for("executions")["since"] == since_epoch

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """Job <id> renders a table with status and duration."""
        execution = make_execution(kind="job", job_id=1, duration_ms=8.5)
        client = cli_client_factory.build_with_routes(
            [("GET", JOB_1_EXECUTIONS_ENDPOINT, 200, [execution.model_dump()])]
        )
        output = runner.stdout(client, cmd_job, job_id=1)

        assert "success" in output.lower() or "Status" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """Job <id> --json outputs the executions as a JSON array."""
        execution = make_execution(kind="job", job_id=1, duration_ms=15.0)
        client = cli_client_factory.build_with_routes(
            [("GET", JOB_1_EXECUTIONS_ENDPOINT, 200, [execution.model_dump()])]
        )

        parsed = runner.json_output(client, cmd_job, job_id=1)
        assert isinstance(parsed, list)
        assert parsed[0]["duration_ms"] == pytest.approx(15.0)

    def test_execution_columns_defined(self) -> None:
        """JOB_EXECUTION_COLUMNS includes key execution fields."""
        field_names = [c.field for c in JOB_EXECUTION_COLUMNS]
        assert "status" in field_names
        assert "duration_ms" in field_names
        assert "execution_start_ts" in field_names
        assert "error_type" in field_names

    def test_execution_columns_count_is_compact(self) -> None:
        """JOB_EXECUTION_COLUMNS uses at most 7 columns for 80-column fit."""
        assert len(JOB_EXECUTION_COLUMNS) <= 7
