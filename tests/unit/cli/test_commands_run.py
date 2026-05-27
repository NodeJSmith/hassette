"""Unit tests for the hassette run command."""

import errno
from unittest.mock import AsyncMock, patch

import pytest

from hassette.cli.commands.run import cmd_run
from hassette.exceptions import AppPrecheckFailedError, FatalError


@patch("hassette.cli.commands.run.run_server", new_callable=AsyncMock)
class TestCmdRun:
    def test_port_in_use_exits_with_code_1(self, mock_run_server: AsyncMock) -> None:
        exc = OSError(errno.EADDRINUSE, "Address already in use")
        mock_run_server.side_effect = exc
        with pytest.raises(SystemExit) as exc_info:
            cmd_run()
        assert exc_info.value.code == 1

    def test_other_oserror_reraises(self, mock_run_server: AsyncMock) -> None:
        exc = OSError(errno.EACCES, "Permission denied")
        mock_run_server.side_effect = exc
        with pytest.raises(OSError, match="Permission denied"):
            cmd_run()

    def test_precheck_failure_exits_with_code_1(self, mock_run_server: AsyncMock) -> None:
        mock_run_server.side_effect = AppPrecheckFailedError("bad app")
        with pytest.raises(SystemExit) as exc_info:
            cmd_run()
        assert exc_info.value.code == 1

    def test_fatal_error_exits_with_code_1(self, mock_run_server: AsyncMock) -> None:
        mock_run_server.side_effect = FatalError("token missing")
        with pytest.raises(SystemExit) as exc_info:
            cmd_run()
        assert exc_info.value.code == 1

    def test_keyboard_interrupt_does_not_raise(self, mock_run_server: AsyncMock) -> None:
        mock_run_server.side_effect = KeyboardInterrupt
        cmd_run()

    def test_passes_cli_flags_to_config(self, mock_run_server: AsyncMock) -> None:
        cmd_run(token="test-token", base_url="http://ha:8123", dev_mode=True)
        mock_run_server.assert_called_once()
        config = mock_run_server.call_args[0][0]
        assert config.token == "test-token"
        assert str(config.base_url) == "http://ha:8123"
        assert config.dev_mode is True
