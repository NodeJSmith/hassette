import typing
from logging import getLogger
from typing import Any, Generic
from warnings import warn

from hassette.core.state_proxy import StateProxy
from hassette.exceptions import EntityNotFoundError, RegistryNotReadyError
from hassette.models.states import BaseState, StateT
from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict


LOGGER = getLogger(__name__)


def make_entity_id(entity_id: str, domain: str) -> str:
    """Ensure the entity_id has the correct domain prefix.

    If the entity_id already contains a domain prefix, validate that it matches the expected domain.

    Args:
        entity_id: The entity ID, with or without domain prefix.
        domain: The expected domain prefix (e.g., "light").

    Returns:
        The entity ID with the correct domain prefix.

    Raises:
        ValueError: If the entity_id has a domain prefix that does not match the expected domain.
    """
    if "." in entity_id:
        prefix, _ = entity_id.split(".", 1)
        if prefix != domain:
            raise ValueError(f"Entity ID '{entity_id}' has domain '{prefix}', expected '{domain}'.")
        return entity_id

    return f"{domain}.{entity_id}"


class _TypedStateGetter(Generic[StateT]):
    """Callable class to get a state typed as a specific model.

    Example:
    ```python
    my_light = self.states.get[states.LightState]("light.bedroom")
    ```
    """

    def __init__(self, proxy: "StateProxy", model: type[StateT]):
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
        return self._model.model_validate(value)


class _StateGetter:
    def __init__(self, proxy: "StateProxy"):
        self._proxy = proxy

    def __getitem__(self, model: type[StateT]) -> _TypedStateGetter[StateT]:
        return _TypedStateGetter(self._proxy, model)


class DomainStates(Generic[StateT]):
    """Generic container for domain-specific state iteration."""

    def __init__(self, states_dict: dict[str, "HassStateDict"], model: type[StateT]) -> None:
        self._states = states_dict
        self._model = model
        self._domain = model.get_domain()

    def __iter__(self) -> typing.Generator[tuple[str, StateT], Any, None]:
        """Iterate over all states in this domain."""
        for entity_id, state in self._states.items():
            try:
                yield entity_id, self._model.model_validate(state)
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

        return self._model.model_validate(state)

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


class StateManager(Resource):
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

        if state_class is None:
            warn(
                f"Domain '{domain}' not registered, returning DomainStates[BaseState]. "
                f"For better type support, create a custom state class that registers this domain.",
                stacklevel=2,
            )
            return DomainStates[BaseState](self._state_proxy.get_domain_states(domain), BaseState)

        # Domain is registered, use its specific class
        return DomainStates[state_class](self._state_proxy.get_domain_states(domain), state_class)

    @property
    def all(self) -> dict[str, "HassStateDict"]:
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
