"""Unit tests for :class:`hassette.exceptions.FailedMessageError`.

These tests pin the structured-error-surface contract that the helper CRUD
work packages rely on. In particular they guard against the most likely
implementation mistake (``from_error_response`` dropping its ``code`` and
``original_data`` kwargs before delegating to ``cls(msg)``) and verify that
positional-only construction remains backward compatible so every existing
``FailedMessageError("msg")`` call site continues to work.

See ``design/specs/2037-helper-crud-api/tasks/WP03.md`` for the full spec.
"""

import pytest

from hassette.exceptions import FailedMessageError


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
        code="name_in_use",
        original_data={"source": "test"},
    )

    assert str(e) == "boom"
    assert e.code == "name_in_use"
    assert e.original_data == {"source": "test"}


def test_failed_message_error_from_error_response_forwards_all_fields() -> None:
    """``from_error_response`` forwards every field AND fixes the typo.

    This is the primary implementation gate for WP03: if the classmethod
    body still reads ``return cls(msg)`` instead of
    ``return cls(msg, code=code, original_data=original_data)``, the
    ``e.code`` / ``e.original_data`` assertions below will fail.

    The ``"for failed"`` assertion guards the typo fix — the old message
    template read ``"WebSocket message for failed with response ..."``.
    """
    e = FailedMessageError.from_error_response(
        error="already exists",
        code="name_in_use",
        original_data={"type": "input_boolean/create"},
    )

    assert e.code == "name_in_use"
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

    This is a regression test for the ``_ws_helper_call`` wrapper that WP04
    will add. The wrapper catches ``FailedMessageError`` and re-raises a new
    one with contextualized message, forwarding ``code`` and
    ``original_data`` from the caught exception. Both the wrapped exception
    and ``__cause__`` must surface the same ``code``.
    """

    def _chain_and_reraise() -> None:
        try:
            raise FailedMessageError("first", code="a", original_data={"k": 1})
        except FailedMessageError as e:
            raise FailedMessageError(
                "wrapped",
                code=e.code,
                original_data=e.original_data,
            ) from e

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
