import typing
from logging import getLogger

from fair_async_rlock import FairAsyncRLock

from hassette import dependencies as D
from hassette.bus import Bus
from hassette.exceptions import ResourceNotReadyError
from hassette.models.states import StateUnion
from hassette.resources.base import Resource
from hassette.types import topics

if typing.TYPE_CHECKING:
    from hassette import Hassette


LOGGER = getLogger(__name__)


class StateProxyResource(Resource):
    states: dict[str, StateUnion]
    lock: FairAsyncRLock
    bus: Bus

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        """Create a new StateProxyResource instance.

        Args:
            hassette: The Hassette instance.
            parent: The parent resource (typically the Hassette core).

        Returns:
            A new StateProxyResource instance.
        """
        inst = cls(hassette=hassette, parent=parent)
        inst.states = {}
        inst.lock = FairAsyncRLock()
        inst.bus = inst.add_child(Bus, priority=100)
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

        # Subscribe to events with high priority before syncing to avoid race conditions
        # Priority 100 ensures state proxy updates before app handlers (priority 0)
        self.bus.on(topic=topics.HASS_EVENT_STATE_CHANGED, handler=self.on_state_changed)

        self.bus.on_homeassistant_stop(handler=self.on_homeassistant_stop)

        # Perform initial state sync
        try:
            states = await self.hassette.api.get_states()
            async with self.lock:
                self.states.clear()
                state_dict = {s.entity_id: s for s in states if s.entity_id}
                self.states.update(state_dict)

            self.logger.info("Initial state sync complete, tracking %d entities", len(self.states))
            self.mark_ready(reason="Initial state sync complete")

        except Exception as e:
            self.logger.exception("Failed to perform initial state sync: %s", e)
            raise

    async def on_shutdown(self) -> None:
        """Shutdown the state proxy and clean up resources."""
        self.logger.debug("Shutting down state proxy")
        self.mark_not_ready(reason="Shutting down")
        self.bus.remove_all_listeners()
        async with self.lock:
            self.states.clear()

    def get_state(self, entity_id: str) -> StateUnion | None:
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
                f"StateProxy is not ready (status: {self.status}). "
                "Call await state_proxy.wait_until_ready() before accessing states."
            )

        # Lock-free read is safe because dict assignment is atomic in CPython
        # and we replace whole objects rather than mutating them
        return self.states.get(entity_id)

    async def on_state_changed(
        self, entity_id: D.EntityId, old_state: D.StateOld[StateUnion], new_state: D.StateNew[StateUnion]
    ) -> None:
        """Handle state_changed events to update the cache.

        This handler runs with priority=100 to ensure the cache is updated before
        app handlers process the event.

        Args:
            entity_id: The entity ID that changed.
            new_state: The new state object, or None if the entity was removed.
        """
        # note: we are not listening to entity_registry_updated because state_changed seems to capture
        # both the new state when renamed and the removal when deleted.

        self.logger.debug("State changed event for %s", entity_id)
        async with self.lock:
            if new_state is None and entity_id in self.states:
                self.states.pop(entity_id)
                self.logger.debug("Removed state for %s", entity_id)
                return

        self.states[entity_id] = new_state
        if old_state is None:
            self.logger.debug("Added state for %s", entity_id)
        else:
            self.logger.debug("Updated state for %s", entity_id)

    async def on_homeassistant_stop(self) -> None:
        """Handle Home Assistant stop events.

        Clears the cache when Home Assistant stops. The cache will be rebuilt when
        Home Assistant starts and we receive state_changed events again, or when
        we detect a reconnection.
        """
        self.logger.info("Home Assistant stopping, clearing state cache")
        async with self.lock:
            self.states.clear()
        self.mark_not_ready(reason="Home Assistant stopped")

        # Subscribe to HA start to trigger resync
        self.bus.on_homeassistant_start(handler=self.on_homeassistant_start, once=True)

    async def on_homeassistant_start(self) -> None:
        """Handle Home Assistant start events to trigger state resync.

        This runs after Home Assistant restart to rebuild the state cache.
        """
        self.logger.info("Home Assistant restarted, performing state resync")

        try:
            states = await self.hassette.api.get_states()
            async with self.lock:
                self.states.clear()
                state_dict = {s.entity_id: s for s in states if s.entity_id}
                self.states.update(state_dict)

            self.logger.info("State resync complete, tracking %d entities", len(self.states))
            self.mark_ready(reason="State resync after HA restart complete")

        except Exception as e:
            self.logger.exception("Failed to resync states after HA restart: %s", e)
