"""`get_typed_signature` resolves string annotations against the module the signature comes from."""

import functools
import inspect
from collections.abc import Callable
from typing import Any, Optional

import pytest

from hassette.utils.type_utils import get_typed_signature
from tests.unit.utils import string_annotated_handlers as handlers


class WrapperPayload:
    """Exists only in this module, so an explicit `__signature__` built here resolves only against these globals."""


def passthrough(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator defined outside the handler module, whose globals have no `Payload`."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


def invoke(handler: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Target of `partial_decorator`'s partial; its parameters carry no `Payload`, so reading them would be wrong."""
    return handler(*args, **kwargs)


def partial_decorator(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that returns a partial carrying `__wrapped__`, so the signature comes from `func`, not `invoke`."""
    return functools.update_wrapper(functools.partial(invoke, func), func)


def with_explicit_signature(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator whose wrapper overrides its signature with an annotation from this module."""
    wrapper = passthrough(func)
    param = inspect.Parameter("x", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation="WrapperPayload")
    wrapper.__signature__ = inspect.Signature([param])  # pyright: ignore[reportFunctionMemberAccess]
    return wrapper


def test_wrapped_handler_resolves_against_wrapped_module() -> None:
    sig = get_typed_signature(passthrough(handlers.handle))
    assert sig.parameters["x"].annotation is handlers.Payload


def test_partial_handler_resolves_against_partial_func_module() -> None:
    sig = get_typed_signature(handlers.partial_handler)
    assert list(sig.parameters) == ["x"]
    assert sig.parameters["x"].annotation is handlers.Payload


def test_callable_instance_resolves_against_call_method_module() -> None:
    sig = get_typed_signature(handlers.CallableHandler())
    assert sig.parameters["x"].annotation is handlers.Payload


def test_wrapped_partial_resolves_against_partial_func_module() -> None:
    sig = get_typed_signature(passthrough(handlers.partial_handler))
    assert list(sig.parameters) == ["x"]
    assert sig.parameters["x"].annotation is handlers.Payload


def test_partial_based_decorator_resolves_against_wrapped_module() -> None:
    sig = get_typed_signature(partial_decorator(handlers.handle))
    assert sig.parameters["x"].annotation is handlers.Payload


def test_explicit_signature_resolves_against_wrapper_module() -> None:
    sig = get_typed_signature(with_explicit_signature(handlers.handle))
    assert sig.parameters["x"].annotation is WrapperPayload


def test_unresolvable_return_annotation_raises_type_error() -> None:
    with pytest.raises(TypeError, match="NotDefinedAnywhere"):
        get_typed_signature(handlers.handle_with_unresolvable_return)


@pytest.mark.parametrize("annotation", ["1/0", "[1][5]", "not valid python"])
def test_annotation_that_fails_to_evaluate_raises_type_error(annotation: str) -> None:
    def handler(x: Any) -> None:
        pass

    handler.__annotations__["x"] = annotation
    with pytest.raises(TypeError, match="Could not resolve annotations"):
        get_typed_signature(handler)


def test_forward_refs_nested_inside_a_string_annotation_resolve() -> None:
    sig = get_typed_signature(handlers.handle_nested_quotes)
    assert sig.parameters["x"].annotation == list[handlers.Payload]
    assert sig.parameters["y"].annotation == Optional[handlers.Payload]  # noqa: UP045


def test_nested_forward_ref_that_fails_to_evaluate_raises_type_error() -> None:
    def handler(x: Any) -> None:
        pass

    handler.__annotations__["x"] = list["1/0"]
    with pytest.raises(TypeError, match="Could not resolve annotation"):
        get_typed_signature(handler)
