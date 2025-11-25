"""State class registry for dynamic domain-to-class mapping.

This module provides a registry system that allows BaseState subclasses to
automatically register themselves when they define a domain. This enables:
1. Dynamic state conversion without hardcoded unions
2. User-defined state classes for custom domains
3. Extensible state system without modifying core code

Example:
    Creating a custom state class that auto-registers:

    ```python
    from hassette.models.states.base import StringBaseState
    from typing import Literal

    class MyCustomState(StringBaseState):
        domain: Literal["my_custom_domain"]
        # Your custom attributes and methods
    ```

    The state will automatically be available for conversion and access:

    ```python
    # In an app
    custom_states = self.states.get_states(MyCustomState)

    # In dependency injection
    async def handler(state: D.StateNew[MyCustomState]):
        # state is typed as MyCustomState
        pass
    ```
"""

import typing
from logging import getLogger
from typing import TYPE_CHECKING, cast

import hassette.exceptions as exc

if TYPE_CHECKING:
    from hassette.events import HassStateDict
    from hassette.models.states.base import BaseState

LOGGER = getLogger(__name__)


class StateRegistry:
    """Registry for mapping domains to their state classes.

    This class maintains a mapping of Home Assistant domains to their corresponding
    BaseState subclasses. State classes register themselves automatically when they
    are defined with a domain literal.

    The registry is a singleton - all access goes through the global instance.
    """

    def __init__(self) -> None:
        """Initialize the registry with empty mappings."""
        self._domain_to_class: dict[str, type[BaseState]] = {}
        self._class_to_domain: dict[type[BaseState], str] = {}
        self._is_ready = False

    def register(self, state_class: type["BaseState"]) -> None:
        """Register a state class for its domain.

        Args:
            state_class: The BaseState subclass to register.

        Raises:
            DuplicateDomainError: If the domain is already registered to a different class.
            ValueError: If the state class doesn't define a domain.
        """
        try:
            domain = state_class.get_domain()
        except (ValueError, AttributeError) as e:
            # Skip registration for base classes that don't define domains
            LOGGER.debug("Skipping registration for %s: %s", state_class.__name__, e)
            return

        if domain in self._domain_to_class:
            existing_class = self._domain_to_class[domain]
            if existing_class is not state_class:
                raise exc.DuplicateDomainError(domain, existing_class, state_class)
            # Already registered, skip
            return

        LOGGER.debug("Registering state class %s for domain '%s'", state_class.__name__, domain)
        self._domain_to_class[domain] = state_class
        self._class_to_domain[state_class] = domain
        self._is_ready = True

    def get_class_for_domain(self, domain: str) -> type["BaseState"] | None:
        """Get the state class registered for a domain.

        Args:
            domain: The domain to look up.

        Returns:
            The state class for the domain, or None if not registered.

        Raises:
            RegistryNotReadyError: If the registry hasn't been initialized yet.
        """
        if not self._is_ready:
            raise exc.RegistryNotReadyError

        return self._domain_to_class.get(domain)

    def get_domain_for_class(self, state_class: type["BaseState"]) -> str | None:
        """Get the domain for a registered state class.

        Args:
            state_class: The state class to look up.

        Returns:
            The domain for the class, or None if not registered.

        Raises:
            RegistryNotReadyError: If the registry hasn't been initialized yet.
        """
        if not self._is_ready:
            raise exc.RegistryNotReadyError

        return self._class_to_domain.get(state_class)

    def all_domains(self) -> list[str]:
        """Get all registered domains.

        Returns:
            A sorted list of all registered domain strings.

        Raises:
            RegistryNotReadyError: If the registry hasn't been initialized yet.
        """
        if not self._is_ready:
            raise exc.RegistryNotReadyError

        return sorted(self._domain_to_class.keys())

    def all_classes(self) -> list[type["BaseState"]]:
        """Get all registered state classes.

        Returns:
            A list of all registered state classes, sorted by domain name.

        Raises:
            RegistryNotReadyError: If the registry hasn't been initialized yet.
        """
        if not self._is_ready:
            raise exc.RegistryNotReadyError

        return [self._domain_to_class[domain] for domain in self.all_domains()]

    def is_ready(self) -> bool:
        """Check if the registry has been initialized with at least one class.

        Returns:
            True if at least one state class has been registered.
        """
        return self._is_ready

    @property
    def count(self) -> int:
        """Get the number of registered state classes.

        Returns:
            The count of registered state classes.
        """
        return len(self._domain_to_class)

    def clear(self) -> None:
        """Clear all registered state classes.

        Warning:
            This is primarily for testing purposes. In normal operation,
            state classes should remain registered for the lifetime of the process.
        """
        self._domain_to_class.clear()
        self._class_to_domain.clear()
        self._is_ready = False


