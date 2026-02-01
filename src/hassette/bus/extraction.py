import inspect
from inspect import Signature
from typing import Any
from warnings import warn

from hassette.event_handling.dependencies import AnnotationDetails, identity
from hassette.exceptions import DependencyInjectionError
from hassette.utils.type_utils import get_type_and_details, is_annotated_type, is_event_type, normalize_annotation


def extract_from_annotated(annotation: Any) -> None | tuple[Any, AnnotationDetails[Any]]:
    if not is_annotated_type(annotation):
        return None

    result = get_type_and_details(annotation)
    if result is None:
        return None

    inner_type, details = result

    # Normalize the inner annotation so DI always sees a canonical form
    target_annotation = normalize_annotation(inner_type)

    if isinstance(details, AnnotationDetails):
        return (target_annotation, details)

    if callable(details):
        return (target_annotation, AnnotationDetails(extractor=details))

    warn(f"Invalid Annotated metadata: {details} is not AnnotationDetails or callable extractor", stacklevel=2)
    return None


def extract_from_event_type(annotation: Any) -> None | tuple[Any, AnnotationDetails]:
    """Handle plain Event types - user wants the full event passed through.

    Returns:
        Tuple of (Event type, identity function) if annotation is Event subclass.
        None otherwise.
    """
    if not is_event_type(annotation):
        return None

    return (annotation, AnnotationDetails(extractor=identity))


def has_dependency_injection(signature: Signature) -> bool:
    """Check if a signature uses any dependency injection."""
    for param in signature.parameters.values():
        if param.annotation is inspect.Parameter.empty:
            continue

        if is_annotated_type(param.annotation) or is_event_type(param.annotation):
            return True

    return False


def validate_di_signature(signature: Signature) -> None:
    """Validate that a signature with DI doesn't have incompatible parameter types.

    Raises:
        ValueError: If signature has VAR_POSITIONAL (*args) or POSITIONAL_ONLY (/) parameters.
    """
    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise DependencyInjectionError(
                f"Handler with dependency injection cannot have *args parameter: {param.name}"
            )

        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            raise DependencyInjectionError(
                f"Handler with dependency injection cannot have positional-only parameter: {param.name}"
            )


def extract_from_signature(signature: Signature) -> dict[str, tuple[Any, AnnotationDetails[Any]]]:
    """Extract parameter types and extractors from a function signature.

    Returns a dict mapping parameter name to (type, extractor_callable).
    Validates that DI signatures don't have incompatible parameter kinds.

    Raises:
        ValueError: If signature has incompatible parameters with DI.
    """
    # Validate signature first
    validate_di_signature(signature)

    param_details: dict[str, tuple[Any, AnnotationDetails[Any]]] = {}

    for param in signature.parameters.values():
        annotation = param.annotation

        # Skip parameters without annotations
        if annotation is inspect.Parameter.empty:
            continue

        result = extract_from_annotated(annotation) or extract_from_event_type(annotation)

        if result:
            param_details[param.name] = result

    return param_details
