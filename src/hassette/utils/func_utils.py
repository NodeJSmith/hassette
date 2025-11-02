import contextlib
import inspect
from collections.abc import Callable
from functools import lru_cache, partial
from types import MethodType
from typing import Any


def is_async_callable(fn: Callable[..., object] | Any) -> bool:
    """Check if a callable is asynchronous.

    Args:
        fn: The callable to check.

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
    if isinstance(fn, partial):
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


@lru_cache(maxsize=1024)
def callable_name(fn: Any) -> str:
    """Get a human-readable name for a callable object.

    This function attempts to return a string representation of the callable that includes
    its module, class (if applicable), and function name. It handles various types of callables
    including functions, methods, and partials.

    Args:
        fn: The callable object to inspect.

    Returns:
        A string representation of the callable.
    """
    # unwrap decorator chains
    with contextlib.suppress(Exception):
        fn = inspect.unwrap(fn)

    # functools.partial
    if isinstance(fn, partial):
        return f"partial({callable_name(fn.func)})"

    # bound method
    if isinstance(fn, MethodType):
        self_obj = fn.__self__
        cls = type(self_obj).__name__
        return f"{self_obj.__module__}.{cls}.{fn.__name__}"

    # plain function
    if hasattr(fn, "__qualname__"):
        mod = getattr(fn, "__module__", None) or "<unknown>"
        return f"{mod}.{fn.__qualname__}"

    # callable object
    if callable(fn):
        cls = type(fn).__name__
        mod = type(fn).__module__
        return f"{mod}.{cls}.__call__"

    return repr(fn)


def callable_short_name(fn: Any) -> str:
    """Get a short name for a callable object.

    This function returns the last part of the callable's full name, which is typically the
    function or method name.

    Args:
        fn: The callable object to inspect.

    Returns:
        The short name of the callable.
    """

    full_name = callable_name(fn)
    return full_name.split(".")[-1]
