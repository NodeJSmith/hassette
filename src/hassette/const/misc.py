import enum
from typing import Literal

HASSETTE_LOGGER_NAME = "hassette"
"""Root of every logger Hassette names; framework loggers and app loggers both live under it."""

SECONDS_PER_DAY = 86400
"""Number of seconds in a day."""

SECONDS_PER_HOUR = 3600
"""Number of seconds in an hour."""

SECONDS_PER_MINUTE = 60
"""Number of seconds in a minute."""

SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY
"""Number of seconds in a week."""


class FalseySentinel(enum.Enum):
    """Sentinel values that are falsey in boolean contexts.

    An ``Enum`` so each member is a pickle-stable singleton that type checkers can narrow with
    ``is`` checks (``x is not MISSING_VALUE``) and know to be falsey.

    The member set is closed: ``FalseySentinel("NAME")`` does not create a new sentinel and the class
    cannot be subclassed. Code that needs its own sentinel should define its own ``Enum``.

    Compare members with ``is``, not truthiness: valid values such as ``0``, ``False`` and ``""`` are
    falsey too, so ``if not x`` cannot tell a sentinel apart from them or from ``None``.
    """

    MISSING_VALUE = enum.auto()
    NOT_PROVIDED = enum.auto()
    ANY_VALUE = enum.auto()

    def __bool__(self) -> Literal[False]:
        return False

    def __repr__(self) -> str:
        return f"<{self.name}>"

    __str__ = __repr__


MISSING_VALUE = FalseySentinel.MISSING_VALUE
"""Returned by accessors and ``D.Maybe*`` dependencies when a field or attribute does not exist.

Different from ``None``, which means the field exists and is null.
"""

NOT_PROVIDED = FalseySentinel.NOT_PROVIDED
"""Default for optional parameters, such as ``on_state_change(changed_from=..., changed_to=...)``.

Marks an argument the caller didn't pass, so ``None`` stays usable as a real value.
"""

ANY_VALUE = FalseySentinel.ANY_VALUE
"""Predicate condition that matches every value without testing it."""
