from dataclasses import dataclass
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

    def __call__(self, value: Any) -> bool:
        import re

        return isinstance(value, str) and re.match(self.pattern, value) is not None

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
