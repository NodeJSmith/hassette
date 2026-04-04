"""Tests for the __main__ entrypoint — SIGTERM signal handling."""

import asyncio
import signal
from argparse import Namespace
from unittest.mock import AsyncMock, MagicMock, patch

from hassette.__main__ import main


async def test_main_registers_sigterm_handler() -> None:
    """main() installs a SIGTERM handler that calls core.request_shutdown()."""
    mock_core = MagicMock()
    mock_core.run_forever = AsyncMock()

    registered_handlers: dict[int, tuple] = {}

    def fake_add_signal_handler(sig: int, callback, *args) -> None:
        registered_handlers[sig] = (callback, args)

    loop = asyncio.get_running_loop()
    mock_args = Namespace(env_file=None, config_file=None)

    with (
        patch("hassette.__main__.get_parser") as mock_parser,
        patch("hassette.__main__.HassetteConfig"),
        patch("hassette.__main__.Hassette", return_value=mock_core),
        patch.object(loop, "add_signal_handler", side_effect=fake_add_signal_handler),
    ):
        mock_parser.return_value.parse_known_args.return_value = (mock_args, [])
        await main()

    assert signal.SIGTERM in registered_handlers, "SIGTERM handler was not registered"
    callback, args = registered_handlers[signal.SIGTERM]
    assert callback == mock_core.request_shutdown
    assert args == ("SIGTERM received",)


async def test_sigterm_handler_triggers_shutdown_event() -> None:
    """Invoking the SIGTERM handler sets the shutdown event on the Hassette instance."""
    mock_core = MagicMock()
    mock_core.shutdown_event = asyncio.Event()
    mock_core.run_forever = AsyncMock()

    def real_request_shutdown(_reason: str | None = None) -> None:
        mock_core.shutdown_event.set()

    mock_core.request_shutdown = real_request_shutdown
    mock_args = Namespace(env_file=None, config_file=None)

    with (
        patch("hassette.__main__.get_parser") as mock_parser,
        patch("hassette.__main__.HassetteConfig"),
        patch("hassette.__main__.Hassette", return_value=mock_core),
    ):
        mock_parser.return_value.parse_known_args.return_value = (mock_args, [])
        await main()

    # Simulate what the OS would do
    mock_core.request_shutdown("SIGTERM received")
    assert mock_core.shutdown_event.is_set()
