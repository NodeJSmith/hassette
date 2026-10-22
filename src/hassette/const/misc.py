import enum
from typing import Literal

# Root of every logger Hassette names; framework loggers and app loggers both live under it.
HASSETTE_LOGGER_NAME = "hassette"

SECONDS_PER_DAY = 86400
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60


class FalseySentinel(enum.Enum):
    """Sentinel values that are falsey in boolean contexts.

    An ``Enum`` so each member is a pickle-stable singleton that type checkers can narrow with
    ``is`` checks (``x is not MISSING_VALUE``) and know to be falsey.

    The member set is closed: ``FalseySentinel("NAME")`` does not create a new sentinel and the class
    cannot be subclassed. Code that needs its own sentinel should define its own ``Enum``.
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
"""Sentinel value to indicate a missing value."""

NOT_PROVIDED = FalseySentinel.NOT_PROVIDED
"""Sentinel value to indicate a value was not provided."""

ANY_VALUE = FalseySentinel.ANY_VALUE
"""Sentinel value to indicate any value is acceptable (used in predicates for presence checks)."""
