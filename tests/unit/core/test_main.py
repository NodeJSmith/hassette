"""Tests for the server entry point — SIGTERM/SIGINT signal handling and startup validation."""

import asyncio
import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hassette.exceptions import FatalError
from hassette.resources.lifecycle import request_shutdown
from hassette.server import _handle_sigint_signal, _sigint_wait_loop, main


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
    pthread_sigmask_side_effect: Any = None,
) -> Iterator[tuple[MagicMock, MagicMock, MagicMock]]:
    """Patch everything main() touches for signal registration.

    Patches ``hassette.server.Hassette`` (returning ``mock_core``), the running loop's
    ``add_signal_handler`` (SIGTERM), ``signal.pthread_sigmask`` (SIGINT blocking), and
    ``threading.Thread`` (the SIGINT-wait thread). The ``Thread`` mock's ``.start()`` is a
    no-op, so the real ``sigwait()``-based thread never actually runs during unit tests —
    without this, every test exercising ``main()`` would leave a thread blocked in a real
    ``signal.sigwait()`` call for the life of the test process.

    Yields ``(Hassette class mock, threading.Thread class mock, pthread_sigmask mock)``.
    """
    loop = asyncio.get_running_loop()

    with (
        patch("hassette.server.Hassette", return_value=mock_core) as mock_hassette_cls,
        patch.object(loop, "add_signal_handler", side_effect=add_signal_handler_side_effect),
        patch("hassette.server.signal.pthread_sigmask", side_effect=pthread_sigmask_side_effect) as mock_sigmask,
        patch("hassette.server.threading.Thread") as mock_thread_cls,
    ):
        yield mock_hassette_cls, mock_thread_cls, mock_sigmask


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


async def test_main_continues_when_sigterm_handler_unsupported() -> None:
    """main() continues to run_forever when add_signal_handler raises NotImplementedError."""
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_registration(mock_core, add_signal_handler_side_effect=NotImplementedError):
        await main(mock_config)

    mock_core.run_forever.assert_awaited_once()


async def test_main_blocks_sigint_before_spawning_the_wait_thread() -> None:
    """main() blocks SIGINT process-wide before starting the sigwait() thread.

    Ordering matters: every thread created after this point (the sigwait thread here, plus
    any the framework spawns later — the sync executor pool, the logging QueueListener) must
    inherit the blocked mask, so none of them are ever eligible targets for the kernel to
    deliver SIGINT to instead of the dedicated wait thread.
    """
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_registration(mock_core) as (_, mock_thread_cls, mock_sigmask):
        await main(mock_config)

    mock_sigmask.assert_called_once_with(signal.SIG_BLOCK, {signal.SIGINT})
    mock_thread_cls.assert_called_once()
    mock_thread_cls.return_value.start.assert_called_once()


async def test_main_starts_sigint_wait_thread_as_daemon() -> None:
    """main() starts a daemon thread running _sigint_wait_loop(core, loop, sigint_seen)."""
    mock_core, mock_config = make_mock_core_and_config()
    loop = asyncio.get_running_loop()

    with patch_hassette_and_signal_registration(mock_core) as (_, mock_thread_cls, _):
        await main(mock_config)

    _, kwargs = mock_thread_cls.call_args
    assert kwargs["target"] is _sigint_wait_loop
    thread_core, thread_loop, thread_sigint_seen = kwargs["args"]
    assert thread_core is mock_core
    assert thread_loop is loop
    assert isinstance(thread_sigint_seen, threading.Event)
    assert kwargs["daemon"] is True


async def test_main_continues_when_sigint_handling_unsupported() -> None:
    """main() continues to run_forever, without starting a thread, when pthread_sigmask is
    unavailable (e.g. Windows, where signal.pthread_sigmask doesn't exist at all).
    """
    mock_core, mock_config = make_mock_core_and_config()

    with patch_hassette_and_signal_registration(mock_core, pthread_sigmask_side_effect=AttributeError) as (
        _,
        mock_thread_cls,
        _,
    ):
        await main(mock_config)

    mock_thread_cls.assert_not_called()
    mock_core.run_forever.assert_awaited_once()


async def test_handle_sigint_signal_requests_shutdown_on_first_call() -> None:
    """The first SIGINT delivery hands request_shutdown off to the loop; it does not exit."""
    mock_core, _ = make_mock_core_and_config()
    mock_core.shutdown_event = asyncio.Event()
    mock_core.ready_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    sigint_seen = threading.Event()

    with patch("hassette.server.os._exit") as mock_exit:
        _handle_sigint_signal(mock_core, loop, sigint_seen)
        mock_exit.assert_not_called()

    assert sigint_seen.is_set()

    # call_soon_threadsafe only schedules request_shutdown — give the loop a turn to run it.
    await asyncio.sleep(0)
    assert mock_core.shutdown_event.is_set()


async def test_handle_sigint_signal_force_exits_once_a_sigint_was_already_seen() -> None:
    """Once sigint_seen is already set, _handle_sigint_signal force-exits instead of no-op'ing."""
    mock_core, _ = make_mock_core_and_config()
    loop = asyncio.get_running_loop()
    sigint_seen = threading.Event()
    sigint_seen.set()

    with patch("hassette.server.os._exit") as mock_exit:
        _handle_sigint_signal(mock_core, loop, sigint_seen)

    mock_exit.assert_called_once_with(1)


async def test_handle_sigint_signal_force_exits_even_if_shutdown_event_not_yet_set() -> None:
    """Regression test: the force-exit decision must not depend on core.shutdown_event.

    core.shutdown_event only becomes set once request_shutdown() actually runs on the loop
    thread via call_soon_threadsafe — which may not have happened yet if the loop is blocked by
    anything at all. A second SIGINT arriving in that window must still force-exit; deciding
    based on core.shutdown_event.is_set() instead of sigint_seen would make every SIGINT before
    the loop catches up look like "the first one" and never escalate.
    """
    mock_core, _ = make_mock_core_and_config()
    mock_core.shutdown_event = asyncio.Event()  # deliberately never set — loop still "blocked"
    loop = asyncio.get_running_loop()
    sigint_seen = threading.Event()

    with patch("hassette.server.os._exit") as mock_exit:
        _handle_sigint_signal(mock_core, loop, sigint_seen)
        mock_exit.assert_not_called()

        _handle_sigint_signal(mock_core, loop, sigint_seen)
        mock_exit.assert_called_once_with(1)


def test_sigint_wait_loop_calls_handler_once_per_wakeup() -> None:
    """_sigint_wait_loop calls _handle_sigint_signal exactly once per sigwait() wakeup."""

    class _StopLoopError(Exception):
        """Sentinel used to break out of _sigint_wait_loop's while True for this test only."""

    mock_core = MagicMock()
    mock_loop = MagicMock()
    sigint_seen = threading.Event()

    with (
        patch("hassette.server.signal.sigwait", side_effect=[signal.SIGINT, _StopLoopError]) as mock_sigwait,
        patch("hassette.server._handle_sigint_signal") as mock_handle,
        pytest.raises(_StopLoopError),
    ):
        _sigint_wait_loop(mock_core, mock_loop, sigint_seen)

    assert mock_sigwait.call_count == 2
    mock_sigwait.assert_called_with({signal.SIGINT})
    mock_handle.assert_called_once_with(mock_core, mock_loop, sigint_seen)


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

    with patch_hassette_and_signal_registration(mock_core) as (mock_hassette_cls, _, _):
        await main(mock_config)

    mock_hassette_cls.assert_called_once_with(config=mock_config)
