import typing
from collections.abc import Iterator
from logging import getLogger
from typing import Any, Generic, NamedTuple

from frozendict import deepfreeze, frozendict

from hassette.core.state_proxy import StateProxy
from hassette.core.state_registry import STATE_REGISTRY, StateKey
from hassette.exceptions import RegistryNotReadyError
from hassette.models.states import BaseState, StateT
from hassette.resources.base import Resource
from hassette.utils.hass_utils import make_entity_id

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict


LOGGER = getLogger(__name__)


class CacheValue(Generic[StateT], NamedTuple):
    context_id: str | None
    frozen_state: frozendict
    model: StateT


class DomainStates(Generic[StateT]):
    """DomainStates provides access to all states within a specific domain, with automatic type validation and caching.

    This classes accesses the StateProxy under the hood to provide access to the current states from HomeAssistant,
    without needing to make direct calls to the Home Assistant API.

    Accessed states are automatically validated against the provided model and cached for efficient repeated access.

    Examples:
    ```python
        # if you know the entity exists
        light_state = self.states.light["bedroom"]

        # to safely access an entity that may not exist
        light_state = self.states.light.get("bedroom")
        if light_state is not None:
            print(light_state.value)

        # or you can check existence ahead of time
        if "bedroom" in self.states.light:
            light_state = self.states.light["bedroom"]
            print(light_state.value)

        # if you are working with a state that isn't defined in Hassette
        self.states
    ```

    """

    def __init__(self, state_proxy: "StateProxy", model: type[StateT]) -> None:
        if not issubclass(model, BaseState):
            raise TypeError(f"Expected a subclass of BaseState, got {model!r}")

        self._state_proxy = state_proxy
        self._model = model
        self._domain = model.get_domain()
        self._cache: dict[str, CacheValue[StateT]] = {}

    def _validate_or_return_from_cache(self, entity_id: str, state: "HassStateDict") -> StateT:
        context_id: str | None = state.get("context", {}).get("id")

        cached = self._cache.get(entity_id)

        # first check if the context ID matches
        if cached is not None and context_id is not None and cached.context_id == context_id:
            return cached.model

        # if not then use deepfreeze and see if frozen states match
        frozen_state = deepfreeze(state)
        if cached is not None and cached.frozen_state == frozen_state:
            return cached.model

        validated = self._model.model_validate(state)
        self._cache[entity_id] = CacheValue(context_id, frozen_state, validated)
        return validated

    def get(self, entity_id: str) -> StateT | None:
        """Get a specific entity state by ID.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom") or just the entity name (e.g., "bedroom").

        Returns:
            The typed state if found and matches domain, None otherwise.

        Raises:
            ValueError: If the entity ID does not belong to this domain.
        """
        entity_id = make_entity_id(entity_id, self._domain)

        state = self._state_proxy.get_state(entity_id)
        if state is None:
            return None

        return self._validate_or_return_from_cache(entity_id, state)

    def items(self) -> Iterator[tuple[str, StateT]]:
        """Iterate (entity_id, typed state) pairs lazily."""
        return iter(self)

    def keys(self) -> list[str]:
        """Return a list of entity IDs for this domain."""
        return [entity_id for entity_id, _ in self]

    def iterkeys(self) -> Iterator[str]:
        """Returns an iterator over entity IDs for this domain."""
        for entity_id, _ in self:
            yield entity_id

    def values(self) -> list[StateT]:
        """Return a list of typed states for this domain.

        This returns an eagerly evaluated list of all typed states in this domain.

        Note:
            This method will iterate over all states in the domain and validate them,
            which may be expensive for large domains. Consider using the iterator
            returned by `__iter__` for lazy evaluation if performance is a concern.
        """
        return [value for _, value in self]

    def itervalues(self) -> Iterator[StateT]:
        """Returns an iterator over typed states for this domain."""
        for _, value in self:
            yield value

    def to_dict(self) -> dict[str, StateT]:
        """Return a dictionary of entity_id to typed state for this domain.

        This returns an eagerly evaluated dictionary of all typed states in this domain.

        Note:
            This method will iterate over all states in the domain and validate them,
            which may be expensive for large domains. Consider using the iterator
            returned by `__iter__` for lazy evaluation if performance is a concern.
        """
        return {entity_id: value for entity_id, value in self}

    def __iter__(self) -> typing.Generator[tuple[str, StateT], Any, None]:
        """Iterate over all states in this domain."""
        for entity_id, state in self._state_proxy.yield_domain_states(self._domain):
            try:
                yield entity_id, self._validate_or_return_from_cache(entity_id, state)
            except Exception as e:
                LOGGER.error(
                    "Error validating state for entity_id '%s' as type %s: %s", entity_id, self._model.__name__, e
                )
                continue

    def __len__(self) -> int:
        """Return the number of entities in this domain."""
        return self._state_proxy.num_domain_states(self._domain)

    def __contains__(self, entity_id: str) -> bool:
        """Check if a specific entity ID exists in this domain."""
        try:
            entity_id = make_entity_id(entity_id, self._domain)
            return entity_id in self._state_proxy
        except ValueError:
            return False

    def __getitem__(self, entity_id: str) -> StateT:
        """Get a specific entity state by ID, raising if not found.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom") or just the entity name (e.g., "bedroom").

        Raises:
            EntityNotFoundError: If the entity is not found.

        Returns:
            The typed state.
        """
        value = self.get(entity_id)
        if value is None:
            raise KeyError(f"State for entity_id '{entity_id}' not found in domain '{self._domain}'")
        return value

    def __repr__(self) -> str:
        """Return a string representation of the DomainStates container."""
        return f"DomainStates(domain='{self._domain}', count={len(self)})"

    def __bool__(self) -> bool:
        """Return True if there are any entities in this domain."""
        return len(self) > 0


