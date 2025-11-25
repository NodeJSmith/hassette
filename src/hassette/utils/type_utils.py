import itertools
import typing
from contextlib import suppress
from functools import lru_cache
from types import UnionType
from typing import TypeAliasType, Union, get_args, get_origin


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
