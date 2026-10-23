# dup-ignore-file: collection-condition dataclasses share __post_init__ + __call__ + summarize by design
"""Conditions receive one or more values extracted from an event and return a boolean indicating
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
    from hassette import C

    await self.bus.on_state_change(
        "sensor.my_phone_location",
        handler=handler,
        changed_to=C.Regex(r"^1101 Main .*"),
        name="phone_location",
    )
    ```

    Value is in a collection

    ```python
    from hassette import C

    await self.bus.on_state_change(
        "sensor.my_phone_activity",
        handler=handler,
        changed_to=C.IsIn(["walking", "running"]),
        name="phone_activity",
    )
    ```

    Using comparison conditions

    ```python
    from hassette import C

    await self.bus.on_state_change(
        "zone.home",
        handler=handler,
        changed=C.Increased(),
        name="zone_home_count",
    )
    ```

"""

import operator
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from hassette.const import MISSING_VALUE
from hassette.conversion.type_registry import TYPE_REGISTRY
from hassette.exceptions import UnableToConvertValueError
from hassette.utils.glob_utils import matches_globs

OPS = Literal[">", "<", ">=", "<=", "==", "!=", "gt", "lt", "ge", "le", "eq", "ne"]
OP_LIST = list(OPS.__args__)

ARROW = "→"
ELLIPSIS_CHAR = "…"

_OP_DISPLAY: dict[str, str] = {"gt": ">", "lt": "<", "ge": ">=", "le": "<=", "eq": "==", "ne": "!="}

_COLLECTION_DISPLAY_LIMIT = 3


def _format_collection(items: Sequence[Any]) -> str:
    if len(items) <= _COLLECTION_DISPLAY_LIMIT:
        return "[" + ", ".join(str(i) for i in items) + "]"
    shown = ", ".join(str(i) for i in items[:_COLLECTION_DISPLAY_LIMIT])
    return f"[{shown}, {ELLIPSIS_CHAR}]"


def coerce_to_literal_type(value: Any, literal: Any) -> Any:
    """Convert a raw string value to the type of the bool or numeric literal it is compared against.

    Home Assistant sends every state as a string (``"on"``, ``"21.5"``), so a literal like ``True`` or ``20``
    never equals the raw value. Bool literals coerce via ``TYPE_REGISTRY`` (``on/off``, ``true/false``,
    ``yes/no``, ``1/0``). Int literals parse the value as an ``int`` first, so large integers keep full precision,
    and fall back to ``float`` for decimal strings like ``"20.0"``; float literals coerce the value to ``float``.
    Non-string values and any other literal type (including ``str``) are returned unchanged, so string comparisons
    keep their exact semantics.

    Args:
        value: The value extracted from the event.
        literal: The literal the value will be compared against.

    Returns:
        The coerced value, or ``value`` unchanged when no coercion applies.

    Raises:
        UnableToConvertValueError: If ``value`` is a string that cannot be converted to the literal's type.
    """
    if not isinstance(value, str):
        return value
    if isinstance(literal, bool):
        return TYPE_REGISTRY.convert(value, bool)
    if isinstance(literal, int):
        try:
            return TYPE_REGISTRY.convert(value, int)
        except UnableToConvertValueError:
            return TYPE_REGISTRY.convert(value, float)
    if isinstance(literal, float):
        return TYPE_REGISTRY.convert(value, float)
    return value


def _validate_collection(collection: Sequence[Any]) -> None:
    if isinstance(collection, str):
        raise ValueError("collection must be a sequence of values, not a string")


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
        """Return True if ``value`` is a string matching ``pattern``; non-strings never match."""
        return isinstance(value, str) and matches_globs(value, (self.pattern,))

    def summarize(self) -> str:
        """Return ``"matches <pattern>"`` (e.g. ``"matches light.*"``)."""
        return f"matches {self.pattern}"

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
        """Return True if ``value`` is a string beginning with ``prefix``; non-strings never match."""
        return isinstance(value, str) and value.startswith(self.prefix)

    def summarize(self) -> str:
        """Return ``"starts with <prefix>"`` (e.g. ``"starts with light."``)."""
        return f"starts with {self.prefix}"

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
        """Return True if ``value`` is a string ending with ``suffix``; non-strings never match."""
        return isinstance(value, str) and value.endswith(self.suffix)

    def summarize(self) -> str:
        """Return ``"ends with <suffix>"`` (e.g. ``"ends with .kitchen"``)."""
        return f"ends with {self.suffix}"

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
        """Return True if ``value`` is a string containing ``substring``; non-strings never match."""
        return isinstance(value, str) and self.substring in value

    def summarize(self) -> str:
        """Return ``"contains <substring>"`` (e.g. ``"contains kitchen"``)."""
        return f"contains {self.substring}"

    def __repr__(self) -> str:
        return f"Contains({self.substring!r})"


