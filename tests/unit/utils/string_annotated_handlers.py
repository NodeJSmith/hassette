"""Handlers whose annotations are strings, for `get_typed_signature` tests.

`Payload` exists only in this module, so resolving it against any other module's globals fails.
"""

from __future__ import annotations  # noqa: TID251 - string annotations are what these tests exercise

import functools


class Payload:
    pass


def handle(x: Payload) -> None:
    pass


def handle_two(prefix: str, x: Payload) -> None:
    pass


class CallableHandler:
    def __call__(self, x: Payload) -> None:
        pass


partial_handler = functools.partial(handle_two, "prefix")
