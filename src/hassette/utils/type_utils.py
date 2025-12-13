import inspect
import itertools
import typing
from collections.abc import Callable
from contextlib import suppress
from functools import lru_cache
from types import GenericAlias, UnionType
from typing import Any, ForwardRef, Union, get_args, get_origin

from pydantic._internal._typing_extra import try_eval_type
from typing_extensions import TypeAliasType


@lru_cache(maxsize=128)
def normalize_for_isinstance(tp: type | UnionType | TypeAliasType) -> tuple[type, ...] | type:
    """Normalize a type annotation for use with isinstance().

    Args:
        tp: The type annotation to normalize.

    Returns:
        A normalized type or tuple of types suitable for isinstance() checks.
    """

    # exit early if we already have a type that works with isinstance()
    with suppress(TypeError):
        isinstance(str, tp)  # type: ignore
        return tp  # pyright: ignore[reportReturnType]

    # Handle PEP 604 unions: A | B | C
    if isinstance(tp, UnionType):
        # returns a tuple of the component types
        value = tuple(normalize_for_isinstance(arg) for arg in tp.__args__)
        value = itertools.chain.from_iterable(arg if isinstance(arg, tuple) else (arg,) for arg in value)
        return tuple(value)

    origin = get_origin(tp)

    # Handle typing.Union[A, B, C]
    if origin is Union:
        args = get_args(tp)
        value = tuple(normalize_for_isinstance(arg) for arg in args)
        value = itertools.chain.from_iterable(arg if isinstance(arg, tuple) else (arg,) for arg in value)
        return tuple(value)

    # if we've hit this point we are no longer dealing with a Union
    if typing.TYPE_CHECKING:
        assert not isinstance(tp, UnionType)

    # Handle type aliases like `TypeAliasType` (3.13's `type` statement)
    # They usually have a `.__value__` that holds the real type.
    value = getattr(tp, "__value__", None)
    if value is not None:
        return normalize_for_isinstance(value)

    # at this point we should no longer be dealing with a TypeAliasType
    if typing.TYPE_CHECKING:
        assert not isinstance(tp, TypeAliasType)

    # Base case: assume it's already a real type or tuple of types
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


def get_concrete_type_from_generic_annotation(tp: type) -> type | None:
    """If the type is a generic type (e.g., Generic[T]), return the concrete type argument T."""

    if not hasattr(tp, "__orig_bases__"):
        return None

    orig_bases = tp.__orig_bases__

    for base in orig_bases:
        args = get_args(base)
        if args:
            return args[0]

    return None


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


def get_typed_return_annotation(call: Callable[..., Any]) -> Any:
    signature = inspect.signature(call)
    annotation = signature.return_annotation

    if annotation is inspect.Signature.empty:
        return None

    globalns = getattr(call, "__globals__", {})
    return get_typed_annotation(annotation, globalns)


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


def get_base_type(annotation: Any) -> Any:
    """Get the base type from a potentially generic annotation, stopping at Optional or Union types."""
    base_type = get_args(annotation)[0] if isinstance(annotation, GenericAlias) else annotation

    while get_args(base_type):
        # if we're now at the point where base_type is Optional[T], stop unwrapping
        if is_optional_type(base_type) or get_origin(base_type) is UnionType:
            break
        base_type = get_args(base_type)[0]

    return base_type
