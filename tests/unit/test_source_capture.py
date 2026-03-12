"""Unit tests for capture_registration_source in hassette.utils.source_capture."""

from __future__ import annotations

import ast
import types
from unittest.mock import patch

from hassette.utils.source_capture import capture_registration_source


def test_capture_from_real_call() -> None:
    """Called from a real module file returns non-None registration_source."""
    source_location, registration_source = capture_registration_source()

    assert source_location is not None
    assert ":" in source_location  # format: filename:lineno
    # Called from a real .py file, so AST parsing should succeed
    assert registration_source is not None
    assert "capture_registration_source" in registration_source


def test_cache_reuse() -> None:
    """Calling twice from same file only parses AST once."""
    with patch("ast.parse", wraps=ast.parse) as mock_parse:
        capture_registration_source()
        first_count = mock_parse.call_count

        capture_registration_source()
        second_count = mock_parse.call_count

    # If the file was already cached after the first call, the second call
    # should not increase the parse count (file is the same test file)
    assert second_count == first_count


def test_graceful_on_no_source() -> None:
    """Simulate a REPL-like frame (no source file): returns (source_location, None) without raising."""
    # Create a fake frame that simulates a REPL environment (filename is "<stdin>")
    fake_frame_info = types.SimpleNamespace(
        filename="<stdin>",
        lineno=1,
        frame=types.SimpleNamespace(f_code=types.SimpleNamespace(co_filename="<stdin>")),
    )
    # Dummy frame representing capture_registration_source's own frame (stack[0], skipped by stack[1:])
    own_frame = types.SimpleNamespace(
        filename="/some/hassette/utils/source_capture.py",
        lineno=57,
        frame=types.SimpleNamespace(f_code=types.SimpleNamespace(co_filename="/some/hassette/utils/source_capture.py")),
    )

    # Patch inspect.stack to return [own_frame, fake_frame_info]; stack[1:] leaves fake_frame_info as first candidate
    with patch("inspect.stack", return_value=[own_frame, fake_frame_info]):
        source_location, registration_source = capture_registration_source()

    assert source_location is not None
    assert "stdin" in source_location or "<" in source_location
    assert registration_source is None
