import inspect
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import asdict, dataclass
from functools import lru_cache
from inspect import isclass
from types import UnionType
from typing import Annotated, Any, ClassVar, ForwardRef, Literal, TypeVar, Union, get_args, get_origin

from pydantic._internal._typing_extra import try_eval_type

from hassette.core.state_registry import convert_state_dict_to_model
from hassette.core.type_registry import TYPE_REGISTRY
from hassette.events.hass.hass import HassPayload, RawStateChangeEvent, TypedStateChangeEvent, TypedStateChangePayload
from hassette.exceptions import UnableToConvertValueError
from hassette.models.states import BaseState

NoneType = type(None)


def flatten_types(items: Iterable[type | tuple[type, ...]]) -> tuple[type, ...]:
    """Flatten an iterable of types and/or tuples of types into a single tuple of types."""
    out: list[type] = []
    for it in items:
        if isinstance(it, tuple):
            out.extend(it)
        else:
            out.append(it)
    # optional: dedupe while preserving order
    seen: set[type] = set()
    uniq: list[type] = []
    for tp in out:
        if tp not in seen:
            seen.add(tp)
            uniq.append(tp)
    return tuple(uniq)


@lru_cache(maxsize=256)
def normalize_for_isinstance(tp: Any) -> type | tuple[type, ...]:
    """
    Normalize a type annotation to something usable in isinstance(x, ...).

    Returns either:
      - a single runtime class (type)
      - or a tuple[type, ...] suitable for isinstance(x, tuple_of_types)
    """

    # ---- Unwrap type aliases (`type Foo = ...`) ----
    value = getattr(tp, "__value__", None)
    if value is not None:
        return normalize_for_isinstance(value)

    # ---- Unwrap Annotated[T, ...] ----
    if get_origin(tp) is Annotated:
        return normalize_for_isinstance(get_args(tp)[0])

    # ---- typing.Any ----
    if tp is Any or tp is Any:
        return object

    # ---- TypeVar ----
    if isinstance(tp, TypeVar):
        if tp.__constraints__:
            return flatten_types(normalize_for_isinstance(c) for c in tp.__constraints__)
        if tp.__bound__ is not None:
            return normalize_for_isinstance(tp.__bound__)
        return object

    # ---- PEP 604 union: A | B ----
    if isinstance(tp, UnionType):
        return flatten_types(normalize_for_isinstance(arg) for arg in get_args(tp))

    origin = get_origin(tp)

    # ---- typing.Union[A, B] ----
    if origin is Union:
        return flatten_types(normalize_for_isinstance(arg) for arg in get_args(tp))

    # ---- Parameterized generic: list[int], Sequence[str], Mapping[K,V], etc. ----
    if origin is not None:
        # For isinstance, we can only check against the origin
        # (we cannot check args at runtime with isinstance).
        # Some origins aren't actual classes (rare), so fall back.
        if isinstance(origin, type):
            return origin
        # e.g. typing.NewType returns a function; Protocol may be special; etc.
        # Last resort: try returning origin anyway, or object.
        with suppress(TypeError):
            isinstance("", origin)
            return origin
        return object

    # ---- Base case: should already be a runtime class or tuple of them ----
    if isinstance(tp, tuple):
        # If someone passed a tuple of types already
        return flatten_types(normalize_for_isinstance(x) for x in tp)

    if isinstance(tp, type):
        return tp

    # ---- Things like Literal[...] / Never / etc. ----
    return tp


def is_optional_type(tp: type) -> bool:
    """Return True if the annotation is Optional[...] (i.e. contains None)."""
    origin = get_origin(tp)
    args = get_args(tp)

    if origin is None:
        return False

    return type(None) in args


def get_optional_type_arg(tp: type) -> type:
    """If the annotation is Optional[T], return T; else raise ValueError."""
    if not is_optional_type(tp):
        raise ValueError(f"Type {tp} is not Optional[...]")

    args = get_args(tp)
    non_none_args = [arg for arg in args if arg is not type(None)]

    if len(non_none_args) != 1:
        raise ValueError(f"Optional type {tp} does not have exactly one non-None argument")

    return non_none_args[0]


