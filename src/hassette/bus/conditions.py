"""
Conditions receive one or more values extracted from an event and return a boolean indicating
whether the condition is met.

These are the building blocks for more complex predicates used in event listeners. Any callable
that takes a single value (or two values for comparison conditions) and returns a boolean can be
used as a condition, so you can also implement your own custom conditions or pass lambda functions.

With helpers like `on_state_change` or `on_attribute_change` you will generally pass conditions to `changed_to`
or `changed_from`. These conditions will receive the relevant value extracted from the event. Some helpers also
allow you to pass conditions to `changed`, which will receive both the old and new values for comparison.

Examples:
    Regex matching

    ```python
    from hassette import conditions as C

    self.bus.on_state_change(
        "sensor.my_phone_location",
        handler=handler,
        changed_to=C.Regex(r"^1101 Main .*"),
    )
    ```

    Value is in a collection

    ```python
    from hassette import conditions as C

    self.bus.on_state_change(
        "sensor.my_phone_activity",
        handler=handler,
        changed_to=C.IsIn(["walking", "running"]),
    )
    ```

    Using comparison conditions

    ```python
    from hassette import conditions as C

    self.bus.on_state_change(
        "zone.home",
        handler=handler,
        changed=C.Increased(),
    )
    ```

"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from hassette.const import MISSING_VALUE
from hassette.utils.glob_utils import matches_globs


@dataclass(frozen=True)
class Glob:
    """Callable matcher for string glob patterns.

    Examples:

    ```python
    ValueIs(source=get_entity_id, condition=Glob("light.*"))

    # Multiple patterns (wrap with AnyOf)
    AnyOf((ValueIs(source=get_entity_id, condition=Glob("light.*")),
           ValueIs(source=get_entity_id, condition=Glob("switch.*"))))
    ```
    """

    pattern: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and matches_globs(value, (self.pattern,))

    def __repr__(self) -> str:
        return f"Glob({self.pattern!r})"


@dataclass(frozen=True)
class StartsWith:
    """Callable matcher for string startswith checks.

    Examples:

    ```python
    ValueIs(source=get_entity_id, condition=StartsWith("light."))

    # Multiple prefixes (wrap with AnyOf)
    AnyOf((ValueIs(source=get_entity_id, condition=StartsWith("light.")),
           ValueIs(source=get_entity_id, condition=StartsWith("switch."))))
    ```
    """

    prefix: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and value.startswith(self.prefix)

    def __repr__(self) -> str:
        return f"StartsWith({self.prefix!r})"


@dataclass(frozen=True)
class EndsWith:
    """Callable matcher for string endswith checks.

    Examples:

    ```python
    ValueIs(source=get_entity_id, condition=EndsWith(".kitchen"))

    # Multiple suffixes (wrap with AnyOf)
    AnyOf((ValueIs(source=get_entity_id, condition=EndsWith(".kitchen")),
           ValueIs(source=get_entity_id, condition=EndsWith(".living_room"))))
    ```
    """

    suffix: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and value.endswith(self.suffix)

    def __repr__(self) -> str:
        return f"EndsWith({self.suffix!r})"


@dataclass(frozen=True)
class Contains:
    """Callable matcher for string containment checks.

    Examples:

    ```python
    ValueIs(source=get_entity_id, condition=Contains("kitchen"))

    # Multiple substrings (wrap with AnyOf)
    AnyOf((ValueIs(source=get_entity_id, condition=Contains("kitchen")),
           ValueIs(source=get_entity_id, condition=Contains("living_room"))))
    ```
    """

    substring: str

    def __call__(self, value: Any) -> bool:
        return isinstance(value, str) and self.substring in value

    def __repr__(self) -> str:
        return f"Contains({self.substring!r})"


@dataclass(frozen=True)
class Regex:
    """Callable matcher for regex pattern matching.

    Examples:

    ```python
    ValueIs(source=get_entity_id, condition=Regex(r"light\\..*kitchen"))

    # Multiple patterns (wrap with AnyOf)
    AnyOf((ValueIs(source=get_entity_id, condition=Regex(r"light\\..*kitchen")),
           ValueIs(source=get_entity_id, condition=Regex(r"switch\\..*living_room"))))
    ```
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

    Examples:

    ```python
    ValueIs(source=get_entity_id, condition=IsIn(collection=["light.kitchen", "light.living"]))
    ```
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

    Examples:

    ```python
    ValueIs(source=get_entity_id, condition=NotIn(collection=["light.kitchen", "light.living"]))
    ```
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

    Examples:

    ```python
    ValueIs(source=get_tags, condition=Intersects(collection=["kitchen", "living"]))
    ```
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

    Examples:

    ```python
    ValueIs(source=get_tags, condition=NotIntersects(collection=["kitchen", "living"]))
    ```
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

    Examples:

    ```python
    # check if the entity_id is either "light.kitchen" or a list containing it
    ValueIs(source=get_entity_id, condition=IsOrContains("light.kitchen"))
    ```
    """

    condition: str

    def __call__(self, value: Sequence[Any] | Any) -> bool:
        if isinstance(value, Sequence) and not isinstance(value, str):
            return any(item == self.condition for item in value)
        return value == self.condition


@dataclass(frozen=True)
class IsNone:
    """Condition that checks if a value is None.

    Examples:

    ```python
    ValueIs(source=get_attribute, condition=IsNone())
    ```
    """

    def __call__(self, value: Any) -> bool:
        return value is None


@dataclass(frozen=True)
class IsNotNone:
    """Condition that checks if a value is not None.

    Examples:

    ```python
    ValueIs(source=get_attribute, condition=IsNotNone())
    ```
    """

    def __call__(self, value: Any) -> bool:
        return value is not None


@dataclass(frozen=True)
class Increased:
    """Comparison condition that checks if a numeric value has increased compared to the previous value.

    Expected to be used with predicates that provide both old and new values, such as StateComparison and
    AttrComparison. Returns False on type conversion errors.

    Examples:

    ```python
    self.on_state_change("zone.home", changed=Increased())
    ```
    """

    def __call__(self, old_value: Any, new_value: Any) -> bool:
        try:
            return float(new_value) > float(old_value)
        except (TypeError, ValueError):
            return False


@dataclass(frozen=True)
class Decreased:
    """Comparison condition that checks if a numeric value has decreased compared to the previous value.

    Expected to be used with predicates that provide both old and new values, such as StateComparison and
    AttrComparison. Returns False on type conversion errors.

    Examples:

    ```python
    self.on_state_change("zone.home", changed=Decreased())
    ```
    """

    def __call__(self, old_value: Any, new_value: Any) -> bool:
        try:
            return float(new_value) < float(old_value)
        except (TypeError, ValueError):
            return False
