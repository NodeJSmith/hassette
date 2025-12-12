import logging
import typing
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

from hassette.event_handling.predicates import AllOf, is_predicate_collection
from hassette.exceptions import DependencyResolutionError
from hassette.utils.type_utils import get_optional_type_arg, is_optional_type, normalize_for_isinstance

if typing.TYPE_CHECKING:
    from hassette.events import Event
    from hassette.types import Predicate


LOGGER = logging.getLogger(__name__)


@lru_cache
def get_raise_on_incorrect_type():
    """Helper to get the config setting for raising on incorrect dependency types.

    Prevents us from having to pass this flag around everywhere.
    """
    try:
        from hassette.context import get_hassette_config

        config = get_hassette_config()

        return config.raise_on_incorrect_dependency_type
    except Exception:
        return True


def extract_with_error_handling(
    event: "Event[Any]", extractor: Callable[["Event[Any]"], Any], param_name: str, param_type: type
) -> Any:
    """Extract a parameter value using the given extractor, with error handling.

    Args:
        event: The event to extract from.
        extractor: The extractor callable.
        param_name: The name of the parameter being extracted.
        param_type: The expected type of the parameter.

    Returns:
        The extracted parameter value.

    Raises:
        DependencyResolutionError: If extraction or conversion fails.
    """

    try:
        extracted_value = extractor(event)
    except DependencyResolutionError:
        # Already has detailed context, just re-raise for caller to log
        raise
    except Exception as e:
        # Wrap unexpected errors with context
        raise DependencyResolutionError(
            f"Failed to extract parameter '{param_name}' (expected {param_type.__name__})"
        ) from e

    return extracted_value


def warn_or_raise_on_incorrect_type(param_name: str, param_type: type, param_value: Any, handler_name: str) -> None:
    """Warn if a parameter value is not of the expected type.

    Args:
        param_name: The name of the parameter.
        param_type: The expected type of the parameter.
        param_value: The actual value of the parameter.
        handler_name: The name of the handler function.

    Returns:
        None
    """

    msg_template = "Handler %s - parameter '%s' is not of expected type %s (got %s)"

    if is_optional_type(param_type) and param_value is None:
        return

    if is_optional_type(param_type):
        param_type = get_optional_type_arg(param_type)

    try:
        norm_type = normalize_for_isinstance(param_type)
        if isinstance(param_value, norm_type):
            return
        msg = msg_template % (handler_name, param_name, param_type, type(param_value))

        if get_raise_on_incorrect_type():
            raise DependencyResolutionError(
                f"Parameter '{param_name}' type mismatch: "
                f"expected {param_type.__name__}, got {type(param_value).__name__}"
            )

        LOGGER.warning(msg)

    except TypeError as e:
        LOGGER.error(
            "Handler %s - cannot check type of parameter '%s' (expected type: %s): %s",
            handler_name,
            param_name,
            param_type,
            e,
        )


def normalize_where(where: "Predicate | Sequence[Predicate] | None"):
    """Normalize a 'where' clause into a single Predicate (usually AllOf.ensure_iterable), or None.

    - If where is None → None
    - If where is a predicate collection (list/tuple/set/...) → AllOf.ensure_iterable(where)
    - Otherwise (single predicate or mapping handled elsewhere) → where
    """
    if where is None:
        return None

    # prevent circular import only when needed
    if is_predicate_collection(where):
        return AllOf.ensure_iterable(where)

    # help the type checker know that `where` is not an Sequence here
    if typing.TYPE_CHECKING:
        assert not isinstance(where, Sequence)

    return where  # single predicate or mapping gets handled by the caller
