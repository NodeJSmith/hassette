import typing
from collections import deque
from contextlib import suppress
from logging import getLogger

from hassette.exceptions import (
    InvalidDataForStateConversionError,
    InvalidEntityIdError,
    NoDomainAnnotationError,
    UnableToConvertStateError,
)
from hassette.resources.base import Resource
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict
    from hassette.models.states.base import BaseState


LOGGER = getLogger(__name__)
CONVERSION_FAIL_TEMPLATE = (
    "Failed to convert state for entity '%s' (domain: '%s') to class '%s'. Data: %s. Error: %s, Traceback: %s"
)


class StateRegistry(Resource):
    """Registry for mapping domains to their state classes.

    This class maintains a mapping of Home Assistant domains to their corresponding
    BaseState subclasses. State classes get registered during the `after_initialize` phase
    by scanning all subclasses of BaseState.
    """

    domain_to_class: dict[str, type["BaseState"]]
    """Mapping of domain strings to their registered state classes."""

    class_to_domain: dict[type["BaseState"], str]
    """Mapping of state classes to their registered domain strings."""

    async def after_initialize(self) -> None:
        self.build_registry()
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
        inst.domain_to_class = {}
        inst.class_to_domain = {}
        return inst

    def build_registry(self):
        # BFS over the subclass tree, starting from BaseState
        from hassette.models.states.base import BaseState

        queue: deque[type[BaseState]] = deque(BaseState.__subclasses__())
        seen: set[type[BaseState]] = set()

        while queue:
            state_cls = queue.popleft()

            if state_cls in seen:
                continue
            seen.add(state_cls)

            # enqueue *its* subclasses so we explore the whole tree
            for sub in state_cls.__subclasses__():
                queue.append(sub)

            # skip the abstract base or any classes that shouldn't register
            # (you can refine this condition however you like)
            with suppress(NoDomainAnnotationError):
                # adjust this call depending on how your registration API works
                self.register(state_cls)
                self.logger.debug("Registered state class %s for domain '%s'", state_cls.__name__, state_cls.get_domain())

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
            self.logger.debug("Skipping registration for %s: %s", state_class.__name__, e)
            return

        if domain in self.domain_to_class:
            existing_class = self.domain_to_class[domain]
            if existing_class is state_class:
                return  # Already registered, skip

            self.logger.warning(
                "Overriding original state class %s for domain '%s' with %s",
                existing_class.__name__,
                domain,
                state_class.__name__,
            )

        self.logger.debug("Registering state class %s for domain '%s'", state_class.__name__, domain)
        self.domain_to_class[domain] = state_class

    def get_class_for_domain(self, domain: str) -> type["BaseState"] | None:
        """Get the state class registered for a domain.

        Args:
            domain: The domain to look up.

        Returns:
            The state class for the domain, or None if not registered.
        """
        return self.domain_to_class.get(domain)

    def get_domain_for_class(self, state_class: type["BaseState"]) -> str | None:
        """Get the domain for a registered state class.

        Args:
            state_class: The state class to look up.

        Returns:
            The domain for the class, or None if not registered.
        """
        return self.class_to_domain.get(state_class)

    def all_domains(self) -> list[str]:
        """Get all registered domains.

        Returns:
            A sorted list of all registered domain strings.
        """
        return sorted(self.domain_to_class.keys())

    def all_classes(self) -> list[type["BaseState"]]:
        """Get all registered state classes.

        Returns:
            A list of all registered state classes, sorted by domain name.
        """

        return [self.domain_to_class[domain] for domain in self.all_domains()]

    def clear(self) -> None:
        """Clear all registered state classes.

        Warning:
            This is primarily for testing purposes. In normal operation,
            state classes should remain registered for the lifetime of the process.
        """
        self.domain_to_class.clear()

    def try_convert_state(self, data: "HassStateDict", entity_id: str | None = None) -> "BaseState":
        """Convert a dictionary representation of a state into a specific state type.

        This function uses the state registry to look up the appropriate state class
        based on the entity's domain. If no specific class is registered for the domain,
        it falls back to the generic BaseState.

        Args:
            data: Dictionary containing state data from Home Assistant.
            entity_id: Optional entity ID to assist in domain determination.

        Returns:
            A properly typed state object (e.g., LightState, SensorState) or BaseState
            for unknown domains.

        Raises:
            InvalidDataForStateConversionError: If the provided data is invalid or malformed.
            InvalidEntityIdError: If the entity_id is invalid or malformed.
            UnableToConvertStateError: If conversion to the determined state class fails.

        Example:
            ```python
            state_dict = {"entity_id": "light.bedroom", "state": "on", ...}
            light_state = try_convert_state(state_dict)  # Returns LightState instance
            ```
        """
        from hassette.models.states.base import BaseState

        if data is None:
            raise InvalidDataForStateConversionError(data)

        if "event" in data:
            self.logger.error(
                "Data contains 'event' key, expected state data, not event data. "
                "To convert state from an event, extract the state data from event.payload.data.new_state "
                "or event.payload.data.old_state.",
                stacklevel=2,
            )
            raise InvalidDataForStateConversionError(data)

        if not entity_id:
            # specifically this way so we also handle empty strings/None
            entity_id = data.get("entity_id") or "<unknown>"

        if not isinstance(entity_id, str):
            self.logger.error("State data has invalid 'entity_id' field: %s", data, stacklevel=2)
            raise InvalidEntityIdError(entity_id)

        if "." not in entity_id:
            self.logger.error("State data has malformed 'entity_id' (missing domain): %s", entity_id, stacklevel=2)
            raise InvalidEntityIdError(entity_id)

        # domain = data["domain"] if "domain" in data else entity_id.split(".", 1)[0]
        domain = data.get("domain") or entity_id.split(".", 1)[0]

        # Look up the appropriate state class from the registry
        state_class = self.get_class_for_domain(domain)

        classes = [state_class, BaseState] if state_class is not None else [BaseState]

        final_idx = len(classes) - 1
        for i, cls in enumerate(classes):
            try:
                return self._conversion_with_error_handling(cls, data, entity_id, domain)
            except UnableToConvertStateError:
                if i == final_idx:
                    raise
                self.logger.debug(
                    "Falling back to next state class after failure to convert to '%s' for entity '%s'",
                    cls.__name__,
                    entity_id,
                )

        raise RuntimeError("Unreachable code reached in try_convert_state")

    def _conversion_with_error_handling(
        self, state_class: type["BaseState"], data: "HassStateDict", entity_id: str, domain: str
    ) -> "BaseState":
        """Helper to convert state data with error handling.

        This function attempts to convert the given data dictionary into an instance
        of the specified state class. If conversion fails, it logs the error and
        returns None.

        Args:
            state_class: The target state class to convert to.
            data: The state data dictionary.
            entity_id: The entity ID associated with the state data.
            domain: The domain associated with the state data.

        Returns:
            An instance of the state class.

        Raises: UnableToConvertStateError if conversion fails.
        """

        class_name = state_class.__name__
        truncated_data = repr(data)
        if len(truncated_data) > 200:
            truncated_data = truncated_data[:200] + "...[truncated]"

        try:
            return state_class.model_validate(data)
        except Exception as e:
            tb = get_short_traceback()

            self.logger.error(
                CONVERSION_FAIL_TEMPLATE,
                entity_id,
                domain,
                class_name,
                truncated_data,
                e,
                tb,
            )
            raise UnableToConvertStateError(entity_id, state_class) from e
