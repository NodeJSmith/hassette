"""Boot a real, manually wired ``Hassette`` with no Home Assistant, and tear it down afterwards."""

import asyncio
import contextlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from hassette import Hassette
from hassette import context as hassette_context
from tests.support.helpers import cleanup_hassette_streams

WEBAPI_READY_TIMEOUT = 10.0


async def teardown_bare_hassette(
    hassette: Hassette,
    run_task: asyncio.Task,
    loop: asyncio.AbstractEventLoop,
    *,
    previous_task_factory: object,
    instance_token: object,
) -> None:
    """Shut down a manually-wired Hassette instance and restore loop/context state.

    Shared by this module's two call sites that construct a bare Hassette (bypassing the
    harness) and drive it via ``run_forever()``. Order matters: restore the task factory
    before anything below (including ``cleanup_hassette_streams``'s internal task creation)
    that might create a new Task on this session-scoped loop — ``run_forever()`` installs a
    TaskBucket-routing factory that seals once shutdown completes. Callers must set their own
    unblocking events (e.g. a hung ``serve()``'s wait event) before calling this.

    The restore/cleanup below runs in a ``finally`` block: ``suppress(Exception)`` around the
    wait for ``run_task`` does not catch ``asyncio.CancelledError`` (a ``BaseException``), so a
    cancellation delivered to *this* coroutine while awaiting ``run_task`` would otherwise skip
    the task-factory restore and instance-token reset entirely. Since the loop is session-scoped,
    a poisoned task factory or a stale global Hassette reference would then affect every later
    test on the same worker, not just this one. The instance-token reset gets its own nested
    ``finally`` around ``cleanup_hassette_streams`` for the same reason: a cancellation delivered
    specifically during that await would otherwise propagate past its own ``suppress(Exception)``
    (again, ``CancelledError`` is a ``BaseException``) and skip the reset below it.
    """
    hassette.shutdown_event.set()
    try:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(run_task, timeout=WEBAPI_READY_TIMEOUT)
    finally:
        loop.set_task_factory(previous_task_factory)  # pyright: ignore[reportArgumentType]
        try:
            with contextlib.suppress(Exception):
                await cleanup_hassette_streams(hassette)
        finally:
            if instance_token is not None:
                hassette_context.HASSETTE_INSTANCE.reset(instance_token)  # pyright: ignore[reportArgumentType]


def wire_hassette_without_ha(
    tmp_path: Path, port: int, *, config_overrides: Mapping[str, Any] | None = None, **web_api_overrides: Any
) -> tuple[Hassette, asyncio.Event, object]:
    """Build and wire a real Hassette instance whose WebsocketService never connects.

    ``StateProxy.load_cache()`` is short-circuited (``hassette.api.get_states_raw`` raises
    immediately) instead of letting the real retry/backoff run against an unreachable HA —
    that boundary-level patch is the same pattern ``tests/integration/test_state_proxy.py``
    uses, and it keeps these tests fast and deterministic. ``WebsocketService.serve()`` is
    replaced with a coroutine that awaits the returned ``asyncio.Event``, so the connection
    state stays DISCONNECTED and ``has_ever_connected`` stays False until the caller sets it.

    ``web_api_overrides`` replace keys of the default ``web_api`` config below, and ``config_overrides``
    are passed through as further top-level config fields.

    Returns the instance, that event, and the ``HASSETTE_INSTANCE`` token to reset on teardown.
    """
    # house-lint: ignore-next[HSL002] - a module-level import makes pytest try to collect TestConfig as a test class
    from tests.conftest import TEST_APPS_PATH, TestConfig

    config = TestConfig(
        data_dir=tmp_path / "data",
        # auth_enabled=False + a loopback host: this test hits /api/health with no credential via
        # `_get_health()`, and auth is on by default now that the default-deny middleware actually
        # enforces it. Pinning host to loopback alongside disabling auth matches the project's
        # startup guard (a non-loopback host with auth disabled refuses to start).
        web_api={"run": True, "port": port, "auth_enabled": False, "host": "127.0.0.1", **web_api_overrides},
        apps={
            "directory": TEST_APPS_PATH,
            "apps": {
                # my_app skips its on_initialize() body under pytest (checks PYTEST_VERSION),
                # so it bootstraps instantly without touching HA — unlike my_app_sync, which
                # would hit the real REST retry/backoff path and slow this test down.
                "my_app": {
                    "filename": "my_app.py",
                    "class_name": "MyApp",
                    "config": {"test_entity": "input_button.test", "instance_name": "unique_instance_name"},
                },
            },
        },
        **(config_overrides or {}),
    )

    hassette = Hassette(config)
    # wire_services() calls context.set_global_hassette(hassette) internally and does not
    # expose the returned Token, so set it ourselves first to capture the Token — wire_services()'s
    # own call then early-returns None (same instance already set) and is a no-op. Callers run
    # setup and teardown in the same coroutine/Context (unlike a pytest-asyncio generator
    # fixture), so resetting a manually-captured Token in their teardown is valid — see
    # tests/integration/conftest.py's hassette_instance docstring for why that would NOT be true
    # across a fixture setup/teardown boundary.
    instance_token = hassette_context.set_global_hassette(hassette)
    hassette.wire_services()

    never_connects = asyncio.Event()

    async def hang_serve() -> None:
        await never_connects.wait()

    hassette.websocket_service.serve = hang_serve  # pyright: ignore[reportAttributeAccessIssue]
    hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("HA unreachable in test"))
    return hassette, never_connects, instance_token
