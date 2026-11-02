"""Unit tests pinning structural contracts in :mod:`hassette.exceptions`.

The round-trip tests pin that every exception survives pickle and ``copy.deepcopy`` with its message and
attributes intact, however its constructor is shaped.

The ``FailedMessageError`` tests pin the structured-error-surface contract that the helper CRUD
work packages rely on. In particular they guard against the most likely
implementation mistake (``from_error_response`` dropping its ``code`` and
``original_data`` kwargs before delegating to ``cls(msg)``) and verify that
positional-only construction remains backward compatible so every existing
``FailedMessageError("msg")`` call site continues to work.

See ``design/specs/031-helper-crud-api/design.md`` for the full spec.
"""

import copy
import inspect
import pickle
from abc import ABC
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from hassette import exceptions as exceptions_module
from hassette.conversion.validation import RegistryValidationIssue
from hassette.core.websocket_reconnect import CoreShuttingDownError
from hassette.exceptions import (
    AppBlockedError,
    AppRemovedError,
    AuthTokenWriteError,
    CannotOverrideFinalError,
    ConnectionClosedError,
    ConvertedTypeDoesNotMatchError,
    DomainNotFoundError,
    DomainRequiredError,
    DuplicateListenerError,
    EntityNotInViewError,
    EntityShapeError,
    FailedMessageError,
    HassetteError,
    HttpRequestError,
    InvalidAuthError,
    InvalidDataForStateConversionError,
    InvalidEntityIdError,
    JobRemovedError,
    LifecycleReentryError,
    ListenerNameRequiredError,
    NoDomainAnnotationError,
    OutcomeUnknownError,
    RegistryNotReadyError,
    RegistryValidationError,
    ResponseLostError,
    ResponseTimeoutError,
    RestartRefusedError,
    RetryableConnectionClosedError,
    SchedulerNameRequiredError,
    SensorShapeMismatchError,
    UnableToConvertAnnotatedStateError,
    UnableToConvertStateError,
)
from hassette.models.states.sensor_shapes import EnumSensorState, NumericSensorState
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult
from hassette.schemas.app_outcomes import InstanceOutcome, OutcomeResult

ROUND_TRIPS: dict[str, Callable[[Any], Any]] = {
    "pickle": lambda err: pickle.loads(pickle.dumps(err)),  # noqa: S301
    "deepcopy": copy.deepcopy,
}

INSTANCE_OUTCOME = InstanceOutcome(instance_index=0, instance_name="kitchen", result=OutcomeResult.REFUSED)

# Every hassette.exceptions class with its own ``__init__`` (except abstract EntityShapeError), plus classes that
# inherit a structured ``__init__``, and CoreShuttingDownError, the one defined outside that module.
ROUND_TRIP_SAMPLES: list[HassetteError] = [
    AppBlockedError("blocked", outcomes=(INSTANCE_OUTCOME,)),
    AppRemovedError("removed", outcomes=(INSTANCE_OUTCOME,)),
    AuthTokenWriteError(Path("/tmp/token"), PermissionError(13, "denied")),
    CannotOverrideFinalError("initialize", "Resource", "my.App", suggested_alt="on_initialize", location="a.py:3"),
    ConvertedTypeDoesNotMatchError("sensor.mode", NumericSensorState, EnumSensorState),
    CoreShuttingDownError("NOT_RUNNING"),
    DomainNotFoundError("light"),
    DomainRequiredError(NumericSensorState),
    DuplicateListenerError("kitchen", "hass.event.state_changed", "a.handler", "b.handler"),
    EntityNotInViewError("sensor.mode", "enum", NumericSensorState),
    FailedMessageError("boom", code="not_found", original_data={"type": "x"}),
    HttpRequestError(500, "Server Error", method="GET", url="/states"),
    InvalidDataForStateConversionError({"bad": "data"}),
    InvalidEntityIdError("not an id"),
    JobRemovedError("nightly", db_id=7),
    LifecycleReentryError("my.App", "shutdown"),
    ListenerNameRequiredError("a.handler", "hass.event.state_changed"),
    NoDomainAnnotationError(NumericSensorState, accessor_hint="sensor.numeric"),
    RegistryNotReadyError(),
    RegistryValidationError(
        [
            RegistryValidationIssue(registry="STATE_REGISTRY", severity="error", message="bad"),
            RegistryValidationIssue(registry="TYPE_REGISTRY", severity="warning", message="odd"),
        ]
    ),
    ResponseLostError("connection lost", close_code=1006),
    ResponseTimeoutError("timed out", original_data={"type": "fire_event"}),
    RestartRefusedError("my.App", ShutdownOutcome(ShutdownResult.INCOMPLETE, ("task-1",), "my.App: body raised")),
    RetryableConnectionClosedError("dropped", close_code=1006),
    SchedulerNameRequiredError("a.handler", "every 5s"),
    SensorShapeMismatchError("sensor.mode", "enum", NumericSensorState),
    UnableToConvertAnnotatedStateError("sensor.mode", "enum", NumericSensorState),
    UnableToConvertStateError("sensor.mode", NumericSensorState),
]


