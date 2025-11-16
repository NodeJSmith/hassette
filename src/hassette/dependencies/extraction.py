import inspect
from collections.abc import Callable
from inspect import Signature, isclass
from typing import Annotated, Any, get_args, get_origin


def is_annotated_type(annotation: Any) -> bool:
    """Check if annotation is an Annotated type."""
    return get_origin(annotation) is Annotated


def is_depends_subclass(annotation: Any) -> bool:
    """Check if annotation is Annotated with a Depends instance."""
    from .classes import Depends

    if not is_annotated_type(annotation):
        return False

    args = get_args(annotation)
    if len(args) < 2:
        return False

    metadata = args[1]
    return isinstance(metadata, Depends)


def is_event_type(annotation: Any) -> bool:
    """Check if annotation is an Event class or subclass."""
    from hassette.events import Event

    if annotation is inspect.Parameter.empty:
        return False

    origin = get_origin(annotation)
    if origin is not None:
        return isclass(origin) and issubclass(origin, Event)

    return isclass(annotation) and issubclass(annotation, Event)


def extract_from_annotated(annotation: Any) -> tuple[Any, Callable] | None:
    """Extract type and extractor from Annotated[Type, extractor].

    Returns:
        Tuple of (type, extractor) if valid Annotated type with callable metadata.
        None otherwise.
    """
    if not is_annotated_type(annotation):
        return None

    args = get_args(annotation)
    if len(args) < 2:
        return None

    base_type, metadata = args[0], args[1]

    # Metadata must be callable (an extractor function)
    if not callable(metadata):
        return None

    return (base_type, metadata)


def extract_from_depends(annotation: Any) -> tuple[Any, Callable] | None:
    """Extract type and extractor from Annotated with Depends instance.

    Returns:
        Tuple of (type, extractor_instance) if valid Annotated with Depends instance.
        None otherwise.
    """
    from .classes import Depends

    if not is_annotated_type(annotation):
        return None

    args = get_args(annotation)
    if len(args) < 2:
        return None

    base_type, metadata = args[0], args[1]

    # Check if metadata is an instance of Depends (including subclasses)
    if isinstance(metadata, Depends):
        return (base_type, metadata)

    return None


def extract_from_event_type(annotation: Any) -> tuple[Any, Callable] | None:
    """Handle plain Event types - user wants the full event passed through.

    Returns:
        Tuple of (Event type, identity function) if annotation is Event subclass.
        None otherwise.
    """
    if not is_event_type(annotation):
        return None

    # Identity function - just pass the event through
    return (annotation, lambda e: e)


def has_dependency_injection(signature: Signature) -> bool:
    """Check if a signature uses any dependency injection."""
    for param in signature.parameters.values():
        if param.annotation is inspect.Parameter.empty:
            continue

        if (
            is_annotated_type(param.annotation)
            or is_depends_subclass(param.annotation)
            or is_event_type(param.annotation)
        ):
            return True

    return False


def validate_di_signature(signature: Signature) -> None:
    """Validate that a signature with DI doesn't have incompatible parameter types.

    Raises:
        ValueError: If signature has VAR_POSITIONAL (*args) or POSITIONAL_ONLY (/) parameters.
    """
    if not has_dependency_injection(signature):
        return

    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise ValueError(f"Handler with dependency injection cannot have *args parameter: {param.name}")

        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            raise ValueError(f"Handler with dependency injection cannot have positional-only parameter: {param.name}")


def extract_from_signature(signature: Signature) -> dict[str, tuple[Any, Callable]]:
    """Extract parameter types and extractors from a function signature.

    Returns a dict mapping parameter name to (type, extractor_callable).
    Validates that DI signatures don't have incompatible parameter kinds.

    Raises:
        ValueError: If signature has incompatible parameters with DI.
    """
    # Validate signature first
    validate_di_signature(signature)

    param_details: dict[str, tuple[Any, Callable]] = {}

    for param in signature.parameters.values():
        annotation = param.annotation

        # Skip parameters without annotations
        if annotation is inspect.Parameter.empty:
            continue

        # Try each extraction strategy in order
        result = (
            extract_from_annotated(annotation)
            or extract_from_depends(annotation)
            or extract_from_event_type(annotation)
        )

        if result:
            param_details[param.name] = result

    return param_details