def get_typed_signature(call: Callable[..., Any]) -> inspect.Signature:
    signature = inspect.signature(call)
    globalns = getattr(call, "__globals__", {})
    typed_params = [
        inspect.Parameter(
            name=param.name,
            kind=param.kind,
            default=param.default,
            annotation=get_typed_annotation(param.annotation, globalns),
        )
        for param in signature.parameters.values()
    ]
    typed_signature = inspect.Signature(typed_params)
    return typed_signature


def get_typed_annotation(annotation: Any, globalns: dict[str, Any]) -> Any:
    if isinstance(annotation, str):
        annotation = ForwardRef(annotation)

    if isinstance(annotation, ForwardRef):
        annotation, _ = try_eval_type(annotation, globalns, globalns)
        if annotation is type(None):
            return None

        if isinstance(annotation, ForwardRef):
            raise TypeError(f"Could not resolve ForwardRef annotation: {annotation}")

    return annotation


def is_union(tp: Any) -> bool:
    origin = get_origin(tp)
    return origin is Union or origin is UnionType


def is_optional(tp: Any) -> bool:
    if not is_union(tp):
        return False
    return any(a is NoneType for a in get_args(tp))


def normalize_constructible(tp: Any) -> Any:
    """
    If tp is typing.List[int] / typing.Dict[str,int] / etc, normalize to
    list[int] / dict[str,int] when possible. Otherwise return tp unchanged.
    """
    origin = get_origin(tp)
    if origin is None:
        return tp

    if not isinstance(origin, type):
        return tp

    args = get_args(tp)
    try:
        # origin is usually a real class like list/dict/tuple
        return origin[args] if args else origin  # pyright: ignore
    except TypeError:
        return tp


def unwrap_annotated(tp: Any) -> Any:
    while get_origin(tp) is Annotated:
        tp = get_args(tp)[0]
    return tp


@dataclass(frozen=True)
class TypeMatcherEntry:
    """How to deeply match a runtime value against a parameterized origin[T,...]."""

    origin: Any
    match_fn: Callable[["TypeMatcher", Any, Any], bool]
    name: str | None = None


class TypeMatcherRegistry:
    """Registry mapping generic origins (list/dict/tuple/...) to deep match functions."""

    map: ClassVar[dict[Any, TypeMatcherEntry]] = {}

    @classmethod
    def register(cls, entry: TypeMatcherEntry) -> None:
        cls.map[entry.origin] = entry

    @classmethod
    def get(cls, origin: Any) -> TypeMatcherEntry | None:
        return cls.map.get(origin)


def register_type_matcher(*origins: Any):
    """Decorator to register deep-matching for one or more generic origins."""

    def deco(fn: Callable[["TypeMatcher", Any, Any], bool]) -> Callable[["TypeMatcher", Any, Any], bool]:
        for origin in origins:
            TypeMatcherRegistry.register(
                TypeMatcherEntry(origin=origin, match_fn=fn, name=getattr(fn, "__name__", None))
            )
        return fn

    return deco


def normalize_annotation(tp: Any, *, constructible: bool = True) -> Any:
    """Peel Annotated + registered wrapper origins until stable.

    If constructible=True, also normalize typing.* generics to builtin equivalents
    where possible (e.g., typing.List[int] -> list[int]).
    """
    tp = unwrap_annotated(tp)

    while True:
        alias_value = getattr(tp, "__value__", None)
        if alias_value is not None:
            tp = unwrap_annotated(alias_value)
            continue

        origin = get_origin(tp)
        if origin is None:
            return tp

        return normalize_constructible(tp) if constructible else tp


