"""State proxy resource for maintaining an in-memory cache of Home Assistant entity states.

The StateProxy provides fast, synchronous-like access to entity states by maintaining a local cache
updated via WebSocket events. This eliminates the need for repeated API calls while ensuring states
stay current through event-driven updates.

Key Features:
- Stores raw state dictionaries for all entities
- Updates in real-time via state_changed events
- Type conversion on read (zero-copy raw dict access also available)
- Handles entity lifecycle via entity_registry_updated events
- Priority-based event handling ensures consistent state before app handlers run
- Automatic cache invalidation on Home Assistant restart

Usage:
    ```python
    from hassette import App, states

    class MyApp(App):
        async def on_initialize(self):
            # Wait for state proxy to be ready
            await self.state_proxy.wait_until_ready()

            # Get typed state
            light = self.state_proxy.get_state("light.kitchen", states.LightState)
            if light:
                print(f"Kitchen light is {light.value}, brightness: {light.attributes.brightness}")

            # Get all states
            all_states = self.state_proxy.get_all_states()
            print(f"Tracking {len(all_states)} entities")

            # Subscribe to state changes - your handler will see consistent proxy state
            self.bus.on_state_change("light.kitchen", handler=self.on_light_change)

        async def on_light_change(self, entity_id: str):
            # Proxy is already updated by the time this runs
            current = self.state_proxy.get_state(entity_id, states.LightState)
            print(f"Light changed, now: {current.value if current else 'unknown'}")
    ```
"""

import typing
from logging import getLogger
from typing import Any, cast

from fair_async_rlock import FairAsyncRLock

import hassette.bus.accessors as A
from hassette import dependencies as D
from hassette.bus import Bus
from hassette.exceptions import ResourceNotReadyError
from hassette.models.states import StateT, StateUnion
from hassette.resources.base import Resource
from hassette.types import topics

if typing.TYPE_CHECKING:
    from hassette import Hassette


LOGGER = getLogger(__name__)


D_Action = typing.Annotated[str, A.get_path("payload.data.action")]
D_Changes = typing.Annotated[dict[str, Any] | None, A.get_path("payload.data.changes")]
D_Old_entity_id = typing.Annotated[str | None, A.get_path("payload.data.old_entity_id")]


