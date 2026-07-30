import asyncio
from collections.abc import Generator
from dataclasses import dataclass
from enum import StrEnum, auto
from itertools import count
from typing import TYPE_CHECKING, Any, ClassVar

from fair_async_rlock import FairAsyncRLock
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from hassette.bus import Bus
from hassette.core.api_resource import ApiResource
from hassette.core.bus_service import BusService
from hassette.core.scheduler_service import SchedulerService
from hassette.events import RawStateChangeEvent
from hassette.events.metadata import get_websocket_generation
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.scheduler import ScheduledJob, Scheduler
from hassette.types import Topic
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.hass_utils import extract_domain

MAX_RETRY_ATTEMPTS = 5

_retry_on_not_ready = retry(
    retry=retry_if_exception_type(ResourceNotReadyError),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=0.01, max=0.1),
    reraise=True,
)

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events import HassStateDict


@dataclass(slots=True)
class _JournalOperation:
    entity_id: str
    state: "HassStateDict | None"


@dataclass(slots=True)
class _ActiveSynchronization:
    request_id: int
    generation: int
    status: "StateSynchronizationStatus"
    baseline_states: dict[str, "HassStateDict"]
    journal: list[_JournalOperation]


class _ConnectedSyncCause:
    CONNECTED = "connected"
    RETRY = "retry"


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


