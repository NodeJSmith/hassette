"""Shared helpers for starting a real uvicorn server in a background thread.

`TestClient`/`AsyncClient` transports run the ASGI app in-process and never exercise
uvicorn's actual WebSocket protocol implementation. Tests that need to verify behavior
against the real backend (e.g. pre-accept auth checks, browser-driven e2e flows) start
a genuine uvicorn server on a free port instead.
"""

import socket
import threading
import time
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI

LIVE_SERVER_START_TIMEOUT_SECONDS = 10
LIVE_SERVER_STOP_TIMEOUT_SECONDS = 5


def get_free_port() -> int:
    """Bind to port 0 and return the OS-assigned free port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_uvicorn_server(
    app: FastAPI,
    *,
    ws: str = "none",
    timeout_graceful_shutdown: int | None = None,
    on_startup: Callable[[], None] | None = None,
) -> tuple[uvicorn.Server, threading.Thread, int]:
    """Start `app` under uvicorn in a daemon thread; block until it accepts connections.

    `ws` selects uvicorn's WebSocket backend: `"none"` disables it (avoids the
    `websockets.legacy` DeprecationWarning, which pytest's `filterwarnings=["error"]`
    promotes to a hard error, for tests that don't need WS); `"websockets-sansio"`
    enables it for tests that do.

    `timeout_graceful_shutdown` bounds how long uvicorn waits for in-flight connections
    (e.g. a browser-held WebSocket) to close during shutdown before it cancels them.

    `on_startup`, if given, is called synchronously from inside uvicorn's own
    `server.startup()` coroutine, once the server is up but before this function
    returns. It runs on the server's event loop in the server's thread, so a caller
    that needs a live reference to that loop (e.g. to schedule work on it later via
    `asyncio.run_coroutine_threadsafe`) can call `asyncio.get_running_loop()` from
    within the hook.

    Returns `(server, thread, port)`. Caller tears down via `stop_uvicorn_server`.
    """
    port = get_free_port()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws=ws,
        timeout_graceful_shutdown=timeout_graceful_shutdown,
    )
    server = uvicorn.Server(config)

    if on_startup is not None:
        original_startup = server.startup

        async def _startup_and_hook(sockets: list[socket.socket] | None = None) -> None:
            await original_startup(sockets=sockets)
            on_startup()

        server.startup = _startup_and_hook

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll until the server is accepting connections.
    # socket.create_connection blocks up to 0.5s on success; the short sleep
    # prevents a tight spin on connection-refused (which returns instantly).
    deadline = time.monotonic() + LIVE_SERVER_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError(f"Live server thread exited before accepting connections on port {port}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.05)
    else:
        stop_uvicorn_server(server, thread)
        raise RuntimeError(f"Live server did not start within {LIVE_SERVER_START_TIMEOUT_SECONDS}s on port {port}")

    return server, thread, port


def stop_uvicorn_server(server: uvicorn.Server, thread: threading.Thread) -> None:
    """Signal `server` to exit and wait for its thread to finish."""
    server.should_exit = True
    thread.join(timeout=LIVE_SERVER_STOP_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise RuntimeError(f"Live server did not stop within {LIVE_SERVER_STOP_TIMEOUT_SECONDS}s")
