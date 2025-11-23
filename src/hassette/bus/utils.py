import itertools
import logging
import typing
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from functools import lru_cache
from inspect import isawaitable, iscoroutinefunction
from types import UnionType
from typing import Any, TypeAliasType, TypeGuard, Union, get_args, get_origin

from boltons.iterutils import is_collection

from hassette.const import NOT_PROVIDED
from hassette.exceptions import CallListenerError, InvalidDependencyReturnTypeError, UnableToExtractParameterError
from hassette.utils.exception_utils import get_short_traceback

if typing.TYPE_CHECKING:
    from hassette.events import Event
    from hassette.types import ChangeType, Predicate


LOGGER = logging.getLogger(__name__)


@lru_cache
def get_raise_on_incorrect_type():
    """Helper to get the config setting for raising on incorrect dependency types.

    Prevents us from having to pass this flag around everywhere.
    """
    from hassette.context import HASSETTE_CONFIG

    config = HASSETTE_CONFIG.get(None)
    if not config:
        raise RuntimeError("HassetteConfig instance not initialized yet.")

    return config.raise_on_incorrect_dependency_type


@lru_cache
def normalize_for_isinstance(tp: type | UnionType | TypeAliasType) -> tuple[type, ...] | type:
    """Normalize a type annotation for use with isinstance().

    Args:
        tp: The type annotation to normalize.

    Returns:
        A normalized type or tuple of types suitable for isinstance() checks.
    """

    # exit early if we already have a type that works with isinstance()
    with suppress(TypeError):
        isinstance(str, tp)  # type: ignore
        return tp  # pyright: ignore[reportReturnType]

    # Handle PEP 604 unions: A | B | C
    if isinstance(tp, UnionType):
        # returns a tuple of the component types
        value = tuple(normalize_for_isinstance(arg) for arg in tp.__args__)
        value = itertools.chain.from_iterable(arg if isinstance(arg, tuple) else (arg,) for arg in value)
        return tuple(value)

    origin = get_origin(tp)

    # Handle typing.Union[A, B, C]
    if origin is Union:
        args = get_args(tp)
        value = tuple(normalize_for_isinstance(arg) for arg in args)
        value = itertools.chain.from_iterable(arg if isinstance(arg, tuple) else (arg,) for arg in value)
        return tuple(value)

    # if we've hit this point we are no longer dealing with a Union
    if typing.TYPE_CHECKING:
        assert not isinstance(tp, UnionType)

    # Handle type aliases like `TypeAliasType` (3.13's `type` statement)
    # They usually have a `.__value__` that holds the real type.
    value = getattr(tp, "__value__", None)
    if value is not None:
        return normalize_for_isinstance(value)

    # at this point we should no longer be dealing with a TypeAliasType
    if typing.TYPE_CHECKING:
        assert not isinstance(tp, TypeAliasType)

    # Base case: assume it's already a real type or tuple of types
    return tp


def extract_with_error_handling(
    event: "Event[Any]", extractor: Callable[[Any], Any], param_name: str, param_type: type, handler_name: str
) -> Any:
    """Extract a parameter value using the given extractor, with error handling.

    Args:
        event: The event to extract from.
        extractor: The extractor callable.
        param_name: The name of the parameter being extracted.
        param_type: The expected type of the parameter.
        handler_name: The name of the handler function.

    Returns:
        The extracted parameter value.

    Raises:
        CallListenerError: If extraction results in an invalid type.
        UnableToExtractParameterError: If extraction fails for an unexpected reason.
    """

    try:
        extracted_value = extractor(event)
    except InvalidDependencyReturnTypeError as e:
        resolved_type = e.resolved_type
        LOGGER.error(
            "Handler %s - dependency for parameter '%s' of type %s returned invalid type: %s",
            handler_name,
            param_name,
            param_type,
            resolved_type,
        )
        # Re-raise to prevent handler from running with missing/invalid data
        raise CallListenerError(
            f"Listener {handler_name} cannot be called due to invalid dependency "
            f"for parameter '{param_name}' of type {param_type}: {resolved_type}"
        ) from e

    except Exception as e:
        # Log detailed error
        LOGGER.error(
            "Handler %s - failed to extract parameter '%s' of type %s: %s",
            handler_name,
            param_name,
            param_type,
            get_short_traceback(),
        )
        # Re-raise to prevent handler from running with missing/invalid data
        raise UnableToExtractParameterError(param_name, param_type, e) from e

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

    try:
        norm_type = normalize_for_isinstance(param_type)
        if isinstance(param_value, norm_type):
            return
        msg = msg_template % (handler_name, param_name, param_type, type(param_value))

        if get_raise_on_incorrect_type():
            raise CallListenerError(msg)

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

        return AllOf.ensure_iterable(where)  # type: ignore[arg-type]

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
