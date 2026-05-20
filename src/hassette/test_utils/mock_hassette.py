"""Shared mock hassette factory for unit and integration tests.

Provides :func:`make_mock_hassette` (stable, end-user API) and
:func:`make_ws_hassette_stub` (internal WebSocket test preset).
"""

import asyncio
import atexit
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, seal

from hassette.test_utils.config import TEST_WS_URL, make_test_config


def make_mock_hassette(
    *,
    data_dir: Path | str | None = None,
    set_ready: bool = True,
    set_loop: bool = True,
    sealed: bool = True,
    **config_overrides: Any,
) -> AsyncMock:
    """Create a fully-wired :class:`unittest.mock.AsyncMock` that stands in for Hassette.

    The mock combines a real, Pydantic-validated :class:`~hassette.config.config.HassetteConfig`
    (via :func:`~hassette.test_utils.config.make_test_config`) with ``AsyncMock`` shells for all
    non-configuration attributes. This eliminates config drift across test files while keeping
    unit tests lightweight — no real Hassette ``__init__`` side effects.

    After wiring all standard attributes, :func:`unittest.mock.seal` is applied so that
    accessing any attribute not explicitly set here raises ``AttributeError``. Tests that need
    additional attributes beyond the defaults pass ``sealed=False``, set their extras, and
    optionally seal the mock themselves.

    Args:
        data_dir: Directory for Hassette data. Defaults to ``tempfile.mkdtemp()`` so unit
            tests don't need ``tmp_path``. Integration tests that need DB isolation should
            pass ``tmp_path`` or ``tmp_path_factory.mktemp()``.
        set_ready: If ``True`` (default), calls ``hassette.ready_event.set()`` so the mock
            appears ready immediately.
        set_loop: If ``True`` (default), sets ``hassette.loop`` to the running event loop via
            ``asyncio.get_running_loop()``. Pass ``False`` for session-scoped fixtures that
            run outside an event loop (e.g. ``_migrated_db_template``).
        sealed: If ``True`` (default), calls :func:`unittest.mock.seal` after wiring all
            attributes. Pass ``False`` if the test needs to set additional attributes.
        **config_overrides: Any :class:`~hassette.config.config.HassetteConfig` field to
            override. Merged on top of ``make_test_config()`` defaults. Nested group fields
            may be passed as dicts::

                make_mock_hassette(database={"retention_days": 14})
                make_mock_hassette(strict_lifecycle=True)

    Returns:
        A sealed (by default) :class:`~unittest.mock.AsyncMock` with:

        - ``.config``: real :class:`~hassette.config.config.HassetteConfig` instance
        - ``.ready_event``, ``.shutdown_event``: :class:`asyncio.Event` instances
        - ``.event_streams_closed``: ``False``
        - ``._loop_thread_id``: current thread ident
        - ``.loop``: running event loop (or ``None`` if ``set_loop=False``)
        - ``._scheduler_service.register_removal_callback``: :class:`~unittest.mock.Mock`
        - ``._scheduler_service.deregister_removal_callback``: :class:`~unittest.mock.Mock`
        - ``._bus_service.remove_listeners_by_owner``: :class:`~unittest.mock.Mock`
        - ``._bus_service.get_listeners_by_owner``: :class:`~unittest.mock.Mock` returning ``[]``
        - ``.app_handler.get``: :class:`~unittest.mock.Mock` returning ``None`` (no app running)
        - ``._runtime_query_service``: ``None`` (wired at runtime by the framework)
        - ``.session_id``: ``None``
        - ``.database_service``: ``None``
        - ``.wait_for_ready``: :class:`~unittest.mock.AsyncMock` returning ``True``
        - ``.children``: ``[]``

    Example::

        async def test_something():
            hassette = make_mock_hassette()
            assert hassette.config.token == "test-token"

        async def test_strict(tmp_path):
            hassette = make_mock_hassette(data_dir=tmp_path, strict_lifecycle=True)
            assert hassette.config.strict_lifecycle is True
    """
    if data_dir is None:
        data_dir = tempfile.mkdtemp()
        atexit.register(shutil.rmtree, data_dir, True)

    config = make_test_config(data_dir=data_dir, **config_overrides)

    hassette = AsyncMock()
    hassette.config = config

    # Readiness / shutdown signals
    ready_event = asyncio.Event()
    if set_ready:
        ready_event.set()
    hassette.ready_event = ready_event
    hassette.shutdown_event = asyncio.Event()

    # Event stream state
    hassette.event_streams_closed = False

    # Thread / loop identity
    hassette._loop_thread_id = threading.get_ident()
    if set_loop:
        try:
            hassette.loop = asyncio.get_running_loop()
        except RuntimeError:
            hassette.loop = None
    else:
        hassette.loop = None

    # Scheduler service stubs
    hassette._scheduler_service.register_removal_callback = Mock()
    hassette._scheduler_service.deregister_removal_callback = Mock()

    # Bus service stubs
    hassette._bus_service.remove_listeners_by_owner = Mock()
    hassette._bus_service.get_listeners_by_owner = Mock(return_value=[])

    # App handler stubs — get() is synchronous; return None (no app running by default)
    hassette.app_handler.get = Mock(return_value=None)

    # Runtime query service — None by default; set_runtime_query_service() wires it at runtime
    hassette._runtime_query_service = None

    # Database / session (wired by initialized_db after DB setup)
    hassette.session_id = None
    hassette.database_service = None

    # Async utilities
    hassette.wait_for_ready = AsyncMock(return_value=True)

    # Resource children
    hassette.children = []

    if sealed:
        seal(hassette)

    return hassette


