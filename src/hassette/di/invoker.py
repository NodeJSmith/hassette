"""Dispatch: resolving a built plan into kwargs at call time."""

from dataclasses import dataclass
from typing import Any

from .types import InjectionParam


@dataclass(frozen=True, slots=True)
class CallableInvoker:
    """Resolves a dependency injection plan into kwargs at call time.

    Does not store or call the target callable - the caller is responsible for invoking
    the target with the resolved kwargs. This keeps the shared layer agnostic to how (or
    whether) the target is sync/async, a function, or a bound method.
    """

    params: tuple[InjectionParam, ...]

    def invoke(self, available: dict[type, Any]) -> dict[str, Any]:
        """Build kwargs for the target callable from `available` source objects.

        Args:
            available: Maps a source type to the live object of that type, e.g.
                `{Event: event}`. Lookup is exact-match - no `isinstance` fallback.

        Raises:
            KeyError: If a param's `source_type` has no entry in `available`.
        """
        return {param.name: param.extractor(available[param.source_type]) for param in self.params}


__all__ = ["CallableInvoker"]
