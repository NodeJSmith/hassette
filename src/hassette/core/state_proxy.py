import typing
from logging import getLogger

from fair_async_rlock import FairAsyncRLock

from hassette.bus import Bus
from hassette.events import RawStateChangeEvent
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.base import Resource
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Subscription
    from hassette.events import HassStateDict

LOGGER = getLogger(__name__)


class StateProxy(Resource):
    states: dict[str, "HassStateDict"]
    lock: FairAsyncRLock
    bus: Bus
    state_change_sub: "Subscription | None"

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        """Create a new StateProxy instance.

        Args:
            hassette: The Hassette instance.
            parent: The parent resource (typically the Hassette core).

        Returns:
            A new StateProxy instance.
        """
        inst = cls(hassette=hassette, parent=parent)
        inst.states = {}
        inst.lock = FairAsyncRLock()
        inst.bus = inst.add_child(Bus, priority=100)
        inst.state_change_sub = None
        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.state_proxy_log_level

    async def on_initialize(self) -> None:
        """Initialize the state proxy.

        Waits for WebSocket and API services to be ready, then performs initial state sync
        and subscribes to state change and registry events with high priority.
        """
        # Wait for dependencies
        self.logger.debug("Waiting for dependencies to be ready")
        await self.hassette.wait_for_ready(
            [self.hassette._websocket_service, self.hassette._api_service, self.hassette._bus_service]
        )

        self.logger.debug("Dependencies ready, performing initial state sync")

        self.subscribe_to_events()

        self.bus.on_websocket_connected(handler=self.on_reconnect)
        self.bus.on_websocket_disconnected(handler=self.on_disconnect)
        # Perform initial state sync
        try:
            await self._load_cache()

            self.mark_ready(reason="Initial state sync complete")

        except Exception as e:
            self.logger.exception("Failed to perform initial state sync: %s", e)
            raise

    def subscribe_to_events(self) -> None:
        self.state_change_sub = self.bus.on(topic=Topic.HASS_EVENT_STATE_CHANGED, handler=self._on_state_change)

    async def on_shutdown(self) -> None:
        """Shutdown the state proxy and clean up resources."""
        self.logger.debug("Shutting down state proxy")
        self.mark_not_ready(reason="Shutting down")
        self.bus.remove_all_listeners()
        async with self.lock:
            self.states.clear()

    def get_state(self, entity_id: str) -> "HassStateDict | None":
        """Get the current state for an entity.

        Args:
            entity_id: The entity ID to look up (e.g., "light.kitchen").

        Returns:
            The typed state object if found, None otherwise.

        Raises:
            ResourceNotReadyError: If the proxy hasn't completed initial sync.
        """
        if not self.is_ready():
            raise ResourceNotReadyError(
                f"StateProxy is not ready (reason: {self._ready_reason}). "
                "Call await state_proxy.wait_until_ready() before accessing states."
            )

        # Lock-free read is safe because dict assignment is atomic in CPython
        # and we replace whole objects rather than mutating them
        return self.states.get(entity_id)

    def get_domain_states(self, domain: str) -> dict[str, "HassStateDict"]:
        """Get all states for a specific domain.

        Args:
            domain: The domain to filter by (e.g., "light").

        Returns:
            A dictionary of entity_id to state for the specified domain.

        Raises:
            ResourceNotReadyError: If the proxy hasn't completed initial sync.
        """
        if not self.is_ready():
            raise ResourceNotReadyError(
                f"StateProxy is not ready (reason: {self._ready_reason}). "
                "Call await state_proxy.wait_until_ready() before accessing states."
            )

        # Lock-free read is safe because dict assignment is atomic in CPython
        # and we replace whole objects rather than mutating them
        return {eid: state for eid, state in self.states.items() if state["entity_id"].split(".")[0] == domain}

    async def _on_state_change(self, event: RawStateChangeEvent) -> None:
        """Handle state_changed events to update the cache.

        This handler runs with priority=100 to ensure the cache is updated before
        app handlers process the event.

        Args:
            entity_id: The entity ID that changed.
            new_state: The new state object, or None if the entity was removed.
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
        """Handle Home Assistant stop events.

        Clears the cache when Home Assistant stops. The cache will be rebuilt when
        Home Assistant starts and we receive state_changed events again, or when
        we detect a reconnection.
        """
        self.logger.info("WebSocket disconnected, clearing state cache")
        async with self.lock:
            self.states.clear()
        if self.state_change_sub is not None:
            self.state_change_sub.cancel()
            self.state_change_sub = None
        self.mark_not_ready(reason="Disconnected")

    async def on_reconnect(self) -> None:
        """Handle Home Assistant start events to trigger state resync.

        This runs after Home Assistant restart to rebuild the state cache.
        """
        self.logger.info("WebSocket reconnected, performing state resync")

        try:
            await self._load_cache()

            self.subscribe_to_events()
            self.mark_ready(reason="Connected")

        except Exception as e:
            self.logger.exception("Failed to resync states after HA restart: %s", e)

    async def _load_cache(self) -> None:
        """Load the state cache from Home Assistant.

        This is called during initialization and reconnection to populate
        the state cache.
        """
        states = await self.hassette.api.get_states_raw()
        async with self.lock:
            self.states.clear()
            state_dict = {s["entity_id"]: s for s in states if s["entity_id"]}
            self.states.update(state_dict)

        self.logger.info("State cache loaded, tracking %d entities", len(self.states))