class TypeMatcher:
    """Runtime matcher for checking if values already satisfy nested type annotations."""

    def matches(self, value: Any, tp: Any) -> bool:
        tp = normalize_annotation(tp)

        # Any matches everything
        if tp is Any:
            return True

        # Unions (typing.Union[...] and PEP604 A | B share your is_union helper)
        if is_union(tp):
            return any(self.matches(value, arg) for arg in get_args(tp))

        # Optional is covered by union logic above; this is just an early fast-path
        if is_optional(tp):
            return value is None or any(self.matches(value, arg) for arg in get_args(tp) if arg is not NoneType)

        # Literal[...] is *very* useful for DI-style validation
        origin = get_origin(tp)
        if origin is Literal:
            return value in get_args(tp)

        # Non-parameterized type: use normalize_for_isinstance
        if origin is None:
            with suppress(TypeError):
                norm = normalize_for_isinstance(tp)
                return isinstance(value, norm)
            return False

        # Parameterized type: must satisfy outer container/protocol first
        with suppress(TypeError):
            if not isinstance(value, origin):
                return False
        # If origin can't be used with isinstance, treat as non-match (forces conversion).
        # If you'd rather be permissive, return True instead.
        if not _safe_isinstance(value, origin):
            return False

        # Deep match for known container origins
        entry = TypeMatcherRegistry.get(origin)
        if entry is not None:
            return entry.match_fn(self, value, tp)

        # Unknown generic: outer match is the best we can do
        return True


def _safe_isinstance(value: Any, tp: Any) -> bool:
    try:
        return isinstance(value, tp)
    except TypeError:
        return False


TYPE_MATCHER = TypeMatcher()
"""Global matcher instance."""


@register_type_matcher(list, set, frozenset)
def match_homogeneous_iterable(m: TypeMatcher, value: Any, tp: Any) -> bool:
    args = get_args(tp)
    if not args:
        return True
    (elem_tp,) = args
    return all(m.matches(v, elem_tp) for v in value)


@register_type_matcher(dict)
def match_dict(m: TypeMatcher, value: Any, tp: Any) -> bool:
    args = get_args(tp)
    if len(args) != 2:
        return True
    key_tp, val_tp = args
    return all(m.matches(k, key_tp) and m.matches(v, val_tp) for k, v in value.items())


@register_type_matcher(tuple)
def match_tuple(m: TypeMatcher, value: Any, tp: Any) -> bool:
    args = get_args(tp)
    if not args:
        return True

    # tuple[T, ...]
    if len(args) == 2 and args[1] is Ellipsis:
        elem_tp = args[0]
        return all(m.matches(v, elem_tp) for v in value)

    # tuple[T1, T2, ...]
    if len(value) != len(args):
        return False

    # zip(strict=True) would be fine in 3.10+, but keep it simple and explicit
    return all(m.matches(v, elem_tp) for v, elem_tp in zip(value, args, strict=True))


@dataclass(frozen=True)
class ContainerConverterEntry:
    origin: Any
    convert: Callable[["AnnotationConverter", Any, Any], Any]
    name: str | None = None


class ContainerConverterRegistry:
    map: ClassVar[dict[Any, ContainerConverterEntry]] = {}

    @classmethod
    def register(cls, entry: ContainerConverterEntry) -> None:
        cls.map[entry.origin] = entry

    @classmethod
    def get(cls, origin: Any) -> ContainerConverterEntry | None:
        return cls.map.get(origin)


def register_container_converter(*origins: Any):
    def deco(fn: Callable[["AnnotationConverter", Any, Any], Any]) -> Callable[["AnnotationConverter", Any, Any], Any]:
        for origin in origins:
            ContainerConverterRegistry.register(
                ContainerConverterEntry(origin=origin, convert=fn, name=getattr(fn, "__name__", None))
            )
        return fn

    return deco


