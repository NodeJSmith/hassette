"""Structured stack frames for blocking-event telemetry: capture, text formatting, and classification.

Frames are captured innermost-first as ``StackFrame`` objects and stored as JSON on each
``blocking_events`` row. Whether a frame is user code is decided here at read time by
``FrameClassifier``, because the answer depends on the current app directories and on the
interpreter's install prefixes, neither of which belongs in a stored row.
"""

import asyncio.events
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from hassette_wire import BlockingFrameRef, StackFrame
from pydantic import TypeAdapter, ValidationError

from hassette.utils.source_capture import is_internal_frame

LIBRARY_DIR_NAMES = frozenset({"site-packages", "dist-packages"})
# The installed or source-checkout ``hassette`` package directory (this file is hassette/utils/...).
HASSETTE_PACKAGE_DIR = PurePath(__file__).parents[1]
# Matches the versioned stdlib directory (e.g. ``python3.13``) under an interpreter prefix, so a
# row recorded under an older image's interpreter still reads as stdlib after an upgrade.
_STDLIB_DIR_PATTERN = re.compile(r"^python\d+\.\d+t?$")
_FRAMES_ADAPTER = TypeAdapter(list[StackFrame])
# asyncio runs every callback and task step through ``Handle._run``. Frames outside it are the
# event loop and the process entry point (runpy, the CLI, ``asyncio.run``), the same on every stall.
# ``Handle._run`` is a private CPython detail: a loop that doesn't dispatch through it (uvloop
# dispatches from compiled code) never matches, and the walk goes to the outermost frame as before.
_LOOP_DISPATCH_CODE = asyncio.events.Handle._run.__code__


def frame_from_raw(frame: Any) -> StackFrame:
    """Build a ``StackFrame`` from a live Python frame object."""
    code = frame.f_code
    module = frame.f_globals.get("__name__") if hasattr(frame, "f_globals") else None
    return StackFrame(filename=code.co_filename, lineno=frame.f_lineno, function=code.co_name, module=module)


def capture_frames(frame: Any, *, max_frames: int) -> tuple[StackFrame, ...]:
    """Capture up to ``max_frames`` non-hassette frames, walking outward from ``frame`` (innermost first).

    Skipped hassette frames don't count toward the limit, so framework layers between a library
    call and the app code that made it can't use up the budget before the app frame is reached.
    The walk stops before the event loop's callback dispatcher, which isn't captured. A stack not
    running inside an asyncio callback, or on a loop that doesn't dispatch through it, is walked to
    its outermost frame.
    """
    frames: list[StackFrame] = []
    while frame is not None and len(frames) < max_frames:
        if frame.f_code is _LOOP_DISPATCH_CODE:
            break
        if not is_internal_frame(frame):
            frames.append(frame_from_raw(frame))
        frame = frame.f_back
    return tuple(frames)


def format_stack_text(frames: Sequence[StackFrame]) -> str | None:
    """Render frames as the multi-line text stored in ``blocking_events.source_location``.

    Returns ``None`` for an empty sequence, matching the column's "no stack captured" value.
    """
    if not frames:
        return None
    return "\n".join(
        f'  File "{f.filename}", line {f.lineno}, in {f.function} ({f.module or "<unknown>"})' for f in frames
    )


def encode_frames(frames: Sequence[StackFrame] | None) -> str | None:
    """Serialize frames for the ``blocking_events.frames`` JSON column; ``None`` stays ``None``."""
    if frames is None:
        return None
    return _FRAMES_ADAPTER.dump_json(list(frames)).decode()


def decode_frames(raw: str | None) -> list[StackFrame] | None:
    """Parse a ``blocking_events.frames`` value: NULL yields no frames, an unreadable value ``None``.

    ``decode_stacks`` in ``hassette.core.telemetry.blocking_findings`` is the reader that turns
    ``None`` into no frames and reports it.
    """
    if raw is None:
        return []
    try:
        return _FRAMES_ADAPTER.validate_json(raw)
    except ValidationError:
        return None


