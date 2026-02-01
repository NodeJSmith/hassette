import inspect
from collections.abc import Callable, Iterable
from contextlib import suppress
from functools import lru_cache
from inspect import isclass
from types import UnionType
from typing import Annotated, Any, ForwardRef, TypeVar, Union, get_args, get_origin

from pydantic._internal._typing_extra import try_eval_type

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


def safe_isinstance(value: Any, tp: Any) -> bool:
    try:
        return isinstance(value, tp)
    except TypeError:
        return False


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


def _make_union(types: set[Any]) -> Any:
    """Create a PEP604 union from a set of type annotations."""
    # Flatten nested unions
    flat: set[Any] = set()
    for t in types:
        if isinstance(t, UnionType) or (get_origin(t) is None and isinstance(t, UnionType)):
            flat.update(get_args(t))
        else:
            # Handle both A|B and typing.Union[...] via get_origin
            o = get_origin(t)
            if o is UnionType:
                flat.update(get_args(t))
            else:
                flat.add(t)

    # Also flatten typing.Union if any slipped in
    really_flat: set[Any] = set()
    for t in flat:
        o = get_origin(t)
        if o is None:
            really_flat.add(t)
        else:
            # PEP604 unions report origin types.UnionType in 3.10+ via get_origin?
            # But typing.Union reports origin typing.Union.
            if str(o).endswith("typing.Union"):
                really_flat.update(get_args(t))
            else:
                really_flat.add(t)

    # Dedupe / stable
    if not really_flat:
        return object
    if len(really_flat) == 1:
        return next(iter(really_flat))

    # Build A | B | C
    out = None
    for t in sorted(really_flat, key=lambda x: _type_sort_key(x)):
        out = t if out is None else (out | t)
    return out


def _type_sort_key(tp: Any) -> tuple[int, str]:
    """Stable-ish ordering: None first, then builtins, then by name."""
    if tp is NoneType:
        return (0, "None")
    if isinstance(tp, type):
        return (1, tp.__module__ + "." + tp.__qualname__)
    return (2, str(tp))


def get_normalized_actual_type_from_value(value: Any) -> Any:
    """Return a normalized annotation describing the runtime structure of value."""
    # None
    if value is None:
        return NoneType

    if value is Any:
        return Any

    # dict
    if isinstance(value, dict):
        if not value:
            return dict[Any, Any]
        key_ann = _make_union({get_normalized_actual_type_from_value(k) for k in value})
        val_ann = _make_union({get_normalized_actual_type_from_value(v) for v in value.values()})
        return dict[key_ann, val_ann]

    # list / set / frozenset
    if isinstance(value, list):
        if not value:
            return list[Any]
        elem_ann = _make_union({get_normalized_actual_type_from_value(v) for v in value})
        return list[elem_ann]

    if isinstance(value, set):
        if not value:
            return set[Any]
        elem_ann = _make_union({get_normalized_actual_type_from_value(v) for v in value})
        return set[elem_ann]

    if isinstance(value, frozenset):
        if not value:
            return frozenset[Any]
        elem_ann = _make_union({get_normalized_actual_type_from_value(v) for v in value})
        return frozenset[elem_ann]

    # tuple (optional but often handy)
    if isinstance(value, tuple):
        if not value:
            return tuple[()]
        elem_anns = tuple(get_normalized_actual_type_from_value(v) for v in value)
        return tuple[elem_anns]

    # leaf type
    return type(value)


def format_annotation(tp: Any) -> str:
    """Format a normalized annotation into a clean string."""
    # NoneType
    if tp is NoneType:
        return "None"

    if tp is Any:
        return "Any"

    # PEP604 union
    if isinstance(tp, UnionType):
        parts = [format_annotation(a) for a in get_args(tp)]
        # Keep None first for readability: None | str
        parts.sort(key=lambda s: (0 if s == "None" else 1, s))
        return " | ".join(parts)

    origin = get_origin(tp)
    if origin is not None:
        args = get_args(tp)

        # tuple[()]
        if origin is tuple and args == ((),):
            return "tuple[()]"

        name = origin.__name__ if hasattr(origin, "__name__") else str(origin)
        if args:
            inner = ", ".join(format_annotation(a) for a in args)
            return f"{name}[{inner}]"
        return name

    # plain class/type
    if isinstance(tp, type):
        # builtins: str, int, dict, etc.
        if tp.__module__ == "builtins":
            return tp.__name__
        return f"{tp.__module__}.{tp.__qualname__}"

    # fallback
    return str(tp)


def get_pretty_actual_type_from_value(value: Any) -> str:
    """Return a pretty string describing the runtime structure of value."""
    ann = get_normalized_actual_type_from_value(value)
    return format_annotation(ann)
