"""Handles returned by ``self.integration.add_button``, ``add_switch`` and ``add_sensor``."""

import typing
from collections.abc import Mapping
from typing import Any

from whenever import Date, Instant

from .declarations import Declaration, EntityState

if typing.TYPE_CHECKING:
    from hassette.bus import Subscription

    from .integration import Integration


class IntegrationEntityHandle:
    """Shared parts of the three handle types: the declaration and the owning ``Integration``.

    A button or switch handle also holds the listener it registered, as ``subscription``.
    """

    declaration: Declaration
    """What was declared."""

    def __init__(self, integration: "Integration", declaration: Declaration) -> None:
        self._integration = integration
        self.declaration = declaration

    @property
    def key(self) -> str:
        """The entity's key, unique within its app instance."""
        return self.declaration.key

    @property
    def name(self) -> str:
        """The entity's display name in Home Assistant."""
        return self.declaration.name

    def __repr__(self) -> str:
        return f"{type(self).__name__}(key={self.key!r}, instance={self._integration.instance_name!r})"


class IntegrationButton(IntegrationEntityHandle):
    """A button an app instance declared. Pressing it in Home Assistant runs its ``on_press`` handler."""

    subscription: "Subscription"
    """The bus listener that runs ``on_press``; it shows in the app's listeners view."""

    def __init__(self, integration: "Integration", declaration: Declaration, subscription: "Subscription") -> None:
        super().__init__(integration, declaration)
        self.subscription = subscription


class IntegrationStatefulHandle(IntegrationEntityHandle):
    """Shared parts of a switch and a sensor: a state that persists across restarts and that ``set()`` replaces."""

    @property
    def state(self) -> EntityState:
        """The current value and attributes: as last set, restored from the last run, or the default.

        A copy: changing its attributes changes nothing until it is passed to ``set()``.

        Raises:
            IntegrationHandleClosedError: The instance has stopped, or its declarations failed to commit.
        """
        return self._integration.read_state(self.declaration)

    @property
    def attributes(self) -> Mapping[str, Any]:
        """The current attributes, as a copy (see ``state``)."""
        return self.state.attributes


class IntegrationSwitch(IntegrationStatefulHandle):
    """A switch an app instance declared.

    Toggling it in Home Assistant runs its ``on_toggle`` handler with the commanded value (``D.SwitchCommand``).
    Its state changes only when the app calls ``set()``, so a handler that doesn't call it leaves the switch as it
    was.
    """

    subscription: "Subscription"
    """The bus listener that runs ``on_toggle``; it shows in the app's listeners view."""

    def __init__(self, integration: "Integration", declaration: Declaration, subscription: "Subscription") -> None:
        super().__init__(integration, declaration)
        self.subscription = subscription

    @property
    def is_on(self) -> bool:
        """Whether the switch is on."""
        return bool(self.state.value)

    async def set(self, on: bool, attributes: Mapping[str, Any] | None = None) -> None:
        """Set the switch on or off, replacing its attributes.

        During initialization the value is held and written when the instance's declarations are committed. After
        that it is written before it is published; setting the state it already has writes nothing.

        Args:
            on: ``True`` for on.
            attributes: The new attributes, a JSON-serializable mapping. ``None`` clears them.

        Raises:
            ValueError: ``on`` isn't a bool, or ``attributes`` isn't JSON-serializable.
            IntegrationHandleClosedError: The instance has stopped, or its declarations failed to commit.
        """
        await self._integration.set_state(self.declaration, on, attributes)


class IntegrationSensor(IntegrationStatefulHandle):
    """A sensor an app instance declared. The app sets its value; Home Assistant shows it."""

    @property
    def value(self) -> bool | int | float | str | Instant | Date | None:
        """The current value; ``None`` is unknown."""
        return self.state.value

    async def set(self, value: object, attributes: Mapping[str, Any] | None = None) -> None:
        """Set the sensor's value, replacing its attributes.

        The value must suit the sensor's declaration, as Home Assistant requires: a number for a numeric sensor,
        one of its options for an enum sensor, an aware ``whenever`` time for a timestamp sensor (stored as an
        ``Instant``), a ``whenever.Date`` for a date sensor, and a string otherwise. ``None`` makes it unknown.

        During initialization the value is held and written when the instance's declarations are committed. After
        that it is written before it is published; setting the state it already has writes nothing.

        Args:
            value: The new value.
            attributes: The new attributes, a JSON-serializable mapping. ``None`` clears them.

        Raises:
            ValueError: The declaration rejects ``value``, or ``attributes`` isn't JSON-serializable.
            IntegrationHandleClosedError: The instance has stopped, or its declarations failed to commit.
        """
        await self._integration.set_state(self.declaration, value, attributes)
