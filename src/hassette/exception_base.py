"""The base class that makes ``HassetteError`` and its subclasses safe to pickle and deep-copy.

``BaseException.__reduce__`` rebuilds an instance as ``cls(*self.args)``, but a Hassette exception's ``args`` holds its
built message, not its constructor arguments. Replaying that message either raises ``TypeError`` or nests it inside
itself. Capturing the real constructor call keeps subclasses free to take structured arguments with no extra code.
"""

from collections.abc import Callable
from types import BuiltinMethodType
from typing import Any, Self


class ReconstructibleError(Exception):
    """Rebuilds through the original constructor call, then restores ``args`` and instance attributes."""

    _ctor_args: tuple[Any, ...]
    _ctor_kwargs: dict[str, Any]

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        self = super().__new__(cls, *args, **kwargs)
        self._ctor_args, self._ctor_kwargs = args, kwargs
        return self

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Builtin exceptions define their own __new__, so `class X(TypeError, HassetteError)` resolves to
        # TypeError's and never reaches the __new__ above. A wrapped parent resolves to a plain function, so its
        # subclasses aren't wrapped again. OSError is left alone: replacing its __new__ makes it parse the
        # constructor's arguments as (errno, strerror), so OSError mixins keep the stdlib's cls(*self.args) rebuild.
        if isinstance(cls.__new__, BuiltinMethodType) and not issubclass(cls, OSError):
            cls.__new__ = staticmethod(capturing_new(cls.__new__))

    def __reduce__(self) -> str | tuple[Any, ...]:
        if "_ctor_args" not in vars(self):
            return super().__reduce__()
        # BaseException.__setstate__ assigns each key as an attribute, so a rewritten `args` survives too.
        return rebuild_error, (type(self), self._ctor_args, self._ctor_kwargs), {**vars(self), "args": self.args}


def capturing_new(builtin_new: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a builtin exception's ``__new__`` to record the constructor call, as ``ReconstructibleError.__new__`` does.

    Returns:
        A function to install as a subclass's ``__new__``.
    """

    def new(cls: type, *args: Any, **kwargs: Any) -> Any:
        self = builtin_new(cls, *args, **kwargs)
        self._ctor_args, self._ctor_kwargs = args, kwargs
        return self

    return new


def rebuild_error(cls: type[BaseException], args: tuple[Any, ...], kwargs: dict[str, Any]) -> BaseException:
    """Replay a captured constructor call; pickle needs a module-level callable to carry ``kwargs``.

    Returns:
        The new exception instance.
    """
    return cls(*args, **kwargs)
