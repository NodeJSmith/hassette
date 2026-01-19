import typing
from logging import getLogger
from typing import Any, Generic
from warnings import warn

from hassette.core.state_proxy import StateProxy
from hassette.exceptions import EntityNotFoundError, RegistryNotReadyError
from hassette.models.states import BaseState, StateT
from hassette.resources.base import Resource
from hassette.utils.hass_utils import make_entity_id

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict


LOGGER = getLogger(__name__)


class DomainStates(Generic[StateT]):
    """Generic container for domain-specific state iteration."""

    def __init__(self, states_dict: dict[str, "HassStateDict"], model: type[StateT]) -> None:
        self._states = states_dict
        self._model = model
        self._domain = model.get_domain()

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

    def keys(self) -> list[str]:
        """Return a list of entity IDs for this domain."""
        return list(self._states.keys())

    def values(self) -> list[StateT]:
        """Return a list of typed states for this domain.

        This returns an eagerly evaluated list of all typed states in this domain.
        """
        return [value for _, value in self]

    def to_dict(self) -> dict[str, StateT]:
        """Return a dictionary of entity_id to typed state for this domain.

        This returns an eagerly evaluated dictionary of all typed states in this domain.
        """
        return dict(self)

    def items(self) -> typing.ItemsView[str, StateT]:
        """Return a view of (entity_id, typed state) items for this domain.

        The returned object behaves like dict_items and reflects all current
        states in this domain.
        """
        return self.to_dict().items()

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

    def __contains__(self, entity_id: str) -> bool:
        """Check if a specific entity ID exists in this domain."""
        entity_id = make_entity_id(entity_id, self._domain)
        return entity_id in self._states

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
        return len(self._states) > 0


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


    def get_states(self, model: type[StateT]) -> DomainStates[StateT]:
        """Get all states for a specific domain model.

        Used for any domain not covered by a dedicated property.

        Args:
            model: The state model class representing the domain.

        Returns:
            DomainStates container for the specified domain.
        """
        return DomainStates[StateT](self._state_proxy, model)
