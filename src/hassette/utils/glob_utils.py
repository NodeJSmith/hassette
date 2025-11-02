import typing
from fnmatch import fnmatch

GLOB_CHARS = "*?["
"""Characters that indicate a glob pattern."""


def is_glob(value: str) -> bool:
    """Returns True if the value is a glob pattern.

    Args:
        value: The value to check.

    Returns:
        True if the value is a glob pattern, False otherwise.
    """

    return any(ch in value for ch in GLOB_CHARS)


def split_exact_and_glob(values: typing.Iterable[str]) -> tuple[set[str], tuple[str, ...]]:
    """Splits a list of strings into exact matches and glob patterns.

    Args:
        values: The list of strings to split.

    Returns:
        A tuple containing a set of exact matches and a tuple of glob patterns.
    """

    exact: set[str] = set()
    globs: list[str] = []
    for value in values:
        if any(ch in value for ch in GLOB_CHARS):
            globs.append(value)
        else:
            exact.add(value)
    return exact, tuple(globs)


def matches_globs(value: str, patterns: tuple[str, ...]) -> bool:
    """Returns True if the value matches any of the glob patterns.

    Args:
        value: The value to check.
        patterns: The glob patterns to match against.

    Returns:
        True if the value matches any of the patterns, False otherwise.
    """

    return any(fnmatch(value, pattern) for pattern in patterns)
