"""Unit tests for hassette job and job <id> commands."""

import json
from unittest.mock import patch

import pytest

from hassette.cli.commands.job import (
    JOB_EXECUTION_COLUMNS,
    JOB_LIST_COLUMNS,
    cmd_job,
)
from hassette.test_utils.web_helpers import make_job_execution, make_job_summary
from tests.unit.cli.conftest import CLIClientFactory, capture_stderr, capture_stdout

# ---------------------------------------------------------------------------
# cmd_job (bare — list all jobs)
# ---------------------------------------------------------------------------


class TestCmdJob:
    def test_calls_global_jobs_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """job (no --app) fetches from GET /api/scheduler/jobs."""
        job = make_job_summary()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/scheduler/jobs", 200, [job.model_dump()])])
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(json=False)

        assert "/api/scheduler/jobs" in called_paths

    def test_app_flag_routes_to_per_app_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """job --app my-app fetches from /api/telemetry/app/my-app/jobs."""
        job = make_job_summary(app_key="my-app")
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/jobs", 200, [job.model_dump()])]
        )
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(app="my-app", json=False)

        assert any("/api/telemetry/app/my-app/jobs" in p for p in called_paths)

    def test_app_and_instance_passes_instance_index(self, cli_client_factory: CLIClientFactory) -> None:
        """job --app my-app --instance 0 passes instance_index=0 as a query param."""
        job = make_job_summary(app_key="my-app", instance_index=0)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/app/my-app/jobs", 200, [job.model_dump()])]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(app="my-app", instance="0", json=False)

        jobs_call = next(r for r in received_params if "jobs" in r["path"])
        assert jobs_call["params"] is not None
        assert jobs_call["params"]["instance_index"] == 0

    def test_instance_without_app_exits_with_usage_error(self, cli_client_factory: CLIClientFactory) -> None:
        """job --instance 0 (without --app) exits non-zero with usage error."""
        client, _ = cli_client_factory.build_with_routes([])

        with (
            capture_stderr(),
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_job(instance="0", json=False)

        assert exc_info.value.code != 0

    def test_source_tier_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """job --source-tier app passes source_tier=app as a query param."""
        job = make_job_summary()
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/scheduler/jobs", 200, [job.model_dump()])])
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(source_tier="app", json=False)

        jobs_call = next(r for r in received_params if "jobs" in r["path"])
        assert jobs_call["params"] is not None
        assert jobs_call["params"]["source_tier"] == "app"

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """job renders a table with job_id and handler_method."""
        job = make_job_summary(job_id=99, handler_method="check_lights")
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/scheduler/jobs", 200, [job.model_dump()])])
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(json=False)

        output = buf.getvalue()
        assert "99" in output
        # Rich may truncate handler name in a narrow console — match the prefix
        assert "check_lig" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """job --json outputs the job list as a JSON array."""
        job = make_job_summary(job_id=3)
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/scheduler/jobs", 200, [job.model_dump()])])
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_job(json=True)

        parsed = json.loads("".join(captured))
        assert isinstance(parsed, list)
        assert parsed[0]["job_id"] == 3

    def test_empty_result_shows_no_results(self, cli_client_factory: CLIClientFactory) -> None:
        """job renders a no-results message when no jobs are returned."""
        client, _ = cli_client_factory.build_with_routes([("GET", "/api/scheduler/jobs", 200, [])])
        with (
            capture_stdout(),
            capture_stderr() as err_buf,
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(json=False)

        assert "No results" in err_buf.getvalue()

    def test_job_list_columns_defined(self) -> None:
        """JOB_LIST_COLUMNS includes key job fields."""
        field_names = [c.field for c in JOB_LIST_COLUMNS]
        assert "job_id" in field_names
        assert "handler_method" in field_names
        assert "trigger_type" in field_names
        assert "total_executions" in field_names

    def test_job_list_columns_count_is_compact(self) -> None:
        """JOB_LIST_COLUMNS uses at most 9 columns for 80-column fit."""
        assert len(JOB_LIST_COLUMNS) <= 9


class TestCmdJobDetail:
    def test_calls_executions_endpoint(self, cli_client_factory: CLIClientFactory) -> None:
        """job <id> fetches from GET /api/telemetry/job/{id}/executions."""
        execution = make_job_execution()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/job/5/executions", 200, [execution.model_dump()])]
        )
        called_paths: list[str] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            called_paths.append(path)
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(job_id=5, json=False)

        assert "/api/telemetry/job/5/executions" in called_paths

    def test_limit_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """job <id> --limit 5 passes limit=5 as a query param."""
        execution = make_job_execution()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/job/5/executions", 200, [execution.model_dump()])]
        )
        received_params: list[dict] = []
        original_get = client.get

        def tracking_get(path, model, params=None):
            received_params.append({"path": path, "params": params})
            return original_get(path, model, params=params)

        with (
            patch.object(client, "get", side_effect=tracking_get),
            capture_stdout(),
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(job_id=5, limit=5, json=False)

        executions_call = next(r for r in received_params if "executions" in r["path"])
        assert executions_call["params"] is not None
        assert executions_call["params"]["limit"] == 5

    def test_since_passed_as_param(self, cli_client_factory: CLIClientFactory) -> None:
        """job <id> --since passes since as a query param."""
        execution = make_job_execution()
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/job/5/executions", 200, [execution.model_dump()])]
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
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(job_id=5, since=since_epoch, json=False)

        executions_call = next(r for r in received_params if "executions" in r["path"])
        assert executions_call["params"] is not None
        assert executions_call["params"]["since"] == since_epoch

    def test_human_mode_renders_table(self, cli_client_factory: CLIClientFactory) -> None:
        """job <id> renders a table with status and duration."""
        execution = make_job_execution(duration_ms=8.5)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/job/1/executions", 200, [execution.model_dump()])]
        )
        with (
            capture_stdout() as buf,
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
        ):
            cmd_job(job_id=1, json=False)

        output = buf.getvalue()
        assert "success" in output.lower() or "Status" in output

    def test_json_mode_outputs_list(self, cli_client_factory: CLIClientFactory) -> None:
        """job <id> --json outputs the executions as a JSON array."""
        execution = make_job_execution(duration_ms=15.0)
        client, _ = cli_client_factory.build_with_routes(
            [("GET", "/api/telemetry/job/1/executions", 200, [execution.model_dump()])]
        )
        captured: list[str] = []

        with (
            patch("hassette.cli.commands.job.HassetteConfig"),
            patch("hassette.cli.commands.job.HassetteCLIClient", return_value=client),
            patch("sys.stdout.write", side_effect=lambda s: captured.append(s) or len(s)),
        ):
            cmd_job(job_id=1, json=True)

        parsed = json.loads("".join(captured))
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
