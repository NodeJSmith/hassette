"""Tests for the server entry point — SIGTERM signal handling and startup validation."""

import asyncio
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.exceptions import FatalError
from hassette.resources.lifecycle import request_shutdown
from hassette.server import main


def make_mock_core_and_config(
    *,
    token: str = "valid-token",  # noqa: S107 — test placeholder, not a real credential
) -> tuple[MagicMock, MagicMock]:
    """Build a mock Hassette core (run_forever mocked) and a mock config with the given token."""
    mock_core = MagicMock()
    mock_core.run_forever = AsyncMock()

    mock_config = MagicMock()
    mock_config.token = token

    return mock_core, mock_config


@contextmanager
def patch_hassette_and_signal_handler(mock_core: MagicMock, *, side_effect: Any = None) -> Iterator[MagicMock]:
    """Patch hassette.server.Hassette (returning mock_core) and the running loop's
    add_signal_handler for main() tests. Yields the patched Hassette class mock.
    """
    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core) as mock_hassette_cls,
        patch.object(loop, "add_signal_handler", side_effect=side_effect),
    ):
        yield mock_hassette_cls


async def test_main_registers_sigterm_handler() -> None:
    """main() installs a SIGTERM handler that calls request_shutdown(core, ...)."""
    mock_core, mock_config = make_mock_core_and_config()

    registered_handlers: dict[int, tuple] = {}

    def fake_add_signal_handler(sig: int, callback, *args) -> None:
        registered_handlers[sig] = (callback, args)

    with patch_hassette_and_signal_handler(mock_core, side_effect=fake_add_signal_handler):
        await main(mock_config)

    assert signal.SIGTERM in registered_handlers, "SIGTERM handler was not registered"
    callback, args = registered_handlers[signal.SIGTERM]
    assert callback == request_shutdown
    assert args == (mock_core, "SIGTERM received")


async def test_sigterm_handler_triggers_shutdown_event() -> None:
    """Invoking the SIGTERM handler sets the shutdown event on the Hassette instance."""
    mock_core, mock_config = make_mock_core_and_config()
    mock_core.shutdown_event = asyncio.Event()
    mock_core.ready_event = asyncio.Event()

    registered_handlers: dict[int, tuple] = {}

    def fake_add_signal_handler(sig: int, callback, *args) -> None:
        registered_handlers[sig] = (callback, args)

    with patch_hassette_and_signal_handler(mock_core, side_effect=fake_add_signal_handler):
        await main(mock_config)

    assert signal.SIGTERM in registered_handlers, "SIGTERM handler was not registered"

    # Simulate what the OS would do by invoking the registered callback
    callback, args = registered_handlers[signal.SIGTERM]
    callback(*args)
    assert mock_core.shutdown_event.is_set()


async def test_main_continues_when_signal_handler_unsupported() -> None:
    """main() continues to run_forever when add_signal_handler raises NotImplementedError."""
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_handler(mock_core, side_effect=NotImplementedError):
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
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_handler(mock_core):
        await main(mock_config)

    mock_core.run_forever.assert_awaited_once()


async def test_main_passes_config_to_hassette() -> None:
    """main() passes the provided HassetteConfig to Hassette."""
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_handler(mock_core) as mock_hassette_cls:
        await main(mock_config)

    mock_hassette_cls.assert_called_once_with(config=mock_config)
