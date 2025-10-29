import contextlib
import typing
from collections.abc import Generator
from contextvars import ContextVar
from typing import Any, TypeVar

if typing.TYPE_CHECKING:
    from hassette import Hassette, HassetteConfig, TaskBucket

T = TypeVar("T")

CURRENT_BUCKET: ContextVar["TaskBucket | None"] = ContextVar("CURRENT_BUCKET", default=None)
HASSETTE_INSTANCE: ContextVar["Hassette | None"] = ContextVar("HASSETTE_INSTANCE", default=None)
HASSETTE_CONFIG: ContextVar["HassetteConfig | None"] = ContextVar("HASSETTE_CONFIG", default=None)


@contextlib.contextmanager
def use(var: ContextVar[T], value: T) -> Generator[None, Any, None]:
    """Temporarily set a ContextVar to `value` within a block."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)
