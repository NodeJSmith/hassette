import inspect
from inspect import Signature, isclass
from types import GenericAlias
from typing import Annotated, Any, get_args, get_origin
from warnings import warn

from hassette.event_handling.dependencies import AnnotationDetails, identity
from hassette.exceptions import DependencyInjectionError
from hassette.utils.type_utils import get_base_type


def is_annotated_type(annotation: Any) -> bool:
    """Check if annotation is an Annotated type."""
    return get_origin(annotation) is Annotated or isinstance(annotation, GenericAlias)


def is_event_type(annotation: Any) -> bool:
    """Check if annotation is an Event class or subclass.

    Does NOT handle Union or Optional types. Use explicit Event types instead:
    - ✅ event: Event
    - ✅ event: RawStateChangeEvent
    - ❌ event: Optional[Event]
    - ❌ event: Event | None
    - ❌ event: Union[Event, RawStateChangeEvent]

    Args:
        annotation: The type annotation to check.

    Returns:
        True if annotation is Event or an Event subclass.
    """
    from hassette.events import Event

    if annotation is inspect.Parameter.empty:
        return False

    # Get the base class for generic types (Event[T] -> Event)
    # For non-generic types, this returns None, so we check annotation directly
    base_type = get_origin(annotation) or annotation

    return isclass(base_type) and issubclass(base_type, Event)


def extract_from_annotated(annotation: Any) -> None | tuple[Any, AnnotationDetails]:
    """Extract type and extractor from Annotated[Type, extractor].

    Returns:
        Tuple of (type, AnnotationDetails) if valid Annotated type with callable metadata.
        None otherwise.
    """
    if not is_annotated_type(annotation):
        return None

    result = _get_base_type_and_details(annotation)
    if result is None:
        return None

    base_type, details = result

    if not isinstance(details, AnnotationDetails):
        if callable(details):
            return (base_type, AnnotationDetails(extractor=details))

        warn(f"Invalid Annotated metadata: {details} is not AnnotationDetails or callable extractor", stacklevel=2)

        return None

    return (base_type, details)


def _get_base_type_and_details(annotation: Any) -> tuple[Any, AnnotationDetails] | None:
    # handle things like `type TypedStateChangeEvent[T] = Annotated[...]`
    if isinstance(annotation, GenericAlias):
        base_type = get_base_type(annotation)

        args = get_args(getattr(annotation, "__value__", None))
        details = args[1]

        return (base_type, details)

    args = get_args(annotation)
    if len(args) < 2:
        return None

    base_type = get_base_type(annotation)

    details = args[1]

    return (base_type, details)


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
