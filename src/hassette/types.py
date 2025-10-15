import typing
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeAlias, TypeVar, runtime_checkable

from whenever import Date, PlainDateTime, SystemDateTime, Time

if typing.TYPE_CHECKING:
    from hassette.const.misc import NOT_PROVIDED

    from .events import Event

E_contra = TypeVar("E_contra", bound="Event[Any]", contravariant=True)


@runtime_checkable
class Predicate(Protocol[E_contra]):
    """Protocol for defining predicates that evaluate events."""

    def __call__(self, event: E_contra) -> bool | Awaitable[bool]: ...


class Handler(Protocol[E_contra]):
    """Protocol for defining event handlers."""

    def __call__(self, event: E_contra) -> Awaitable[None] | None: ...


class AsyncHandler(Protocol[E_contra]):
    """Protocol for defining asynchronous event handlers."""

    def __call__(self, event: E_contra) -> Awaitable[None]: ...


class TriggerProtocol(Protocol):
    """Protocol for defining triggers."""

    def next_run_time(self) -> SystemDateTime:
        """Return the next run time of the trigger."""
        ...


@runtime_checkable
class PredicateCallable(Protocol):
    """Protocol for defining callables that evaluate values."""

    def __call__(self, value: "KnownTypes") -> bool: ...


KnownTypes: TypeAlias = SystemDateTime | PlainDateTime | Time | Date | None | float | int | bool | str
"""Alias for all known valid state types."""

ChangeType: TypeAlias = "None | NOT_PROVIDED | KnownTypes | PredicateCallable"  # pyright: ignore[reportInvalidTypeForm]
"""Alias for types that can be used to specify state or attribute changes."""

JobCallable = Callable[..., Awaitable[None]] | Callable[..., Any]
"""Alias for a callable that can be scheduled as a job."""