class StateProxyResource(Resource):
    """State proxy that maintains a cache of all Home Assistant entity states.

    This resource subscribes to state_changed events with high priority (100) to ensure
    the cache is updated before app handlers process events. States are stored as raw
    dictionaries and converted to typed models on read.

    The proxy automatically handles:
    - Initial state sync from Home Assistant
    - Real-time updates via WebSocket events
    - Entity renames/removals via entity_registry_updated events
    - Cache invalidation on Home Assistant restart

    States are stored as raw dicts to minimize memory overhead and defer type conversion
    until read time. This allows zero-copy dict access via get_state_raw() for apps that
    need maximum performance.
    """

    states: dict[str, StateUnion]
    """Internal state cache mapping entity_id to raw state dict (HassStateDict)."""

    lock: FairAsyncRLock
    """Lock for thread-safe state cache access."""

    bus: "Bus"
    """Event bus for subscribing to state changes."""

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
        self.bus.on(topic=topics.HASS_EVENT_STATE_CHANGED, handler=self._on_state_changed)

        self.bus.on(topic=topics.HASS_EVENT_ENTITY_REGISTRY_UPDATED, handler=self._on_entity_registry_updated)

        self.bus.on_homeassistant_stop(handler=self.on_homeassistant_stop)

        # Perform initial state sync
        try:
            raw_states = await self.hassette.api.get_states()
            async with self.lock:
                for state_dict in raw_states:
                    entity_id = state_dict.entity_id
                    if entity_id:
                        self.states[entity_id] = state_dict
                    else:
                        self.logger.warning("State dict missing entity_id: %s", state_dict)

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

    async def wait_until_ready(self) -> None:
        """Wait until the state proxy has completed initial sync and is ready for use.

        This is a convenience method that apps can call to ensure the proxy is ready
        before attempting to read states.

        Raises:
            asyncio.TimeoutError: If waiting times out (controlled by caller).
        """
        await self.ready_event.wait()

    def get_state(self, entity_id: str, state_type: type[StateT] | None = None) -> StateT | None:
        """Get the current state for an entity with optional type conversion.

        States are stored as raw dictionaries and converted to typed models on read.
        This method performs a deep copy before conversion to prevent mutation of the
        cached state.

        Args:
            entity_id: The entity ID to look up (e.g., "light.kitchen").
            state_type: Optional state type to convert to. If None, returns BaseState.

        Returns:
            The typed state object if found, None otherwise.

        Raises:
            ResourceNotReadyError: If the proxy hasn't completed initial sync.

        Examples:
            ```python
            # Get generic state
            state = self.state_proxy.get_state("sensor.temperature")

            # Get typed state
            from hassette import states
            light = self.state_proxy.get_state("light.kitchen", states.LightState)
            if light and light.attributes.brightness:
                print(f"Brightness: {light.attributes.brightness}")
            ```
        """
        if not self.is_ready():
            raise ResourceNotReadyError(
                f"StateProxy is not ready (status: {self.status}). "
                "Call await state_proxy.wait_until_ready() before accessing states."
            )

        # Lock-free read is safe because dict assignment is atomic in CPython
        # and we replace whole objects rather than mutating them
        return cast("StateT", self.states.get(entity_id))

    @property
    def entity_count(self) -> int:
        """Return the number of entities currently cached."""
        return len(self.states)

    async def _on_state_changed(self, entity_id: D.EntityId, new_state: D.StateNew[StateUnion]) -> None:
        """Handle state_changed events to update the cache.

        This handler runs with priority=100 to ensure the cache is updated before
        app handlers process the event.

        Args:
            entity_id: The entity ID that changed.
            new_state: The new state dict, or None if entity was removed.
        """
        self.logger.info("State changed event for %s", entity_id)
        async with self.lock:
            if new_state is None:
                # Entity state removed
                if entity_id in self.states:
                    self.states.pop(entity_id)
                    self.logger.debug("Removed state for %s", entity_id)
            else:
                # Entity state added or updated
                self.states[entity_id] = new_state
                self.logger.debug("Updated state for %s", entity_id)

    async def _on_entity_registry_updated(
        self,
        action: D_Action,
        entity_id: D.EntityId,
        changes: D_Changes = None,
        old_entity_id: D_Old_entity_id = None,
    ) -> None:
        """Handle entity_registry_updated events for entity lifecycle management.

        Handles entity renames (action=update) and removals (action=remove).
        Entity creation (action=create) is handled implicitly via state_changed events.

        Args:
            action: The registry action ("create", "update", or "remove").
            entity_id: The entity ID.
            changes: The changes made to the entity (for updates).
            old_entity_id: The previous entity ID (for renames).
        """
        self.logger.info("Entity registry updated event for %s: %s", entity_id, action)
        async with self.lock:
            if action == "remove":
                if entity_id in self.states:
                    self.states.pop(entity_id)
                    self.logger.info("Removed entity from cache: %s", entity_id)
                return

            if action == "update":
                self.logger.info("Changes received for %s: %s", entity_id, changes)
                if old_entity_id and old_entity_id != entity_id:
                    # Entity was renamed
                    if old_entity_id in self.states:
                        state = self.states.pop(old_entity_id)
                        # Update entity_id in the state dict itself
                        state.entity_id = entity_id
                        self.states[entity_id] = state
                        self.logger.info("Renamed entity in cache: %s -> %s", old_entity_id, entity_id)
                return

            if action == "create":
                self.logger.debug("Entity created: %s (will be synced via state_changed)", entity_id)

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
        self.bus.on_homeassistant_start(handler=self._on_homeassistant_start, once=True)

    async def _on_homeassistant_start(self) -> None:
        """Handle Home Assistant start events to trigger state resync.

        This runs after Home Assistant restart to rebuild the state cache.
        """
        self.logger.info("Home Assistant restarted, performing state resync")

        try:
            raw_states = await self.hassette.api.get_states()
            async with self.lock:
                self.states.clear()
                for state_dict in raw_states:
                    entity_id = state_dict.entity_id
                    if entity_id:
                        self.states[entity_id] = state_dict

            self.logger.info("State resync complete, tracking %d entities", len(self.states))
            self.mark_ready(reason="State resync after HA restart complete")

        except Exception as e:
            self.logger.exception("Failed to resync states after HA restart: %s", e)
