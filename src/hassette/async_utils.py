import asyncio
import functools
import inspect
from collections.abc import Awaitable, Callable
from logging import getLogger
from typing import ParamSpec, TypeVar, cast, overload

LOGGER = getLogger(__name__)


P = ParamSpec("P")
R = TypeVar("R")


def _is_async_callable(fn: Callable[..., object]) -> bool:
    """True for coroutine functions, including functools.partial(async_fn)."""
    if asyncio.iscoroutinefunction(fn):
        return True
    if isinstance(fn, functools.partial) and asyncio.iscoroutinefunction(fn.func):  # type: ignore[attr-defined]
        return True
    # unwrap decorated callables (keeps metadata nice, too)
    try:
        unwrapped = inspect.unwrap(fn)  # no-op if not wrapped
    except Exception:
        return False
    return asyncio.iscoroutinefunction(unwrapped)


@overload
def make_async_adapter(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]: ...
@overload
def make_async_adapter(fn: Callable[P, R]) -> Callable[P, Awaitable[R]]: ...


def make_async_adapter(fn: Callable[P, R] | Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """
    Normalize a callable (sync or async) into an async callable with the same signature.

    - If `fn` is async: await it.
    - If `fn` is sync: run it in Hassette's thread pool executor.
    """

    from hassette.core.core import Hassette

    # Keep original metadata for logging/debugging
    def _wrap(meta_src: Callable[..., object], wrapped: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        functools.update_wrapper(wrapped, meta_src)  # preserves __name__/__qualname__/__module__/__wrapped__
        return wrapped

    if _is_async_callable(fn):

        async def _async_fn(*args: P.args, **kwargs: P.kwargs) -> R:
            # Cast solely for type-checkers; at runtime it's already awaitable.
            return await cast("Callable[P, Awaitable[R]]", fn)(*args, **kwargs)

        return _wrap(cast("Callable[..., object]", fn), _async_fn)

    # sync function path
    async def _sync_fn(*args: P.args, **kwargs: P.kwargs) -> R:
        inst = Hassette.get_instance()
        loop = inst._loop
        if not loop:
            raise RuntimeError("Event loop is not running")

        # run_in_executor can't take kwargs; use partial to bind both.
        bound = functools.partial(cast("Callable[P, R]", fn), *args, **kwargs)
        fut = loop.run_in_executor(inst._thread_pool, bound)
        try:
            return await fut
        except Exception:
            fut.cancel()
            raise

    return _wrap(cast("Callable[..., object]", fn), _sync_fn)