class BuiltinFirstError(ValueError, HassetteError):
    """A user-style subclass with a builtin exception ahead of ``HassetteError`` in its MRO."""

    def __init__(self, entity_id: str, *, retries: int = 0) -> None:
        super().__init__(f"bad entity {entity_id}")
        self.entity_id = entity_id
        self.retries = retries


class OSErrorFirstError(OSError, HassetteError):
    """A user-style subclass with ``OSError`` ahead of ``HassetteError`` and a multi-argument constructor."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path


class HassetteFirstOSError(HassetteError, ConnectionError):
    """A user-style subclass with ``HassetteError`` ahead of an ``OSError`` family builtin."""

    def __init__(self, host: str, reason: str) -> None:
        super().__init__(f"{host}: {reason}")
        self.host = host


class AbstractBaseError(HassetteError, ABC):
    """A user-style abstract exception base, which must not hit a metaclass conflict."""


class ConcreteAbcError(AbstractBaseError):
    def __init__(self, entity_id: str, reason: str) -> None:
        super().__init__(f"{entity_id}: {reason}")


def test_failed_message_error_backward_compat_positional_only() -> None:
    """Positional-only construction continues to work.

    All existing call sites in ``src/`` pass a single positional ``msg`` and
    nothing else. This test pins that behavior: no kwargs must be required,
    and the two new attributes must default to ``None``.
    """
    e = FailedMessageError("boom")

    assert str(e) == "boom"
    assert e.code is None
    assert e.original_data is None


def test_failed_message_error_stores_kwargs() -> None:
    """``code`` and ``original_data`` are stored as instance attributes."""
    e = FailedMessageError(
        "boom",
        code="invalid_format",
        original_data={"source": "test"},
    )

    assert str(e) == "boom"
    assert e.code == "invalid_format"
    assert e.original_data == {"source": "test"}


def test_failed_message_error_from_error_response_forwards_all_fields() -> None:
    """``from_error_response`` forwards every field AND fixes the typo.

    If the classmethod body still reads ``return cls(msg)`` instead of
    ``return cls(msg, code=code, original_data=original_data)``, the
    ``e.code`` / ``e.original_data`` assertions below will fail.

    The ``"for failed"`` assertion guards the typo fix — the old message
    template read ``"WebSocket message for failed with response ..."``.
    """
    e = FailedMessageError.from_error_response(
        error="already exists",
        code="invalid_format",
        original_data={"type": "input_boolean/create"},
    )

    assert e.code == "invalid_format"
    assert e.original_data == {"type": "input_boolean/create"}
    assert "WebSocket message failed" in str(e)
    assert "for failed" not in str(e)
    assert "already exists" in str(e)


def test_failed_message_error_from_error_response_defaults_code_to_none() -> None:
    """The new ``code`` parameter is optional and defaults to ``None``.

    This keeps the classmethod backward compatible with any caller that was
    only passing ``error`` and/or ``original_data``.
    """
    e = FailedMessageError.from_error_response(error="x")

    assert e.code is None
    assert e.original_data is None
    assert "x" in str(e)


def test_failed_message_error_chain_preserves_original() -> None:
    """Chaining via ``raise ... from e`` preserves ``code`` on both frames.

    This is a regression test for the ``_ws_helper_call`` wrapper. The wrapper
    catches ``FailedMessageError`` and re-raises a new one with a contextualized
    message, forwarding ``code`` and ``original_data`` from the caught exception.
    Both the wrapped exception and ``__cause__`` must surface the same ``code``.
    """

    def _chain_and_reraise() -> None:
        try:
            raise FailedMessageError("first", code="a", original_data={"k": 1})
        except FailedMessageError as exc:
            raise FailedMessageError(
                "wrapped",
                code=exc.code,
                original_data=exc.original_data,
            ) from exc

    with pytest.raises(FailedMessageError) as exc_info:
        _chain_and_reraise()

    wrapped = exc_info.value
    assert wrapped.code == "a"
    assert wrapped.original_data == {"k": 1}
    assert str(wrapped) == "wrapped"

    cause = wrapped.__cause__
    assert isinstance(cause, FailedMessageError)
    assert cause.code == "a"
    assert cause.original_data == {"k": 1}


def test_retryable_connection_closed_error_default_close_code() -> None:
    """close_code defaults to None when not provided."""
    e = RetryableConnectionClosedError("connection dropped")

    assert str(e) == "connection dropped"
    assert e.close_code is None


def test_retryable_connection_closed_error_with_close_code() -> None:
    """close_code is stored when provided as keyword argument."""
    e = RetryableConnectionClosedError("connection dropped", close_code=1006)

    assert str(e) == "connection dropped"
    assert e.close_code == 1006


def test_retryable_connection_closed_error_inheritance() -> None:
    """RetryableConnectionClosedError is still a subclass of ConnectionClosedError."""
    e = RetryableConnectionClosedError("connection dropped")

    assert isinstance(e, ConnectionClosedError)


def test_response_timeout_error_is_outcome_unknown_failed_message() -> None:
    """Takes FailedMessageError's constructor; existing ``except FailedMessageError`` still catches it."""
    exc = ResponseTimeoutError("timed out", original_data={"type": "fire_event", "id": 3})

    assert isinstance(exc, OutcomeUnknownError)
    assert isinstance(exc, FailedMessageError)
    assert not isinstance(exc, TimeoutError)
    assert exc.code is None
    assert exc.original_data == {"type": "fire_event", "id": 3}


