"""Errors the state registry and state conversion raise. Re-exported from ``hassette.exceptions``."""

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from hassette.exception_base import HassetteError

if TYPE_CHECKING:
    from hassette.models.states import BaseState


class StateRegistryError(HassetteError):
    """Base exception for state registry errors."""


class RegistryNotReadyError(StateRegistryError):
    """Raised when attempting to use the registry before any classes are registered."""

    def __init__(self) -> None:
        super().__init__(
            "State registry has not been initialized. "
            "No state classes have been registered yet. "
            "Ensure state modules are imported before attempting state conversion."
        )


class NoDomainAnnotationError(StateRegistryError):
    """Raised when a state class does not define a domain annotation or the annotation is empty.

    Generally ignored, this indicates that the class is a base class and not intended to be registered.

    A class may optionally set :attr:`~hassette.models.states.base.BaseState.accessor_hint` to name
    a dedicated ``StateManager`` accessor that exists for exactly this case — e.g. the four narrowed
    sensor-shape classes in ``models/states/sensor_shapes.py``, which deliberately do not re-declare
    ``domain`` and so always hit this error via ``self.states[<class>]``. When set, the hint becomes
    the error's ``suggestion``; every other state class gets a suggestion to declare ``domain``.
    """

    def __init__(self, state_class: type["BaseState[Any]"], accessor_hint: str | None = None) -> None:
        msg = f"State class {state_class.__name__} does not define a domain annotation or the annotation is empty."
        super().__init__(msg)
        if accessor_hint is not None:
            self.suggestion = f"Use self.states.{accessor_hint} instead."
        else:
            self.suggestion = f"Declare the domain on {state_class.__name__}, e.g. `domain: Literal['light']`."
        self.state_class = state_class
        self.accessor_hint = accessor_hint


class DomainNotFoundError(StateRegistryError):
    """Raised when no state class is found for a given domain."""

    def __init__(self, domain: str):
        super().__init__(f"No state class found for domain '{domain}'.")
        self.domain = domain
        self.suggestion = (
            f"Check the domain for typos, or define a custom state class with `domain: Literal['{domain}']`."
        )


class DomainRequiredError(StateRegistryError):
    """Raised when ``register_state_converter`` (or ``StateRegistry.register``) gets ``domain=None``.

    A concrete domain is required to register a class in the catalog — ``None`` would
    silently store an unresolvable ``StateKey(domain=None)`` entry that ``resolve(domain=None)``
    could return before any caller validates the result. Contrast with
    :class:`NoDomainAnnotationError`, which fires during *automatic* registration when a
    class's own ``Literal`` annotation is absent; that path is expected for base classes and
    is suppressed by ``BaseState.__init_subclass__``. This error covers the *explicit*
    registration path, where a missing domain is always a caller mistake.
    """

    def __init__(self, state_class: type["BaseState[Any]"]) -> None:
        msg = (
            f"Cannot register {state_class.__name__} with domain=None. Pass an explicit domain, "
            f"e.g. register_state_converter({state_class.__name__}, domain='my_domain')."
        )
        super().__init__(msg)
        self.state_class = state_class


class InvalidDataForStateConversionError(StateRegistryError):
    """Raised when the data provided for state conversion is invalid or malformed."""

    def __init__(self, data: Any):
        super().__init__(f"Invalid or malformed data provided for state conversion: {data!r}")
        self.data = data


class UnableToConvertStateError(StateRegistryError):
    """Raised when a state dictionary cannot be converted to a specific state class."""

    def __init__(self, entity_id: str, state_class: type["BaseState"]) -> None:
        super().__init__(f"Unable to convert state for entity_id '{entity_id}' to class {state_class.__name__}.")
        self.entity_id = entity_id
        self.state_class = state_class


