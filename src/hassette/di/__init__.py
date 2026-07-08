"""Shared dependency injection primitives.

Consumers (the event bus, and future consumers like the scheduler) use this package to
inspect handler/predicate signatures, build an injection plan, and resolve kwargs at
dispatch time - without needing to know about each other's source types.

See `design/specs/004-extract-event-handling-di/design.md` for the full architecture.
"""

from .invoker import CallableInvoker
from .matchers import AnnotatedMatcher, TypeMatcher
from .plan import build_injection_plan, validate_di_signature
from .types import AnnotationDetails, InjectionParam, ParameterMatcher, identity

__all__ = [
    "AnnotatedMatcher",
    "AnnotationDetails",
    "CallableInvoker",
    "InjectionParam",
    "ParameterMatcher",
    "TypeMatcher",
    "build_injection_plan",
    "identity",
    "validate_di_signature",
]
