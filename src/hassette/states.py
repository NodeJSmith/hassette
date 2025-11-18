import typing
from typing import Any, Generic, TypeVar

from hassette.core.state_proxy import StateProxyResource
from hassette.exceptions import EntityNotFoundError
from hassette.models import states
from hassette.models.states import BaseState
from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.models.states import StateT

StateT = TypeVar("StateT", bound=BaseState)


class _TypedStateGetter(Generic[StateT]):
    """Callable class to get a state typed as a specific model.

    Example:
    ```python
    my_light = self.states.get[states.LightState]("light.bedroom")
    ```
    """

    def __init__(self, proxy: "StateProxyResource", model: type[StateT]):
        self._proxy = proxy
        self._model = model

    def __call__(self, entity_id: str) -> StateT:
        """Get a specific entity state by ID.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom").

        Raises:
            EntityNotFoundError

        """
        value = self._proxy.get_state(entity_id)
        if not value:
            raise EntityNotFoundError(f"State for entity_id '{entity_id}' not found")
        return self._model.model_validate(value)

    def get(self, entity_id: str) -> StateT | None:
        """Get a specific entity state by ID, returning None if not found.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom").

        Returns:
            The typed state if found, None otherwise.
        """
        raw = self._proxy.get_state(entity_id)
        if raw is None:
            return None
        return self._model.model_validate(raw)


class _StateGetter:
    def __init__(self, proxy: "StateProxyResource"):
        self._proxy = proxy

    def __getitem__(self, model: type[StateT]) -> _TypedStateGetter[StateT]:
        return _TypedStateGetter(self._proxy, model)


class DomainStates(Generic[StateT]):
    """Generic container for domain-specific state iteration."""

    def __init__(self, states_dict: dict[str, BaseState], domain: str) -> None:
        self._states = states_dict
        self._domain = domain

    def __iter__(self) -> typing.Generator[tuple[str, StateT], Any]:
        """Iterate over all states in this domain."""
        for entity_id, state in self._states.items():
            if state.domain == self._domain:
                yield entity_id, typing.cast("StateT", state)

    def __len__(self) -> int:
        """Return the number of entities in this domain."""
        return sum(1 for _ in self)

    def get(self, entity_id: str) -> StateT | None:
        """Get a specific entity state by ID.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom").

        Returns:
            The typed state if found and matches domain, None otherwise.
        """
        state = self._states.get(entity_id)
        if state and state.domain == self._domain:
            return typing.cast("StateT", state)
        return None


class States(Resource):
    """Resource for managing Home Assistant states.

    Provides typed access to entity states by domain through dynamic properties.

    Examples:
        >>> # Iterate over all lights
        >>> for entity_id, light_state in self.states.lights:
        ...     print(f"{entity_id}: {light_state.state}")
        ...
        >>> # Get specific entity
        >>> bedroom_light = self.states.lights.get("light.bedroom")
        >>> if bedroom_light and bedroom_light.attributes.brightness:
        ...     print(f"Brightness: {bedroom_light.attributes.brightness}")
        ...
        >>> # Check count
        >>> print(f"Total lights: {len(self.states.lights)}")
    """

    @property
    def state_proxy(self) -> StateProxyResource:
        """Access the underlying StateProxyResource instance."""
        return self.hassette._state_proxy_resource

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        """Create a new States resource instance.

        Args:
            hassette: The Hassette instance.
            parent: The parent resource (typically the Hassette core).

        Returns:
            A new States resource instance.
        """
        inst = cls(hassette=hassette, parent=parent)

        return inst

    @property
    def lights(self) -> DomainStates[states.LightState]:
        """Access all light entity states with full typing."""
        return DomainStates[states.LightState](self.state_proxy.states, "light")

    @property
    def sensors(self) -> DomainStates[states.SensorState]:
        """Access all sensor entity states with full typing."""
        return DomainStates[states.SensorState](self.state_proxy.states, "sensor")

    @property
    def switches(self) -> DomainStates[states.SwitchState]:
        """Access all switch entity states with full typing."""
        return DomainStates[states.SwitchState](self.state_proxy.states, "switch")

    @property
    def covers(self) -> DomainStates[states.CoverState]:
        """Access all cover entity states with full typing."""
        return DomainStates[states.CoverState](self.state_proxy.states, "cover")

    @property
    def binary_sensors(self) -> DomainStates[states.BinarySensorState]:
        """Access all binary sensor entity states with full typing."""
        return DomainStates[states.BinarySensorState](self.state_proxy.states, "binary_sensor")

    @property
    def climate(self) -> DomainStates[states.ClimateState]:
        """Access all climate entity states with full typing."""
        return DomainStates[states.ClimateState](self.state_proxy.states, "climate")

    @property
    def media_players(self) -> DomainStates[states.MediaPlayerState]:
        """Access all media player entity states with full typing."""
        return DomainStates[states.MediaPlayerState](self.state_proxy.states, "media_player")

    @property
    def device_trackers(self) -> DomainStates[states.DeviceTrackerState]:
        """Access all device tracker entity states with full typing."""
        return DomainStates[states.DeviceTrackerState](self.state_proxy.states, "device_tracker")

    @property
    def persons(self) -> DomainStates[states.PersonState]:
        """Access all person entity states with full typing."""
        return DomainStates[states.PersonState](self.state_proxy.states, "person")

    @property
    def zones(self) -> DomainStates[states.ZoneState]:
        """Access all zone entity states with full typing."""
        return DomainStates[states.ZoneState](self.state_proxy.states, "zone")

    @property
    def all(self) -> dict[str, BaseState]:
        """Access all entity states as a dictionary.

        Returns:
            Dictionary mapping entity_id to BaseState (or subclass).
        """
        return self.state_proxy.states.copy()

    def get_states(self, model: type[StateT]) -> DomainStates[StateT]:
        """Get all states for a specific domain model.

        Used for any domain not covered by a dedicated property.

        Args:
            model: The state model class representing the domain.

        Returns:
            DomainStates container for the specified domain.
        """
        return DomainStates[StateT](self.state_proxy.states, model.get_domain())

    @property
    def get(self) -> _StateGetter:
        """Get a state recognized as a specific type.

        Example:
        ```python

        my_light = self.states.get[states.LightState]("light.bedroom")
        ```

        Returns:
            A callable that takes a state model and returns a typed state getter.

        """
        return _StateGetter(self.state_proxy)