class EntityShapeError(StateRegistryError):
    """Base for state-conversion errors carrying ``(entity_id, device_class, state_class)`` context.

    Shared by :class:`UnableToConvertAnnotatedStateError`, :class:`SensorShapeMismatchError`, and
    :class:`EntityNotInViewError`, which differ only in the message template: each overrides the abstract
    :meth:`_build_message` and leaves ``__init__`` alone so the attribute assignments stay in one place (except
    :class:`EntityNotInViewError`, which mixes in ``KeyError`` and must re-delegate; see its ``__init__``).

    Matches design.md's documented exception convention ("a message plus structured attributes, not
    a bare string"; see ``UnableToConvertStateError``) — that convention constrains the shape of each
    subclass's public surface, not whether they share an implementation.
    """

    def __init__(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> None:
        super().__init__(self._build_message(entity_id, device_class, state_class))
        self.entity_id = entity_id
        self.device_class = device_class
        self.state_class = state_class

    @abstractmethod
    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        raise NotImplementedError  # BaseException.__new__ skips ABCMeta's instantiation check


class UnableToConvertAnnotatedStateError(EntityShapeError):
    """Raised when a state dict fails Pydantic validation against a DI-annotated state class.

    Wraps the underlying ``pydantic.ValidationError`` (chained via ``raise ... from exc``) with a
    message that names the entity, its actual device class, and the annotated class — legible where
    a bare Pydantic error is not.

    Distinct from :class:`UnableToConvertStateError`, which is raised by
    ``StateRegistry.conversion_with_error_handling`` for the ``try_convert_state``/``self.states``
    path. This one is raised directly by ``convert_state_dict_to_model``, which the dependency
    injection annotation converter (``hassette.conversion.annotation_converter``) calls without
    going through that wrapper — so without this error, a DI conversion failure surfaced a raw
    Pydantic ``ValidationError`` with no entity context.
    """

    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        return (
            f"Unable to convert state for entity_id '{entity_id}' (device_class: {device_class!r}) "
            f"to annotated class {state_class.__name__}."
        )


class SensorShapeMismatchError(EntityShapeError):
    """Raised when a DI-annotated narrowed sensor shape class does not match the entity's value shape.

    Raised even when coercion would otherwise succeed.

    Only triggered for the four narrowed sensor shape classes (``NumericSensorState``,
    ``EnumSensorState``, ``TimestampSensorState``, ``DateSensorState``) from
    ``hassette.models.states.sensor_shapes`` — annotating plain ``SensorState`` makes no shape claim
    and is never checked. An entity whose shape classifies as ``SensorShape.UNKNOWN`` contradicts no
    claim and does not raise this error.
    """

    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        return (
            f"Entity '{entity_id}' (device_class: {device_class!r}) does not match the value shape "
            f"declared by annotated class {state_class.__name__}."
        )


class EntityNotInViewError(KeyError, EntityShapeError):
    """Raised when direct lookup finds an entity in its domain that is not in a filtered ``DomainStates`` view.

    The entity's state either fails the view's membership predicate, or its current value does
    not convert to the view's model.

    Subclasses both ``KeyError`` and the state-error hierarchy: ``Mapping.get()`` is implemented by
    catching ``KeyError``, so ``.get()`` returns ``None`` for non-members — consistent with
    ``__contains__`` returning ``False`` and iteration silently skipping the entity — while ``[]``
    still fails loudly with a legible message. Only raised by views built with an explicit
    membership predicate (e.g. the narrowed sensor-shape accessors); a plain ``DomainStates`` with
    no predicate keeps raising the underlying conversion error directly.
    """

    def __init__(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> None:
        # Must delegate explicitly rather than inherit EntityShapeError.__init__. On Python <= 3.13
        # KeyError carries its own __init__ slot, and KeyError precedes EntityShapeError in this
        # class's MRO, so an inherited __init__ resolves to KeyError's — leaving entity_id,
        # device_class, and state_class unset, so every read of them raises AttributeError. Python
        # 3.14 drops that slot and resolves to EntityShapeError, which is why the bug only surfaced
        # on the supported lower bound. super().__init__() would hit KeyError too; name the base
        # directly. Pinned by test_entity_not_in_view_error_defines_own_init.
        EntityShapeError.__init__(self, entity_id, device_class, state_class)

    def __str__(self) -> str:
        # KeyError precedes HassetteError in the MRO, and KeyError.__str__ returns repr() of the
        # message (extra quotes, escaped inner quotes) and skips the suggestion suffix. As with
        # __init__, super() would resolve to KeyError; name the base directly.
        return HassetteError.__str__(self)

    def _build_message(self, entity_id: str, device_class: str | None, state_class: type["BaseState"]) -> str:
        return (
            f"Entity '{entity_id}' (device_class: {device_class!r}) is not a member of this view; "
            f"it does not match the shape expected by {state_class.__name__}."
        )


class ConvertedTypeDoesNotMatchError(StateRegistryError):
    """Raised when a converted state does not match the expected type."""

    def __init__(self, entity_id: str, expected_class: type["BaseState"], actual_class: type["BaseState"]) -> None:
        super().__init__(
            f"Converted state for entity_id '{entity_id}' is of type {actual_class.__name__}, "
            f"expected {expected_class.__name__}."
        )
        self.entity_id = entity_id
        self.expected_class = expected_class
        self.actual_class = actual_class


class InvalidEntityIdError(StateRegistryError):
    """Raised when an entity ID is invalid or malformed."""

    def __init__(self, entity_id: Any):
        super().__init__(f"Invalid or malformed entity ID: {entity_id!r}")
        self.entity_id = entity_id
