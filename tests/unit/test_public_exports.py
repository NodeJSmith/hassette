"""Pin the export surface of hassette's public packages and the exception hierarchy."""

import inspect

import pytest

import hassette
from hassette import config, const, events, exception_base, exceptions, state_errors, types
from hassette.config.models import BlockingIODetectionConfig
from hassette.const.misc import FalseySentinel
from hassette.events.hass.hass import TypedStateChangeEvent, TypedStateChangePayload
from hassette.exceptions import HassetteError, HassetteNotInitializedError
from hassette.types.enums import BlockingIOBehavior, ForgottenAwaitBehavior

EXCEPTION_MODULES = {exceptions.__name__, exception_base.__name__, state_errors.__name__}
"""``hassette.exceptions`` and the modules it re-exports from, split out to keep it under the file-size gate."""


@pytest.mark.parametrize(
    ("module", "name", "expected"),
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
def test_symbol_exported(module: object, name: str, expected: object) -> None:
    """The symbol is listed in the package's ``__all__`` and resolves to the canonical object."""
    assert name in module.__all__  # pyright: ignore[reportAttributeAccessIssue]
    assert getattr(module, name) is expected


def test_exceptions_all_lists_every_public_exception() -> None:
    """``hassette.exceptions.__all__`` names exactly the public exception and warning classes it defines or
    re-exports from its split-out modules.
    """
    defined = {
        name
        for name, member in vars(exceptions).items()
        if inspect.isclass(member)
        and issubclass(member, BaseException)
        and member.__module__ in EXCEPTION_MODULES
        and not name.startswith("_")
    }
    assert set(exceptions.__all__) == defined


def test_hassette_not_initialized_error_is_hassette_error() -> None:
    """``except HassetteError`` catches it, and ``except RuntimeError`` still does."""
    err = HassetteNotInitializedError("x")
    assert isinstance(err, HassetteError)
    assert isinstance(err, RuntimeError)
