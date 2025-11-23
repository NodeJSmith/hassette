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
        if value is None:
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
    def _state_proxy(self) -> StateProxyResource:
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
    def automation(self) -> DomainStates[states.AutomationState]:
        """Access all automation entity states with full typing."""
        return self.get_states(states.AutomationState)

    @property
    def binary_sensor(self) -> DomainStates[states.BinarySensorState]:
        """Access all binary sensor entity states with full typing."""
        return self.get_states(states.BinarySensorState)

    @property
    def button(self) -> DomainStates[states.ButtonState]:
        """Access all button entity states with full typing."""
        return self.get_states(states.ButtonState)

    @property
    def calendar(self) -> DomainStates[states.CalendarState]:
        """Access all calendar entity states with full typing."""
        return self.get_states(states.CalendarState)

    @property
    def climate(self) -> DomainStates[states.ClimateState]:
        """Access all climate entity states with full typing."""
        return self.get_states(states.ClimateState)

    @property
    def conversation(self) -> DomainStates[states.ConversationState]:
        """Access all conversation entity states with full typing."""
        return self.get_states(states.ConversationState)

    @property
    def cover(self) -> DomainStates[states.CoverState]:
        """Access all cover entity states with full typing."""
        return self.get_states(states.CoverState)

    @property
    def device_tracker(self) -> DomainStates[states.DeviceTrackerState]:
        """Access all device tracker entity states with full typing."""
        return self.get_states(states.DeviceTrackerState)

    @property
    def event(self) -> DomainStates[states.EventState]:
        """Access all event entity states with full typing."""
        return self.get_states(states.EventState)

    @property
    def fan(self) -> DomainStates[states.FanState]:
        """Access all fan entity states with full typing."""
        return self.get_states(states.FanState)

    @property
    def humidifier(self) -> DomainStates[states.HumidifierState]:
        """Access all humidifier entity states with full typing."""
        return self.get_states(states.HumidifierState)

    @property
    def input_boolean(self) -> DomainStates[states.InputBooleanState]:
        """Access all input boolean entity states with full typing."""
        return self.get_states(states.InputBooleanState)

    @property
    def input_datetime(self) -> DomainStates[states.InputDatetimeState]:
        """Access all input datetime entity states with full typing."""
        return self.get_states(states.InputDatetimeState)

    @property
    def input_number(self) -> DomainStates[states.InputNumberState]:
        """Access all input number entity states with full typing."""
        return self.get_states(states.InputNumberState)

    @property
    def input_text(self) -> DomainStates[states.InputTextState]:
        """Access all input text entity states with full typing."""
        return self.get_states(states.InputTextState)

    @property
    def light(self) -> DomainStates[states.LightState]:
        """Access all light entity states with full typing."""
        return self.get_states(states.LightState)

    @property
    def media_player(self) -> DomainStates[states.MediaPlayerState]:
        """Access all media player entity states with full typing."""
        return self.get_states(states.MediaPlayerState)

    @property
    def number(self) -> DomainStates[states.NumberState]:
        """Access all number entity states with full typing."""
        return self.get_states(states.NumberState)

    @property
    def person(self) -> DomainStates[states.PersonState]:
        """Access all person entity states with full typing."""
        return self.get_states(states.PersonState)

    @property
    def remote(self) -> DomainStates[states.RemoteState]:
        """Access all remote entity states with full typing."""
        return self.get_states(states.RemoteState)

    @property
    def scene(self) -> DomainStates[states.SceneState]:
        """Access all scene entity states with full typing."""
        return self.get_states(states.SceneState)

    @property
    def script(self) -> DomainStates[states.ScriptState]:
        """Access all script entity states with full typing."""
        return self.get_states(states.ScriptState)

    @property
    def select(self) -> DomainStates[states.SelectState]:
        """Access all select entity states with full typing."""
        return self.get_states(states.SelectState)

    @property
    def sensor(self) -> DomainStates[states.SensorState]:
        """Access all sensor entity states with full typing."""
        return self.get_states(states.SensorState)

    @property
    def stt(self) -> DomainStates[states.SttState]:
        """Access all speech-to-text entity states with full typing."""
        return self.get_states(states.SttState)

    @property
    def sun(self) -> DomainStates[states.SunState]:
        """Access all sun entity states with full typing."""
        return self.get_states(states.SunState)

    @property
    def switch(self) -> DomainStates[states.SwitchState]:
        """Access all switch entity states with full typing."""
        return self.get_states(states.SwitchState)

    @property
    def timer(self) -> DomainStates[states.TimerState]:
        """Access all timer entity states with full typing."""
        return self.get_states(states.TimerState)

    @property
    def tts(self) -> DomainStates[states.TtsState]:
        """Access all text-to-speech entity states with full typing."""
        return self.get_states(states.TtsState)

    @property
    def update(self) -> DomainStates[states.UpdateState]:
        """Access all update entity states with full typing."""
        return self.get_states(states.UpdateState)

    @property
    def weather(self) -> DomainStates[states.WeatherState]:
        """Access all weather entity states with full typing."""
        return self.get_states(states.WeatherState)

    @property
    def zone(self) -> DomainStates[states.ZoneState]:
        """Access all zone entity states with full typing."""
        return self.get_states(states.ZoneState)

    @property
    def all(self) -> dict[str, BaseState]:
        """Access all entity states as a dictionary.

        Returns:
            Dictionary mapping entity_id to BaseState (or subclass).
        """
        return self._state_proxy.states.copy()

    def get_states(self, model: type[StateT]) -> DomainStates[StateT]:
        """Get all states for a specific domain model.

        Used for any domain not covered by a dedicated property.

        Args:
            model: The state model class representing the domain.

        Returns:
            DomainStates container for the specified domain.
        """
        return DomainStates[StateT](self._state_proxy.states, model.get_domain())

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
        return _StateGetter(self._state_proxy)
