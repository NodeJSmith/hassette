import inspect
import typing
from collections.abc import Callable, Iterable
from contextlib import suppress
from functools import lru_cache, reduce
from logging import getLogger
from operator import or_
from types import NoneType, UnionType
from typing import Annotated, Any, ForwardRef, TypeVar, TypeVarTuple, Union, Unpack, get_args, get_origin

from pydantic._internal._typing_extra import try_eval_type

LOGGER = getLogger(__name__)

MAX_ALIAS_DEPTH = 64
"""Alias expansions `unwrap_type_alias` performs before treating the alias as cyclic."""

ELEMENT_CONTAINERS: tuple[Any, ...] = (list, set, frozenset)
"""Single-element-type containers `get_normalized_actual_type_from_value` describes as `container[elem]`."""


def flatten_types(items: Iterable[type | tuple[type, ...]]) -> tuple[type, ...]:
    """Flatten an iterable of types and/or tuples of types into a single tuple of types."""
    out: list[type] = []
    for it in items:
        if isinstance(it, tuple):
            out.extend(it)
        else:
            out.append(it)
    seen: set[type] = set()
    uniq: list[type] = []
    for tp in out:
        if tp not in seen:
            seen.add(tp)
            uniq.append(tp)
    return tuple(uniq)


def is_type_alias(tp: Any) -> bool:
    """True if `tp` is a bare type alias.

    Duck-typed on purpose: `typing_extensions.TypeAliasType` (the only alias type on 3.11) is a
    different class from `typing.TypeAliasType` on 3.12+, and both must be recognized.
    """
    return hasattr(tp, "__value__") and hasattr(tp, "__type_params__")


def substitute_alias_args(alias: Any, args: tuple[Any, ...]) -> Any:
    """Return `alias.__value__` with the alias's type parameters replaced by `args`.

    `Foo[int].__value__` forwards to the bare alias and drops the arguments, and CPython exposes no
    public way to substitute them. So build a throwaway `typing.Callable[[*params], value]` whose
    parameters are exactly the alias's, in order, and subscript it: CPython's own substitution then
    handles reordered parameters, `TypeVarTuple` packs, `ParamSpec` lists, and a value that is a bare
    parameter. Trailing parameters left out of `args` take their declared defaults (PEP 696), with any
    earlier parameter a default refers to (`type Dep[T, U = T]`) replaced by its bound argument.

    If CPython rejects the arguments (too few with no defaults), the value is returned unsubstituted.
    """
    type_params = alias.__type_params__
    missing = type_params[len(args) :]
    try:
        if missing and all(getattr(p, "has_default", lambda: False)() for p in missing):
            for i in range(len(args), len(type_params)):
                args = (*args, substitute_params(type_params[:i], type_params[i].__default__, args))
        return substitute_params(type_params, alias.__value__, args)
    except TypeError:
        LOGGER.debug("Could not substitute %r into type alias %r; using its unsubstituted value", args, alias)
        return alias.__value__


def substitute_params(type_params: tuple[Any, ...], value: Any, args: tuple[Any, ...]) -> Any:
    """Replace `type_params` in `value` with `args` through CPython's substitution.

    Raises:
        TypeError: CPython rejects `args` for `type_params`.
    """
    if not type_params:
        return value
    params = [Unpack[p] if isinstance(p, TypeVarTuple) else p for p in type_params]
    # `typing.Callable`, not `collections.abc.Callable`: only the former accepts a parameter list it re-subscripts.
    carrier = typing.Callable[[*params], value]
    substituted = carrier[args]  # pyright: ignore[reportIndexIssue]  # carrier is a runtime generic alias
    return get_args(substituted)[-1]


def unwrap_type_alias(tp: Any) -> Any:
    """Resolve a PEP 695 type alias (`type Foo = ...`), including alias chains, to the type it names.

    A subscripted generic alias (`Foo[int]` for `type Foo[T] = ...`) resolves to the alias's value
    with the alias's type parameters replaced by the subscript's arguments. Anything that is not an
    alias is returned unchanged.
    """
    # A cyclic (`type X = Y; type Y = X`) or ever-growing (`type G[T] = G[list[T]]`) alias never resolves;
    # stop after a depth no real alias chain reaches.
    for _ in range(MAX_ALIAS_DEPTH):
        origin = get_origin(tp)
        if is_type_alias(origin):
            alias, args = origin, get_args(tp)
        elif is_type_alias(tp):
            alias, args = tp, None
        else:
            return tp

        tp = alias.__value__ if args is None else substitute_alias_args(alias, args)

    LOGGER.debug("Type alias did not resolve within %d expansions; stopping at %r", MAX_ALIAS_DEPTH, tp)
    return tp