def test_response_lost_error_is_outcome_unknown_connection_closed() -> None:
    """Takes RetryableConnectionClosedError's constructor and is not a FailedMessageError."""
    exc = ResponseLostError("connection lost", close_code=1006)

    assert isinstance(exc, OutcomeUnknownError)
    assert isinstance(exc, RetryableConnectionClosedError)
    assert not isinstance(exc, FailedMessageError)
    assert exc.close_code == 1006


def test_outcome_unknown_error_is_a_bodyless_marker() -> None:
    """No ``__init__`` of its own, so the two concrete parents' constructors never meet."""
    assert "__init__" not in vars(OutcomeUnknownError)


def test_entity_not_in_view_error_defines_own_init() -> None:
    """EntityNotInViewError must define ``__init__`` itself rather than inheriting it.

    It subclasses both ``KeyError`` and ``EntityShapeError``. On Python <= 3.13 ``KeyError``
    carries its own ``__init__`` slot that precedes ``EntityShapeError`` in the MRO, so an
    inherited ``__init__`` resolves to ``KeyError``'s and leaves ``entity_id``, ``device_class``,
    and ``state_class`` unset — every read of those attributes then raises ``AttributeError``.
    Python 3.14 dropped that slot, so the attribute assertions in
    ``tests/unit/state_manager/test_domain_states_membership.py`` pass on 3.14 whether or not the
    override exists. This ``__dict__`` check fails on every supported version, so dropping the
    override cannot slip through a local 3.14-only run.
    """
    assert "__init__" in EntityNotInViewError.__dict__, (
        "EntityNotInViewError must define __init__ itself; inheriting it is version-dependent."
    )

    err = EntityNotInViewError("sensor.mode", "enum", NumericSensorState)
    assert err.entity_id == "sensor.mode"
    assert err.device_class == "enum"
    assert err.state_class is NumericSensorState


def test_hassette_error_without_suggestion_renders_message_unchanged() -> None:
    assert str(HassetteError("msg")) == "msg"


def test_hassette_error_with_suggestion_appends_suffix() -> None:
    class SuggestingError(HassetteError):
        def __init__(self, msg: str) -> None:
            super().__init__(msg)
            self.suggestion = "do the thing"

    assert str(SuggestingError("msg")) == "msg\n  Suggestion: do the thing"


def test_class_level_suggestion_surfaces_through_str() -> None:
    assert str(InvalidAuthError("bad token")) == f"bad token\n  Suggestion: {InvalidAuthError.suggestion}"


def test_domain_not_found_error_suggestion_names_domain() -> None:
    text = str(DomainNotFoundError("my_domain"))
    assert text.startswith("No state class found for domain 'my_domain'.\n  Suggestion: ")
    assert "Literal['my_domain']" in text


def test_cannot_override_final_error_moves_alt_to_suggestion_line() -> None:
    exc = CannotOverrideFinalError("initialize", "Resource", "my.App", suggested_alt="on_initialize", location="a.py:3")
    assert str(exc) == (
        "App 'my.App' attempted to override the final lifecycle method 'initialize' defined in 'Resource'."
        " (at a.py:3)\n  Suggestion: Use 'on_initialize' instead."
    )