class StateProxy(Resource):
    depends_on: ClassVar[list[type[Resource]]] = [ApiResource, BusService, SchedulerService]

    states: dict[str, "HassStateDict"]
    lock: FairAsyncRLock
    bus: Bus
    scheduler: Scheduler
    state_change_sub: "Subscription | None"
    poll_job: "ScheduledJob | None"

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.states = {}
        self.lock = FairAsyncRLock()
        self.bus = self.add_child(Bus, priority=100)
        self.scheduler = self.add_child(Scheduler)
        self.state_change_sub = None
        self.poll_job = None
        self._synchronization_status = StateSynchronizationStatus.IDLE
        self._cache_freshness = StateCacheFreshness.UNAVAILABLE
        self._maintained_generation: int | None = None
        self._initial_state_capability_event = asyncio.Event()
        self._sync_control_lock = asyncio.Lock()
        self._sync_task: asyncio.Task[None] | None = None
        self._sync_generation: int | None = None
        self._active_sync: _ActiveSynchronization | None = None
        self._pending_reconnect_generation: int | None = None
        self._request_ids = count(1)
        self._bootstrap_task: asyncio.Task[None] | None = None
        self._retry_task: asyncio.Task[None] | None = None
        self._retry_generation: int | None = None
        self._retry_attempt = 0

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.state_proxy

    @property
    def synchronization_status(self) -> StateSynchronizationStatus:
        return self._synchronization_status

    @property
    def cache_freshness(self) -> StateCacheFreshness:
        return self._cache_freshness

    @property
    def has_cache_entries(self) -> bool:
        return bool(self.states)

    @property
    def maintained_generation(self) -> int | None:
        return self._maintained_generation

    def has_initial_state_capability(self) -> bool:
        return self._initial_state_capability_event.is_set()

    async def wait_initial_state_capability(self, *, timeout: float | None = None) -> bool:
        if self._initial_state_capability_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._initial_state_capability_event.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return self._initial_state_capability_event.is_set()

    async def on_initialize(self) -> None:
        self.logger.debug("Dependencies ready, wiring StateProxy synchronization coordinator")
        await self.subscribe_to_events()
        await self._install_poll_job()
        mark_ready(self, reason="StateProxy initialized")
        self._bootstrap_task = self.task_bucket.spawn(self._bootstrap_initial_sync(), name="state_proxy:bootstrap")

    async def subscribe_to_events(self) -> None:
        if self.state_change_sub is not None:
            return
        self.state_change_sub = await self.bus.on(
            topic=Topic.HASS_EVENT_STATE_CHANGED,
            handler=self.on_state_change,
            name="hassette.state_proxy.on_state_change",
        )
        self.hassette.websocket_service.add_connected_observer(self._on_websocket_connected)
        self.hassette.websocket_service.add_disconnected_observer(self._on_websocket_disconnected)

    async def _install_poll_job(self) -> None:
        if self.hassette.config.disable_state_proxy_polling:
            self.poll_job = None
            self.logger.warning("State proxy polling is disabled per configuration")
            return

        self.poll_job = await self.scheduler.run_every(
            self.load_cache,
            seconds=self.hassette.config.state_proxy_poll_interval_seconds,
            name="state_proxy_poll",
            if_exists="skip",
            mode="single",
        )

    async def _bootstrap_initial_sync(self) -> None:
        websocket_service = self.hassette.websocket_service
        timeout = websocket_service.total_timeout_seconds
        self.logger.debug("Waiting up to %.1fs for initial WebSocket connection before state sync", timeout)
        connected = await websocket_service.wait_initial_connection(timeout=timeout)
        if not connected:
            self.logger.warning("Initial WebSocket connection did not complete within %.1fs", timeout)
            return

        generation = websocket_service.get_connected_generation()
        if generation is not None:
            await self._request_connected_synchronization(generation, cause=_ConnectedSyncCause.CONNECTED)

    async def on_shutdown(self) -> None:
        self.hassette.websocket_service.remove_connected_observer(self._on_websocket_connected)
        self.hassette.websocket_service.remove_disconnected_observer(self._on_websocket_disconnected)

        if self._bootstrap_task is not None:
            self._bootstrap_task.cancel()
            await asyncio.gather(self._bootstrap_task, return_exceptions=True)
            self._bootstrap_task = None

        await self._cancel_retry_task()

        if self._sync_task is not None:
            self._sync_task.cancel()
            await asyncio.gather(self._sync_task, return_exceptions=True)
            self._sync_task = None

        self._active_sync = None
        self._pending_reconnect_generation = None
        self._synchronization_status = StateSynchronizationStatus.IDLE
        self._sync_generation = None
        self._cache_freshness = StateCacheFreshness.UNAVAILABLE
        self._maintained_generation = None
        self._initial_state_capability_event = asyncio.Event()
        self.poll_job = None
        self.state_change_sub = None
        mark_not_ready(self, reason="Shutting down")

        async with self.lock:
            self.states = {}

    def num_domain_states(self, domain: str) -> int:
        return sum(1 for _ in self.yield_domain_states(domain))

    @_retry_on_not_ready
    def get_state(self, entity_id: str) -> "HassStateDict | None":
        return self.get_state_once(entity_id)

    def _check_ready(self) -> None:
        if self._cache_freshness == StateCacheFreshness.UNAVAILABLE:
            raise ResourceNotReadyError(f"StateProxy is not ready (reason: {self._ready_reason}).")

    def get_state_once(self, entity_id: str) -> "HassStateDict | None":
        self._check_ready()
        return self.states.get(entity_id)

    def get_domain_states(self, domain: str) -> dict[str, "HassStateDict"]:
        return dict(self.yield_domain_states(domain))

    @_retry_on_not_ready
    def yield_domain_states(self, domain: str) -> Generator[tuple[str, "HassStateDict"], Any, None]:
        self._check_ready()

        def iter_states() -> Generator[tuple[str, "HassStateDict"], Any, None]:
            for eid, state in list(self.states.items()):
                try:
                    if extract_domain(eid) == domain:
                        yield eid, state
                except ValueError:
                    self.logger.warning("State for entity %s has invalid 'entity_id' value", eid)

        return iter_states()

    @_retry_on_not_ready
    def __contains__(self, entity_id: str) -> bool:
        self._check_ready()
        return entity_id in self.states

    async def on_state_change(self, event: RawStateChangeEvent) -> None:
        entity_id = event.payload.data.entity_id
        old_state_dict = event.payload.data.old_state
        new_state_dict = event.payload.data.new_state
        event_generation = get_websocket_generation(event)
        current_generation = self.hassette.websocket_service.get_connected_generation()
        if event_generation is None:
            event_generation = current_generation
        elif current_generation is not None and event_generation != current_generation:
            self.logger.debug(
                "Ignoring stale state event for %s from generation %s (current=%s)",
                entity_id,
                event_generation,
                current_generation,
            )
            return

        self.logger.debug("State changed event for %s", entity_id)
        async with self.lock:
            if new_state_dict is None:
                if entity_id in self.states:
                    self.states.pop(entity_id)
                    self._append_journal_operation(entity_id, None, event_generation)
                    self.logger.debug("Removed state for %s", entity_id)
                    return
                self.logger.debug("Ignoring removal of unknown entity %s", entity_id)
                self._append_journal_operation(entity_id, None, event_generation)
                return

            if self._is_older_or_equal_state(self.states.get(entity_id), new_state_dict):
                self.logger.debug("Ignoring out-of-date state update for %s", entity_id)
                return

            self.states[entity_id] = new_state_dict
            self._append_journal_operation(entity_id, new_state_dict, event_generation)
            if old_state_dict is None:
                self.logger.debug("Added state for %s", entity_id)
            else:
                self.logger.debug("Updated state for %s", entity_id)

    def _append_journal_operation(
        self,
        entity_id: str,
        state: "HassStateDict | None",
        event_generation: int | None,
    ) -> None:
        active_sync = self._active_sync
        if active_sync is None:
            return
        if event_generation is None or active_sync.generation != event_generation:
            return
        active_sync.journal.append(_JournalOperation(entity_id=entity_id, state=state))

    async def on_disconnect(self) -> None:
        await self._cancel_retry_task()

        sync_task = await self._detach_active_sync_task()
        if sync_task is not None:
            sync_task.cancel()
            await asyncio.gather(sync_task, return_exceptions=True)

        if self.has_initial_state_capability():
            self._cache_freshness = StateCacheFreshness.STALE
        else:
            self._cache_freshness = StateCacheFreshness.UNAVAILABLE

    async def on_reconnect(self) -> None:
        generation = self.hassette.websocket_service.get_connected_generation()
        if generation is None:
            return
        await self._request_connected_synchronization(generation, cause=_ConnectedSyncCause.CONNECTED)

    async def _on_websocket_connected(self, generation: int) -> None:
        await self._request_connected_synchronization(generation, cause=_ConnectedSyncCause.CONNECTED)

    async def _on_websocket_disconnected(self) -> None:
        await self.on_disconnect()

    async def load_cache(self) -> None:
        generation = self.hassette.websocket_service.get_connected_generation()
        if generation is None:
            self.logger.debug("Skipping poll refresh without an active connected generation")
            return
        await self._request_poll_synchronization(generation)

    async def _request_poll_synchronization(self, generation: int) -> None:
        async with self._sync_control_lock:
            self._cancel_retry_task_locked_if_superseded(generation)
            active_task = self._active_sync_task()
            if active_task is not None:
                self.logger.debug("Skipping poll refresh during active synchronization")
                return
            if self._needs_connected_synchronization(generation):
                task = self._start_sync_task(
                    generation,
                    self._determine_connected_sync_status(generation, cause=_ConnectedSyncCause.RETRY),
                )
            else:
                task = self._start_sync_task(generation, StateSynchronizationStatus.POLL)
        await task

    async def _request_connected_synchronization(self, generation: int, *, cause: str) -> None:
        while True:
            started_new_task = False
            continue_after_active_task = False
            async with self._sync_control_lock:
                self._cancel_retry_task_locked_if_superseded(generation)
                active_task = self._active_sync_task()
                if active_task is not None:
                    if self._synchronization_status == StateSynchronizationStatus.POLL or (
                        self._sync_generation is not None and self._sync_generation != generation
                    ):
                        self._pending_reconnect_generation = generation
                        continue_after_active_task = True
                    task = active_task
                else:
                    pending_generation = self._pending_reconnect_generation
                    if pending_generation is not None:
                        generation = pending_generation
                    if not self._needs_connected_synchronization(generation):
                        if self._pending_reconnect_generation == generation:
                            self._pending_reconnect_generation = None
                        return
                    status = self._determine_connected_sync_status(generation, cause=cause)
                    self._pending_reconnect_generation = None
                    task = self._start_sync_task(generation, status)
                    started_new_task = True
            await task
            if started_new_task or not continue_after_active_task:
                return

    def _active_sync_task(self) -> asyncio.Task[None] | None:
        if self._sync_task is None or self._sync_task.done():
            return None
        return self._sync_task

    def _needs_connected_synchronization(self, generation: int) -> bool:
        if not self.has_initial_state_capability():
            return True
        if self._maintained_generation != generation:
            return True
        return self._cache_freshness != StateCacheFreshness.FRESH

    def _determine_connected_sync_status(
        self,
        generation: int,
        *,
        cause: str,
    ) -> StateSynchronizationStatus:
        if not self.has_initial_state_capability():
            return StateSynchronizationStatus.INITIAL
        if self._maintained_generation != generation or self._cache_freshness != StateCacheFreshness.FRESH:
            return StateSynchronizationStatus.RECONNECT
        if cause == _ConnectedSyncCause.RETRY:
            return StateSynchronizationStatus.POLL
        return StateSynchronizationStatus.RECONNECT

    def _start_sync_task(self, generation: int, status: StateSynchronizationStatus) -> asyncio.Task[None]:
        self._synchronization_status = status
        self._sync_generation = generation
        request_id = next(self._request_ids)
        task = self.task_bucket.spawn(
            self._run_synchronization(request_id=request_id, generation=generation, status=status),
            name=f"state_proxy:sync:{status}:{generation}:{request_id}",
        )
        self._sync_task = task
        return task

    async def _run_synchronization(
        self,
        *,
        request_id: int,
        generation: int,
        status: StateSynchronizationStatus,
    ) -> None:
        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("StateProxy synchronization must run inside an asyncio task")
        baseline_states = await self._begin_synchronization(request_id=request_id, generation=generation, status=status)
        committed = False
        try:
            raw_states = await self.hassette.api.get_states_raw()
            candidate_states = self._build_candidate_states(raw_states, baseline_states)
            committed = await self._commit_candidate_states(
                request_id=request_id,
                generation=generation,
                status=status,
                candidate_states=candidate_states,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("State synchronization failed (%s generation=%s)", status, generation)
            await self._handle_synchronization_failure(generation)
        finally:
            await self._finish_synchronization(request_id=request_id, task=current_task, committed=committed)

    async def _begin_synchronization(
        self,
        *,
        request_id: int,
        generation: int,
        status: StateSynchronizationStatus,
    ) -> dict[str, "HassStateDict"]:
        async with self.lock:
            baseline_states = dict(self.states)
            self._active_sync = _ActiveSynchronization(
                request_id=request_id,
                generation=generation,
                status=status,
                baseline_states=baseline_states,
                journal=[],
            )
        return baseline_states

    def _build_candidate_states(
        self,
        raw_states: list["HassStateDict"],
        baseline_states: dict[str, "HassStateDict"],
    ) -> dict[str, "HassStateDict"]:
        candidate_states: dict[str, HassStateDict] = {}
        for state in raw_states:
            entity_id = state.get("entity_id")
            if not entity_id:
                continue
            baseline_state = baseline_states.get(entity_id)
            if baseline_state is not None and self._is_older_or_equal_state(baseline_state, state):
                candidate_states[entity_id] = baseline_state
            else:
                candidate_states[entity_id] = state
        return candidate_states

    async def _commit_candidate_states(
        self,
        *,
        request_id: int,
        generation: int,
        status: StateSynchronizationStatus,
        candidate_states: dict[str, "HassStateDict"],
    ) -> bool:
        async with self.lock:
            active_sync = self._active_sync
            if active_sync is None or active_sync.request_id != request_id or active_sync.generation != generation:
                return False

            if self.hassette.websocket_service.get_connected_generation() != generation:
                return False

            for operation in active_sync.journal:
                if operation.state is None:
                    candidate_states.pop(operation.entity_id, None)
                else:
                    candidate_states[operation.entity_id] = operation.state

            self.states = candidate_states
            self._cache_freshness = StateCacheFreshness.FRESH
            self._maintained_generation = generation
            self._retry_attempt = 0
            if status == StateSynchronizationStatus.INITIAL:
                self._initial_state_capability_event.set()
            return True

    async def _handle_synchronization_failure(self, generation: int) -> None:
        current_generation = self.hassette.websocket_service.get_connected_generation()
        if current_generation != generation:
            return

        if self.has_initial_state_capability():
            self._cache_freshness = StateCacheFreshness.STALE
        else:
            self._cache_freshness = StateCacheFreshness.UNAVAILABLE

        if self.poll_job is not None:
            return
        await self._schedule_retry(generation)

    async def _detach_active_sync_task(self) -> asyncio.Task[None] | None:
        async with self._sync_control_lock:
            task = self._sync_task
            self._sync_task = None
            self._sync_generation = None
            self._pending_reconnect_generation = None
            self._synchronization_status = StateSynchronizationStatus.IDLE
        async with self.lock:
            self._active_sync = None
        return task

    async def _finish_synchronization(
        self,
        *,
        request_id: int,
        task: asyncio.Task[None],
        committed: bool,
    ) -> None:
        async with self.lock:
            if self._active_sync is not None and self._active_sync.request_id == request_id:
                self._active_sync = None

        async with self._sync_control_lock:
            if self._sync_task is task:
                self._sync_task = None
                self._sync_generation = None
                self._synchronization_status = StateSynchronizationStatus.IDLE
            if not committed and self._pending_reconnect_generation is None:
                return

    async def _schedule_retry(self, generation: int) -> None:
        async with self._sync_control_lock:
            current_task = asyncio.current_task()
            if self._retry_generation == generation and self._retry_task is not None and not self._retry_task.done():
                if self._retry_task is not current_task:
                    return
            else:
                if self._retry_generation != generation:
                    self._retry_attempt = 0
                self._cancel_retry_task_locked()
            self._retry_generation = generation
            self._retry_attempt += 1
            delay = self._compute_retry_delay(self._retry_attempt)
            self._retry_task = self.task_bucket.spawn(
                self._run_retry_after_delay(generation=generation, delay=delay),
                name=f"state_proxy:retry:{generation}:{self._retry_attempt}",
            )

    def _compute_retry_delay(self, attempt: int) -> float:
        initial = self.hassette.config.websocket.connect_retry_initial_wait_seconds
        max_wait = self.hassette.config.websocket.connect_retry_max_wait_seconds
        return min(initial * (2 ** max(attempt - 1, 0)), max_wait)

    async def _run_retry_after_delay(self, *, generation: int, delay: float) -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(delay)
            async with self._sync_control_lock:
                if self._retry_task is current_task:
                    self._retry_task = None
            await self._request_connected_synchronization(generation, cause=_ConnectedSyncCause.RETRY)
            async with self._sync_control_lock:
                if self._retry_generation == generation and self._retry_task is None:
                    self._retry_generation = None
                    self._retry_attempt = 0
        except asyncio.CancelledError:
            raise
        finally:
            async with self._sync_control_lock:
                if self._retry_task is current_task:
                    self._retry_task = None
                    self._retry_generation = None

    async def _cancel_retry_task(self) -> None:
        task: asyncio.Task[None] | None = None
        async with self._sync_control_lock:
            task = self._retry_task
            self._cancel_retry_task_locked()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def _cancel_retry_task_locked_if_superseded(self, generation: int) -> None:
        if self._retry_generation is None or self._retry_generation == generation:
            return
        self._cancel_retry_task_locked()
        self._retry_attempt = 0

    def _cancel_retry_task_locked(self) -> None:
        if self._retry_task is not None and not self._retry_task.done():
            self._retry_task.cancel()
        self._retry_task = None
        self._retry_generation = None

    @staticmethod
    def _is_older_or_equal_state(
        current_state: "HassStateDict | None",
        new_state_dict: "HassStateDict",
    ) -> bool:
        if current_state is None:
            return False
        curr_last_updated = current_state.get("last_updated")
        new_last_updated = new_state_dict.get("last_updated")
        if curr_last_updated is None or new_last_updated is None:
            return False
        return new_last_updated <= curr_last_updated