@lru_cache(maxsize=256)
def normalize_for_isinstance(tp: Any) -> type | tuple[type, ...]:
    """Normalize a type annotation to something usable in isinstance()."""
    tp = normalize_annotation(tp, constructible=False)

    if tp is Any:
        return object

    if isinstance(tp, TypeVar):
        if tp.__constraints__:
            return flatten_types(normalize_for_isinstance(c) for c in tp.__constraints__)
        if tp.__bound__ is not None:
            return normalize_for_isinstance(tp.__bound__)
        return object

    if is_union(tp):
        return flatten_types(normalize_for_isinstance(arg) for arg in get_args(tp))

    origin = get_origin(tp)

    # Parameterized generic: list[int], Sequence[str], Mapping[K,V], etc.
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

    if isinstance(tp, tuple):
        return flatten_types(normalize_for_isinstance(x) for x in tp)

    if isinstance(tp, type):
        return tp

    # Things like Literal[...] / Never / etc.
    return tp


def get_typed_signature(call: Callable[..., Any]) -> inspect.Signature:
    """Return the callable's signature with string and forward-reference parameter annotations resolved.

    ``inspect.signature(eval_str=True)`` evaluates each string annotation against the globals of the function it was
    read from, so ``functools.partial``, ``__wrapped__`` chains and callable instances resolve against the right
    module. ``inspect`` does not evaluate the annotations of an explicit ``__signature__``, so any left as strings
    are resolved in a second pass against ``call.__globals__`` (empty for a partial or callable instance).

    Raises:
        TypeError: If an annotation cannot be resolved. The return annotation is evaluated too, so it must resolve
            even though the returned signature leaves it out.
        ValueError: If ``inspect`` finds no signature for ``call`` (some builtins and C callables).
    """
    try:
        signature = inspect.signature(call, eval_str=True)
    except (ValueError, TypeError):
        raise
    except Exception as exc:
        # eval_str runs eval() on each annotation string, so a bad one can raise anything (NameError, SyntaxError, ...).
        raise TypeError(f"Could not resolve annotations of {call!r}: {exc}") from exc

    # eval_str resolves top-level strings but not forward refs nested inside them (list["Payload"]), and never touches
    # an explicit __signature__. Both are resolved here against call's own globals: exact for a plain function or
    # bound method. A partial or callable instance has no __globals__, so nested refs on those stay unresolved.
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
    """Resolve a string or ``ForwardRef`` annotation against the given globals.

    Forward references nested in a generic (``list["Payload"]``) are resolved too, where the globals allow; a nested
    name the globals lack is left in place.

    Returns:
        The resolved annotation, ``None`` for a ``None`` annotation, or the input unchanged if it is already a type.

    Raises:
        TypeError: If a top-level forward reference cannot be resolved, or a nested one fails to evaluate.
    """
    if isinstance(annotation, str):
        annotation = ForwardRef(annotation)

    if isinstance(annotation, ForwardRef):
        annotation, _ = try_eval_type(annotation, globalns, globalns)
        if annotation is type(None):
            return None

        if isinstance(annotation, ForwardRef):
            raise TypeError(f"Could not resolve ForwardRef annotation: {annotation}")
    elif get_args(annotation):
        try:
            annotation, _ = try_eval_type(annotation, globalns, globalns)
        except Exception as exc:
            raise TypeError(f"Could not resolve annotation {annotation!r}: {exc}") from exc

    return annotation


def is_union(tp: Any) -> bool:
    """Return True if the annotation is a ``typing.Union`` or a PEP 604 ``X | Y`` union."""
    origin = get_origin(tp)
    return origin is Union or origin is UnionType