@dataclass(frozen=True)
class Regex:
    r"""Callable matcher for regex pattern matching.

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
        """Return True if ``value`` is a string whose start matches ``pattern`` (``re.match`` semantics)."""
        return isinstance(value, str) and self._compiled.match(value) is not None

    def summarize(self) -> str:
        """Return ``"matches /<pattern>/"``, with the pattern between slashes to mark it as a regex."""
        return f"matches /{self.pattern}/"

    def __repr__(self) -> str:
        return f"Regex({self.pattern!r})"


@dataclass(frozen=True)
class Exact:
    """Condition that matches when the value equals ``value`` exactly, with no type coercion.

    A bare literal passed to ``changed_to``/``changed_from`` coerces the raw Home Assistant string to the literal's
    type first (so ``changed_to=True`` matches ``"on"``). Wrap the literal in ``Exact`` to compare against the raw
    value instead.

    Examples:
    ```python
    ValueIs(source=get_attr_new("level"), condition=Exact(1))
    ```
    """

    value: Any

    def __call__(self, value: Any) -> bool:
        """Return True if ``value`` equals the stored value, comparing the raw value without type coercion."""
        return value == self.value

    def summarize(self) -> str:
        """Return ``"exactly <value repr>"`` (e.g. ``"exactly 1"`` or ``"exactly 'on'"``)."""
        return f"exactly {self.value!r}"


@dataclass(frozen=True)
class Present:
    """Condition that checks if a value extracted from an event is present (not MISSING_VALUE)."""

    def __call__(self, value: Any) -> bool:
        """Return True unless ``value`` is the ``MISSING_VALUE`` sentinel."""
        return value is not MISSING_VALUE

    def summarize(self) -> str:
        """Return ``"present"``."""
        return "present"


@dataclass(frozen=True)
class Missing:
    """Condition that checks if a value extracted from an event is missing (MISSING_VALUE)."""

    def __call__(self, value: Any) -> bool:
        """Return True only when ``value`` is the ``MISSING_VALUE`` sentinel."""
        return value is MISSING_VALUE

    def summarize(self) -> str:
        """Return ``"missing"``."""
        return "missing"


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
        _validate_collection(self.collection)
        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        """Return True if ``value`` is a member of ``collection``."""
        return value in self.collection

    def summarize(self) -> str:
        """Return ``"in <collection>"``, listing the collection's items."""
        return f"in {_format_collection(self.collection)}"


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
        _validate_collection(self.collection)
        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        """Return True if ``value`` is not a member of ``collection``."""
        return value not in self.collection

    def summarize(self) -> str:
        """Return ``"not in <collection>"``, listing the collection's items."""
        return f"not in {_format_collection(self.collection)}"


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
        _validate_collection(self.collection)
        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        """Return True if any item of the sequence ``value`` is in ``collection``; a non-sequence never matches."""
        if not isinstance(value, Sequence):
            return False
        # not using actual set operations to allow unhashable items
        return any(item in self.collection for item in value)

    def summarize(self) -> str:
        """Return ``"intersects <collection>"``, listing the collection's items."""
        return f"intersects {_format_collection(self.collection)}"


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
        _validate_collection(self.collection)
        object.__setattr__(self, "collection", self.collection)

    def __call__(self, value: Any) -> bool:
        """Return True if no item of the sequence ``value`` is in ``collection``; a non-sequence always matches."""
        if not isinstance(value, Sequence):
            return True
        # not using actual set operations to allow unhashable items
        return all(item not in self.collection for item in value)

    def summarize(self) -> str:
        """Return ``"does not intersect <collection>"``, listing the collection's items."""
        return f"does not intersect {_format_collection(self.collection)}"


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
        """Return True if ``value`` equals ``condition`` or, for a non-string sequence, contains an item equal to it."""
        if isinstance(value, Sequence) and not isinstance(value, str):
            return any(item == self.condition for item in value)
        return value == self.condition

    def summarize(self) -> str:
        """Return ``"is or contains <condition>"`` (e.g. ``"is or contains light.kitchen"``)."""
        return f"is or contains {self.condition}"


@dataclass(frozen=True)
class IsNone:
    """Condition that checks if a value is None.

    Examples:
    ```python
    ValueIs(source=get_attribute, condition=IsNone())
    ```
    """

    def __call__(self, value: Any) -> bool:
        """Return True if ``value`` is None."""
        return value is None

    def summarize(self) -> str:
        """Return ``"is none"``."""
        return "is none"


@dataclass(frozen=True)
class IsNotNone:
    """Condition that checks if a value is not None.

    Examples:
    ```python
    ValueIs(source=get_attribute, condition=IsNotNone())
    ```
    """

    def __call__(self, value: Any) -> bool:
        """Return True if ``value`` is not None."""
        return value is not None

    def summarize(self) -> str:
        """Return ``"is not none"``."""
        return "is not none"


