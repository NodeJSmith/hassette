import functools
import inspect
from collections.abc import Callable
from typing import Any


def is_async_callable(fn: Callable[..., object] | Any) -> bool:
    """Check if a callable is asynchronous.

    Args:
        fn (Callable[..., object] | Any): The callable to check.

    Returns:
        True if the callable is asynchronous, False otherwise.

    This function checks for various types of callables, including:
    - Plain async functions
    - functools.partial objects wrapping async functions
    - Callable instances with an async __call__ method
    - Functions decorated with @wraps that preserve the async nature

    """

    # plain async def foo(...)
    if inspect.iscoroutinefunction(fn):
        return True

    # functools.partial of something async
    if isinstance(fn, functools.partial):
        return is_async_callable(fn.func)

    # callable instance with async __call__
    call = getattr(fn, "__call__", None)  # noqa: B004
    if call and inspect.iscoroutinefunction(call):
        return True

    # unwrapped functions (decorated with @wraps)
    if hasattr(fn, "__wrapped__"):
        try:
            unwrapped = inspect.unwrap(fn)  # follows __wrapped__ chain
        except Exception:
            return False
        return inspect.iscoroutinefunction(unwrapped)

    return False