def make_ws_hassette_stub(*, strict_lifecycle: bool = False, sealed: bool = True) -> AsyncMock:
    """Create a mock hassette pre-configured for WebSocket testing with fast timeouts.

    Thin wrapper around :func:`make_mock_hassette` that bakes in the config overrides
    needed by ``test_ws_connection_state.py`` and ``test_websocket_readiness_events.py``.
    Both test files share an identical config shape — this wrapper eliminates duplication.

    The ``websocket.*`` overrides use low retry/timeout values (sub-millisecond for backoff,
    low-single-digit seconds for connection timeouts) so tests complete quickly. The
    non-websocket overrides set DEBUG logging, a small cache, and fast lifecycle timeouts.

    Args:
        strict_lifecycle: Passed through to ``make_mock_hassette()`` as a config override.
            Set ``True`` for strict-lifecycle test scenarios.
        sealed: If ``True`` (default), calls :func:`unittest.mock.seal` after wiring all
            attributes. Pass ``False`` if the test needs to set additional attributes
            (e.g. ``send_event``) after construction.

    Returns:
        A :class:`~unittest.mock.AsyncMock` configured for WebSocket unit tests.
    """
    hassette = make_mock_hassette(
        sealed=False,
        logging={"log_level": "DEBUG", "websocket": "DEBUG", "task_bucket": "DEBUG"},
        default_cache_size=1024,
        lifecycle={"resource_shutdown_timeout_seconds": 1, "task_cancellation_timeout_seconds": 1},
        verify_ssl=False,
        websocket={
            "response_timeout_seconds": 1,
            "connection_timeout_seconds": 1,
            "total_timeout_seconds": 2,
            "heartbeat_interval_seconds": 5,
            "authentication_timeout_seconds": 5,
            "connect_retry_max_attempts": 3,
            "connect_retry_initial_wait_seconds": 0.001,
            "connect_retry_max_wait_seconds": 0.01,
            "early_drop_backoff_initial_seconds": 0.001,
            "early_drop_backoff_max_seconds": 0.01,
        },
        strict_lifecycle=strict_lifecycle,
    )
    hassette.ws_url = TEST_WS_URL
    if sealed:
        seal(hassette)
    return hassette