# Global registry instance
_registry = StateRegistry()


def get_registry() -> StateRegistry:
    """Get the global state registry instance.

    Returns:
        The global StateRegistry instance.
    """
    return _registry


def register_state_class(state_class: type["BaseState"]) -> type["BaseState"]:
    """Decorator to explicitly register a state class.

    This decorator is optional - state classes with domain literals are
    registered automatically via __init_subclass__. Use this if you need
    to control registration timing or for debugging.

    Args:
        state_class: The state class to register.

    Returns:
        The same state class (for use as a decorator).

    Example:
        ```python
        @register_state_class
        class CustomState(StringBaseState):
            domain: Literal["custom"]
        ```
    """
    _registry.register(state_class)
    return state_class


@typing.overload
def try_convert_state(data: None) -> None: ...


@typing.overload
def try_convert_state(data: "HassStateDict | BaseState") -> "BaseState": ...


def try_convert_state(data: "HassStateDict | BaseState | None") -> "BaseState | None":
    """Convert a dictionary representation of a state into a specific state type.

    This function uses the state registry to look up the appropriate state class
    based on the entity's domain. If no specific class is registered for the domain,
    it falls back to the generic BaseState.

    Args:
        data: Dictionary containing state data from Home Assistant, or None.

    Returns:
        A properly typed state object (e.g., LightState, SensorState) or BaseState
        for unknown domains. Returns None if data is None or conversion fails.

    Raises:
        RegistryNotReadyError: If called before any state classes have been registered.

    Example:
        ```python
        state_dict = {"entity_id": "light.bedroom", "state": "on", ...}
        light_state = try_convert_state(state_dict)  # Returns LightState instance
        ```
    """
    from hassette.models.states.base import BaseState

    if data is None:
        return None

    # if BaseState or any subclass, extract the raw data dict
    if isinstance(data, BaseState):
        data = cast("HassStateDict", data.raw_data)

    if "event" in data:
        LOGGER.error(
            "Data contains 'event' key, expected state data, not event data. "
            "To convert state from an event, extract the state data from event.payload.data.new_state "
            "or event.payload.data.old_state.",
            stacklevel=2,
        )
        return None

    entity_id = data.get("entity_id", "<unknown>")
    if not entity_id or not isinstance(entity_id, str):
        LOGGER.error("State data has invalid 'entity_id' field: %s", data, stacklevel=2)
        return None

    if "domain" in data:
        domain = data["domain"]
    else:
        if "." not in entity_id:
            LOGGER.error("State data has malformed 'entity_id' (missing domain): %s", entity_id, stacklevel=2)
            return None
        domain = entity_id.split(".", 1)[0]

    # Look up the appropriate state class from the registry
    registry = get_registry()
    state_class = registry.get_class_for_domain(domain)

    if state_class is not None:
        result = _conversion_with_error_handling(state_class, data)
        if result is not None:
            return result
    else:
        # Domain not registered, log a warning
        LOGGER.debug(
            "No state class registered for domain '%s', falling back to BaseState for entity %s",
            domain,
            entity_id,
        )

    # Fall back to generic BaseState
    return _conversion_with_error_handling(BaseState, data)


def _conversion_with_error_handling(
    state_class: type["BaseState"], data: "HassStateDict | BaseState"
) -> "BaseState | None":
    """Helper to convert state data with error handling.

    This function attempts to convert the given data dictionary into an instance
    of the specified state class. If conversion fails, it logs the error and
    returns None.

    Args:
        state_class: The target state class to convert to.
        data: The state data dictionary.

    Returns:
        An instance of the state class, or None if conversion failed.
    """
    from hassette.models.states.base import BaseState

    if isinstance(data, BaseState):
        data = cast("HassStateDict", data.raw_data)

    class_name = state_class.__name__

    try:
        return state_class.model_validate(data)
    except (TypeError, ValueError) as e:
        entity_id = data.get("entity_id", "<unknown>")
        domain = data.get("domain", "<unknown>")
        # Truncate data for logging, avoid leaking full dict
        truncated_data = repr(data)
        if len(truncated_data) > 200:
            truncated_data = truncated_data[:200] + "...[truncated]"
        LOGGER.error(
            "Unable to convert state data to %s for entity '%s' (domain '%s'): %s\nData: %s",
            class_name,
            entity_id,
            domain,
            type(e).__name__,
            truncated_data,
        )
        return None
    except Exception as e:
        entity_id = data.get("entity_id", "<unknown>")
        domain = data.get("domain", "<unknown>")
        LOGGER.error(
            "Unexpected error converting state data to %s for entity '%s' (domain '%s'): %s",
            class_name,
            entity_id,
            domain,
            type(e).__name__,
        )
        return None
