"""Unit tests for the extracted helper functions in hassette.utils.app_utils.

Covers root_cause, find_user_frame, and log_compact_load_error.
"""

import traceback
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.utils.app_utils import find_user_frame, log_compact_load_error, root_cause


class TestRootCause:
    def test_returns_self_when_no_chain(self):
        exc = ValueError("direct")
        assert root_cause(exc) is exc

    def test_follows_explicit_cause_chain(self):
        inner = TypeError("root")
        outer = ValueError("wrapper")
        outer.__cause__ = inner
        assert root_cause(outer) is inner

    def test_follows_deep_cause_chain(self):
        a = TypeError("a")
        b = ValueError("b")
        c = RuntimeError("c")
        c.__cause__ = b
        b.__cause__ = a
        assert root_cause(c) is a

    def test_falls_back_to_context_when_no_cause(self):
        inner = TypeError("implicit")
        outer = ValueError("wrapper")
        outer.__context__ = inner
        assert root_cause(outer) is inner

    def test_cause_takes_priority_over_context(self):
        cause = TypeError("explicit cause")
        context = RuntimeError("implicit context")
        outer = ValueError("wrapper")
        outer.__cause__ = cause
        outer.__context__ = context
        assert root_cause(outer) is cause

    def test_does_not_override_deepest_cause_with_context(self):
        """After walking __cause__, __context__ on the deepest cause is ignored."""
        deepest_cause = TypeError("deepest cause")
        context_of_deepest = RuntimeError("context on deepest")
        deepest_cause.__context__ = context_of_deepest

        outer = ValueError("wrapper")
        outer.__cause__ = deepest_cause

        assert root_cause(outer) is deepest_cause


class TestFindUserFrame:
    def test_prefers_frame_inside_app_dir(self, tmp_path: Path):
        app_file = tmp_path / "my_app.py"
        app_file.write_text("raise ValueError('boom')")

        try:
            exec(compile(app_file.read_text(), str(app_file), "exec"))
        except ValueError as exc:
            frame = find_user_frame(exc, tmp_path)
            assert frame is not None
            assert frame.filename == str(app_file)

    def test_returns_last_frame_as_fallback(self, tmp_path: Path):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            frame = find_user_frame(exc, tmp_path)
            assert frame is not None
            assert frame.filename == __file__

    def test_returns_none_for_no_traceback(self, tmp_path: Path):
        exc = ValueError("no traceback")
        assert find_user_frame(exc, tmp_path) is None

    def test_skips_hassette_and_site_packages_frames(self, tmp_path: Path):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            tb = traceback.extract_tb(exc.__traceback__)
            assert len(tb) > 0
            frame = find_user_frame(exc, tmp_path)
            assert frame is not None


class TestLogCompactLoadError:
    def test_logs_with_frame_info(self, tmp_path: Path):
        app_file = tmp_path / "broken_app.py"
        app_file.write_text("raise ImportError('missing module')")

        manifest = MagicMock()
        manifest.display_name = "broken_app"
        manifest.app_dir = tmp_path

        try:
            exec(compile(app_file.read_text(), str(app_file), "exec"))
        except ImportError as exc:
            log_compact_load_error(manifest, exc)

    def test_logs_without_frame_info(self):
        manifest = MagicMock()
        manifest.display_name = "no_traceback_app"
        manifest.app_dir = Path("/nonexistent")

        exc = ImportError("missing module")
        log_compact_load_error(manifest, exc)

    def test_includes_exception_type_in_output(self, tmp_path: Path, caplog: pytest.LogCaptureFixture):
        app_file = tmp_path / "bad_app.py"
        app_file.write_text("x = 1 / 0")

        manifest = MagicMock()
        manifest.display_name = "bad_app"
        manifest.app_dir = tmp_path

        try:
            exec(compile(app_file.read_text(), str(app_file), "exec"))
        except ZeroDivisionError as exc:
            with caplog.at_level("ERROR"):
                log_compact_load_error(manifest, exc)

            assert any("bad_app" in r.message for r in caplog.records)
            assert any("ZeroDivisionError" in r.message for r in caplog.records)
