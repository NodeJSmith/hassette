import typing
from collections.abc import Callable, Iterator, Mapping
from logging import getLogger
from typing import Generic, NamedTuple

from frozendict import deepfreeze, frozendict

from hassette.conversion import STATE_REGISTRY, StateKey
from hassette.exceptions import EntityNotInViewError, RegistryNotReadyError
from hassette.models import states
from hassette.models.states import BaseState
from hassette.models.states.sensor_shapes import SensorShape, classify_sensor_shape
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


def _shape_predicate(shape: SensorShape) -> Callable[["HassStateDict"], bool]:
    """Build a membership predicate for one of the four narrowed sensor-shape accessors.

    Each predicate re-runs :func:`classify_sensor_shape` per access rather than caching a
    result, so a runtime ``device_class`` change is picked up on the very next access — see
    ``design/specs/093-sensor-device-class-subtypes/design.md`` Edge Cases, "device_class
    changes at runtime."
    """

    def predicate(state: "HassStateDict") -> bool:
        return classify_sensor_shape(state.get("attributes", {})) == shape

    return predicate


_NUMERIC_SENSOR_PREDICATE = _shape_predicate(SensorShape.NUMERIC)
_ENUM_SENSOR_PREDICATE = _shape_predicate(SensorShape.ENUM)
_TIMESTAMP_SENSOR_PREDICATE = _shape_predicate(SensorShape.TIMESTAMP)
_DATE_SENSOR_PREDICATE = _shape_predicate(SensorShape.DATE)


