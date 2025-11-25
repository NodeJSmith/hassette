import typing
from logging import getLogger
from typing import Any, Generic
from warnings import warn

from hassette.core.state_proxy import StateProxyResource
from hassette.exceptions import EntityNotFoundError, RegistryNotReadyError
from hassette.models.states import BaseState, StateT
from hassette.resources.base import Resource
from hassette.state_registry import get_registry

if typing.TYPE_CHECKING:
    from hassette import Hassette


LOGGER = getLogger(__name__)


def make_entity_id(entity_id: str, domain: str) -> str:
    """Ensure the entity_id has the correct domain prefix."""
    return entity_id if "." in entity_id else f"{domain}.{entity_id}"


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
        self._domain = model.get_domain()

    def __call__(self, entity_id: str) -> StateT:
        """Get a specific entity state by ID.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom") or just the entity name (e.g., "bedroom").

        Raises:
            EntityNotFoundError

        """
        value = self.get(entity_id)
        if value is None:
            raise EntityNotFoundError(f"State for entity_id '{entity_id}' not found")
        return value

    def get(self, entity_id: str) -> StateT | None:
        """Get a specific entity state by ID, returning None if not found.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom") or just the entity name (e.g., "bedroom").

        Returns:
            The typed state if found, None otherwise.
        """
        entity_id = make_entity_id(entity_id, self._domain)

        value = self._proxy.get_state(entity_id)
        if value is None:
            return None
        return self._model.model_validate(value.raw_data)


class _StateGetter:
    def __init__(self, proxy: "StateProxyResource"):
        self._proxy = proxy

    def __getitem__(self, model: type[StateT]) -> _TypedStateGetter[StateT]:
        return _TypedStateGetter(self._proxy, model)


class DomainStates(Generic[StateT]):
    """Generic container for domain-specific state iteration."""

    def __init__(self, states_dict: dict[str, BaseState], model: type[StateT]) -> None:
        self._states = states_dict
        self._model = model
        self._domain = model.get_domain()

    def __iter__(self) -> typing.Generator[tuple[str, StateT], Any]:
        """Iterate over all states in this domain."""
        for entity_id, state in self._states.items():
            try:
                yield entity_id, self._model.model_validate(state.raw_data)
            except Exception as e:
                LOGGER.error(
                    "Error validating state for entity_id '%s' as type %s: %s", entity_id, self._model.__name__, e
                )
                continue

    def __len__(self) -> int:
        """Return the number of entities in this domain."""
        return len(self._states)

    def get(self, entity_id: str) -> StateT | None:
        """Get a specific entity state by ID.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom") or just the entity name (e.g., "bedroom").

        Returns:
            The typed state if found and matches domain, None otherwise.
        """
        entity_id = make_entity_id(entity_id, self._domain)

        state = self._states.get(entity_id)
        if state is None:
            return None

        # If already the correct type (and not just BaseState), return it
        if isinstance(state, self._model) and type(state) is not BaseState:
            return state

        # Otherwise, try to convert
        return self._model.model_validate(state.raw_data)


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

    def __getattr__(self, name: str) -> "DomainStates[BaseState]":
        """Dynamically access domain states by property name.

        This method provides dynamic access to domain states at runtime while
        maintaining type safety through the companion .pyi stub file. For known
        domains (defined in the stub), IDEs will provide full type hints. For
        custom/unknown domains, use `get_states(CustomStateClass)` directly.

        Args:
            name: The domain name (e.g., "light", "switch", "custom_domain").

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
        if name.startswith("_") or name in ("hassette", "parent", "name"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        registry = get_registry()
        try:
            state_class = registry.get_class_for_domain(name)
        except RegistryNotReadyError:
            raise AttributeError(
                f"State registry not initialized. Cannot access domain '{name}'. "
                "Ensure state modules are imported before accessing States properties."
            ) from None

        if state_class is None:
            warn(
                f"Domain '{name}' not registered, returning DomainStates[BaseState]. "
                f"For better type support, create a custom state class that registers this domain.",
                stacklevel=2,
            )
            return DomainStates[BaseState](self._state_proxy.get_domain_states(name), BaseState)

        # Domain is registered, use its specific class
        return DomainStates[state_class](self._state_proxy.get_domain_states(name), state_class)

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
        return DomainStates[StateT](self._state_proxy.get_domain_states(model.get_domain()), model)

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