@dataclass(frozen=True)
class FrameClassifier:
    """Decides which captured frames are user code, and how to display a frame's path.

    A frame under one of ``app_dirs`` is app code. When no frame in a stack is, the fallback
    treats a frame as user code if it lies outside every ``excluded_dirs`` entry and has no
    ``site-packages``/``dist-packages`` path segment. ``excluded_dirs`` holds the interpreter's
    install prefixes plus the hassette package directory: a source run (``python -m hassette``)
    leaves ``hassette/__main__.py`` under module name ``__main__``, which the capture-time module
    filter can't recognize, on stacks walked to their outermost frame (rows recorded before capture
    stopped at the loop's callback dispatcher, and stalls outside a callback). Prefix matching
    assumes the frames were recorded by this same interpreter, which holds because the server
    classifies its own rows.
    """

    app_dirs: tuple[PurePath, ...]
    excluded_dirs: tuple[PurePath, ...]
    # Per-filename answers, so each distinct path is tested against the prefixes once. They assume a
    # classifier serves one request on one thread, which the ``blocking_findings`` builders guarantee by
    # building fresh classifiers per request; a long-lived classifier would grow them without bound.
    _app_dir_cache: dict[str, PurePath | None] = field(default_factory=dict, init=False, compare=False, repr=False)
    _fallback_cache: dict[str, bool] = field(default_factory=dict, init=False, compare=False, repr=False)

    @classmethod
    def for_current_interpreter(cls, app_dirs: Iterable[PurePath]) -> "FrameClassifier":
        excluded = {PurePath(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, HASSETTE_PACKAGE_DIR)}
        return cls(app_dirs=tuple(app_dirs), excluded_dirs=tuple(excluded))

    def app_dir_for(self, filename: str) -> PurePath | None:
        """Return the app directory containing ``filename``, or ``None``."""
        if filename not in self._app_dir_cache:
            path = PurePath(filename)
            self._app_dir_cache[filename] = next((d for d in self.app_dirs if path.is_relative_to(d)), None)
        return self._app_dir_cache[filename]

    def is_fallback_user_code(self, filename: str) -> bool:
        """True when ``filename`` is outside the interpreter and every installed-library directory."""
        cached = self._fallback_cache.get(filename)
        if cached is not None:
            return cached
        if filename.startswith("<"):
            result = False  # <frozen ...>, <string>, <stdin>: no real source file
        else:
            path = PurePath(filename)
            result = not LIBRARY_DIR_NAMES.intersection(path.parts) and not any(
                path.is_relative_to(excluded) for excluded in self.excluded_dirs
            )
        self._fallback_cache[filename] = result
        return result

    def is_user_code(self, filename: str) -> bool:
        return self.app_dir_for(filename) is not None or self.is_fallback_user_code(filename)

    def find_call_site(self, frames: Sequence[StackFrame]) -> int | None:
        """Index of the innermost app-code frame in an innermost-first stack, or ``None``.

        A frame under an app directory wins over any fallback-classified frame, wherever it sits.
        """
        for i, frame in enumerate(frames):
            if self.app_dir_for(frame.filename) is not None:
                return i
        for i, frame in enumerate(frames):
            if self.is_fallback_user_code(frame.filename):
                return i
        return None

    def display_path(self, filename: str) -> str:
        """Short path for summary lines; see ``BlockingFrameRef.display_path`` for the rule."""
        app_dir = self.app_dir_for(filename)
        if app_dir is not None:
            return PurePath(filename).relative_to(app_dir).as_posix()
        if filename.startswith("<"):
            return filename
        parts = PurePath(filename).parts
        library_idx = max((i for i, part in enumerate(parts) if part in LIBRARY_DIR_NAMES), default=None)
        if library_idx is not None:
            return PurePath(*parts[library_idx + 1 :]).as_posix()
        if not self.is_fallback_user_code(filename):
            stdlib_idx = max((i for i, part in enumerate(parts) if _STDLIB_DIR_PATTERN.match(part)), default=None)
            if stdlib_idx is not None:
                return PurePath("stdlib", *parts[stdlib_idx + 1 :]).as_posix()
        return filename

    def ref(self, frame: StackFrame) -> BlockingFrameRef:
        return BlockingFrameRef(**frame.model_dump(), display_path=self.display_path(frame.filename))

    def top_level_package(self, frame: StackFrame) -> str:
        """Name of the package a non-user frame belongs to, e.g. ``"requests"`` or ``"stdlib"``."""
        if frame.module and frame.module != "__main__":
            return frame.module.split(".", 1)[0]
        display = self.display_path(frame.filename)
        return display.split("/", 1)[0] if "/" in display else display
