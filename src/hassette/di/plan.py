"""Plan building: inspecting a signature to produce a dependency injection plan."""

from collections.abc import Sequence
from inspect import Parameter, Signature

from hassette.exceptions import DependencyInjectionError

from .types import InjectionParam, ParameterMatcher


def validate_di_signature(signature: Signature) -> None:
    """Validate that a handler or predicate signature can be called with keyword arguments only.

    Every bus handler and scheduler ``where=`` predicate goes through this check, whether or not
    its signature uses ``D.*`` dependency injection annotations, because the invoker passes all
    arguments by keyword.

    Raises:
        DependencyInjectionError: If signature has VAR_POSITIONAL (*args) or
            POSITIONAL_ONLY (/) parameters.
    """
    for param in signature.parameters.values():
        if param.kind == Parameter.VAR_POSITIONAL:
            raise DependencyInjectionError(
                f"Handler and predicate signatures cannot have a *args parameter: {param.name}"
            )

        if param.kind == Parameter.POSITIONAL_ONLY:
            raise DependencyInjectionError(
                f"Handler and predicate signatures cannot have a positional-only parameter: {param.name}"
            )


def build_injection_plan(sig: Signature, matchers: Sequence[ParameterMatcher]) -> tuple[InjectionParam, ...]:
    """Walk a signature's parameters and build a dependency injection plan.

    Each parameter is tried against `matchers` in order; the first matcher that returns a
    non-`None` `InjectionParam` wins. Parameters without annotations, and annotated
    parameters that no matcher recognizes, are silently skipped.

    Raises:
        DependencyInjectionError: If the signature has VAR_POSITIONAL or POSITIONAL_ONLY
            parameters (see `validate_di_signature`).
    """
    validate_di_signature(sig)

    params: list[InjectionParam] = []
    for param in sig.parameters.values():
        if param.annotation is Parameter.empty:
            continue

        for matcher in matchers:
            result = matcher.match(param)
            if result is not None:
                params.append(result)
                break

    return tuple(params)


__all__ = ["build_injection_plan", "validate_di_signature"]
