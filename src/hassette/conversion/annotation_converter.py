from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, get_args, get_origin

from hassette.conversion.state_registry import convert_state_dict_to_model
from hassette.events.hass.hass import HassPayload, RawStateChangeEvent, TypedStateChangeEvent, TypedStateChangePayload
from hassette.exceptions import UnableToConvertValueError
from hassette.utils.type_utils import is_union, normalize_annotation


@dataclass(frozen=True)
class ContainerConverterEntry:
    """How to convert a runtime value to match a parameterized origin[T,...]."""

    origin: Any
    convert: Callable[["AnnotationConverter", Any, Any], Any]
    name: str | None = None


class ContainerConverterRegistry:
    """Registry mapping generic origins (list/dict/tuple/...) to conversion functions."""

    map: ClassVar[dict[Any, ContainerConverterEntry]] = {}

    @classmethod
    def register(cls, entry: ContainerConverterEntry) -> None:
        cls.map[entry.origin] = entry

    @classmethod
    def get(cls, origin: Any) -> ContainerConverterEntry | None:
        return cls.map.get(origin)


class AnnotationConverter:
    """Converts runtime values to match rich annotations (including nested containers)."""

    def convert(self, value: Any, annotation: Any) -> Any:
        from hassette.conversion import TYPE_MATCHER, TYPE_REGISTRY
        from hassette.models.states import BaseState

        tp = normalize_annotation(annotation, constructible=True)

        # Already correct (deep) => no-op
        if TYPE_MATCHER.matches(value, tp):
            return value

        # Union / Optional: try arms
        if is_union(tp):
            last_err: Exception | None = None
            for arm in get_args(tp):
                try:
                    return self.convert(value, arm)
                except Exception as e:
                    last_err = e
            raise UnableToConvertValueError(f"Unable to convert {value!r} to {tp!r}") from last_err

        # Literal: match exact allowed values (conversion generally not meaningful)
        if get_origin(tp) is Literal:
            allowed = get_args(tp)
            if value in allowed:
                return value
            raise UnableToConvertValueError(f"{value!r} is not one of {allowed!r}")

        origin = get_origin(tp)
        if origin is not None:
            entry = ContainerConverterRegistry.get(origin)
            if entry is not None:
                return entry.convert(self, value, tp)

        # Special case: BaseState subclass conversion from dict
        if isinstance(tp, type) and issubclass(tp, BaseState):
            # NOTE: this expects tp is the concrete model class (LightState, etc.)
            return convert_state_dict_to_model(value, tp)

        # Leaf conversion: tp should be a runtime type
        if isinstance(tp, type):
            return TYPE_REGISTRY.convert(value, tp)

        # Fall back: try converting to origin if that's a runtime type
        if origin is not None and isinstance(origin, type):
            return TYPE_REGISTRY.convert(value, origin)

        raise UnableToConvertValueError(f"Unable to convert {value!r} to {tp!r}")


def register_container_converter(*origins: Any):
    def deco(fn: Callable[["AnnotationConverter", Any, Any], Any]) -> Callable[["AnnotationConverter", Any, Any], Any]:
        for origin in origins:
            ContainerConverterRegistry.register(
                ContainerConverterEntry(origin=origin, convert=fn, name=getattr(fn, "__name__", None))
            )
        return fn

    return deco


@register_container_converter(list, set, frozenset)
def convert_homogeneous_iterable(c: "AnnotationConverter", value: Any, tp: Any) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)

    elem_tp = args[0] if args else Any

    if origin not in (list, set, frozenset):
        raise UnableToConvertValueError(f"Unsupported iterable origin{origin!r}")

    if not isinstance(value, origin):
        raise UnableToConvertValueError(f"Expected {origin.__name__}, got {type(value).__name__}")

    # Strict: only accept the matching concrete container at runtime
    if origin is list:
        return [c.convert(v, elem_tp) for v in value]

    if origin is set:
        return {c.convert(v, elem_tp) for v in value}

    if origin is frozenset:
        return frozenset(c.convert(v, elem_tp) for v in value)

    raise UnableToConvertValueError(f"Unsupported iterable origin: {origin!r}")


@register_container_converter(dict)
def convert_dict(c: "AnnotationConverter", value: Any, tp: Any) -> Any:
    if not isinstance(value, dict):
        raise UnableToConvertValueError(f"Expected dict, got {type(value).__name__}")

    args = get_args(tp)
    key_tp, val_tp = args if len(args) == 2 else (Any, Any)
    return {c.convert(k, key_tp): c.convert(v, val_tp) for k, v in value.items()}


@register_container_converter(tuple)
def convert_tuple(c: "AnnotationConverter", value: Any, tp: Any) -> Any:
    if not isinstance(value, tuple):
        raise UnableToConvertValueError(f"Expected tuple, got {type(value).__name__}")

    args = get_args(tp)
    if not args:
        return value

    if len(args) == 2 and args[1] is Ellipsis:
        elem_tp = args[0]
        return tuple(c.convert(v, elem_tp) for v in value)

    if len(args) != len(value):
        raise UnableToConvertValueError(f"Tuple length mismatch: {len(value)} vs {len(args)}")

    return tuple(c.convert(v, elem_tp) for v, elem_tp in zip(value, args, strict=True))


@register_container_converter(TypedStateChangeEvent)
def convert_typed_state_change_event(c: "AnnotationConverter", value: Any, tp: Any) -> Any:
    # tp is TypedStateChangeEvent[StateT] (already normalized/constructible)
    if not isinstance(value, RawStateChangeEvent):
        raise UnableToConvertValueError(
            f"Cannot convert {type(value).__name__} to TypedStateChangeEvent; expected RawStateChangeEvent"
        )

    args = get_args(tp)
    state_tp = args[0] if args else Any  # TypedStateChangeEvent without args -> Any

    # Use the engine to convert new_state/old_state to the target state type.
    # This automatically handles dict->BaseState and Optional states, etc.
    data = value.payload.data
    entity_id = data.entity_id
    if entity_id is None:
        raise UnableToConvertValueError("State change event data must contain 'entity_id'")

    old_state_obj = None if data.old_state is None else c.convert(data.old_state, state_tp)
    new_state_obj = None if data.new_state is None else c.convert(data.new_state, state_tp)

    data = TypedStateChangePayload(entity_id=entity_id, old_state=old_state_obj, new_state=new_state_obj)
    return TypedStateChangeEvent(
        topic=value.topic,
        payload=HassPayload(
            event_type=value.payload.event_type,
            data=data,
            origin=value.payload.origin,
            time_fired=value.payload.time_fired,
            context=value.payload.context,
        ),
    )
