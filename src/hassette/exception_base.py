"""The base class that makes ``HassetteError`` and its subclasses safe to pickle and deep-copy.

``BaseException.__reduce__`` rebuilds an instance as ``cls(*self.args)``, but a Hassette exception's ``args`` holds its
built message, not its constructor arguments. Replaying that message either raises ``TypeError`` or nests it inside
itself. Capturing the real constructor call keeps subclasses free to take structured arguments with no extra code.
"""

from abc import ABCMeta
from typing import Any


class ConstructorCapturingMeta(ABCMeta):
    """Records each instance's constructor call.

    The capture lives here, not in ``__new__``: builtin exceptions' ``__new__`` wins the lookup when a builtin comes
    first in the MRO, and any Python ``__new__`` makes ``OSError`` parse the constructor's arguments as
    ``(errno, strerror)``. Extending ``ABCMeta`` lets subclasses mix in ``ABC`` without a metaclass conflict.
    """

    def __call__(cls, *args: Any, **kwargs: Any):
        self = super().__call__(*args, **kwargs)
        self._ctor_args, self._ctor_kwargs = args, kwargs
        return self


class ReconstructibleError(Exception, metaclass=ConstructorCapturingMeta):
    """Rebuilds through the original constructor call, then restores ``args`` and instance attributes."""

    _ctor_args: tuple[Any, ...]
    _ctor_kwargs: dict[str, Any]

    def __reduce_ex__(self, protocol: Any) -> str | tuple[Any, ...]:
        # __reduce_ex__, not __reduce__: pickle and copy call it first, and OSError defines a __reduce__ that would win
        # the lookup for a subclass with OSError first in its MRO.
        if "_ctor_args" not in vars(self):
            return super().__reduce_ex__(protocol)
        # BaseException.__setstate__ assigns each key as an attribute, so a rewritten `args` survives too.
        return rebuild_error, (type(self), self._ctor_args, self._ctor_kwargs), {**vars(self), "args": self.args}


def rebuild_error(cls: type[BaseException], args: tuple[Any, ...], kwargs: dict[str, Any]) -> BaseException:
    """Replay a captured constructor call; pickle needs a module-level callable to carry ``kwargs``.

    Returns:
        The new exception instance.
    """
    return cls(*args, **kwargs)