@dataclass(frozen=True, init=False)
class Comparison:
    """Condition that compares an extracted value to a specified value using a specified comparison operator."""

    compare_to: Any
    """Value to compare against"""

    op: OPS
    """Comparison operator to use"""

    op_fn: Callable[[Any, Any], bool]
    """Operator function"""

    def __init__(self, op: OPS, value: Any):
        object.__setattr__(self, "compare_to", value)
        object.__setattr__(self, "op", op)
        match op:
            case ">" | "gt":
                op_fn = operator.gt
            case "<" | "lt":
                op_fn = operator.lt
            case ">=" | "ge":
                op_fn = operator.ge
            case "<=" | "le":
                op_fn = operator.le
            case "==" | "eq":
                op_fn = operator.eq
            case "!=" | "ne":
                op_fn = operator.ne
            case _:
                raise ValueError(f"Invalid comparison operator {op}. Allowed operators are {OP_LIST}")
        object.__setattr__(self, "op_fn", op_fn)

    def __call__(self, value: Any) -> bool:
        """Return the result of applying ``op`` to ``value`` (coerced to ``compare_to``'s type) and ``compare_to``."""
        # A value that can't be coerced or compared fails closed for every operator, including "!=":
        # an "unavailable" state never satisfies a numeric or bool comparison.
        try:
            return self.op_fn(coerce_to_literal_type(value, self.compare_to), self.compare_to)
        except (TypeError, ValueError, UnableToConvertValueError):
            return False

    def summarize(self) -> str:
        """Return the operator's display symbol followed by ``compare_to`` (e.g. ``"> 20"``)."""
        return f"{_OP_DISPLAY.get(self.op, self.op)} {self.compare_to}"


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
        """Return True if ``new_value`` is numerically greater than ``old_value``, False if either isn't numeric."""
        try:
            return float(new_value) > float(old_value)
        except (TypeError, ValueError):
            return False

    def summarize(self) -> str:
        """Return ``"increased"``."""
        return "increased"


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
        """Return True if ``new_value`` is numerically less than ``old_value``, False if either isn't numeric."""
        try:
            return float(new_value) < float(old_value)
        except (TypeError, ValueError):
            return False

    def summarize(self) -> str:
        """Return ``"decreased"``."""
        return "decreased"


@dataclass(frozen=True)
class CrossedAbove:
    """Comparison condition that checks if a numeric value crossed above a threshold.

    Fires only on the transition: the old value is at or below the threshold and the new value is above it. Later
    updates that stay above the threshold do not fire again. A missing or non-numeric old or new value (such as
    ``unavailable`` or ``unknown``) never fires, so ``unavailable`` → ``26`` does not count as a crossing.
    Boolean values never fire either, so an attribute flipping ``False`` → ``True`` is not read as ``0`` → ``1``.

    Expected to be used with predicates that provide both old and new values, such as StateComparison and
    AttrComparison.

    Examples:
    ```python
    self.on_state_change("sensor.temperature", changed=CrossedAbove(25))
    ```
    """

    threshold: float
    """Value the reading must rise above."""

    def __call__(self, old_value: Any, new_value: Any) -> bool:
        """Return True if ``old_value`` is at or below ``threshold`` and ``new_value`` is above it."""
        if isinstance(old_value, bool) or isinstance(new_value, bool):
            return False
        try:
            return float(old_value) <= self.threshold < float(new_value)
        except (TypeError, ValueError):
            return False

    def summarize(self) -> str:
        """Return ``"crossed above <threshold>"`` (e.g. ``"crossed above 25"``)."""
        return f"crossed above {self.threshold}"


@dataclass(frozen=True)
class CrossedBelow:
    """Comparison condition that checks if a numeric value crossed below a threshold.

    Fires only on the transition: the old value is at or above the threshold and the new value is below it. Later
    updates that stay below the threshold do not fire again. A missing or non-numeric old or new value (such as
    ``unavailable`` or ``unknown``) never fires, and neither does a boolean value.

    Expected to be used with predicates that provide both old and new values, such as StateComparison and
    AttrComparison.

    Examples:
    ```python
    self.on_state_change("sensor.phone_battery", changed=CrossedBelow(20))
    ```
    """

    threshold: float
    """Value the reading must fall below."""

    def __call__(self, old_value: Any, new_value: Any) -> bool:
        """Return True if ``old_value`` is at or above ``threshold`` and ``new_value`` is below it."""
        if isinstance(old_value, bool) or isinstance(new_value, bool):
            return False
        try:
            return float(old_value) >= self.threshold > float(new_value)
        except (TypeError, ValueError):
            return False

    def summarize(self) -> str:
        """Return ``"crossed below <threshold>"`` (e.g. ``"crossed below 20"``)."""
        return f"crossed below {self.threshold}"