def test_cannot_override_final_error_without_alt_has_no_suggestion() -> None:
    exc = CannotOverrideFinalError("initialize", "Resource", "my.App")
    assert exc.suggestion is None
    assert "Suggestion" not in str(exc)


def assert_same_error(original: BaseException, rebuilt: BaseException) -> None:
    """Assert a round trip kept the type, rendered message, ``args``, and every instance attribute."""
    assert type(rebuilt) is type(original)
    assert str(rebuilt) == str(original)
    assert rebuilt.args == original.args
    # repr, because a nested exception such as AuthTokenWriteError.original_error has no value equality.
    assert {k: repr(v) for k, v in vars(rebuilt).items()} == {k: repr(v) for k, v in vars(original).items()}


@pytest.mark.parametrize("round_trip", ROUND_TRIPS.values(), ids=ROUND_TRIPS.keys())
@pytest.mark.parametrize("err", ROUND_TRIP_SAMPLES, ids=lambda err: type(err).__name__)
def test_exception_survives_round_trip(err: HassetteError, round_trip: Callable[[Any], Any]) -> None:
    assert_same_error(err, round_trip(err))


def test_round_trip_samples_cover_every_custom_init() -> None:
    """A new exception with its own ``__init__`` must join ``ROUND_TRIP_SAMPLES``."""
    custom_init = {
        cls
        for _, cls in inspect.getmembers(exceptions_module, inspect.isclass)
        if issubclass(cls, HassetteError) and cls.__module__ == exceptions_module.__name__ and "__init__" in vars(cls)
    }
    # EntityShapeError can't be instantiated: subclasses supply the _build_message its __init__ calls.
    missing = custom_init - {EntityShapeError} - {type(err) for err in ROUND_TRIP_SAMPLES}
    assert not missing


@pytest.mark.parametrize("round_trip", ROUND_TRIPS.values(), ids=ROUND_TRIPS.keys())
@pytest.mark.parametrize(
    "err",
    [
        BuiltinFirstError("sensor.mode", retries=3),
        OSErrorFirstError("/tmp/x", "gone"),
        HassetteFirstOSError("ha.local", "refused"),
        ConcreteAbcError("sensor.mode", "bad"),
    ],
    ids=lambda err: type(err).__name__,
)
def test_subclass_with_builtin_exception_first_survives_round_trip(
    err: HassetteError, round_trip: Callable[[Any], Any]
) -> None:
    """User subclasses get the same guarantee, whatever their bases and their order."""
    assert_same_error(err, round_trip(err))


@pytest.mark.parametrize("round_trip", ROUND_TRIPS.values(), ids=ROUND_TRIPS.keys())
def test_round_trip_keeps_state_set_after_construction(round_trip: Callable[[Any], Any]) -> None:
    """Rewritten ``args``, added notes, and ad hoc attributes aren't lost to re-running ``__init__``."""
    err = DomainNotFoundError("light")
    err.args = ("rewritten with context",)
    err.add_note("while resolving kitchen")
    err.request_id = 42  # pyright: ignore[reportAttributeAccessIssue]

    rebuilt = round_trip(err)

    assert_same_error(err, rebuilt)
    assert rebuilt.__notes__ == ["while resolving kitchen"]
    assert rebuilt.request_id == 42


@pytest.mark.parametrize("cls", [OSErrorFirstError, HassetteFirstOSError])
def test_oserror_mixin_constructor_arguments_are_not_parsed_as_errno(cls: type[HassetteError]) -> None:
    """``OSError.__new__`` parses its arguments as ``(errno, strerror)`` if a Python ``__new__`` displaces it."""
    err = cls("/tmp/x", "gone")

    assert str(err) == "/tmp/x: gone"
    assert err.errno is None  # pyright: ignore[reportAttributeAccessIssue]


def test_oserror_mixin_without_init_keeps_errno_parsing_through_round_trip() -> None:
    class NoInitOSError(HassetteError, OSError):
        pass

    err = NoInitOSError(13, "denied", "/tmp/x")

    assert (err.errno, err.strerror, err.filename) == (13, "denied", "/tmp/x")
    rebuilt = copy.deepcopy(err)
    assert (rebuilt.errno, rebuilt.strerror, rebuilt.filename) == (13, "denied", "/tmp/x")
    assert str(rebuilt) == str(err)
