import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from hassette.const.misc import MISSING_VALUE
from hassette.utils.glob_utils import matches_globs


@dataclass(frozen=True)
class Glob:
    """Callable matcher for string glob patterns.

    Examples
    --------
    Basic::

        ValueIs(source=get_entity_id, condition=Glob("light.*"))

    Multiple patterns (wrap with AnyOf)::

        AnyOf((ValueIs(source=get_entity_id, condition=Glob("light.*")),
               ValueIs(source=get_entity_id, condition=Glob("switch.*"))))
    """

    pattern: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and matches_globs(value, (self.pattern,))

    def __repr__(self) -> str:
        return f"Glob({self.pattern!r})"


@dataclass(frozen=True)
class StartsWith:
    """Callable matcher for string startswith checks.

    Examples
    --------
    Basic::

        ValueIs(source=get_entity_id, condition=StartsWith("light."))

    Multiple prefixes (wrap with AnyOf)::

        AnyOf((ValueIs(source=get_entity_id, condition=StartsWith("light.")),
               ValueIs(source=get_entity_id, condition=StartsWith("switch."))))
    """

    prefix: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and value.startswith(self.prefix)

    def __repr__(self) -> str:
        return f"StartsWith({self.prefix!r})"


@dataclass(frozen=True)
class EndsWith:
    """Callable matcher for string endswith checks.

    Examples
    --------
    Basic::

        ValueIs(source=get_entity_id, condition=EndsWith(".kitchen"))

    Multiple suffixes (wrap with AnyOf)::

        AnyOf((ValueIs(source=get_entity_id, condition=EndsWith(".kitchen")),
               ValueIs(source=get_entity_id, condition=EndsWith(".living_room"))))
    """

    suffix: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and value.endswith(self.suffix)

    def __repr__(self) -> str:
        return f"EndsWith({self.suffix!r})"


@dataclass(frozen=True)
class Contains:
    """Callable matcher for string containment checks.

    Examples
    --------
    Basic::

        ValueIs(source=get_entity_id, condition=Contains("kitchen"))

    Multiple substrings (wrap with AnyOf)::

        AnyOf((ValueIs(source=get_entity_id, condition=Contains("kitchen")),
               ValueIs(source=get_entity_id, condition=Contains("living_room"))))
    """

    substring: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and self.substring in value

    def __repr__(self) -> str:
        return f"Contains({self.substring!r})"


@dataclass(frozen=True)
class Regex:
    """Callable matcher for regex pattern matching.

    Examples
    --------
    Basic::

        ValueIs(source=get_entity_id, condition=Regex(r"light\\..*kitchen"))

    Multiple patterns (wrap with AnyOf)::

        AnyOf((ValueIs(source=get_entity_id, condition=Regex(r"light\\..*kitchen")),
               ValueIs(source=get_entity_id, condition=Regex(r"switch\\..*living_room"))))
    """

    pattern: str
    _compiled: re.Pattern = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_compiled", re.compile(self.pattern))

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and self._compiled.match(value) is not None

    def __repr__(self) -> str:
        return f"Regex({self.pattern!r})"


@dataclass(frozen=True)
class Present:
    """Condition that checks if a value extracted from an event is present (not MISSING_VALUE)."""

    def __call__(self, value: Any) -> bool:
        return value is not MISSING_VALUE


@dataclass(frozen=True)
class Missing:
    """Condition that checks if a value extracted from an event is missing (MISSING_VALUE)."""

    def __call__(self, value: Any) -> bool:
        return value is MISSING_VALUE


@dataclass(frozen=True)
class IsIn:
    """Condition that checks if a value is in a given collection.

    Examples
    --------
    Basic::

        ValueIs(source=get_entity_id, condition=IsIn(collection=["light.kitchen", "light.living"]))

    """

    collection: Sequence[Any]

    def __post_init__(self) -> None:
        if isinstance(self.collection, str):
            raise ValueError("collection must be a sequence of values, not a string")

        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        return value in self.collection


@dataclass(frozen=True)
class NotIn:
    """Condition that checks if a value is not in a given collection.

    Examples
    --------
    Basic::

        ValueIs(source=get_entity_id, condition=NotIn(collection=["light.kitchen", "light.living"]))

    """

    collection: Sequence[Any]

    def __post_init__(self) -> None:
        if isinstance(self.collection, str):
            raise ValueError("collection must be a sequence of values, not a string")

        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        return value not in self.collection


@dataclass(frozen=True)
class Intersects:
    """Condition that checks if a collection value intersects with a given collection.

    Examples
    --------
    Basic::

        ValueIs(source=get_tags, condition=Intersects(collection=["kitchen", "living"]))

    """

    collection: Sequence[Any]

    def __post_init__(self) -> None:
        if isinstance(self.collection, str):
            raise ValueError("collection must be a sequence of values, not a string")

        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        if not isinstance(value, Sequence):
            return False
        # not using actual set operations to allow unhashable items
        return any(item in self.collection for item in value)


@dataclass(frozen=True)
class NotIntersects:
    """Condition that checks if a collection value does not intersect with a given collection.

    Examples
    --------
    Basic::

        ValueIs(source=get_tags, condition=NotIntersects(collection=["kitchen", "living"]))

    """

    collection: Sequence[Any]

    def __post_init__(self) -> None:
        if isinstance(self.collection, str):
            raise ValueError("collection must be a sequence of values, not a string")

        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        if not isinstance(value, Sequence):
            return True
        # not using actual set operations to allow unhashable items
        return all(item not in self.collection for item in value)


@dataclass(frozen=True)
class IsOrContains:
    """Condition that checks if a value is equal to or contained in a given collection.

    Examples
    --------
    Basic::

        # check if the entity_id is either "light.kitchen" or a list containing it

        ValueIs(source=get_entity_id, condition=IsOrContains("light.kitchen"))

    """

    condition: str

    def __call__(self, value: Sequence[Any] | Any) -> bool:
        if isinstance(value, Sequence) and not isinstance(value, str):
            return any(item == self.condition for item in value)
        return value == self.condition
