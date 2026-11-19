"""`get_typed_signature` resolves string annotations against the module the signature comes from."""

import functools
from collections.abc import Callable
from typing import Any

from hassette.utils.type_utils import get_typed_signature
from tests.unit.utils import string_annotated_handlers as handlers


def passthrough(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator defined outside the handler module, whose globals have no `Payload`."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return wrapper


def test_wrapped_handler_resolves_against_wrapped_module() -> None:
    sig = get_typed_signature(passthrough(handlers.handle))
    assert sig.parameters["x"].annotation is handlers.Payload


def test_partial_handler_resolves_against_underlying_function_module() -> None:
    sig = get_typed_signature(handlers.partial_handler)
    assert list(sig.parameters) == ["x"]
    assert sig.parameters["x"].annotation is handlers.Payload


def test_callable_instance_resolves_against_call_method_module() -> None:
    sig = get_typed_signature(handlers.CallableHandler())
    assert sig.parameters["x"].annotation is handlers.Payload
