from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, get_args, get_origin

from hassette.utils.type_utils import (
    NoneType,
    is_optional,
    is_union,
    normalize_annotation,
    normalize_for_isinstance,
    safe_isinstance,
)


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
        if not safe_isinstance(value, origin):
            return False

        # Deep match for known container origins
        entry = TypeMatcherRegistry.get(origin)
        if entry is not None:
            return entry.match_fn(self, value, tp)

        # Unknown generic: outer match is the best we can do
        return True


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
