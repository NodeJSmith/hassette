import typing
from collections import deque
from contextlib import suppress
from logging import getLogger

from hassette.exceptions import NoDomainAnnotationError
from hassette.resources.base import Resource

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict
    from hassette.models.states.base import BaseState


LOGGER = getLogger(__name__)


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
                print(f"Registered state class {state_cls.__name__} for domain '{state_cls.get_domain()}'")

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

    @typing.overload
    def try_convert_state(self, data: None) -> None: ...

    @typing.overload
    def try_convert_state(self, data: "HassStateDict") -> "BaseState": ...

    def try_convert_state(self, data: "HassStateDict | None") -> "BaseState | None":
        """Convert a dictionary representation of a state into a specific state type.

        This function uses the state registry to look up the appropriate state class
        based on the entity's domain. If no specific class is registered for the domain,
        it falls back to the generic BaseState.

        Args:
            data: Dictionary containing state data from Home Assistant, or None.

        Returns:
            A properly typed state object (e.g., LightState, SensorState) or BaseState
            for unknown domains. Returns None if data is None.

        Example:
            ```python
            state_dict = {"entity_id": "light.bedroom", "state": "on", ...}
            light_state = try_convert_state(state_dict)  # Returns LightState instance
            ```
        """
        from hassette.models.states.base import BaseState

        if data is None:
            return None

        if "event" in data:
            self.logger.error(
                "Data contains 'event' key, expected state data, not event data. "
                "To convert state from an event, extract the state data from event.payload.data.new_state "
                "or event.payload.data.old_state.",
                stacklevel=2,
            )
            return None

        entity_id = data.get("entity_id", "<unknown>")
        if not entity_id or not isinstance(entity_id, str):
            self.logger.error("State data has invalid 'entity_id' field: %s", data, stacklevel=2)
            return None

        if "domain" in data:
            domain = data["domain"]
        else:
            if "." not in entity_id:
                self.logger.error("State data has malformed 'entity_id' (missing domain): %s", entity_id, stacklevel=2)
                return None
            domain = entity_id.split(".", 1)[0]

        # Look up the appropriate state class from the registry
        state_class = self.get_class_for_domain(domain)

        classes = []
        if state_class is not None:
            classes.append(state_class)
        if state_class is not BaseState:
            classes.append(BaseState)

        for i, cls in enumerate(classes):
            try:
                return self._conversion_with_error_handling(cls, data)
            except Exception:
                if i == len(classes) - 1:
                    raise
                self.logger.debug(
                    "Falling back to next state class after failure to convert to '%s' for entity '%s'",
                    cls.__name__,
                    entity_id,
                )

        raise RuntimeError("Unreachable code reached in try_convert_state")

    def _conversion_with_error_handling(self, state_class: type["BaseState"], data: "HassStateDict") -> "BaseState":
        """Helper to convert state data with error handling.

        This function attempts to convert the given data dictionary into an instance
        of the specified state class. If conversion fails, it logs the error and
        returns None.

        Args:
            state_class: The target state class to convert to.
            data: The state data dictionary.

        Returns:
            An instance of the state class.

        Raises:
        """

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
            self.logger.error(
                "Unable to convert state data to %s for entity '%s' (domain '%s'): %s\nData: %s",
                class_name,
                entity_id,
                domain,
                type(e).__name__,
                truncated_data,
            )
            raise
        except Exception as e:
            entity_id = data.get("entity_id", "<unknown>")
            domain = data.get("domain", "<unknown>")
            self.logger.error(
                "Unexpected error converting state data to %s for entity '%s' (domain '%s'): %s",
                class_name,
                entity_id,
                domain,
                type(e).__name__,
            )
            raise