class AnnotationConverter:
    """Converts runtime values to match rich annotations (including nested containers)."""

    def convert(self, value: Any, annotation: Any) -> Any:
        tp = normalize_annotation(annotation, constructible=True)

        # Already correct (deep) => no-op
        if TYPE_MATCHER.matches(value, tp):
            return value

        # Union / Optional: try arms
        if is_union(tp):
            last_err: BaseException | None = None
            for arm in get_args(tp):
                try:
                    return self.convert(value, arm)
                except BaseException as e:
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


ANNOTATION_CONVERTER = AnnotationConverter()


@register_container_converter(list, set, frozenset)
def convert_homogeneous_iterable(c: AnnotationConverter, value: Any, tp: Any) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)

    elem_tp = args[0] if args else Any

    # Strict: only accept the matching concrete container at runtime
    if origin is list:
        if not isinstance(value, list):
            raise UnableToConvertValueError(f"Expected list, got {type(value).__name__}")
        return [c.convert(v, elem_tp) for v in value]

    if origin is set:
        if not isinstance(value, set):
            raise UnableToConvertValueError(f"Expected set, got {type(value).__name__}")
        return {c.convert(v, elem_tp) for v in value}

    if origin is frozenset:
        if not isinstance(value, frozenset):
            raise UnableToConvertValueError(f"Expected frozenset, got {type(value).__name__}")
        return frozenset(c.convert(v, elem_tp) for v in value)

    raise UnableToConvertValueError(f"Unsupported iterable origin: {origin!r}")


@register_container_converter(dict)
def convert_dict(c: AnnotationConverter, value: Any, tp: Any) -> Any:
    if not isinstance(value, dict):
        raise UnableToConvertValueError(f"Expected dict, got {type(value).__name__}")

    args = get_args(tp)
    key_tp, val_tp = args if len(args) == 2 else (Any, Any)
    return {c.convert(k, key_tp): c.convert(v, val_tp) for k, v in value.items()}


@register_container_converter(tuple)
def convert_tuple(c: AnnotationConverter, value: Any, tp: Any) -> Any:
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
def convert_typed_state_change_event(c: AnnotationConverter, value: Any, tp: Any) -> Any:
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

    # Build typed payload/event without type:ignore by using the concrete StateT at runtime.

    curr_payload = {k: v for k, v in asdict(value.payload).items() if k != "data"}
    payload = TypedStateChangePayload(
        entity_id=entity_id,
        old_state=old_state_obj,
        new_state=new_state_obj,
    )
    return TypedStateChangeEvent(topic=value.topic, payload=HassPayload(**curr_payload, data=payload))


def get_type_and_details(annotation: Any) -> tuple[Any, Any] | None:
    # Unwrap type alias: `type Foo = ...`
    alias_value = getattr(annotation, "__value__", None)
    if alias_value is not None:
        return get_type_and_details(alias_value)

    if not is_annotated_type(annotation):
        return None

    args = get_args(annotation)
    if len(args) < 2:
        return None

    return (args[0], args[1])


def is_annotated_type(annotation: Any) -> bool:
    """True if this annotation is Annotated[...] or an alias whose value is Annotated[...]."""
    value = getattr(annotation, "__value__", None)
    if value is not None:
        return is_annotated_type(value)

    return get_origin(annotation) is Annotated


def is_event_type(annotation: Any) -> bool:
    """Check if annotation is an Event class or subclass.

    Does NOT handle Union or Optional types. Use explicit Event types instead:
    - ✅ event: Event
    - ✅ event: RawStateChangeEvent
    - ❌ event: Optional[Event]
    - ❌ event: Event | None
    - ❌ event: Union[Event, RawStateChangeEvent]

    Args:
        annotation: The type annotation to check.

    Returns:
        True if annotation is Event or an Event subclass.
    """
    from hassette.events import Event

    if annotation is inspect.Parameter.empty:
        return False

    # Get the base class for generic types (Event[T] -> Event)
    # For non-generic types, this returns None, so we check annotation directly
    base_type = get_origin(annotation) or annotation

    return isclass(base_type) and issubclass(base_type, Event)
