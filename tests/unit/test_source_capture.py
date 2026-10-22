"""Unit tests for capture_registration_source in hassette.utils.source_capture."""

import ast
import os
import types
from pathlib import Path
from unittest.mock import patch

from hassette.utils.source_capture import capture_registration_source, find_call_source


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


def test_cache_refreshes_after_file_edit(tmp_path: Path) -> None:
    """Editing a file (hot-reload scenario) yields the new snippet, not a stale cached one."""
    f = tmp_path / "my_app.py"
    f.write_text("x = old_call(1)\n")
    assert find_call_source(str(f), 1) == "old_call(1)"

    f.write_text("x = new_call(2)\n")
    # Force a different mtime even on filesystems with coarse timestamp resolution.
    stat = f.stat()
    os.utime(f, (stat.st_atime, stat.st_mtime + 10))
    assert find_call_source(str(f), 1) == "new_call(2)"


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


def test_repeat_lookup_skips_ast_walk(tmp_path: Path) -> None:
    """A repeat lookup of an unchanged file/line is served from cache — no AST walk or segment work."""
    f = tmp_path / "runtime_app.py"
    f.write_text("x = run_in(job, 5)\n")
    assert find_call_source(str(f), 1) == "run_in(job, 5)"

    with (
        patch("ast.walk", wraps=ast.walk) as mock_walk,
        patch("ast.get_source_segment", wraps=ast.get_source_segment) as mock_segment,
    ):
        assert find_call_source(str(f), 1) == "run_in(job, 5)"

    assert mock_walk.call_count == 0
    assert mock_segment.call_count == 0


def test_repeat_lookup_does_not_open_file(tmp_path: Path) -> None:
    """A repeat lookup never calls open, so the blocking-IO guard (which patches open) cannot flag it."""
    f = tmp_path / "runtime_app2.py"
    f.write_text("y = schedule(job)\n")
    assert find_call_source(str(f), 1) == "schedule(job)"

    with patch("hassette.utils.source_capture._builtin_open", side_effect=AssertionError("file reopened")):
        assert find_call_source(str(f), 1) == "schedule(job)"
