"""Pin the export surface of hassette's public packages and the exception hierarchy."""

import inspect

import pytest

import hassette
from hassette import config, const, events, exceptions, types
from hassette.config.models import BlockingIODetectionConfig
from hassette.const.misc import FalseySentinel
from hassette.events.hass.hass import TypedStateChangeEvent, TypedStateChangePayload
from hassette.exceptions import HassetteError, HassetteNotInitializedError
from hassette.types.enums import BlockingIOBehavior, ForgottenAwaitBehavior


@pytest.mark.parametrize(
    ("module", "name", "obj"),
    [
        (events, "TypedStateChangeEvent", TypedStateChangeEvent),
        (events, "TypedStateChangePayload", TypedStateChangePayload),
        (hassette, "TypedStateChangeEvent", TypedStateChangeEvent),
        (hassette, "TypedStateChangePayload", TypedStateChangePayload),
        (const, "FalseySentinel", FalseySentinel),
        (hassette, "FalseySentinel", FalseySentinel),
        (types, "BlockingIOBehavior", BlockingIOBehavior),
        (types, "ForgottenAwaitBehavior", ForgottenAwaitBehavior),
        (config, "BlockingIODetectionConfig", BlockingIODetectionConfig),
    ],
)
def test_symbol_exported(module: object, name: str, obj: object) -> None:
    """The symbol is listed in the package's ``__all__`` and resolves to the canonical object."""
    assert name in module.__all__  # pyright: ignore[reportAttributeAccessIssue]
    assert getattr(module, name) is obj


def test_exceptions_all_lists_every_public_exception() -> None:
    """``hassette.exceptions.__all__`` names exactly the public exception and warning classes it defines."""
    defined = {
        name
        for name, obj in vars(exceptions).items()
        if inspect.isclass(obj)
        and issubclass(obj, BaseException)
        and obj.__module__ == exceptions.__name__
        and not name.startswith("_")
    }
    assert set(exceptions.__all__) == defined


def test_hassette_not_initialized_error_is_hassette_error() -> None:
    """``except HassetteError`` catches it, and ``except RuntimeError`` still does."""
    err = HassetteNotInitializedError("x")
    assert isinstance(err, HassetteError)
    assert isinstance(err, RuntimeError)
