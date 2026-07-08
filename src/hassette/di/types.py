"""Shared data structures for the dependency injection layer.

These types describe *what* a dependency injection plan contains, independent of how the
plan is built (see `di/plan.py`) or how it's dispatched at call time (see `di/invoker.py`).
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def identity(x: Any) -> Any:
    """Identity function - returns the input as-is.

    Used when a parameter needs the full source object without transformation.
    """
    return x


@dataclass(slots=True, frozen=True)
class AnnotationDetails(Generic[T]):
    """Details about an annotation used for dependency injection."""

    extractor: Callable[[T], Any]
    """Function to extract the dependency from the source object."""

    converter: Callable[[Any, Any], Any] | None = None
    """Optional converter function to convert the extracted value to the desired type."""

    source_type: type[T] | None = None
    """The source type this extractor operates on, e.g. `Event` or `ScheduledJob`.

    When `None`, the consuming matcher (e.g. `AnnotatedMatcher`) falls back to its own
    constructor-provided `source_type`. Set this to override the matcher's default on a
    per-annotation basis - for example, an extractor that reads from `StateManager`
    alongside other `Event`-sourced extractors on the same handler.
    """


@dataclass(frozen=True, slots=True)
class InjectionParam:
    """One parameter's resolved injection plan.

    Produced by a `ParameterMatcher` during plan building (`build_injection_plan`) and
    consumed by `CallableInvoker.invoke` at dispatch time.
    """

    name: str
    """The parameter name on the target callable."""

    source_type: type
    """Key to look up in the `available` dict passed to `CallableInvoker.invoke`."""

    target_type: Any
    """The annotation's type, e.g. `LightState` - used by consumers that convert the
    extracted value (the shared layer itself does not convert)."""

    extractor: Callable[[Any], Any]
    """Function that pulls the value out of the source object."""

    converter: Callable[[Any, Any], Any] | None = None
    """Optional converter carried through from `AnnotationDetails.converter`."""


class ParameterMatcher(Protocol):
    """Protocol for matching a single `inspect.Parameter` to an `InjectionParam`.

    Implementations inspect a parameter's annotation and return an `InjectionParam` when
    they recognize it, or `None` when they don't. `build_injection_plan` tries a sequence
    of matchers in order and takes the first match.
    """

    def match(self, param: inspect.Parameter) -> InjectionParam | None: ...
