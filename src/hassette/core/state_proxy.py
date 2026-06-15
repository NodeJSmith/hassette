import asyncio
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, ClassVar

from fair_async_rlock import FairAsyncRLock
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from hassette.bus import Bus
from hassette.core.api_resource import ApiResource
from hassette.core.bus_service import BusService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.websocket_service import WebsocketService
from hassette.events import RawStateChangeEvent
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.base import Resource
from hassette.scheduler import ScheduledJob, Scheduler
from hassette.types import Topic
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.hass_utils import extract_domain

MAX_RETRY_ATTEMPTS = 5

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events import HassStateDict


class StateProxy(Resource):
    depends_on: ClassVar[list[type[Resource]]] = [WebsocketService, ApiResource, BusService, SchedulerService]

    states: dict[str, "HassStateDict"]
    lock: FairAsyncRLock
    _reconnect_lock: asyncio.Lock
    bus: Bus
    scheduler: Scheduler
    state_change_sub: "Subscription | None"
    poll_job: "ScheduledJob | None"

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self.states = {}
        self.lock = FairAsyncRLock()
        self._reconnect_lock = asyncio.Lock()
        self.bus = self.add_child(Bus, priority=100)
        self.scheduler = self.add_child(Scheduler)
        self.state_change_sub = None
        self.poll_job = None

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.state_proxy

    async def on_initialize(self) -> None:
        """Initialize the state proxy.

        WebsocketService, ApiResource, BusService, and SchedulerService are guaranteed
        ready by depends_on auto-wait. Performs initial state sync and subscribes to
        state change and registry events with high priority.
        """
        self.logger.debug("Dependencies ready, performing initial state sync")

        await self.subscribe_to_events()

        await self.bus.on_websocket_connected(handler=self.on_reconnect, name="hassette.state_proxy.on_reconnect")
        await self.bus.on_websocket_disconnected(handler=self.on_disconnect, name="hassette.state_proxy.on_disconnect")

        # Perform initial state sync
        try:
            await self.load_cache()

            self.mark_ready(reason="Initial state sync complete")

        except Exception as e:
            self.logger.exception("Failed to perform initial state sync: %s", e)
            raise

    async def subscribe_to_events(self) -> None:
        # Cancel existing subscriptions to prevent leaks on rapid reconnect
        if self.state_change_sub is not None:
            self.state_change_sub.cancel()
            self.state_change_sub = None
        if self.poll_job is not None:
            self.scheduler.scheduler_service.dequeue_job(self.poll_job)
            self.poll_job = None

        self.state_change_sub = await self.bus.on(
            topic=Topic.HASS_EVENT_STATE_CHANGED,
            handler=self.on_state_change,
            name="hassette.state_proxy.on_state_change",
        )
        if not self.hassette.config.disable_state_proxy_polling:
            self.poll_job = await self.scheduler.run_every(
                self.load_cache,
                seconds=self.hassette.config.state_proxy_poll_interval_seconds,
                if_exists="skip",
            )
        else:
            self.poll_job = None
            self.logger.warning("State proxy polling is disabled per configuration")

    async def on_shutdown(self) -> None:
        """Shutdown the state proxy and clean up resources."""
        self.logger.debug("Shutting down state proxy")
        self.mark_not_ready(reason="Shutting down")
        # Null out subscription/job references to guard against on_disconnect() race.
        self.poll_job = None
        self.state_change_sub = None

        async with self.lock:
            self.states.clear()

    def num_domain_states(self, domain: str) -> int:
        """Return the number of states for a specific domain.

        Args:
            domain: The domain to filter by (e.g., "light").

        Returns:
            The number of states in the specified domain.

        Raises:
            ResourceNotReadyError: If not ready and cache is empty (cold start).
                When disconnected but cache is populated, stale data is returned.
        """
        return sum(1 for _ in self.yield_domain_states(domain))

    @retry(
        retry=retry_if_exception_type(ResourceNotReadyError),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(),
        reraise=True,
    )
    def get_state(self, entity_id: str) -> "HassStateDict | None":
        """Get the current state for an entity.

        Args:
            entity_id: The entity ID to look up (e.g., "light.kitchen").

        Returns:
            The typed state object if found, None otherwise.

        Raises:
            ResourceNotReadyError: If not ready and cache is empty (cold start).
                When disconnected but cache is populated, stale data is returned.
        """

        # Lock-free read is safe because dict assignment is atomic in CPython
        # and we replace whole objects rather than mutating them

        return self.get_state_once(entity_id)

    def get_state_once(self, entity_id: str) -> "HassStateDict | None":
        # Stale reads allowed when cache is populated; only raise during cold start
        if not self.is_ready() and not self.states:
            raise ResourceNotReadyError(f"StateProxy is not ready (reason: {self._ready_reason}).")

        return self.states.get(entity_id)

    def get_domain_states(self, domain: str) -> dict[str, "HassStateDict"]:
        """Get all states for a specific domain.

        Args:
            domain: The domain to filter by (e.g., "light").

        Returns:
            A dictionary of entity_id to state for the specified domain.

        Raises:
            ResourceNotReadyError: If not ready and cache is empty (cold start).
                When disconnected but cache is populated, stale data is returned.
        """

        return {eid: state for eid, state in self.yield_domain_states(domain)}

    @retry(
        retry=retry_if_exception_type(ResourceNotReadyError),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(),
        reraise=True,
    )
    def yield_domain_states(self, domain: str) -> Generator[tuple[str, "HassStateDict"], Any, None]:
        """Yield all states for a specific domain.

        Args:
            domain: The domain to filter by (e.g., "light").

        Yields:
            Tuples of (entity_id, state) for the specified domain.

        Raises:
            ResourceNotReadyError: If not ready and cache is empty (cold start).
                When disconnected but cache is populated, stale data is returned.
        """
        if not self.is_ready() and not self.states:
            raise ResourceNotReadyError(f"StateProxy is not ready (reason: {self._ready_reason}).")

        # Snapshot to avoid RuntimeError if load_cache() mutates the dict mid-iteration
        for eid, state in list(self.states.items()):
            try:
                if extract_domain(eid) == domain:
                    yield eid, state
            except ValueError:
                self.logger.warning("State for entity %s has invalid 'entity_id' value", eid)

    @retry(
        retry=retry_if_exception_type(ResourceNotReadyError),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(),
        reraise=True,
    )
    def __contains__(self, entity_id: str) -> bool:
        """Check if a specific entity ID exists in the state proxy.

        Args:
            entity_id: The entity ID to check (e.g., "light.kitchen").

        Returns:
            True if the entity exists, False otherwise.

        Raises:
            ResourceNotReadyError: If not ready and cache is empty (cold start).
                When disconnected but cache is populated, stale data is returned.
        """
        if not self.is_ready() and not self.states:
            raise ResourceNotReadyError(f"StateProxy is not ready (reason: {self._ready_reason}).")
        return entity_id in self.states

    async def on_state_change(self, event: RawStateChangeEvent) -> None:
        """Handle state_changed events to update the cache.

        This handler runs with priority=100 to ensure the cache is updated before
        app handlers process the event.
        """
        # note: we are not listening to entity_registry_updated because state_changed seems to capture
        # both the new state when renamed and the removal when deleted.

        entity_id = event.payload.data.entity_id
        old_state_dict = event.payload.data.old_state
        new_state_dict = event.payload.data.new_state

        self.logger.debug("State changed event for %s", entity_id)
        async with self.lock:
            if new_state_dict is None:
                if entity_id in self.states:
                    self.states.pop(entity_id)
                    self.logger.debug("Removed state for %s", entity_id)
                    return
                self.logger.debug("Ignoring removal of unknown entity %s", entity_id)
                return

            # walrus operator to help type checker know we already validated these aren't None
            if (
                entity_id in self.states
                and (curr_last_updated := self.states[entity_id].get("last_updated")) is not None
                and (new_last_updated := new_state_dict.get("last_updated")) is not None
            ):
                if new_last_updated <= curr_last_updated:
                    self.logger.debug(
                        "Ignoring out-of-date state update for %s (new last_updated: %s, current: %s)",
                        entity_id,
                        new_last_updated,
                        curr_last_updated,
                    )
                    return

            self.states[entity_id] = new_state_dict
            if old_state_dict is None:
                self.logger.debug("Added state for %s", entity_id)
            else:
                self.logger.debug("Updated state for %s", entity_id)

    async def on_disconnect(self) -> None:
        """Handle WebSocket disconnection.

        Retains the state cache so consumers can read stale data while disconnected
        instead of hitting ResourceNotReadyError. Callers can check ``is_ready()`` to
        distinguish fresh from stale data. The cache is replaced with fresh data on
        reconnect via ``load_cache()``.

        This method is idempotent: if StateProxy is already not-ready, subsequent
        calls are no-ops. This prevents redundant work during early-drop retry loops.
        """
        if not self.is_ready():
            return

        self.logger.info("WebSocket disconnected, retaining stale state cache (%d entities)", len(self.states))

        # cancel the state change subscription (WS events won't arrive while disconnected)
        if self.state_change_sub is not None:
            self.state_change_sub.cancel()
            self.state_change_sub = None

        # poll job stays alive so the cache can self-heal between
        # disconnect and the next on_reconnect call

        self.mark_not_ready(reason="Disconnected")
        await self._emit_readiness_event()

    async def on_reconnect(self) -> None:
        """Handle Home Assistant start events to trigger state resync.

        This runs after Home Assistant restart to rebuild the state cache.
        Serialized via _reconnect_lock to prevent duplicate subscriptions
        when WebSocket flaps rapidly (#993).
        """
        async with self._reconnect_lock:
            self.logger.info("WebSocket reconnected, performing state resync")

            load_cache_succeeded = False
            try:
                await self.load_cache()
                load_cache_succeeded = True
            except Exception as e:
                self.logger.exception("Failed to resync states after HA restart: %s", e)

            subscribe_succeeded = False
            try:
                await self.subscribe_to_events()
                subscribe_succeeded = True
            except Exception as e:
                self.logger.exception("Failed to subscribe to events after reconnect: %s", e)

            if load_cache_succeeded and subscribe_succeeded:
                self.mark_ready(reason="Connected")
            elif not load_cache_succeeded:
                self.mark_not_ready(reason="Failed to resync states after HA restart")
            else:
                self.mark_not_ready(reason="Failed to subscribe to events after reconnect")

            await self._emit_readiness_event()

    async def load_cache(self) -> None:
        """Load the state cache from Home Assistant.

        This is called during initialization and reconnection to populate
        the state cache, as well as during periodic polling to keep the cache up to date.
        """
        states = await self.hassette.api.get_states_raw()
        state_dict = {s["entity_id"]: s for s in states if s["entity_id"]}
        async with self.lock:
            self.states = state_dict

        self.logger.debug("State cache loaded, tracking %d entities", len(self.states))
