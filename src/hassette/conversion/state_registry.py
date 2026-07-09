import typing
from collections.abc import Hashable
from contextlib import suppress
from logging import getLogger

from hassette.conversion.type_registry import TYPE_REGISTRY
from hassette.exceptions import (
    InvalidDataForStateConversionError,
    InvalidEntityIdError,
    UnableToConvertStateError,
    UnableToConvertValueError,
)
from hassette.models.states.base import BaseState
from hassette.models.states.catalog import (
    _STATE_CATALOG,
    resolve,
)
from hassette.models.states.catalog import (
    StateKey as StateKey,
)
from hassette.models.states.catalog import (
    register_state_converter as register_state_converter,
)
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

    from hassette.events import HassStateDict


LOGGER = getLogger(__name__)
CONVERSION_FAIL_TEMPLATE = (
    "Failed to convert state for entity '%s' (domain: '%s') to class '%s'. Data: %s. Error: %s, Traceback: %s"
)
STATE_REPR_MAX_LENGTH = 200
TRUNCATION_SUFFIX = "...[truncated]"


class StateRegistry:
    """Registry for mapping domains to their state classes.

    This class maintains a mapping of Home Assistant domains to their corresponding
    BaseState subclasses. State classes get registered during the `after_initialize` phase
    by scanning all subclasses of BaseState.
    """

    @property
    def registry(self) -> "dict[StateKey, type[BaseState]]":
        """Read accessor over the catalog leaf dict — for validation.py and other readers."""
        return _STATE_CATALOG

    def get_entity_id(self, data: "HassStateDict", entity_id: str | None = None) -> str:
        if not entity_id:
            entity_id = data.get("entity_id") or "<unknown>"

        if not isinstance(entity_id, str):
            LOGGER.error("State data has invalid 'entity_id' field: %s", data, stacklevel=2)
            raise InvalidEntityIdError(entity_id)

        if "." not in entity_id:
            LOGGER.error("State data has malformed 'entity_id' (missing domain): %s", entity_id, stacklevel=2)
            raise InvalidEntityIdError(entity_id)

        return entity_id

    def try_convert_state(self, data: "HassStateDict", entity_id: str | None = None) -> "BaseState":
        """Convert a raw HA state dict to the most specific registered state class, falling back to BaseState.

        Args:
            data: Dictionary containing state data from Home Assistant.
            entity_id: Optional entity ID to assist in domain determination.

        Returns:
            A properly typed state object (e.g., LightState, SensorState) or BaseState
            for unknown domains.

        Raises:
            InvalidDataForStateConversionError: If the provided data is an event payload.
            InvalidEntityIdError: If the entity_id is missing or malformed.
            UnableToConvertStateError: If conversion to the resolved state class fails.
        """
        if "event" in data:
            LOGGER.error(
                "Data contains 'event' key, expected state data, not event data. "
                "To convert state from an event, extract the state data from event.payload.data.new_state "
                "or event.payload.data.old_state.",
                stacklevel=2,
            )
            raise InvalidDataForStateConversionError(data)

        entity_id = self.get_entity_id(data, entity_id=entity_id)
        domain = entity_id.split(".", 1)[0]

        state_class = self.resolve(domain=domain)

        classes = [state_class, BaseState] if state_class is not None else [BaseState]

        final_idx = len(classes) - 1
        for i, cls in enumerate(classes):
            try:
                return self.conversion_with_error_handling(cls, data, entity_id, domain)
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
    def register(
        cls,
        state_class: type["BaseState"],
        *,
        domain: Hashable | None = None,
        device_class: Hashable | None = None,
    ) -> None:
        """Register a state class for a given domain and optional device_class combination.

        Args:
            state_class: The state class to register. Must be a subclass of BaseState.
            domain: The Home Assistant domain (e.g., "light", "sensor").
            device_class: The device class (e.g., "temperature", "motion").
        """
        register_state_converter(state_class, domain=domain, device_class=device_class)

    @classmethod
    def resolve(cls, *, domain: Hashable | None = None, device_class: Hashable | None = None) -> type[BaseState] | None:
        """Resolve a state class from the registry based on domain and device_class."""
        return resolve(domain=domain, device_class=device_class)

    def coerce_and_construct(
        self, state_class: "type[BaseState]", data: "HassStateDict", entity_id: str
    ) -> "BaseState":
        """Coerce a raw HA state dict to a typed model using a known target class.

        Applies domain extraction and unknown/unavailable normalization before coercing
        the value, so the pipeline never attempts to coerce "unknown" or "unavailable"
        against a non-string value_type.

        Args:
            state_class: The target state model class (e.g., LightState, SensorState).
            data: Raw state dict from Home Assistant.
            entity_id: The entity ID for domain extraction and error reporting.

        Returns:
            The typed state model instance.

        Raises:
            UnableToConvertStateError: If coercion or validation fails.
        """
        domain = entity_id.split(".", 1)[0]
        return self.conversion_with_error_handling(state_class, data, entity_id, domain)

    def conversion_with_error_handling(
        self, state_class: "type[BaseState]", data: "HassStateDict", entity_id: str, domain: str
    ) -> "BaseState":
        """Convert state data, logging and re-raising as UnableToConvertStateError on failure.

        Args:
            state_class: The target state model class.
            data: Raw state dict from Home Assistant.
            entity_id: The entity ID for error reporting.
            domain: The HA domain string (e.g., "light", "sensor").

        Returns:
            The typed state model instance.

        Raises:
            UnableToConvertStateError: If conversion fails for any reason.
        """

        class_name = state_class.__name__
        truncated_data = repr(data)
        if len(truncated_data) > STATE_REPR_MAX_LENGTH:
            truncated_data = truncated_data[:STATE_REPR_MAX_LENGTH] + TRUNCATION_SUFFIX

        try:
            return convert_state_dict_to_model(data, state_class)
        except Exception as exc:
            tb = get_short_traceback()

            LOGGER.error(
                CONVERSION_FAIL_TEMPLATE,
                entity_id,
                domain,
                class_name,
                truncated_data,
                exc,
                tb,
            )
            raise UnableToConvertStateError(entity_id, state_class) from exc

    def __contains__(self, model: "type[BaseState]") -> bool:
        """Check if the registry contains a state class for the given model."""
        return any(cls is model for cls in _STATE_CATALOG.values())

    def __iter__(self) -> "Iterator[tuple[StateKey, type[BaseState]]]":
        """Iterate over all registered state classes with their keys."""
        return iter(_STATE_CATALOG.items())

    def items(self) -> "Iterator[tuple[StateKey, type[BaseState]]]":
        return iter(_STATE_CATALOG.items())

    def values(self) -> "Iterator[type[BaseState]]":
        return (state_class for state_class in _STATE_CATALOG.values())

    def keys(self) -> "Iterator[StateKey]":
        return (key for key in _STATE_CATALOG)


