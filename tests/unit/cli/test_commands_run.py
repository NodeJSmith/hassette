"""Unit tests for the hassette run command."""

import errno
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from hassette.cli import app
from hassette.cli.commands.run import EX_CONFIG, cmd_run
from hassette.cli.context import CLIContext
from hassette.exceptions import AppPrecheckFailedError, ConfigError, FatalError
from tests.unit.cli.conftest import capture_stderr


class TestBareHassetteShowsHelp:
    def test_no_args_prints_help_not_server(self) -> None:
        """Bare `hassette` with no arguments must show help, not start the server."""
        buf = StringIO()
        with patch("sys.stdout", buf), patch("hassette.cli.commands.run.run_server") as mock_server:
            with pytest.raises(SystemExit) as exc_info:
                app.meta([])
            assert exc_info.value.code == 0
        output = buf.getvalue()
        assert "Commands" in output
        assert "run" in output
        mock_server.assert_not_called()


@patch("hassette.cli.commands.run.run_server", new_callable=AsyncMock)
class TestCmdRun:
    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(OSError(errno.EADDRINUSE, "Address already in use"), id="port-in-use"),
            pytest.param(FatalError("token missing"), id="fatal-error"),
        ],
    )
    def test_startup_failure_exits_with_code_1(self, mock_run_server: AsyncMock, failure: Exception) -> None:
        mock_run_server.side_effect = failure
        with pytest.raises(SystemExit) as exc_info:
            cmd_run()
        assert exc_info.value.code == 1

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(AppPrecheckFailedError("bad app"), id="precheck-failure"),
            pytest.param(ConfigError("reserved app key"), id="manifest-validation"),
        ],
    )
    def test_config_failure_during_startup_exits_78(self, mock_run_server: AsyncMock, failure: Exception) -> None:
        mock_run_server.side_effect = failure
        with pytest.raises(SystemExit) as exc_info:
            cmd_run()
        assert exc_info.value.code == EX_CONFIG

    def test_other_oserror_reraises(self, mock_run_server: AsyncMock) -> None:
        exc = OSError(errno.EACCES, "Permission denied")
        mock_run_server.side_effect = exc
        with pytest.raises(OSError, match="Permission denied"):
            cmd_run()

    def test_keyboard_interrupt_does_not_raise(self, mock_run_server: AsyncMock) -> None:
        mock_run_server.side_effect = KeyboardInterrupt
        cmd_run()

    def test_passes_cli_flags_to_config(self, mock_run_server: AsyncMock) -> None:
        cmd_run(token="test-token", base_url="http://ha:8123", dev_mode=True)
        mock_run_server.assert_called_once()
        config = mock_run_server.call_args[0][0]
        assert config.token.get_secret_value() == "test-token"
        assert str(config.base_url) == "http://ha:8123"
        assert config.dev_mode is True

    @pytest.mark.parametrize(
        ("app_values", "expected"),
        [
            pytest.param(["kitchen"], ("kitchen",), id="single"),
            pytest.param(["kitchen", "porch"], ("kitchen", "porch"), id="repeated"),
            pytest.param(["kitchen,porch"], ("kitchen", "porch"), id="comma-separated"),
            pytest.param(["kitchen, porch"], ("kitchen", "porch"), id="comma-separated-with-space"),
            pytest.param(["kitchen", "kitchen,porch"], ("kitchen", "porch"), id="deduplicated"),
        ],
    )
    def test_app_flag_populates_only_apps(
        self, mock_run_server: AsyncMock, app_values: list[str], expected: tuple[str, ...]
    ) -> None:
        cmd_run(app=app_values)
        config = mock_run_server.call_args[0][0]
        assert config.only_apps == expected

    def test_no_app_flag_leaves_only_apps_empty(self, mock_run_server: AsyncMock) -> None:
        cmd_run()
        config = mock_run_server.call_args[0][0]
        assert config.only_apps == ()

    @pytest.mark.parametrize(
        "app_values",
        [
            pytest.param([""], id="empty-string"),
            pytest.param([","], id="bare-comma"),
            pytest.param([",,"], id="multiple-commas"),
            pytest.param([" "], id="whitespace"),
        ],
    )
    def test_empty_app_values_rejected(self, mock_run_server: AsyncMock, app_values: list[str]) -> None:
        with capture_stderr() as buf, pytest.raises(SystemExit) as exc_info:
            cmd_run(app=app_values)
        assert exc_info.value.code == 1
        assert "--app requires at least one non-empty app key" in buf.getvalue()
        mock_run_server.assert_not_called()


