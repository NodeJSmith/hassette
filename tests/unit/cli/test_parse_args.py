"""Tests that dispatch through cyclopts' real ``parse_args`` — not direct function calls.

These tests exist because a bug (``--since 7d`` failing) went undetected: every existing
test called command functions directly with pre-converted values, so nothing exercised
cyclopts' flag parsing, type conversion, and subcommand routing end to end. ``app.parse_args``
performs the full pipeline and returns the resolved command function plus bound arguments
without executing the command.
"""

from unittest.mock import patch

import pytest
from whenever import Instant

from hassette.cli import app
from hassette.const.misc import SECONDS_PER_DAY, SECONDS_PER_HOUR, SECONDS_PER_MINUTE
from tests.unit.cli.conftest import NOW_EPOCH, fixed_now


class TestSubcommandRouting:
    @pytest.mark.parametrize(
        ("argv", "expected_name"),
        [
            pytest.param(["app"], "cmd_app", id="app"),
            pytest.param(["app", "health", "test-app"], "cmd_app_health", id="app-health"),
            pytest.param(["app", "activity", "test-app"], "cmd_app_activity", id="app-activity"),
            pytest.param(["app", "config", "test-app"], "cmd_app_config", id="app-config"),
            pytest.param(["app", "source", "test-app"], "cmd_app_source", id="app-source"),
            pytest.param(["config"], "cmd_config", id="config"),
            pytest.param(["dashboard"], "cmd_dashboard", id="dashboard"),
            pytest.param(["execution", "some-uuid"], "cmd_execution", id="execution"),
            pytest.param(["job"], "cmd_job", id="job"),
            pytest.param(["listener"], "cmd_listener", id="listener"),
            pytest.param(["log"], "cmd_log", id="log"),
            pytest.param(["run"], "cmd_run", id="run"),
            pytest.param(["status"], "cmd_status", id="status"),
            pytest.param(["telemetry"], "cmd_telemetry", id="telemetry"),
        ],
    )
    def test_routes_to_expected_function(self, argv: list[str], expected_name: str) -> None:
        cmd, _bound, _ = app.parse_args(argv)
        assert cmd.__name__ == expected_name


class TestSinceConverterWiring:
    @pytest.mark.parametrize(
        ("argv", "expected_seconds_ago"),
        [
            pytest.param(["log", "--since", "7d"], 7 * SECONDS_PER_DAY, id="log-7d"),
            pytest.param(["listener", "--since", "1h"], SECONDS_PER_HOUR, id="listener-1h"),
            pytest.param(["job", "--since", "30m"], 30 * SECONDS_PER_MINUTE, id="job-30m"),
            pytest.param(["app", "health", "test-app", "--since", "2w"], 14 * SECONDS_PER_DAY, id="app-health-2w"),
            pytest.param(["app", "activity", "test-app", "--since", "7d"], 7 * SECONDS_PER_DAY, id="app-activity-7d"),
        ],
    )
    def test_relative_since_through_dispatch(self, argv: list[str], expected_seconds_ago: int) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            _cmd, bound, _ = app.parse_args(argv)

        since = bound.arguments["since"]
        assert isinstance(since, float)
        assert since == pytest.approx(NOW_EPOCH - expected_seconds_ago, abs=1)

    def test_absolute_since_through_dispatch(self) -> None:
        _cmd, bound, _ = app.parse_args(["log", "--since", "2026-05-22T18:00:00Z"])

        since = bound.arguments["since"]
        assert since == pytest.approx(Instant.parse_iso("2026-05-22T18:00:00Z").timestamp(), abs=1)

    def test_omitted_since_is_none(self) -> None:
        _cmd, bound, _ = app.parse_args(["log"])

        assert bound.arguments.get("since") is None


class TestFlagCombinations:
    def test_listener_app_since_limit(self) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            _cmd, bound, _ = app.parse_args(["listener", "--app", "my-app", "--since", "1h", "--limit", "50"])

        assert bound.arguments["app"] == "my-app"
        assert bound.arguments["since"] == pytest.approx(NOW_EPOCH - SECONDS_PER_HOUR, abs=1)
        assert bound.arguments["limit"] == 50

    def test_job_app_source_tier(self) -> None:
        _cmd, bound, _ = app.parse_args(["job", "--app", "my-app", "--source-tier", "framework"])

        assert bound.arguments["app"] == "my-app"
        assert bound.arguments["source_tier"] == "framework"

    def test_app_health_instance_since(self) -> None:
        with patch("hassette.cli.types.now_epoch", fixed_now):
            _cmd, bound, _ = app.parse_args(["app", "health", "test-app", "--instance", "office", "--since", "7d"])

        assert bound.arguments["instance"] == "office"
        assert bound.arguments["since"] == pytest.approx(NOW_EPOCH - 7 * SECONDS_PER_DAY, abs=1)

    def test_execution_uuid_limit(self) -> None:
        _cmd, bound, _ = app.parse_args(["execution", "abc-123-def", "--limit", "100"])

        assert bound.arguments["uuid"] == "abc-123-def"
        assert bound.arguments["limit"] == 100


class TestInvalidInputRejection:
    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(["log", "--since", "banana"], id="invalid-since"),
            pytest.param(["log", "--source-tier", "bogus"], id="invalid-source-tier"),
            pytest.param(["execution"], id="missing-required-arg"),
        ],
    )
    def test_raises_system_exit(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit):
            app.parse_args(argv)


class TestGlobalFlagWiring:
    def test_json_flag(self) -> None:
        cmd, bound, _ = app.meta.parse_args(["--json", "log"])

        assert cmd.__name__ == "launcher"
        assert bound.arguments["json"] is True
        assert "log" in bound.arguments["tokens"]

    def test_debug_flag(self) -> None:
        _cmd, bound, _ = app.meta.parse_args(["--debug", "status"])

        assert bound.arguments["debug"] is True

    def test_config_file_flag(self) -> None:
        _cmd, bound, _ = app.meta.parse_args(["--config-file", "/some/path.toml", "status"])

        assert bound.arguments["config_file"] == "/some/path.toml"

    def test_no_global_flags(self) -> None:
        _cmd, bound, _ = app.meta.parse_args(["log"])

        assert not bound.arguments.get("json", False)
        assert not bound.arguments.get("debug", False)
