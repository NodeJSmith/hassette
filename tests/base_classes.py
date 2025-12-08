"""Base test classes for Hassette tests.

Provides reusable base classes with common setup for different types of tests.
These classes reduce boilerplate and standardize test patterns across the suite.
"""

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hassette import Api, Hassette
    from hassette.bus import Bus
    from hassette.core.state_proxy import StateProxy
    from hassette.events import Event
    from hassette.states import States


class HassetteTestCase:
    """Base class for tests that need a full Hassette instance.

    Automatically sets up self.hassette, self.api, and self.bus from the fixture.
    Use this as a base when you need the complete Hassette runtime.

    Example:
        ```python
        class TestMyFeature(HassetteTestCase):
            async def test_something(self, hassette_with_bus):
                self.setup_hassette(hassette_with_bus)
                # self.hassette, self.api, self.bus are now available
                assert self.api is not None
        ```
    """

    hassette: "Hassette"
    api: "Api"
    bus: "Bus"

    def setup_hassette(self, hassette: "Hassette") -> None:
        """Set up Hassette instance and extract common resources.

        Args:
            hassette: The Hassette instance from fixture
        """
        self.hassette = hassette
        self.api = hassette.api  # type: ignore[assignment]
        self.bus = hassette._bus  # type: ignore[assignment]


class StateProxyTestCase(HassetteTestCase):
    """Base class for tests that need StateProxy.

    Extends HassetteTestCase with StateProxy access and helper methods for
    sending state change events.

    Example:
        ```python
        class TestStateProxyFeature(StateProxyTestCase):
            async def test_state_update(self, hassette_with_state_proxy):
                self.setup_hassette(hassette_with_state_proxy)
                # self.proxy is now available
                await self.send_state_event("light.kitchen", None, {"state": "on"})
                assert "light.kitchen" in self.proxy.states
        ```
    """

    proxy: "StateProxy"

    def setup_hassette(self, hassette: "Hassette") -> None:
        """Set up Hassette instance and extract StateProxy.

        Args:
            hassette: The Hassette instance from fixture
        """
        super().setup_hassette(hassette)
        self.proxy = hassette._state_proxy  # type: ignore[assignment]

    async def send_state_event(
        self,
        entity_id: str,
        old_state_dict: dict | None,
        new_state_dict: dict | None,
    ) -> None:
        """Helper to send a state change event.

        Args:
            entity_id: Entity ID for the state change
            old_state_dict: Old state dictionary (or None)
            new_state_dict: New state dictionary (or None)
        """
        from hassette.test_utils.helpers import make_full_state_change_event
        from hassette.types import topics

        event = make_full_state_change_event(entity_id, old_state_dict, new_state_dict)
        await self.hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        # Give time for event processing
        await asyncio.sleep(0.1)


class StatesTestCase(StateProxyTestCase):
    """Base class for tests that need States resource.

    Extends StateProxyTestCase with States instance creation and access.

    Example:
        ```python
        class TestStatesFeature(StatesTestCase):
            async def test_domain_accessor(self, hassette_with_state_proxy):
                self.setup_hassette(hassette_with_state_proxy)
                # self.states_instance is now available
                lights = self.states_instance.light
                assert isinstance(lights, dict)
        ```
    """

    states_instance: "States"

    def setup_hassette(self, hassette: "Hassette") -> None:
        """Set up Hassette instance and create States instance.

        Args:
            hassette: The Hassette instance from fixture
        """
        super().setup_hassette(hassette)
        from hassette.states import States

        self.states_instance = States.create(hassette, hassette)


class BusTestCase(HassetteTestCase):
    """Base class for tests that need Bus functionality.

    Extends HassetteTestCase with helper methods for sending events.

    Example:
        ```python
        class TestBusFeature(BusTestCase):
            async def test_event_routing(self, hassette_with_bus):
                self.setup_hassette(hassette_with_bus)
                await self.send_event("custom.topic", my_event)
                # Event has been sent to bus
        ```
    """

    async def send_event(self, topic: str, event: "Event") -> None:
        """Helper to send an event to the bus.

        Args:
            topic: Event topic
            event: Event to send
        """
        await self.hassette.send_event(topic, event)
        # Give time for event processing
        await asyncio.sleep(0.05)
