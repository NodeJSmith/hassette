import typing
from logging import getLogger
from typing import ClassVar, cast

from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict
    from hassette.models.states.base import BaseState

LOGGER = getLogger(__name__)


class StateRegistry(Resource):
    """Registry for mapping domains to their state classes.

    This class maintains a mapping of Home Assistant domains to their corresponding
    BaseState subclasses. State classes register themselves automatically when they
    are defined with a domain literal.

    The registry is a singleton - all access goes through the global instance.
    """

    domain_to_class: ClassVar[dict[str, type["BaseState"]]] = {}
    """Mapping of domain strings to their registered state classes."""

    class_to_domain: ClassVar[dict[type["BaseState"], str]] = {}
    """Mapping of state classes to their registered domain strings."""

    async def after_initialize(self) -> None:
        self.mark_ready()

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        """Create a new StateRegistry resource instance.

        Args:
            hassette: The Hassette instance.
            parent: The parent resource (typically the Hassette core).

        Returns:
            A new StateRegistry instance.
        """
        inst = cls(hassette=hassette, parent=parent)

        return inst

    @classmethod
    def register(cls, state_class: type["BaseState"]) -> None:
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

        if domain in cls.domain_to_class:
            existing_class = cls.domain_to_class[domain]
            if existing_class is state_class:
                return  # Already registered, skip

            LOGGER.warning(
                "Overriding original state class %s for domain '%s' with %s",
                existing_class.__name__,
                domain,
                state_class.__name__,
            )

        LOGGER.debug("Registering state class %s for domain '%s'", state_class.__name__, domain)
        cls.domain_to_class[domain] = state_class

    @classmethod
    def get_class_for_domain(cls, domain: str) -> type["BaseState"] | None:
        """Get the state class registered for a domain.

        Args:
            domain: The domain to look up.

        Returns:
            The state class for the domain, or None if not registered.
        """
        return cls.domain_to_class.get(domain)

    @classmethod
    def get_domain_for_class(cls, state_class: type["BaseState"]) -> str | None:
        """Get the domain for a registered state class.

        Args:
            state_class: The state class to look up.

        Returns:
            The domain for the class, or None if not registered.
        """
        return cls.class_to_domain.get(state_class)

    @classmethod
    def all_domains(cls) -> list[str]:
        """Get all registered domains.

        Returns:
            A sorted list of all registered domain strings.
        """
        return sorted(cls.domain_to_class.keys())

    @classmethod
    def all_classes(cls) -> list[type["BaseState"]]:
        """Get all registered state classes.

        Returns:
            A list of all registered state classes, sorted by domain name.
        """

        return [cls.domain_to_class[domain] for domain in cls.all_domains()]

    @classmethod
    def clear(cls) -> None:
        """Clear all registered state classes.

        Warning:
            This is primarily for testing purposes. In normal operation,
            state classes should remain registered for the lifetime of the process.
        """
        cls.domain_to_class.clear()

    @typing.overload
    @classmethod
    def try_convert_state(cls, data: None) -> None: ...

    @typing.overload
    @classmethod
    def try_convert_state(cls, data: "HassStateDict | BaseState") -> "BaseState": ...

    @classmethod
    def try_convert_state(cls, data: "HassStateDict | BaseState | None") -> "BaseState | None":
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
        state_class = cls.get_class_for_domain(domain)

        if state_class is not None:
            result = cls._conversion_with_error_handling(state_class, data)
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
        return cls._conversion_with_error_handling(BaseState, data)

    @classmethod
    def _conversion_with_error_handling(
        cls, state_class: type["BaseState"], data: "HassStateDict | BaseState"
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
