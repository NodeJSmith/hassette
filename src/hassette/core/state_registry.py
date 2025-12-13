import typing
from collections.abc import Hashable
from dataclasses import dataclass
from logging import getLogger
from typing import ClassVar

from hassette.exceptions import InvalidDataForStateConversionError, InvalidEntityIdError, UnableToConvertStateError
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette.events import HassStateDict
    from hassette.models.states.base import BaseState


LOGGER = getLogger(__name__)
CONVERSION_FAIL_TEMPLATE = (
    "Failed to convert state for entity '%s' (domain: '%s') to class '%s'. Data: %s. Error: %s, Traceback: %s"
)


@dataclass(frozen=True)
class StateKey:
    domain: Hashable | None = None
    """The domain of the entity (e.g., 'light', 'sensor')."""

    device_class: Hashable | None = None
    """Optional device class of the entity (e.g., 'temperature', 'humidity'). Not yet being used."""


def register_state_converter(state_class: type["BaseState"], domain: Hashable, device_class: Hashable | None = None):
    """Register a state converter class for a specific domain and optional device class."""
    STATE_REGISTRY.register(state_class, domain=domain, device_class=device_class)


class StateRegistry:
    """Registry for mapping domains to their state classes.

    This class maintains a mapping of Home Assistant domains to their corresponding
    BaseState subclasses. State classes get registered during the `after_initialize` phase
    by scanning all subclasses of BaseState.
    """

    _registry: ClassVar[dict[StateKey, type["BaseState"]]] = {}

    def _get_entity_id(self, data: "HassStateDict", entity_id: str | None = None) -> str:
        if not entity_id:
            # specifically this way so we also handle empty strings/None
            entity_id = data.get("entity_id") or "<unknown>"

        if not isinstance(entity_id, str):
            LOGGER.error("State data has invalid 'entity_id' field: %s", data, stacklevel=2)
            raise InvalidEntityIdError(entity_id)

        if "." not in entity_id:
            LOGGER.error("State data has malformed 'entity_id' (missing domain): %s", entity_id, stacklevel=2)
            raise InvalidEntityIdError(entity_id)

        return entity_id

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
            LOGGER.error(
                "Data contains 'event' key, expected state data, not event data. "
                "To convert state from an event, extract the state data from event.payload.data.new_state "
                "or event.payload.data.old_state.",
                stacklevel=2,
            )
            raise InvalidDataForStateConversionError(data)

        entity_id = self._get_entity_id(data, entity_id=entity_id)
        domain = entity_id.split(".", 1)[0]

        # Look up the appropriate state class from the registry
        state_class = self.resolve(domain=domain)

        classes = [state_class, BaseState] if state_class is not None else [BaseState]

        final_idx = len(classes) - 1
        for i, cls in enumerate(classes):
            try:
                return self._conversion_with_error_handling(cls, data, entity_id, domain)
            except UnableToConvertStateError:
                if i == final_idx:
                    raise
                LOGGER.debug(
                    "Falling back to next state class after failure to convert to '%s' for entity '%s'",
                    cls.__name__,
                    entity_id,
                )

        raise RuntimeError("Unreachable code reached in try_convert_state")

    @classmethod
    def register(cls, state_class: type["BaseState"], *, domain: Hashable = None, device_class: Hashable = None):
        key = StateKey(domain=domain, device_class=device_class)
        cls._registry[key] = state_class

    @classmethod
    def resolve(cls, *, domain: Hashable = None, device_class: Hashable = None) -> type["BaseState"] | None:
        """Resolve a state class from the registry based on domain and device_class."""
        candidates = [StateKey(domain=domain, device_class=device_class)]
        if device_class is not None:
            candidates.append(StateKey(domain=domain, device_class=None))

        for k in candidates:
            if k in cls._registry:
                return cls._registry[k]
        return None

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
            return convert_state_dict_to_model(data, state_class)
        except Exception as e:
            tb = get_short_traceback()

            LOGGER.error(
                CONVERSION_FAIL_TEMPLATE,
                entity_id,
                domain,
                class_name,
                truncated_data,
                e,
                tb,
            )
            raise UnableToConvertStateError(entity_id, state_class) from e


STATE_REGISTRY = StateRegistry()
"""Global state registry for mapping domains and device classes to state converter classes."""


def convert_state_dict_to_model(value: typing.Any, model: type["BaseState"]) -> "BaseState":
    """Convert a raw Home Assistant state dict to a typed state model.

    This converter is used by state object extractors (StateNew, StateOld, etc.) to transform
    the raw state dictionary from Home Assistant into a strongly-typed Pydantic model.

    Args:
        value: The raw state dict from Home Assistant
        model: The target state model class (e.g., LightState, SensorState)

    Returns:
        The typed state model instance

    Raises:
        TypeError: If value is not a dict or model instance
        ValidationError: If the state dict doesn't match the model schema
    """
    if isinstance(value, model):
        return value

    if not isinstance(value, dict):
        raise TypeError(f"Cannot convert {type(value).__name__} to {model.__name__}, expected dict")

    return model.model_validate(value)