def is_optional(tp: Any) -> bool:
    """Return True if the annotation is a union that includes ``None``."""
    if not is_union(tp):
        return False
    return any(a is NoneType for a in get_args(tp))


def normalize_constructible(tp: Any) -> Any:
    """Normalize typing aliases like typing.List[int] to builtin generics like list[int].

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
        return origin[args] if args else origin  # pyright: ignore[reportIndexIssue]
    except TypeError:
        return tp


def unwrap_annotated(tp: Any) -> Any:
    """Strip all ``Annotated[...]`` layers from an annotation and return the underlying type."""
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
        alias_value = unwrap_type_alias(tp)
        # An alias still standing after unwrap_type_alias's expansion budget is cyclic; re-expanding it
        # would restart that budget forever, so stop here.
        if alias_value is not tp and not is_type_alias(alias_value) and not is_type_alias(get_origin(alias_value)):
            tp = unwrap_annotated(alias_value)
            continue
        tp = alias_value

        origin = get_origin(tp)
        if origin is None:
            return tp

        return normalize_constructible(tp) if constructible else tp


def safe_isinstance(value: Any, tp: Any) -> bool:
    """Return ``isinstance(value, tp)``, or False if ``tp`` cannot be used with ``isinstance``."""
    try:
        return isinstance(value, tp)
    except TypeError:
        return False


def get_type_and_details(annotation: Any) -> tuple[Any, Any] | None:
    """Split an ``Annotated[T, meta, ...]`` annotation (or a type alias of one) into its type and first metadata item.

    Returns:
        A ``(type, metadata)`` tuple, or None if the annotation is not ``Annotated`` with metadata.
    """
    annotation = unwrap_type_alias(annotation)
    if not is_annotated_type(annotation):
        return None

    args = get_args(annotation)
    if len(args) < 2:
        return None

    return (args[0], args[1])


def is_annotated_type(annotation: Any) -> bool:
    """True if this annotation is Annotated[...] or an alias whose value is Annotated[...]."""
    return get_origin(unwrap_type_alias(annotation)) is Annotated


def make_union(types: set[Any]) -> Any:
    """Create a PEP604 union from a set of type annotations."""
    flat: set[Any] = set()
    for t in types:
        if is_union(t):
            flat.update(get_args(t))
        else:
            flat.add(t)

    if not flat:
        return object
    if len(flat) == 1:
        return next(iter(flat))

    return reduce(or_, sorted(flat, key=type_sort_key))


def type_sort_key(tp: Any) -> tuple[int, str]:
    """Deterministic ordering: None first, then builtins, then by name."""
    if tp is NoneType:
        return (0, "None")
    if isinstance(tp, type):
        return (1, tp.__module__ + "." + tp.__qualname__)
    return (2, str(tp))


def get_normalized_actual_type_from_value(value: Any) -> Any:
    """Return a normalized annotation describing the runtime structure of value."""
    if value is None:
        return NoneType

    if value is Any:
        return Any

    if isinstance(value, dict):
        if not value:
            return dict[Any, Any]
        key_ann = make_union({get_normalized_actual_type_from_value(k) for k in value})
        val_ann = make_union({get_normalized_actual_type_from_value(v) for v in value.values()})
        return dict[key_ann, val_ann]

    for container in ELEMENT_CONTAINERS:
        if isinstance(value, container):
            if not value:
                return container[Any]
            elem_ann = make_union({get_normalized_actual_type_from_value(v) for v in value})
            return container[elem_ann]

    if isinstance(value, tuple):
        if not value:
            return tuple[()]
        elem_anns = tuple(get_normalized_actual_type_from_value(v) for v in value)
        return tuple[elem_anns]

    return type(value)


def format_annotation(tp: Any) -> str:
    """Format a normalized annotation into a clean string."""
    if tp is NoneType:
        return "None"

    if tp is Any:
        return "Any"

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

    if isinstance(tp, type):
        # builtins: str, int, dict, etc.
        if tp.__module__ == "builtins":
            return tp.__name__
        return f"{tp.__module__}.{tp.__qualname__}"

    return str(tp)


def get_pretty_actual_type_from_value(value: Any) -> str:
    """Return a pretty string describing the runtime structure of value."""
    ann = get_normalized_actual_type_from_value(value)
    return format_annotation(ann)