@pytest.fixture
def clean_hassette_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Drop the developer's HASSETTE* env vars and run from an empty directory; returns a config dir."""
    for key in list(os.environ):
        if key.upper().startswith("HASSETTE"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    return config_dir


@patch("hassette.cli.commands.run.run_server", new_callable=AsyncMock)
def test_unknown_key_exits_78_before_starting(
    mock_run_server: AsyncMock, clean_hassette_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HASSETTE__APP_DIR", "/apps")

    with pytest.raises(SystemExit) as exc_info:
        cmd_run(ctx=CLIContext(config_dir=clean_hassette_env))

    assert exc_info.value.code == EX_CONFIG
    mock_run_server.assert_not_called()


def test_server_logs_to_stdout(clean_hassette_env: Path) -> None:
    """`hassette run` keeps its whole log on stdout; only data commands route bootstrap logging to stderr."""
    env = {**os.environ, "HASSETTE__CONFIG_DIR": str(clean_hassette_env)}  # no token: fails at config check

    result = subprocess.run(
        [sys.executable, "-m", "hassette", "run"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == EX_CONFIG, result.stderr
    assert "HA token is required" in result.stdout
    assert "HA token is required" not in result.stderr


class TestRunCheck:
    @pytest.fixture(autouse=True)
    def token(self, clean_hassette_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HASSETTE__TOKEN", "test-token")

    def test_prints_only_the_resolved_locations(
        self, clean_hassette_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (clean_hassette_env / "hassette.toml").write_text('[apps]\ndirectory = "my apps"\n', encoding="utf-8")

        cmd_run(check=True, ctx=CLIContext(config_dir=clean_hassette_env))

        assert capsys.readouterr().out.splitlines() == [
            f"CONFIG_DIR={clean_hassette_env}",
            f"CONFIG_HOME={clean_hassette_env}",
            f"APPS_DIR='{clean_hassette_env / 'my apps'}'",
        ]

    @patch("hassette.config.config.autodetect_apps")
    def test_does_not_autodetect_apps_or_start(
        self, mock_autodetect: AsyncMock, clean_hassette_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Autodetect imports app modules, which `--check` must never do."""
        with patch("hassette.cli.commands.run.run_server", new_callable=AsyncMock) as mock_run_server:
            cmd_run(check=True, ctx=CLIContext(config_dir=clean_hassette_env))

        mock_autodetect.assert_not_called()
        mock_run_server.assert_not_called()
        assert len(capsys.readouterr().out.splitlines()) == 3

    def test_missing_token_exits_78(
        self, clean_hassette_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HASSETTE__TOKEN")

        with pytest.raises(SystemExit) as exc_info:
            cmd_run(check=True, ctx=CLIContext(config_dir=clean_hassette_env))

        captured = capsys.readouterr()
        assert exc_info.value.code == EX_CONFIG
        assert captured.out == ""
        assert "HA token is required" in captured.err

    @pytest.mark.parametrize(
        ("entry", "error"),
        [
            pytest.param('[apps.porch]\nfilename = "porch.py"\nclass_name = "Porch"\ncache_key = "../escape"\n',
                         "Invalid app 'porch'", id="unsafe-cache-key"),
            pytest.param('[apps."a/b"]\nfilename = "ab.py"\nclass_name = "AB"\n', "App key 'a/b'", id="unsafe-key"),
        ],
    )  # fmt: skip
    def test_invalid_explicit_app_entry_exits_78(
        self, clean_hassette_env: Path, capsys: pytest.CaptureFixture[str], entry: str, error: str
    ) -> None:
        (clean_hassette_env / "hassette.toml").write_text(entry, encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            cmd_run(check=True, ctx=CLIContext(config_dir=clean_hassette_env))

        captured = capsys.readouterr()
        assert exc_info.value.code == EX_CONFIG
        assert captured.out == ""
        assert error in captured.err

    def test_config_error_exits_78_with_the_error_on_stderr(
        self, clean_hassette_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (clean_hassette_env / "hassette.toml").write_text("bogus = 1\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            cmd_run(check=True, ctx=CLIContext(config_dir=clean_hassette_env))

        captured = capsys.readouterr()
        assert exc_info.value.code == EX_CONFIG
        assert captured.out == ""
        assert "bogus" in captured.err
        assert captured.err.count("Invalid configuration") == 1

    def test_malformed_toml_is_a_config_error_naming_the_file(
        self, clean_hassette_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        toml = clean_hassette_env / "hassette.toml"
        toml.write_text("[apps\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            cmd_run(check=True, ctx=CLIContext(config_dir=clean_hassette_env))

        captured = capsys.readouterr()
        assert exc_info.value.code == EX_CONFIG
        assert captured.out == ""
        assert str(toml) in captured.err

    def test_warnings_stay_off_stdout(self, clean_hassette_env: Path) -> None:
        """A warning logged during the check goes to stderr; the entrypoint's logging is what's under test."""
        env = {
            **os.environ,
            "HASSETTE__LOGGING__LOG_LEVEL": "bogus",
            "HASSETTE__CONFIG_DIR": str(clean_hassette_env),
            "HASSETTE__TOKEN": "test-token",
        }

        result = subprocess.run(
            [sys.executable, "-m", "hassette", "run", "--check"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert [line.split("=")[0] for line in result.stdout.splitlines()] == ["CONFIG_DIR", "CONFIG_HOME", "APPS_DIR"]
        assert "not valid" in result.stderr
