from typing_extensions import Sentinel


class FalseySentinel(Sentinel):
    """A Sentinel subclass that is Falsey in boolean contexts."""

    def __bool__(self) -> bool:
        return False


MISSING_VALUE = FalseySentinel("MISSING_VALUE")
"""Sentinel value to indicate a missing value."""

NOT_PROVIDED = FalseySentinel("NOT_PROVIDED")
"""Sentinel value to indicate a value was not provided."""

ANY_VALUE = FalseySentinel("ANY_VALUE")
"""Sentinel value to indicate any value is acceptable (used in predicates for presence checks)."""
