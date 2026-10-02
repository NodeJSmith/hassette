"""Tests for structured stack frames: capture, text form, storage, and user-code classification."""

import sys
from pathlib import PurePath

import pytest
from hassette_wire import StackFrame

from hassette.utils.stack_frames import (
    HASSETTE_PACKAGE_DIR,
    FrameClassifier,
    capture_frames,
    decode_frames,
    encode_frames,
    format_stack_text,
)

# The live container layout: venv at /app/.venv on top of a /usr/local interpreter, apps at /apps.
CONTAINER = FrameClassifier(
    app_dirs=(PurePath("/apps/src/hautomate"),),
    excluded_dirs=(PurePath("/app/.venv"), PurePath("/usr/local")),
)


def frame(filename: str, *, lineno: int = 1, function: str = "f", module: str | None = None) -> StackFrame:
    return StackFrame(filename=filename, lineno=lineno, function=function, module=module)


class TestFindCallSite:
    def test_app_dir_frame_wins_over_inner_fallback_frame(self) -> None:
        """A helper outside app_dir is skipped when a frame under app_dir exists further out."""
        frames = [
            frame("/usr/local/lib/python3.13/ssl.py"),
            frame("/config/lib/util.py"),
            frame("/apps/src/hautomate/calendar_service.py"),
        ]
        assert CONTAINER.find_call_site(frames) == 2

    def test_innermost_app_frame_is_chosen(self) -> None:
        frames = [
            frame("/app/.venv/lib/python3.13/site-packages/gcsa/events.py"),
            frame("/apps/src/hautomate/calendar_service.py", lineno=98),
            frame("/apps/src/hautomate/car_climate.py", lineno=40),
        ]
        assert CONTAINER.find_call_site(frames) == 1

    def test_fallback_finds_helper_outside_app_dir(self) -> None:
        frames = [frame("/usr/local/lib/python3.13/socket.py"), frame("/config/lib/util.py")]
        assert CONTAINER.find_call_site(frames) == 1

    @pytest.mark.parametrize(
        "filename",
        [
            "/usr/local/lib/python3.13/ssl.py",  # stdlib under base_prefix
            "/usr/local/lib/python3.12/weakref.py",  # an older image's interpreter, same prefix
            "/app/.venv/bin/hassette",  # console-script launcher under sys.prefix
            "/root/.local/lib/python3.13/site-packages/requests/api.py",  # pip install --user
            "/opt/other/dist-packages/lib.py",
            "<frozen importlib._bootstrap>",
        ],
    )
    def test_non_user_frames_are_never_call_sites(self, filename: str) -> None:
        assert CONTAINER.find_call_site([frame(filename)]) is None

    def test_user_path_containing_hassette_is_user_code(self) -> None:
        """A path segment named after the framework does not exclude user code."""
        assert CONTAINER.find_call_site([frame("/opt/hassette-config/helpers.py")]) == 0

    def test_empty_stack_has_no_call_site(self) -> None:
        assert CONTAINER.find_call_site([]) is None


class TestMemoizedClassification:
    def test_repeat_answers_match_and_leave_equality_unchanged(self) -> None:
        fresh = FrameClassifier(app_dirs=CONTAINER.app_dirs, excluded_dirs=CONTAINER.excluded_dirs)
        paths = ["/apps/src/hautomate/car.py", "/app/.venv/lib/python3.13/site-packages/x.py", "/srv/helper.py"]

        first = [(fresh.app_dir_for(p), fresh.is_fallback_user_code(p)) for p in paths]
        second = [(fresh.app_dir_for(p), fresh.is_fallback_user_code(p)) for p in paths]

        assert first == second == [(PurePath("/apps/src/hautomate"), True), (None, False), (None, True)]
        assert fresh == CONTAINER


class TestDisplayPath:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("/apps/src/hautomate/calendar_service.py", "calendar_service.py"),
            ("/apps/src/hautomate/sub/mod.py", "sub/mod.py"),
            (
                "/app/.venv/lib/python3.13/site-packages/gcsa/_services/events_service.py",
                "gcsa/_services/events_service.py",
            ),
            ("/usr/local/lib/python3.13/ssl.py", "stdlib/ssl.py"),
            ("/usr/local/lib/python3.12/http/client.py", "stdlib/http/client.py"),
            ("/config/lib/util.py", "/config/lib/util.py"),
            ("<frozen importlib._bootstrap>", "<frozen importlib._bootstrap>"),
        ],
    )
    def test_display_path(self, filename: str, expected: str) -> None:
        assert CONTAINER.display_path(filename) == expected

    def test_ref_keeps_the_absolute_path(self) -> None:
        ref = CONTAINER.ref(frame("/apps/src/hautomate/x.py", lineno=7, function="go"))
        assert ref.filename == "/apps/src/hautomate/x.py"
        assert ref.display_path == "x.py"
        assert (ref.lineno, ref.function) == (7, "go")


class TestTopLevelPackage:
    def test_from_module_name(self) -> None:
        assert (
            CONTAINER.top_level_package(frame("/x/site-packages/requests/api.py", module="requests.api")) == "requests"
        )

    def test_from_path_when_module_unknown(self) -> None:
        site = "/app/.venv/lib/python3.13/site-packages/gcsa/events.py"
        assert CONTAINER.top_level_package(frame(site)) == "gcsa"
        assert CONTAINER.top_level_package(frame("/usr/local/lib/python3.13/ssl.py")) == "stdlib"


class TestStorage:
    def test_round_trip(self) -> None:
        frames = [frame("/a.py", lineno=3, function="g", module="a"), frame("/b.py")]
        assert decode_frames(encode_frames(frames)) == frames

    def test_null_column_means_no_frames(self) -> None:
        assert encode_frames(None) is None
        assert decode_frames(None) == []

    def test_unreadable_value_means_no_frames(self) -> None:
        assert decode_frames("not json") == []
        assert decode_frames('[{"filename": 1}]') == []


class TestCapture:
    def test_captures_this_frame_innermost_first(self) -> None:
        frames = capture_frames(sys._getframe(), max_depth=5)
        assert frames[0].function == "test_captures_this_frame_innermost_first"
        assert frames[0].filename == __file__
        assert frames[0].module == __name__

    def test_text_form_matches_stored_source_location_format(self) -> None:
        frames = [frame("/a.py", lineno=3, function="g", module="a"), frame("/b.py", lineno=9, function="h")]
        assert format_stack_text(frames) == (
            '  File "/a.py", line 3, in g (a)\n  File "/b.py", line 9, in h (<unknown>)'
        )
        assert format_stack_text([]) is None


def test_source_run_launcher_frame_is_not_user_code() -> None:
    """``python -m hassette`` from a checkout leaves hassette/__main__.py (module ``__main__``) on the stack."""
    classifier = FrameClassifier.for_current_interpreter([])
    launcher = str(HASSETTE_PACKAGE_DIR / "__main__.py")
    assert not classifier.is_user_code(launcher)
    assert classifier.find_call_site([frame(launcher, module="__main__")]) is None


def test_current_interpreter_prefixes_exclude_stdlib() -> None:
    """The real interpreter's stdlib is never user code, whatever the install layout."""
    classifier = FrameClassifier.for_current_interpreter([])
    assert not classifier.is_user_code(sys.modules["json"].__file__ or "")