STATE_REGISTRY = StateRegistry()


def convert_state_dict_to_model(value: typing.Any, model: "type[BaseState]") -> "BaseState":
    """Convert a raw HA state dict to a typed state model via preprocessing + value coercion.

    Applies the same preprocessing order as the old model validator: domain extraction,
    then unknown/unavailable normalization (setting state to None before coercion touches it),
    then TYPE_REGISTRY.convert for the model's value_type.

    Args:
        value: The raw state dict from Home Assistant (or an already-validated model instance).
        model: The target state model class (e.g., LightState, SensorState).

    Returns:
        The typed state model instance.

    Raises:
        TypeError: If value is not a dict or model instance.
        ValidationError: If the state dict doesn't match the model schema.
    """
    if isinstance(value, model):
        return value

    if not isinstance(value, dict):
        raise TypeError(f"Cannot convert {type(value).__name__} to {model.__name__}, expected dict")

    prepared = dict(value)

    entity_id = prepared.get("entity_id")
    if entity_id:
        prepared["domain"] = str(entity_id).split(".", 1)[0]

    if "state" in prepared:
        state = prepared["state"]
        if state == "unknown":
            prepared["is_unknown"] = True
            prepared["state"] = state = None
        elif state == "unavailable":
            prepared["is_unavailable"] = True
            prepared["state"] = state = None

        with suppress(UnableToConvertValueError):
            prepared["state"] = TYPE_REGISTRY.convert(state, model.value_type)

    return model.model_validate(prepared)
