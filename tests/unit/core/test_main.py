"""Tests for the server entry point — SIGTERM/SIGINT signal handling and startup validation."""

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
def patch_hassette_and_signal_registration(
    mock_core: MagicMock,
    *,
    add_signal_handler_side_effect: Any = None,
    signal_signal_side_effect: Any = None,
) -> Iterator[MagicMock]:
    """Patch hassette.server.Hassette (returning mock_core), the running loop's
    add_signal_handler (used for SIGTERM), and signal.signal (used for SIGINT) for main()
    tests. Yields the patched Hassette class mock.
    """
    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core) as mock_hassette_cls,
        patch.object(loop, "add_signal_handler", side_effect=add_signal_handler_side_effect),
        patch("hassette.server.signal.signal", side_effect=signal_signal_side_effect) as mock_signal_signal,
    ):
        yield mock_hassette_cls, mock_signal_signal


async def test_main_registers_sigterm_handler() -> None:
    """main() installs a SIGTERM handler that calls request_shutdown(core, ...) directly."""
    mock_core, mock_config = make_mock_core_and_config()

    registered_handlers: dict[signal.Signals, tuple[Any, tuple[Any, ...]]] = {}

    def fake_add_signal_handler(registered_sig: signal.Signals, callback, *args) -> None:
        registered_handlers[registered_sig] = (callback, args)

    with patch_hassette_and_signal_registration(mock_core, add_signal_handler_side_effect=fake_add_signal_handler):
        await main(mock_config)

    assert signal.SIGTERM in registered_handlers, "SIGTERM handler was not registered"
    callback, args = registered_handlers[signal.SIGTERM]
    assert callback == request_shutdown
    assert args == (mock_core, "SIGTERM received")


async def test_main_registers_sigint_handler_via_raw_signal() -> None:
    """main() installs SIGINT via signal.signal(), not loop.add_signal_handler().

    A callback registered through the loop only runs once the loop next gets control, which
    never happens if a blocking shutdown hook is what's stalling teardown — see the module
    docstring on _handle_sigint. signal.signal() is delivered regardless of loop state.
    """
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_registration(mock_core) as (_, mock_signal_signal):
        await main(mock_config)

    mock_signal_signal.assert_called_once()
    registered_sig, handler = mock_signal_signal.call_args[0]
    assert registered_sig == signal.SIGINT
    assert handler.func.__name__ == "_handle_sigint"
    assert handler.args == (mock_core,)


async def test_sigterm_handler_triggers_shutdown_event() -> None:
    """Invoking the registered SIGTERM handler sets the shutdown event on the Hassette instance."""
    mock_core, mock_config = make_mock_core_and_config()
    mock_core.shutdown_event = asyncio.Event()
    mock_core.ready_event = asyncio.Event()

    registered_handlers: dict[signal.Signals, tuple[Any, tuple[Any, ...]]] = {}

    def fake_add_signal_handler(registered_sig: signal.Signals, callback, *args) -> None:
        registered_handlers[registered_sig] = (callback, args)

    with patch_hassette_and_signal_registration(mock_core, add_signal_handler_side_effect=fake_add_signal_handler):
        await main(mock_config)

    callback, args = registered_handlers[signal.SIGTERM]
    callback(*args)
    assert mock_core.shutdown_event.is_set()


async def test_second_sigint_forces_immediate_exit() -> None:
    """A second SIGINT, received after shutdown was already requested, force-exits instead of no-op'ing."""
    mock_core, mock_config = make_mock_core_and_config()
    mock_core.shutdown_event = asyncio.Event()
    mock_core.ready_event = asyncio.Event()

    with patch_hassette_and_signal_registration(mock_core) as (_, mock_signal_signal):
        await main(mock_config)

    mock_signal_signal.assert_called_once()
    handler = mock_signal_signal.call_args[0][1]

    # First SIGINT: requests shutdown, does not exit.
    with patch("hassette.server.os._exit") as mock_exit:
        handler(signal.SIGINT, None)
        mock_exit.assert_not_called()
    assert mock_core.shutdown_event.is_set()

    # Second SIGINT: shutdown already requested, so it force-exits instead of no-op'ing.
    with patch("hassette.server.os._exit") as mock_exit:
        handler(signal.SIGINT, None)
        mock_exit.assert_called_once_with(1)


async def test_main_continues_when_sigterm_handler_unsupported() -> None:
    """main() continues to run_forever when add_signal_handler raises NotImplementedError."""
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_registration(mock_core, add_signal_handler_side_effect=NotImplementedError):
        await main(mock_config)

    mock_core.run_forever.assert_awaited_once()


async def test_main_continues_when_sigint_handler_unsupported() -> None:
    """main() continues to run_forever when signal.signal() raises ValueError (not main thread)."""
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_registration(mock_core, signal_signal_side_effect=ValueError):
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

    with patch_hassette_and_signal_registration(mock_core):
        await main(mock_config)

    mock_core.run_forever.assert_awaited_once()


async def test_main_passes_config_to_hassette() -> None:
    """main() passes the provided HassetteConfig to Hassette."""
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_registration(mock_core) as (mock_hassette_cls, _):
        await main(mock_config)

    mock_hassette_cls.assert_called_once_with(config=mock_config)
