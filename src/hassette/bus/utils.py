import logging
import typing
from collections.abc import Callable, Mapping, Sequence
from functools import lru_cache
from inspect import isawaitable, iscoroutinefunction
from typing import Any, TypeGuard

from boltons.iterutils import is_collection

from hassette.const import NOT_PROVIDED
from hassette.exceptions import DependencyResolutionError
from hassette.utils.type_utils import get_optional_type_arg, is_optional_type, normalize_for_isinstance

if typing.TYPE_CHECKING:
    from hassette.events import Event
    from hassette.types import ChangeType, Predicate


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


def _is_predicate_collection(obj: Any) -> TypeGuard[Sequence["Predicate"]]:
    """Return True for *predicate collections* we want to recurse into.

    We treat only list/tuple/set/frozenset-like things as collections of predicates.
    We explicitly DO NOT recurse into:
      - mappings (those feed ServiceDataWhere elsewhere),
      - strings/bytes,
      - callables (predicates are callables; don't explode them),
      - None.
    """
    if obj is None:
        return False
    if callable(obj):
        return False
    if isinstance(obj, (str, bytes, Mapping)):
        return False
    # boltons.is_collection filters out scalars for us; we just fence off types we don't want
    return is_collection(obj)


def normalize_where(where: "Predicate | Sequence[Predicate] | None"):
    """Normalize a 'where' clause into a single Predicate (usually AllOf.ensure_iterable), or None.

    - If where is None → None
    - If where is a predicate collection (list/tuple/set/...) → AllOf.ensure_iterable(where)
    - Otherwise (single predicate or mapping handled elsewhere) → where
    """
    if where is None:
        return None

    # prevent circular import only when needed
    if _is_predicate_collection(where):
        from .predicates import AllOf

        return AllOf.ensure_iterable(where)

    # help the type checker know that `where` is not an Sequence here
    if typing.TYPE_CHECKING:
        assert not isinstance(where, Sequence)

    return where  # single predicate or mapping gets handled by the caller


def ensure_tuple(where: "Predicate | Sequence[Predicate]") -> tuple["Predicate", ...]:
    """Ensure the 'where' is a flat tuple of predicates, flattening *only* predicate collections.

    Recurses into list/tuple/set/frozenset; leaves Mapping, strings/bytes, and callables intact.
    """
    if _is_predicate_collection(where):
        out: list[Predicate] = []
        # mypy/pyright: guarded by _is_predicate_collection, so safe to iterate
        for item in typing.cast("Sequence[Predicate | Sequence[Predicate]]", where):
            out.extend(ensure_tuple(item))
        return tuple(out)

    return (typing.cast("Predicate", where),)


def compare_value(actual: Any, condition: "ChangeType") -> bool:
    """Compare an actual value against a condition.

    Args:
        actual: The actual value to compare.
        condition: The condition to compare against. Can be a literal value or a callable.

    Returns:
        True if the actual value matches the condition, False otherwise.

    Behavior:
        - If condition is NOT_PROVIDED, treat as 'no constraint' (True).
        - If condition is a non-callable, compare for equality only.
        - If condition is a callable, call and ensure bool.
        - Async/coroutine predicates are explicitly disallowed (raise).

    Warnings:
        - This function does not handle collections any differently than other literals, it will compare
            them for equality only. Use specific conditions like IsIn/NotIn/Intersects for collection membership tests.
    """
    if condition is NOT_PROVIDED:
        return True

    if not callable(condition):
        return actual == condition

    # Disallow async predicates to keep filters pure/fast.
    if iscoroutinefunction(condition):
        raise TypeError("Async predicates are not supported; make the condition synchronous.")

    if typing.TYPE_CHECKING:
        condition = typing.cast("Callable[[Any], bool]", condition)

    result = condition(actual)

    if isawaitable(result):
        raise TypeError("Predicate returned an awaitable; make it return bool.")

    # Fallback: callable but not declared as PredicateCallable; still require bool.
    if not isinstance(result, bool):
        raise TypeError(f"Predicate must return bool, got {type(result)}")
    return result