class StateManager(Resource):
    """Resource for managing Home Assistant states.

    Provides typed access to entity states by domain through dynamic properties.

    Examples:
    ```python
        # Iterate over all lights
        for entity_id, light_state in self.states.lights:
            print(f"{entity_id}: {light_state.value}")

        # Get specific entity
        bedroom_light = self.states.lights.get("light.bedroom")
        if bedroom_light and bedroom_light.attributes.brightness:
            print(f"Brightness: {bedroom_light.attributes.brightness}")

        # Check count
        print(f"Total lights: {len(self.states.lights)}")
    ```
    """

    _domain_states_cache: dict[type[BaseState], DomainStates[BaseState]]

    async def after_initialize(self) -> None:
        self.mark_ready()

    @property
    def _state_proxy(self) -> StateProxy:
        """Access the underlying StateProxy instance."""
        return self.hassette._state_proxy

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
        inst._domain_states_cache = {}

        return inst

    def __getattr__(self, domain: str) -> "DomainStates[BaseState]":
        """Dynamically access domain states by property name.

        This method provides dynamic access to domain states at runtime while
        maintaining type safety through the companion .pyi stub file. For known
        domains (defined in the stub), IDEs will provide full type hints. For
        custom/unknown domains, use `get_states(CustomStateClass)` directly.

        Args:
            domain: The domain name (e.g., "light", "switch", "custom_domain").

        Returns:
            DomainStates container for the requested domain.

        Raises:
            AttributeError: If the attribute name matches a reserved name or
                if the domain is not registered in the state registry.

        Example:
            ```python
            # Known domain (typed via .pyi stub)
            for entity_id, light in self.states.light:
                print(light.attributes.brightness)

            # Custom domain (fallback to BaseState at runtime)
            custom_states = self.states.custom_domain
            for entity_id, state in custom_states:
                print(state.value)
            ```
        """
        # Avoid recursion for internal attributes
        if domain.startswith("_") or domain in ("hassette", "parent", "name"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{domain}'")

        try:
            state_class = self.hassette.state_registry.resolve(domain=domain)
        except RegistryNotReadyError:
            raise AttributeError(
                f"State registry not initialized. Cannot access domain '{domain}'. "
                "Ensure state modules are imported before accessing States properties."
            ) from None

        if state_class in self._domain_states_cache:
            return self._domain_states_cache[state_class]

        if state_class is None:
            raise ValueError(
                f"Domain '{domain}' is not registered in the state registry. Use `states[{{state_class}}]` "
                "if you have a custom state class for this domain."
            )

        # Domain is registered, use its specific class
        self._domain_states_cache[state_class] = self[state_class]
        return self._domain_states_cache[state_class]

    def __getitem__(self, model: type[StateT]) -> DomainStates[StateT]:
        """Access domain states using the indexing syntax. This is required if you need
        to access domain states for a state model class that is not known by the StateRegistry.

        Args:
            model: The state model class representing the domain.

        Returns:
            DomainStates container for the specified domain.

        Example:
            ```python
            my_state_instance = self.states[MyStateClass].get("custom_entity")
            ```
        """
        return DomainStates[StateT](self._state_proxy, model)

    def __contains__(self, model: type[StateT]) -> bool:
        """Check if model is registered in the state registry.

        Args:
            model: The state model class to check.

        Returns:
            True if the model is registered in the state registry, False otherwise.

        Example:
            ```python
            if MyStateClass in self.states:
                print("States for MyStateClass are available")
            ```
        """
        return model in STATE_REGISTRY

    def __iter__(self) -> Iterator[tuple[StateKey, DomainStates[Any]]]:
        """Iterate over all registered state classes with their keys.

        Returns:
            An iterator over tuples of (StateKey, DomainStates) for all registered state classes.
        """
        yield from self.items()

    def items(self) -> Iterator[tuple[StateKey, DomainStates[Any]]]:
        """Iterate over all registered state classes with their keys.

        Returns:
            An iterator over tuples of (StateKey, DomainStates) for all registered state classes.
        """
        for key, state_class in STATE_REGISTRY.items():
            yield key, self[state_class]

    def values(self) -> Iterator[DomainStates[Any]]:
        """Iterate over all registered state classes.

        Returns:
            An iterator over all registered DomainStates instances.
        """
        for state_class in STATE_REGISTRY.values():
            yield self[state_class]

    def keys(self) -> Iterator[StateKey]:
        """Iterate over all registered state keys.

        Returns:
            An iterator over all registered state keys.
        """
        return iter(STATE_REGISTRY.keys())
