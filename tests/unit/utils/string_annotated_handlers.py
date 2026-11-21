"""Handlers whose annotations are strings, for `get_typed_signature` tests.

`Payload` exists only in this module, so resolving it against any other module's globals fails.
"""

import functools
from typing import Optional


class Payload:
    pass


def handle(x: "Payload") -> None:
    pass


def handle_two(prefix: str, x: "Payload") -> None:
    pass


def handle_with_unresolvable_return(x: "Payload") -> "NotDefinedAnywhere":  # noqa: F821  # pyright: ignore[reportUndefinedVariable]
    """Its return annotation resolves nowhere, on purpose."""


class CallableHandler:
    def __call__(self, x: "Payload") -> None:
        pass


partial_handler = functools.partial(handle_two, "prefix")


def handle_nested_quotes(x: 'list["Payload"]', y: 'Optional["Payload"]') -> None:  # noqa: UP045
    """Annotations as `from __future__ import annotations` writes them when the source quotes an inner name."""