class CacheValue(Generic[StateT], NamedTuple):
    last_updated: str | None
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

    def __init__(
        self,
        state_proxy: StateReader,
        model: type[StateT],
        *,
        domain: str | None = None,
        predicate: Callable[["HassStateDict"], bool] | None = None,
    ) -> None:
        if not issubclass(model, BaseState):
            raise TypeError(f"Expected a subclass of BaseState, got {model!r}")

        self._state_proxy: StateReader = state_proxy
        self._model = model
        self._domain = domain if domain is not None else model.get_domain()
        self._predicate = predicate
        self._cache: dict[str, CacheValue[StateT]] = {}

    def _validate_or_return_from_cache(self, entity_id: str, state: "HassStateDict") -> StateT:
        last_updated: str | None = state.get("last_updated")

        cached = self._cache.get(entity_id)

        # last_updated moves whenever the state or its attributes change, so it
        # identifies the content. The context id does not: Home Assistant attaches
        # one context to every state that results from the same cause, so a lamp
        # ramping through a transition or an automation run reports several
        # different states under a single id.
        if cached is not None and last_updated is not None and cached.last_updated == last_updated:
            return cached.model

        # fast path didn't match — compare full content
        frozen_state = deepfreeze(state)
        if cached is not None and cached.frozen_state == frozen_state:
            return cached.model

        validated = STATE_REGISTRY.coerce_and_construct(self._model, state, entity_id)
        self._cache[entity_id] = CacheValue(last_updated=last_updated, frozen_state=frozen_state, model=validated)
        return validated

    def _validate_if_member(self, entity_id: str, state: "HassStateDict") -> StateT | None:
        """Return the validated model if entity_id/state is a member of this view, else None.

        Membership is the predicate (if one is set) AND convertibility, checked in that order —
        the predicate is a cheap first gate, and conversion is amortized by
        ``_validate_or_return_from_cache``'s per-entity cache. A conversion failure is logged at
        ``debug``: for a deliberately filtered view a non-match is expected, not exceptional.
        """
        if self._predicate is not None and not self._predicate(state):
            return None

        try:
            return self._validate_or_return_from_cache(entity_id, state)
        except Exception as exc:
            LOGGER.debug(
                "Error validating state for entity_id '%s' as type %s: %s",
                entity_id,
                self._model.__name__,
                exc,
            )
            return None

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
        """Iterate over entity IDs in this domain, skipping non-member and un-convertible entities."""
        for entity_id, state in self._state_proxy.yield_domain_states(self._domain):
            if self._validate_if_member(entity_id, state) is not None:
                yield entity_id

    def __len__(self) -> int:
        """Return the number of member entities in this domain.

        Computed by iterating and checking membership (predicate AND convertibility) rather than
        consulting the state proxy's raw domain count, so this always agrees with ``list(self)`` —
        see ``_validate_if_member``.
        """
        return sum(1 for _ in self)

    def __contains__(self, entity_id: object) -> bool:
        """Check if a specific entity ID is a member of this view (predicate AND convertibility)."""
        if not isinstance(entity_id, str):
            return False
        try:
            entity_id = make_entity_id(entity_id, self._domain)
        except ValueError:
            return False

        state = self._state_proxy.get_state(entity_id)
        if state is None:
            return False
        return self._validate_if_member(entity_id, state) is not None

    def __getitem__(self, entity_id: str) -> StateT:
        """Get a specific entity state by ID, raising if not found or not a member of this view.

        Args:
            entity_id: The full entity ID (e.g., "light.bedroom") or just the entity name (e.g., "bedroom").

        Raises:
            KeyError: If the entity is not found in this domain at all.
            EntityNotInViewError: If a membership predicate is set and the entity exists in the
                domain but fails the predicate or fails to convert. Also a ``KeyError``.
            UnableToConvertStateError: If no predicate is set (this view has no shape claim) and
                the state dict fails to convert to this domain's state class.

        Returns:
            The typed state.
        """
        entity_id = make_entity_id(entity_id, self._domain)
        state = self._state_proxy.get_state(entity_id)
        if state is None:
            raise KeyError(f"State for entity_id '{entity_id}' not found in domain '{self._domain}'")

        if self._predicate is None:
            return self._validate_or_return_from_cache(entity_id, state)

        device_class = state.get("attributes", {}).get("device_class")
        if not self._predicate(state):
            raise EntityNotInViewError(entity_id, device_class, self._model)

        try:
            return self._validate_or_return_from_cache(entity_id, state)
        except Exception as exc:
            raise EntityNotInViewError(entity_id, device_class, self._model) from exc

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

    def _domain_states_for(
        self,
        state_class: type[StateT],
        *,
        domain: str | None = None,
        predicate: Callable[["HassStateDict"], bool] | None = None,
    ) -> "DomainStates[StateT]":
        """Get-or-create a DomainStates instance from the cache, keyed by state class.

        ``domain`` and ``predicate`` are only consulted the first time a given ``state_class``
        is requested — the cached instance is reused on every subsequent call, so a caller must
        pass the same values for a given class every time (both ``__getattr__`` and the four
        sensor-shape accessors below do).

        The cache itself is keyed and valued at the erased ``BaseState`` level, so the lookup's
        static type is widened back to ``DomainStates[BaseState]``; the ``cast`` back to
        ``DomainStates[StateT]`` restates the invariant every caller already relies on — the
        cache is keyed by ``state_class``, so a lookup for ``state_class`` always returns a
        ``DomainStates`` constructed from that exact class.
        """
        cached = self._domain_states_cache.get(state_class)
        if cached is None:
            cached = DomainStates(self._state_proxy, state_class, domain=domain, predicate=predicate)
            self._domain_states_cache[state_class] = cached
        return typing.cast("DomainStates[StateT]", cached)

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

    @property
    def numeric_sensor(self) -> "DomainStates[states.NumericSensorState]":
        """Sensors whose value is a number — see :class:`hassette.models.states.NumericSensorState`.

        A filtered view over ``self.states.sensor``, not a separate domain: the same entities
        are reachable from both, with ``value`` typed ``str | None`` there and ``float | None``
        here. Membership requires both a matching shape and a value that actually converts —
        see :func:`hassette.models.states.sensor_shapes.classify_sensor_shape`.
        """
        return self._domain_states_for(states.NumericSensorState, domain="sensor", predicate=_NUMERIC_SENSOR_PREDICATE)

    @property
    def enum_sensor(self) -> "DomainStates[states.EnumSensorState]":
        """Sensors whose value is one of a fixed set of options — see
        :class:`hassette.models.states.EnumSensorState`.

        A filtered view over ``self.states.sensor``; see :attr:`numeric_sensor` for the
        view/projection contract shared by all four narrowed sensor accessors.
        """
        return self._domain_states_for(states.EnumSensorState, domain="sensor", predicate=_ENUM_SENSOR_PREDICATE)

    @property
    def timestamp_sensor(self) -> "DomainStates[states.TimestampSensorState]":
        """Sensors whose value is a timezone-aware point in time — see
        :class:`hassette.models.states.TimestampSensorState`.

        Includes both ``device_class: timestamp`` and ``device_class: uptime`` sensors; there is
        no separate uptime accessor. A filtered view over ``self.states.sensor``; see
        :attr:`numeric_sensor` for the view/projection contract shared by all four narrowed
        sensor accessors.
        """
        return self._domain_states_for(
            states.TimestampSensorState, domain="sensor", predicate=_TIMESTAMP_SENSOR_PREDICATE
        )

    @property
    def date_sensor(self) -> "DomainStates[states.DateSensorState]":
        """Sensors whose value is a calendar date — see
        :class:`hassette.models.states.DateSensorState`.

        A filtered view over ``self.states.sensor``; see :attr:`numeric_sensor` for the
        view/projection contract shared by all four narrowed sensor accessors.
        """
        return self._domain_states_for(states.DateSensorState, domain="sensor", predicate=_DATE_SENSOR_PREDICATE)

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
