import typing
from collections.abc import Iterator, Mapping
from logging import getLogger
from typing import Generic, NamedTuple

from frozendict import deepfreeze, frozendict

from hassette.conversion import STATE_REGISTRY, StateKey
from hassette.exceptions import RegistryNotReadyError
from hassette.models import states
from hassette.models.states import BaseState
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.types import StateReader, StateT
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.hass_utils import make_entity_id

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict


LOGGER = getLogger(__name__)

HOME_STATE = "home"
"""State value Home Assistant reports for a person or device_tracker that is home."""


class CacheValue(Generic[StateT], NamedTuple):
    context_id: str | None
    frozen_state: frozendict
    model: StateT


class DomainStates(Mapping[str, StateT]):
    """DomainStates provides access to all states within a specific domain, with automatic type validation and caching.

    This class reads through a StateReader under the hood to provide access to the current states from HomeAssistant,
    without needing to make direct calls to the Home Assistant API.

    Accessed states are automatically validated against the provided model and cached for efficient repeated access.

    Implements ``collections.abc.Mapping`` — ``keys()``, ``values()``, and ``items()`` return re-iterable views
    (not one-shot iterators), and ``for entity_id in domain_states`` yields entity ID strings, matching Python
    convention. Use ``.items()`` for ``(entity_id, state)`` pairs.

    Examples:
    ```python
        # if you know the entity exists
        light_state = self.states.light["bedroom"]

        # to safely access an entity that may not exist
        light_state = self.states.light.get("bedroom")
        if light_state is not None:
            self.logger.info("Light state: %s", light_state.value)

        # or you can check existence ahead of time
        if "bedroom" in self.states.light:
            light_state = self.states.light["bedroom"]
            self.logger.info("Light state: %s", light_state.value)

        # iterate over all entities in a domain
        for entity_id, state in self.states.light.items():
            self.logger.info("%s: %s", entity_id, state.value)
    ```

    """

    def __init__(self, state_proxy: StateReader, model: type[StateT]) -> None:
        if not issubclass(model, BaseState):
            raise TypeError(f"Expected a subclass of BaseState, got {model!r}")

        self._state_proxy: StateReader = state_proxy
        self._model = model
        self._domain = model.get_domain()
        self._cache: dict[str, CacheValue[StateT]] = {}

    def _validate_or_return_from_cache(self, entity_id: str, state: "HassStateDict") -> StateT:
        context_id: str | None = state.get("context", {}).get("id")

        cached = self._cache.get(entity_id)

        # first check if the context ID matches
        if cached is not None and context_id is not None and cached.context_id == context_id:  # pyright: ignore[reportUnnecessaryComparison]
            return cached.model

        # if not then use deepfreeze and see if frozen states match
        frozen_state = deepfreeze(state)
        if cached is not None and cached.frozen_state == frozen_state:
            return cached.model

        validated = STATE_REGISTRY.coerce_and_construct(self._model, state, entity_id)
        self._cache[entity_id] = CacheValue(context_id, frozen_state, validated)
        return validated

    def to_dict(self) -> dict[str, StateT]:
        """Return a dictionary of entity_id to typed state for this domain.

        This returns an eagerly evaluated dictionary of all typed states in this domain.

        Note:
            This method will iterate over all states in the domain and validate them,
            which may be expensive for large domains. Consider using the iterator
            returned by `__iter__` for lazy evaluation if performance is a concern.
        """
        return dict(self)

    def __iter__(self) -> Iterator[str]:
        """Iterate over entity IDs in this domain, skipping un-convertible entities."""
        for entity_id, state in self._state_proxy.yield_domain_states(self._domain):
            try:
                self._validate_or_return_from_cache(entity_id, state)
                yield entity_id
            except Exception as exc:
                LOGGER.error(
                    "Error validating state for entity_id '%s' as type %s: %s",
                    entity_id,
                    self._model.__name__,
                    exc,
                )
                continue

    def __len__(self) -> int:
        """Return the number of entities in this domain."""
        return self._state_proxy.num_domain_states(self._domain)

    def __contains__(self, entity_id: object) -> bool:
        """Check if a specific entity ID exists in this domain."""
        if not isinstance(entity_id, str):
            return False
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
            KeyError: If the entity is not found in this domain.
            UnableToConvertStateError: If the state dict fails to convert to this domain's state class.

        Returns:
            The typed state.
        """
        entity_id = make_entity_id(entity_id, self._domain)
        state = self._state_proxy.get_state(entity_id)
        if state is None:
            raise KeyError(f"State for entity_id '{entity_id}' not found in domain '{self._domain}'")
        return self._validate_or_return_from_cache(entity_id, state)

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
        for entity_id, light_state in self.states.light.items():
            self.logger.info("%s: %s", entity_id, light_state.value)

        # Get specific entity
        bedroom_light = self.states.light.get("light.bedroom")
        if bedroom_light and bedroom_light.attributes.brightness:
            self.logger.info("Brightness: %s", bedroom_light.attributes.brightness)

        # Check count
        self.logger.info("Total lights: %d", len(self.states.light))
    """

    _domain_states_cache: dict[type[BaseState], DomainStates[BaseState]]

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._domain_states_cache = {}

    async def after_initialize(self) -> None:
        mark_ready(self, reason="StateManager initialized")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.logging.state_proxy

    @property
    def _state_proxy(self) -> StateReader:
        """Access the underlying state proxy (as a StateReader) via the public, wiring-checked accessor."""
        return self.hassette.state_proxy

    def _domain_states_for(self, state_class: type[BaseState]) -> "DomainStates[BaseState]":
        """Get-or-create a DomainStates instance from the cache, keyed by state class."""
        cached = self._domain_states_cache.get(state_class)
        if cached is None:
            cached = self[state_class]
            self._domain_states_cache[state_class] = cached
        return cached

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
            AttributeError: If the attribute name matches a reserved name or if the domain is not registered in the
                state registry.

        Example:
            ```python
            # Known domain (typed via .pyi stub)
            for entity_id, light in self.states.light.items():
                print(light.attributes.brightness)

            # Custom domain (fallback to BaseState at runtime)
            custom_states = self.states.custom_domain
            for entity_id, state in custom_states.items():
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
            raise AttributeError(
                f"Domain '{domain}' is not registered in the state registry. Use `states[<state_class>]` "
                "if you have a custom state class for this domain."
            )

        return self._domain_states_for(state_class)

    def __getitem__(self, model: type[StateT]) -> DomainStates[StateT]:
        """Access domain states using the indexing syntax. This is required if you need
        to access domain states for a state model class that is not known by the StateRegistry.

        Returns a fresh ``DomainStates`` on every call — it does not share the per-entity validation
        cache that attribute access (``self.states.light``) and iteration (``values()``) reuse. Prefer
        those for repeated access in a loop; use indexing for custom state classes not in the registry.

        Args:
            model: The state model class representing the domain.

        Returns:
            DomainStates container for the specified domain (freshly constructed, uncached).

        Example:
            ```python
            my_state_instance = self.states[MyStateClass].get("custom_entity")
            ```
        """
        return DomainStates[StateT](self._state_proxy, model)

    def get(self, entity_id: str) -> BaseState | None:
        """Get a state by entity ID, returning the most specific type available.

        This method provides generic access to any entity state, regardless of whether
        a domain-specific state class is registered. If a specific class is registered
        (e.g., LightState for domain "light"), it will be used. Otherwise, the state
        is returned as a BaseState instance.

        Args:
            entity_id: Full entity ID (e.g., "light.bedroom" or "test.test_entity")

        Returns:
            Typed state object (domain-specific or BaseState), or None if not found.

        Examples:
            ```python
            # Get a registered domain (returns LightState)
            light = self.states.get("light.bedroom")

            # Get an unregistered domain (returns BaseState)
            test_entity = self.states.get("test.test_entity")
            if test_entity:
                print(f"Domain: {test_entity.domain}, Value: {test_entity.value}")
            ```
        """
        state_dict = self._state_proxy.get_state(entity_id)
        if state_dict is None:
            return None

        try:
            return self.hassette.state_registry.try_convert_state(state_dict, entity_id)
        except Exception as exc:
            LOGGER.error(
                "Failed to convert state for entity '%s': %s",
                entity_id,
                exc,
                stacklevel=2,
            )
            return None

    def anybody_home(self) -> bool:
        """Return True if at least one tracked person is home.

        Reads the local state cache — no network call. Checks the ``person`` domain,
        falling back to ``device_tracker`` when no ``person`` entities are configured.

        Returns:
            True if any tracked entity is home. False otherwise, including when no
            presence entities are tracked.

        Examples:
            ```python
            if self.states.anybody_home():
                await self.api.turn_on("light.porch")
            ```
        """
        return any(state.value == HOME_STATE for state in self._presence_states())

    def everybody_home(self) -> bool:
        """Return True if every tracked person is home.

        Reads the local state cache — no network call. Checks the ``person`` domain,
        falling back to ``device_tracker`` when no ``person`` entities are configured.

        Returns:
            True if all tracked entities are home. False when no presence entities are
            tracked — there is no one to be home.
        """
        tracked = self._presence_states()
        if not tracked:
            return False
        return all(state.value == HOME_STATE for state in tracked)

    def nobody_home(self) -> bool:
        """Return True if no tracked person is home.

        Reads the local state cache — no network call. The inverse of
        :meth:`anybody_home`; returns True when no presence entities are tracked.
        """
        return not self.anybody_home()

    def is_home(self, entity_id: str) -> bool:
        """Return True if a single person or device_tracker entity is home.

        Reads the local state cache — no network call.

        Args:
            entity_id: Full entity id, e.g. "person.jessica" or "device_tracker.phone".

        Returns:
            True if the entity exists and its state is home, False otherwise.

        Examples:
            ```python
            if self.states.is_home("person.jessica"):
                await self.api.turn_on("light.office")
            ```
        """
        state = self.get(entity_id)
        return state is not None and state.value == HOME_STATE

    def _presence_states(self) -> list[BaseState]:
        """Return the states to evaluate for presence.

        Uses the ``person`` domain, falling back to ``device_tracker`` when no
        ``person`` entities exist.
        """
        domain = self.person or self.device_tracker
        return list(domain.values())

    def __contains__(self, model: object) -> bool:
        """Check the global STATE_REGISTRY, not this proxy's cached instances."""
        if not isinstance(model, type) or not issubclass(model, BaseState):
            return False
        return model in STATE_REGISTRY

    def __iter__(self) -> Iterator[StateKey]:
        """Iterate over registered state keys."""
        return iter(STATE_REGISTRY.keys())

    def items(self) -> Iterator[tuple[StateKey, DomainStates[states.BaseState]]]:
        """Iterate over all registered state classes with their keys."""
        for key, state_class in STATE_REGISTRY.items():
            yield key, self._domain_states_for(state_class)

    def values(self) -> Iterator[DomainStates[states.BaseState]]:
        """Iterate over all registered DomainStates instances."""
        for state_class in STATE_REGISTRY.values():
            yield self._domain_states_for(state_class)

    def keys(self) -> Iterator[StateKey]:
        """Iterate over all registered state keys."""
        return iter(self)
