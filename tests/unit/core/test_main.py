"""Tests for the server entry point — SIGTERM signal handling and startup validation."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.exceptions import FatalError
from hassette.resources.lifecycle import request_shutdown
from hassette.server import main


async def test_main_registers_sigterm_handler() -> None:
    """main() installs a SIGTERM handler that calls request_shutdown(core, ...)."""
    mock_core = MagicMock()
    mock_core.run_forever = AsyncMock()
    mock_config = MagicMock()
    mock_config.token = "valid-token"

    registered_handlers: dict[int, tuple] = {}

    def fake_add_signal_handler(sig: int, callback, *args) -> None:
        registered_handlers[sig] = (callback, args)

    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core),
        patch.object(loop, "add_signal_handler", side_effect=fake_add_signal_handler),
    ):
        await main(mock_config)

    assert signal.SIGTERM in registered_handlers, "SIGTERM handler was not registered"
    callback, args = registered_handlers[signal.SIGTERM]
    assert callback == request_shutdown
    assert args == (mock_core, "SIGTERM received")


async def test_sigterm_handler_triggers_shutdown_event() -> None:
    """Invoking the SIGTERM handler sets the shutdown event on the Hassette instance."""
    mock_core = MagicMock()
    mock_core.shutdown_event = asyncio.Event()
    mock_core.ready_event = asyncio.Event()
    mock_core.run_forever = AsyncMock()

    mock_config = MagicMock()
    mock_config.token = "valid-token"

    registered_handlers: dict[int, tuple] = {}

    def fake_add_signal_handler(sig: int, callback, *args) -> None:
        registered_handlers[sig] = (callback, args)

    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core),
        patch.object(loop, "add_signal_handler", side_effect=fake_add_signal_handler),
    ):
        await main(mock_config)

    assert signal.SIGTERM in registered_handlers, "SIGTERM handler was not registered"

    # Simulate what the OS would do by invoking the registered callback
    callback, args = registered_handlers[signal.SIGTERM]
    callback(*args)
    assert mock_core.shutdown_event.is_set()


async def test_main_continues_when_signal_handler_unsupported() -> None:
    """main() continues to run_forever when add_signal_handler raises NotImplementedError."""
    mock_core = MagicMock()
    mock_core.run_forever = AsyncMock()

    mock_config = MagicMock()
    mock_config.token = "valid-token"

    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core),
        patch.object(loop, "add_signal_handler", side_effect=NotImplementedError),
    ):
        await main(mock_config)

    mock_core.run_forever.assert_awaited_once()


async def test_main_raises_fatal_error_when_token_is_none() -> None:
    """main() raises FatalError before creating Hassette when token is None."""
    mock_config = MagicMock()
    mock_config.token = None

    with patch("hassette.server.Hassette") as mock_hassette, pytest.raises(FatalError, match="HA token is required"):
        await main(mock_config)

    mock_hassette.assert_not_called()


async def test_main_proceeds_when_token_is_set() -> None:
    """main() proceeds to create Hassette when token is not None."""
    mock_core = MagicMock()
    mock_core.run_forever = AsyncMock()

    mock_config = MagicMock()
    mock_config.token = "valid-token"

    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core),
        patch.object(loop, "add_signal_handler"),
    ):
        await main(mock_config)

    mock_core.run_forever.assert_awaited_once()


async def test_main_passes_config_to_hassette() -> None:
    """main() passes the provided HassetteConfig to Hassette."""
    mock_core = MagicMock()
    mock_core.run_forever = AsyncMock()

    mock_config = MagicMock()
    mock_config.token = "valid-token"

    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core) as mock_hassette_cls,
        patch.object(loop, "add_signal_handler"),
    ):
        await main(mock_config)

    mock_hassette_cls.assert_called_once_with(config=mock_config)
