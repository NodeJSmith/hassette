"""A second action on an app whose lifecycle lock is held answers 409 ``action_in_progress`` at once.

Queuing behind the lock would let a client that gave up on its request (timeout, "outcome unknown")
have the action run anyway once the lock frees.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx2 import AsyncClient

from tests.integration.conftest import make_manifest_mock

from .conftest import APPS_PATH

WAIT_TIMEOUT_SECONDS = 5

ACTIONS = [
    ("start", "start_app"),
    ("stop", "stop_app"),
    ("reload", "reload_app"),
    ("instances/0/start", "start_instance"),
    ("instances/0/stop", "stop_instance"),
    ("instances/0/reload", "reload_instance"),
]
"""Each action route suffix and the ``AppHandler`` method it calls."""


class InFlightReload:
    """Holds ``my_app``'s lock inside a reload until :meth:`finish` is called."""

    def __init__(self, mock_hassette: MagicMock) -> None:
        self.lock = asyncio.Lock()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        handler = mock_hassette.app_handler
        handler.registry.get_manifest.return_value = make_manifest_mock()
        handler.is_action_in_progress = MagicMock(
            side_effect=lambda app_key: app_key == "my_app" and self.lock.locked()
        )
        handler.reload_app = AsyncMock(side_effect=self.slow_reload)

    async def slow_reload(self, _app_key: str, **_kwargs: object) -> None:
        async with self.lock:
            self.started.set()
            await self.release.wait()

    async def begin(self, client: AsyncClient) -> "asyncio.Task":
        task = asyncio.create_task(client.post(f"{APPS_PATH}/my_app/reload"))
        await asyncio.wait_for(self.started.wait(), WAIT_TIMEOUT_SECONDS)
        return task

    async def finish(self, task: "asyncio.Task") -> None:
        self.release.set()
        response = await asyncio.wait_for(task, WAIT_TIMEOUT_SECONDS)
        assert response.status_code == 202, response.text


@pytest.mark.parametrize(("suffix", "handler_method"), ACTIONS, ids=[suffix for suffix, _ in ACTIONS])
async def test_action_while_lock_held_is_rejected_without_running(
    client: AsyncClient, mock_hassette: MagicMock, suffix: str, handler_method: str
) -> None:
    in_flight = InFlightReload(mock_hassette)
    first = await in_flight.begin(client)
    second_action = getattr(mock_hassette.app_handler, handler_method)
    calls_before = second_action.await_count

    response = await asyncio.wait_for(client.post(f"{APPS_PATH}/my_app/{suffix}"), WAIT_TIMEOUT_SECONDS)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "action_in_progress"
    assert response.json()["detail"] == "Another action on app 'my_app' is still running"
    await in_flight.finish(first)
    assert second_action.await_count == calls_before


async def test_action_on_another_app_runs_while_lock_held(client: AsyncClient, mock_hassette: MagicMock) -> None:
    in_flight = InFlightReload(mock_hassette)
    first = await in_flight.begin(client)

    response = await asyncio.wait_for(client.post(f"{APPS_PATH}/other_app/start"), WAIT_TIMEOUT_SECONDS)

    assert response.status_code == 202, response.text
    mock_hassette.app_handler.start_app.assert_awaited_once_with("other_app")
    await in_flight.finish(first)


async def test_action_after_lock_released_is_accepted(client: AsyncClient, mock_hassette: MagicMock) -> None:
    in_flight = InFlightReload(mock_hassette)
    await in_flight.finish(await in_flight.begin(client))

    response = await client.post(f"{APPS_PATH}/my_app/start")

    assert response.status_code == 202, response.text
    mock_hassette.app_handler.start_app.assert_awaited_once_with("my_app")


@pytest.mark.parametrize("suffix", ["stop", "instances/0/stop"])
async def test_busy_app_with_vanished_registry_entries_is_rejected_not_404(
    client: AsyncClient, mock_hassette: MagicMock, suffix: str
) -> None:
    """Stopping an orphaned app unregisters its instances before awaiting their shutdown, so a
    concurrent request sees neither a manifest nor instances while the lock is still held.
    """
    handler = mock_hassette.app_handler
    handler.registry.get_manifest.return_value = None
    handler.registry.get_instances.return_value = {}
    handler.is_action_in_progress = MagicMock(return_value=True)

    response = await client.post(f"{APPS_PATH}/my_app/{suffix}")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "action_in_progress"
