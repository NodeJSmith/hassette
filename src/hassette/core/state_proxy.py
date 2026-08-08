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
from hassette.scheduler import Job, Scheduler
from hassette.types import Topic
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.hass_utils import extract_domain

MAX_RETRY_ATTEMPTS = 5

# Backoff for the `@_retry_on_not_ready` decorator, applied to read methods that may be called
# briefly before initial state capability is established (see ResourceNotReadyError). Distinct
# from `_compute_retry_delay`'s connect-retry backoff, which governs whole-synchronization retries.
RETRY_ON_NOT_READY_INITIAL_WAIT_SECONDS = 0.01
RETRY_ON_NOT_READY_MAX_WAIT_SECONDS = 0.1

# Base of the exponential backoff used by `_compute_retry_delay` for synchronization retries.
SYNC_RETRY_BACKOFF_BASE = 2

_retry_on_not_ready = retry(
    retry=retry_if_exception_type(ResourceNotReadyError),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(
        initial=RETRY_ON_NOT_READY_INITIAL_WAIT_SECONDS, max=RETRY_ON_NOT_READY_MAX_WAIT_SECONDS
    ),
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


class _ConnectedSyncCause(StrEnum):
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


class StateProxy(Resource):
    """In-memory cache of Home Assistant entity state, kept in sync via the WebSocket connection.

    ``StateProxy`` is both a read-through cache (``get_state``, ``get_domain_states``,
    ``yield_domain_states``, etc.) and the coordinator that keeps that cache synchronized with Home
    Assistant across connects, disconnects, and reconnects. Synchronization is
    connection-generation-aware: each WebSocket reconnect gets a new generation from
    ``WebsocketService``, and any state-changed event or synchronization result tagged with a
    stale generation is rejected instead of corrupting the cache with data from a superseded
    connection.

    A full synchronization pass (``_run_synchronization``) fetches every entity's current state
    via ``Api.get_states_raw()`` and replays a per-generation journal of state-changed events
    observed while that fetch was in flight (``_JournalOperation`` / ``_ActiveSynchronization``),
    so no update racing the bulk fetch is lost. On failure it retries with exponential backoff
    (``_schedule_retry`` / ``_compute_retry_delay``) unless polling is enabled, in which case the
    next scheduled poll (``load_cache``) is left to converge instead.

    Its own ``Resource`` readiness means only "the synchronization coordinator is wired" — not
    that Home Assistant data is usable yet. ``has_initial_state_capability()`` /
    ``wait_initial_state_capability()`` is a separate, one-way latch that
    ``AppBootstrapCoordinator`` waits on before releasing app bootstrap: it opens only once the
    first full synchronization for a connected generation has committed, and never closes again
    on a later disconnect (see ``StateCacheFreshness`` — a later loss of connection marks the
    cache ``STALE`` rather than ``UNAVAILABLE``, preserving stale reads for already-running apps).
    """

    depends_on: ClassVar[list[type[Resource]]] = [ApiResource, BusService, SchedulerService]

    states: dict[str, "HassStateDict"]
    lock: FairAsyncRLock
    bus: Bus
    scheduler: Scheduler
    state_change_sub: "Subscription | None"
    poll_job: "Job | None"

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        """Initialize the state cache and synchronization bookkeeping.

        Args:
            hassette: The owning ``Hassette`` instance.
            parent: The parent resource, if any.
        """
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
        # Bounds ERROR-level traceback logging during an extended connected-but-failing outage:
        # only the first failure per generation logs a full traceback, repeats downgrade to WARNING.
        self._last_logged_sync_failure_generation: int | None = None

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Configured log level for the state proxy (``hassette.config.logging.state_proxy``)."""
        return self.hassette.config.logging.state_proxy

    @property
    def synchronization_status(self) -> StateSynchronizationStatus:
        """The kind of state synchronization work, if any, currently in flight."""
        return self._synchronization_status

    @property
    def cache_freshness(self) -> StateCacheFreshness:
        """Freshness of the published state cache. See ``StateCacheFreshness``."""
        return self._cache_freshness

    @property
    def has_cache_entries(self) -> bool:
        """True if the state cache holds at least one entity."""
        return bool(self.states)

    @property
    def maintained_generation(self) -> int | None:
        """The connection generation the current cache contents were last synchronized against.

        None if no synchronization has committed yet.
        """
        return self._maintained_generation

    def has_initial_state_capability(self) -> bool:
        """Return whether the initial-state capability latch has opened.

        True once the first full synchronization for a connected generation has committed at
        least once. Never reverts to False afterward, even across later disconnects — see the
        class docstring for how this differs from ``cache_freshness``.
        """
        return self._initial_state_capability_event.is_set()

    async def wait_initial_state_capability(self, *, timeout: float | None = None) -> bool:
        """Wait for the initial-state capability latch to open.

        Args:
            timeout: Maximum time to wait, in seconds. None waits indefinitely.

        Returns:
            True if the capability is already, or becomes, available before the timeout; False
            if the wait timed out.
        """
        if self._initial_state_capability_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._initial_state_capability_event.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return self._initial_state_capability_event.is_set()

    async def on_initialize(self) -> None:
        """Wire the synchronization coordinator and start the background bootstrap sync.

        ``ApiResource``, ``BusService``, and ``SchedulerService`` are guaranteed ready by
        ``depends_on`` auto-wait. Subscribes to state-changed events and websocket connect/
        disconnect observers, installs the periodic poll job (unless polling is disabled), then
        marks this resource ready and spawns the initial synchronization in the background.
        Resource readiness here means only "wired," not that Home Assistant data is available
        yet — see ``has_initial_state_capability``.
        """
        self.logger.debug("Dependencies ready, wiring StateProxy synchronization coordinator")
        await self.subscribe_to_events()
        await self._install_poll_job()
        mark_ready(self, reason="StateProxy initialized")
        self._bootstrap_task = self.task_bucket.spawn(self._bootstrap_initial_sync(), name="state_proxy:bootstrap")

    async def subscribe_to_events(self) -> None:
        """Subscribe to state-changed events and websocket connect/disconnect observers.

        Idempotent: a no-op if a state-changed subscription is already active.
        """
        if self.state_change_sub is not None:
            return
        self.state_change_sub = await self.bus.on(
            topic=Topic.HASS_EVENT_STATE_CHANGED,
            handler=self.on_state_change,
            name="hassette.state_proxy.on_state_change",
        )
        self.hassette.websocket_service.connected_observers.add(self._on_websocket_connected)
        self.hassette.websocket_service.disconnected_observers.add(self._on_websocket_disconnected)

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
        # StateProxy.depends_on excludes WebsocketService, and WebsocketService has no depends_on of
        # its own, so WebsocketService routinely reaches CONNECTED before StateProxy's own dependencies
        # (gated behind DatabaseService/SyncExecutorService) let it register its connected-observer. This
        # explicit post-registration check is what catches that race and starts sync anyway — it is not
        # redundant with the observer callbacks.
        websocket_service = self.hassette.websocket_service
        timeout = websocket_service.total_timeout_seconds
        self.logger.debug("Waiting up to %.1fs for initial WebSocket connection before state sync", timeout)
        connected = await websocket_service.wait_initial_connection(timeout=timeout)
        if not connected:
            self.logger.warning("Initial WebSocket connection did not complete within %.1fs", timeout)
            return

        generation = websocket_service.get_connected_generation()
        if generation is not None:
            await self._request_connected_synchronization(generation, cause=_ConnectedSyncCause.CONNECTED_SIGNAL)

    async def on_shutdown(self) -> None:
        """Cancel all in-flight synchronization and retry work and reset the cache to empty.

        Cancels the bootstrap task, any pending retry task, and any active synchronization task;
        resets synchronization bookkeeping (freshness, maintained generation, the initial-state
        capability latch); clears the state cache; and marks the resource not-ready.
        """
        self.hassette.websocket_service.connected_observers.remove(self._on_websocket_connected)
        self.hassette.websocket_service.disconnected_observers.remove(self._on_websocket_disconnected)

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
        self._initial_state_capability_event.clear()
        self.poll_job = None
        self.state_change_sub = None
        mark_not_ready(self, reason="Shutting down")

        async with self.lock:
            self.states = {}

    @_retry_on_not_ready
    def get_state(self, entity_id: str) -> "HassStateDict | None":
        """Get the current cached state for an entity.

        Args:
            entity_id: The entity ID to look up (e.g., "light.kitchen").

        Returns:
            The raw state dict if found, None otherwise.

        Raises:
            ResourceNotReadyError: If the cache freshness is UNAVAILABLE (no synchronization has
                ever committed) even after retries. Once the cache has been synchronized at
                least once, a later disconnect marks it STALE rather than UNAVAILABLE, so stale
                reads succeed instead of raising.
        """
        return self.get_state_once(entity_id)

    def _check_ready(self) -> None:
        if self._cache_freshness == StateCacheFreshness.UNAVAILABLE:
            raise ResourceNotReadyError(
                f"StateProxy cache is not available yet (freshness={self._cache_freshness}, "
                f"initial_capability={self.has_initial_state_capability()})."
            )

    def get_state_once(self, entity_id: str) -> "HassStateDict | None":
        """Get the current cached state for an entity, without the not-ready retry decorator.

        Args:
            entity_id: The entity ID to look up (e.g., "light.kitchen").

        Returns:
            The raw state dict if found, None otherwise.

        Raises:
            ResourceNotReadyError: If the cache freshness is UNAVAILABLE. Unlike ``get_state``,
                this call is not retried.
        """
        self._check_ready()
        return self.states.get(entity_id)

    def get_domain_states(self, domain: str) -> dict[str, "HassStateDict"]:
        """Get all cached states for a specific domain.

        Args:
            domain: The domain to filter by (e.g., "light").

        Returns:
            A dictionary of entity_id to state for the specified domain.

        Raises:
            ResourceNotReadyError: If the cache freshness is UNAVAILABLE even after retries
                (see ``get_state``).
        """
        return dict(self.yield_domain_states(domain))

    @_retry_on_not_ready
    def yield_domain_states(self, domain: str) -> Generator[tuple[str, "HassStateDict"], Any, None]:
        """Yield all cached states for a specific domain.

        This method is deliberately NOT a generator function itself: the readiness check runs
        eagerly, and iteration is delegated to a nested generator. That is required for
        ``@_retry_on_not_ready`` to work — a generator body would defer the check past the
        decorated call, leaving the retry inert. Do not collapse this back into a single
        generator function.

        Args:
            domain: The domain to filter by (e.g., "light").

        Yields:
            Tuples of (entity_id, state) for the specified domain.

        Raises:
            ResourceNotReadyError: If the cache freshness is UNAVAILABLE even after retries
                (see ``get_state``).
        """
        self._check_ready()

        def iter_states() -> Generator[tuple[str, "HassStateDict"], Any, None]:
            for eid, state in list(self.states.items()):
                try:
                    if extract_domain(eid) == domain:
                        yield eid, state
                except ValueError:
                    self.logger.warning("State for entity %s has invalid 'entity_id' value", eid)

        return iter_states()

    async def on_state_change(self, event: RawStateChangeEvent) -> None:
        """Apply a state_changed event to the cache.

        Rejects events whose websocket generation does not match the current (or, while
        disconnected, last-maintained) generation, so a stale event from a superseded connection
        cannot corrupt the cache. Accepted removals and updates are also appended to the
        in-flight synchronization journal, if one is active, so a concurrent full
        synchronization can replay them over its baseline fetch.
        """
        entity_id = event.payload.data.entity_id
        old_state_dict = event.payload.data.old_state
        new_state_dict = event.payload.data.new_state
        event_generation = get_websocket_generation(event)
        current_generation = self.hassette.websocket_service.get_connected_generation()
        if event_generation is None:
            event_generation = current_generation
        else:
            # While disconnected, current_generation is None — fall back to the last generation
            # this cache actually committed, so an event carrying a stale generation from a prior
            # connection is still rejected instead of falling through unconditionally accepted.
            reference_generation = current_generation if current_generation is not None else self._maintained_generation
            if reference_generation is not None and event_generation != reference_generation:
                self.logger.debug(
                    "Ignoring stale state event for %s from generation %s (reference=%s)",
                    entity_id,
                    event_generation,
                    reference_generation,
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
        """Handle websocket disconnection.

        Cancels any pending retry task and detaches the active synchronization task (cancelling
        it if still running), then downgrades the cache freshness: to STALE if the initial-state
        capability has already been reached (so already-running apps keep reading stale data),
        or to UNAVAILABLE otherwise.
        """
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
        """Handle websocket reconnection by requesting a synchronization for the new generation.

        A no-op if the websocket has no current connected generation (e.g. a subsequent
        disconnect already invalidated it by the time this handler runs).
        """
        generation = self.hassette.websocket_service.get_connected_generation()
        if generation is None:
            return
        await self._request_connected_synchronization(generation, cause=_ConnectedSyncCause.CONNECTED_SIGNAL)

    async def _on_websocket_connected(self, generation: int) -> None:
        await self._request_connected_synchronization(generation, cause=_ConnectedSyncCause.CONNECTED_SIGNAL)

    async def _on_websocket_disconnected(self) -> None:
        await self.on_disconnect()

    async def load_cache(self) -> None:
        """Refresh the state cache via a poll-triggered synchronization.

        Called periodically by the poll job (unless polling is disabled) to keep the cache
        fresh between reconnects. A no-op if there is no current connected generation.
        """
        generation = self.hassette.websocket_service.get_connected_generation()
        if generation is None:
            self.logger.debug("Skipping poll refresh without an active connected generation")
            return
        await self._request_poll_synchronization(generation)

    async def _request_poll_synchronization(self, generation: int) -> None:
        """Handle a periodic poll tick: upgrade to a full connected sync if one is owed.

        Skips entirely if a synchronization is already active. Otherwise starts a RECONNECT/
        INITIAL sync if the cache isn't fresh for this generation (``_needs_connected_synchronization``),
        or a plain POLL sync otherwise.
        """
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

    async def _request_connected_synchronization(self, generation: int, *, cause: _ConnectedSyncCause) -> None:
        """Ensure a synchronization for ``generation`` runs, deferring to or superseding one in flight.

        If a synchronization is already active for a different generation (or is a mere POLL),
        this records ``generation`` as pending and loops back around once that task finishes,
        rather than starting a second concurrent synchronization. If no synchronization is
        needed for the (possibly superseded-and-updated) generation, this returns without
        starting one.
        """
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
        """Return whether the cache is out of date for ``generation`` and needs a full sync.

        True if the initial-state capability hasn't opened yet, if the cache was last
        synchronized against a different generation, or if the cache freshness has dropped
        below FRESH (e.g. a prior synchronization failed).
        """
        if not self.has_initial_state_capability():
            return True
        if self._maintained_generation != generation:
            return True
        return self._cache_freshness != StateCacheFreshness.FRESH

    def _determine_connected_sync_status(
        self,
        generation: int,
        *,
        cause: _ConnectedSyncCause,
    ) -> StateSynchronizationStatus:
        """Classify which kind of synchronization a connected-generation request should run.

        INITIAL if the initial-state capability hasn't opened yet (first-ever sync), RECONNECT
        if the cache is stale for this generation, otherwise POLL for a retry-driven check-in or
        RECONNECT for a fresh connected signal (``_ConnectedSyncCause``).
        """
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
        """Run one full synchronization pass: fetch, merge, and commit, or handle failure.

        Fetches every entity's current state, merges it against the pre-fetch baseline plus any
        journaled state-changed events observed during the fetch (see ``_build_candidate_states``
        and ``_commit_candidate_states``), and commits the result. On failure, logs (a full
        traceback for the first failure per generation, a downgraded one-line warning for
        repeats) and defers to ``_handle_synchronization_failure`` for freshness/retry handling.
        Always detaches itself as the active synchronization in the ``finally`` block, regardless
        of outcome.
        """
        current_task = asyncio.current_task()
        if current_task is None:
            raise RuntimeError("StateProxy synchronization must run inside an asyncio task")
        baseline_states = await self._begin_synchronization(request_id=request_id, generation=generation, status=status)
        try:
            raw_states = await self.hassette.api.get_states_raw()
            candidate_states = self._build_candidate_states(raw_states, baseline_states)
            await self._commit_candidate_states(
                request_id=request_id,
                generation=generation,
                status=status,
                candidate_states=candidate_states,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._last_logged_sync_failure_generation == generation:
                self.logger.warning(
                    "State synchronization still failing (%s generation=%s): %s", status, generation, exc
                )
            else:
                self.logger.exception("State synchronization failed (%s generation=%s)", status, generation)
                self._last_logged_sync_failure_generation = generation
            await self._handle_synchronization_failure(generation)
        finally:
            await self._finish_synchronization(request_id=request_id, task=current_task)

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
        """Merge a fresh bulk fetch with the pre-fetch baseline, keeping whichever side is newer.

        For each fetched entity, keeps the baseline (pre-fetch) state instead of the freshly
        fetched one if the baseline is at least as new (``_is_older_or_equal_state``) — this
        preserves updates that arrived via live events between the baseline snapshot and the
        bulk fetch completing. The journal of events observed *during* the fetch is applied on
        top of this result separately, in ``_commit_candidate_states``.
        """
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
        """Commit a synchronization's merged states as the new cache, if still valid to do so.

        Abandons the commit (returns False, leaves the cache untouched) if this synchronization
        is no longer the active one for its request_id/generation, or if ``generation`` is no
        longer the currently connected generation — both indicate a newer synchronization or
        reconnect has superseded this one. Otherwise, replays the journal captured during the
        fetch on top of ``candidate_states`` (journal entries win, since they are the newest
        known state), installs the result as ``self.states``, marks the cache FRESH, resets the
        retry/failure-logging counters, and — for an INITIAL synchronization — opens the
        initial-state capability latch.
        """
        async with self.lock:
            active_sync = self._active_sync
            if active_sync is None or active_sync.request_id != request_id or active_sync.generation != generation:
                self.logger.debug(
                    "Abandoning synchronization commit: active_sync mismatch (request_id=%s, generation=%s, "
                    "active_sync=%s)",
                    request_id,
                    generation,
                    active_sync,
                )
                return False

            if self.hassette.websocket_service.get_connected_generation() != generation:
                self.logger.debug(
                    "Abandoning synchronization commit: generation %s is no longer the connected generation (%s)",
                    generation,
                    self.hassette.websocket_service.get_connected_generation(),
                )
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
            self._last_logged_sync_failure_generation = None
            if status == StateSynchronizationStatus.INITIAL:
                self._initial_state_capability_event.set()
            return True

    async def _handle_synchronization_failure(self, generation: int) -> None:
        """React to a failed synchronization: downgrade freshness and, if unpolled, retry.

        A no-op if ``generation`` is no longer the currently connected generation (a reconnect
        has already superseded this failure). Otherwise downgrades the cache freshness the same
        way ``on_disconnect`` does (STALE if the initial-state capability has already been
        reached, else UNAVAILABLE). If periodic polling is enabled, the next poll tick is left
        to converge the cache and no retry is scheduled; otherwise schedules a backoff retry.
        """
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
    ) -> None:
        async with self.lock:
            if self._active_sync is not None and self._active_sync.request_id == request_id:
                self._active_sync = None

        async with self._sync_control_lock:
            if self._sync_task is task:
                self._sync_task = None
                self._sync_generation = None
                self._synchronization_status = StateSynchronizationStatus.IDLE

    async def _schedule_retry(self, generation: int) -> None:
        """Schedule (or re-arm) a single backoff-delayed retry task for ``generation``.

        If a live retry task is already scheduled for this same generation, this is a no-op
        unless called from that very task (letting a retry re-schedule its own successor).
        Otherwise cancels any stale retry task, bumps the attempt counter (resetting it first if
        the generation changed), and spawns a new delayed retry sized by
        ``_compute_retry_delay``.
        """
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
        return min(initial * (SYNC_RETRY_BACKOFF_BASE ** max(attempt - 1, 0)), max_wait)

    async def _run_retry_after_delay(self, *, generation: int, delay: float) -> None:
        """Sleep for ``delay``, then attempt the connected synchronization for ``generation``.

        Clears ``_retry_task`` before the retry attempt itself so a subsequent failure can
        schedule a fresh successor retry rather than being blocked by "a retry is already
        scheduled" (see ``_schedule_retry``). Only clears ``_retry_generation``/``_retry_attempt``
        (resetting backoff) if this retry's generation is still the tracked one and no new retry
        task has since been scheduled for it.
        """
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
