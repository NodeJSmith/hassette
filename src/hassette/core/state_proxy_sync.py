"""Support types and the retry/backoff functions for ``StateProxy``.

The retry functions take the proxy as an explicit first argument (the same pattern as
``hassette.resources.lifecycle``) and manage its retry bookkeeping (``_retry_*``), which is
guarded by ``proxy._sync_control_lock``; the ``*_locked`` variants assume the caller already
holds it. The synchronization orchestration itself stays on ``StateProxy`` — a retry calls
back into ``proxy._request_connected_synchronization``.
"""

import asyncio
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import TYPE_CHECKING

from hassette.core.websocket_reconnect import fast_backoff_delay

if TYPE_CHECKING:
    from hassette.core.state_proxy import StateProxy
    from hassette.events import HassStateDict


@dataclass(slots=True)
class JournalOperation:
    entity_id: str
    state: "HassStateDict | None"


@dataclass(slots=True)
class ActiveSynchronization:
    request_id: int
    generation: int
    status: "StateSynchronizationStatus"
    baseline_states: dict[str, "HassStateDict"]
    journal: list[JournalOperation]


class ConnectedSyncCause(StrEnum):
    """Why a connected-generation synchronization was requested.

    ``CONNECTED_SIGNAL`` uses a distinct value from ``ConnectionState.CONNECTED`` — the two
    enums represent unrelated concepts (a sync trigger vs. a WebSocket connection state) and
    sharing the string "connected" made it easy to grep for the wrong one.
    """

    CONNECTED_SIGNAL = "connected_signal"
    RETRY = auto()


class StateSynchronizationStatus(StrEnum):
    """What kind of state synchronization work, if any, is currently active."""

    IDLE = auto()
    INITIAL = auto()
    RECONNECT = auto()
    POLL = auto()


class StateCacheFreshness(StrEnum):
    """Freshness of the published StateProxy cache."""

    UNAVAILABLE = auto()
    FRESH = auto()
    STALE = auto()


async def handle_synchronization_failure(proxy: "StateProxy", generation: int) -> None:
    """React to a failed synchronization: downgrade freshness and, with no poll job, retry.

    A no-op if ``generation`` is no longer the currently connected generation (a reconnect
    has already superseded this failure). Otherwise downgrades the cache freshness the same
    way ``on_disconnect`` does (STALE if the initial-state capability has already been
    reached, else UNAVAILABLE). If the poll job is installed, the next poll tick is left to
    converge the cache and no retry is scheduled; otherwise schedules a backoff retry.
    """
    current_generation = proxy.hassette.websocket_service.get_connected_generation()
    if current_generation != generation:
        return

    if proxy.has_initial_state_capability():
        proxy._cache_freshness = StateCacheFreshness.STALE
    else:
        proxy._cache_freshness = StateCacheFreshness.UNAVAILABLE

    if proxy.poll_job is not None:
        return
    await schedule_retry(proxy, generation)


async def schedule_retry(proxy: "StateProxy", generation: int) -> None:
    """Schedule (or re-arm) a single backoff-delayed retry task for ``generation``.

    If a live retry task is already scheduled for this same generation, this is a no-op
    unless called from that very task (letting a retry re-schedule its own successor).
    Otherwise cancels any stale retry task, bumps the attempt counter (resetting it first if
    the generation changed), and spawns a new delayed retry sized by
    ``compute_retry_delay``.
    """
    async with proxy._sync_control_lock:
        current_task = asyncio.current_task()
        if proxy._retry_generation == generation and proxy._retry_task is not None and not proxy._retry_task.done():
            if proxy._retry_task is not current_task:
                return
        else:
            if proxy._retry_generation != generation:
                proxy._retry_attempt = 0
            cancel_retry_task_locked(proxy)
        proxy._retry_generation = generation
        proxy._retry_attempt += 1
        delay = compute_retry_delay(proxy._retry_attempt)
        proxy._retry_task = proxy.task_bucket.spawn(
            run_retry_after_delay(proxy, generation=generation, delay=delay),
            name=f"state_proxy:retry:{generation}:{proxy._retry_attempt}",
        )


def compute_retry_delay(attempt: int) -> float:
    return fast_backoff_delay(attempt)


async def run_retry_after_delay(proxy: "StateProxy", *, generation: int, delay: float) -> None:
    """Sleep for ``delay``, then attempt the connected synchronization for ``generation``.

    Clears ``_retry_task`` before the retry attempt itself so a subsequent failure can
    schedule a fresh successor retry rather than being blocked by "a retry is already
    scheduled" (see ``schedule_retry``). Only clears ``_retry_generation``/``_retry_attempt``
    (resetting backoff) if this retry's generation is still the tracked one and no new retry
    task has since been scheduled for it.
    """
    current_task = asyncio.current_task()
    try:
        await asyncio.sleep(delay)
        async with proxy._sync_control_lock:
            if proxy._retry_task is current_task:
                proxy._retry_task = None
        await proxy._request_connected_synchronization(generation, cause=ConnectedSyncCause.RETRY)
        async with proxy._sync_control_lock:
            if proxy._retry_generation == generation and proxy._retry_task is None:
                proxy._retry_generation = None
                proxy._retry_attempt = 0
    except asyncio.CancelledError:
        raise
    finally:
        async with proxy._sync_control_lock:
            if proxy._retry_task is current_task:
                proxy._retry_task = None
                proxy._retry_generation = None


async def cancel_retry_task(proxy: "StateProxy") -> None:
    task: asyncio.Task[None] | None = None
    async with proxy._sync_control_lock:
        task = proxy._retry_task
        cancel_retry_task_locked(proxy)
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)


def cancel_retry_task_locked_if_superseded(proxy: "StateProxy", generation: int) -> None:
    if proxy._retry_generation is None or proxy._retry_generation == generation:
        return
    cancel_retry_task_locked(proxy)
    proxy._retry_attempt = 0


def cancel_retry_task_locked(proxy: "StateProxy") -> None:
    if proxy._retry_task is not None and not proxy._retry_task.done():
        proxy._retry_task.cancel()
    proxy._retry_task = None
    proxy._retry_generation = None
