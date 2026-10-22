"""Utilities for capturing the source location and code of a registration call."""

import ast
import builtins
import functools
import inspect
from pathlib import Path
from typing import Any

from hassette_wire import StackFrame

# Capture the original open before block_io_guard monkeypatches builtins.open.
# Source capture reads Python files for AST analysis during handler/job registration, which
# runs on the event loop at any time — including runtime registrations from handlers. Each
# file is read at most once per modification (LRU-cached by mtime), so repeat registrations
# never reach this open; the guard would only flag the first, already-bounded read.
_builtin_open = builtins.open

# Per-file source/AST cache entries kept before LRU eviction.
SOURCE_CACHE_MAX_SIZE = 256
# Per-call-site snippet cache entries kept before LRU eviction — one per registering line.
CALL_SOURCE_CACHE_MAX_SIZE = 2048
# Stack frames inspected after skipping internal frames — user code is 1-3 frames
# from the public def, so 8 leaves generous headroom.
DEFAULT_FRAME_LIMIT = 8
# Frames at the top of inspect.stack() that belong to the walk itself: _walk_to_caller, then the
# public walker (find_caller_frame or find_caller_stack_frame) that called it.
_WALKER_FRAMES = 2


def is_internal_frame(frame: Any) -> bool:
    """Return True if the frame belongs to an internal hassette module.

    Uses ``f_globals["__name__"]`` for the check — works from site-packages and
    on any OS without relying on filesystem path separators or path fragments.
    """
    name: str = frame.f_globals.get("__name__", "") if hasattr(frame, "f_globals") else ""
    return name == "hassette" or name.startswith("hassette.")


@functools.lru_cache(maxsize=SOURCE_CACHE_MAX_SIZE)
def get_source_and_ast(filename: str, mtime: int | None) -> tuple[str, ast.Module] | None:  # noqa: ARG001 — mtime is cache-key only
    """Return a cached (source, AST) pair for *filename*.

    Uses ``functools.lru_cache`` (``SOURCE_CACHE_MAX_SIZE`` entries) so each file is read and parsed
    at most once per modification.  ``mtime`` is the nanosecond ``st_mtime_ns``
    and is part of the cache key only — when a file changes (e.g. hot-reload
    after an app edit), the new mtime misses the cache and the stale entry falls
    out of the LRU naturally.  Nanosecond resolution avoids reusing a stale entry
    for two edits that land within the same coarse ``st_mtime`` tick.
    Thread-safe via the lru_cache internal lock.

    Returns None if the file cannot be read or parsed.
    """
    try:
        with _builtin_open(filename, encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=filename)
        return source, tree
    except Exception:
        return None


def find_call_source(filename: str, lineno: int) -> str | None:
    """Find the source snippet of the Call node at *lineno* in *filename*.

    The only per-call work is one ``stat`` (no ``open``, so the blocking-IO guard does not
    flag it) to read the file's mtime; the AST walk and segment extraction are cached per
    ``(filename, mtime, lineno)`` by ``call_source_at``, so repeat registrations from the
    same line — e.g. ``run_in(..., if_exists="replace")`` inside a handler — are a cache hit.
    An edited file has a new mtime and so yields a fresh snippet.

    Returns the source segment string, or None if unavailable.
    """
    try:
        mtime: int | None = Path(filename).stat().st_mtime_ns
    except OSError:
        mtime = None
    return call_source_at(filename, mtime, lineno)


@functools.lru_cache(maxsize=CALL_SOURCE_CACHE_MAX_SIZE)
def call_source_at(filename: str, mtime: int | None, lineno: int) -> str | None:
    """Return the cached source segment of the first Call node at *lineno* in *filename*.

    ``mtime`` keys both this cache and ``get_source_and_ast``, so a modified file misses
    both and is re-read. Returns None if the file is unreadable or has no Call at *lineno*.
    """
    cached = get_source_and_ast(filename, mtime)
    if cached is None:
        return None

    source, tree = cached

    try:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and hasattr(node, "lineno") and node.lineno == lineno:
                segment = ast.get_source_segment(source, node)
                if segment is not None:
                    return segment
        return None
    except Exception:
        return None


def find_caller_frame(*, frames_to_skip: int = 0, limit: int | None = DEFAULT_FRAME_LIMIT) -> tuple[str, int]:
    """Walk the stack and return ``(filename, lineno)`` of the first non-hassette frame.

    The shared stack-walk half of source capture — no file read, no AST parse.
    Internal hassette frames (including this module's own callers) are skipped
    via the module-name filter, so wrapper depth does not affect attribution.

    Returns ``("<unknown>", 0)`` when stack walking fails entirely.
    """
    chosen = _walk_to_caller(frames_to_skip, limit)
    if chosen is None:
        return ("<unknown>", 0)
    filename = getattr(chosen, "filename", "<unknown>") or "<unknown>"
    lineno: int = getattr(chosen, "lineno", 0) or 0
    return (filename, lineno)


def find_caller_stack_frame(*, frames_to_skip: int = 0, limit: int | None = DEFAULT_FRAME_LIMIT) -> StackFrame | None:
    """Walk the stack and return the first non-hassette frame with its function and module.

    Returns ``None`` when stack walking fails entirely.
    """
    chosen = _walk_to_caller(frames_to_skip, limit)
    if chosen is None:
        return None
    f_globals = getattr(getattr(chosen, "frame", chosen), "f_globals", None)
    return StackFrame(
        filename=getattr(chosen, "filename", "<unknown>") or "<unknown>",
        lineno=getattr(chosen, "lineno", 0) or 0,
        function=getattr(chosen, "function", "<unknown>") or "<unknown>",
        module=f_globals.get("__name__") if isinstance(f_globals, dict) else None,
    )


def _walk_to_caller(frames_to_skip: int, limit: int | None) -> Any:
    """Return the first non-hassette ``FrameInfo`` above the public walker that called this.

    Only ``find_caller_frame`` and ``find_caller_stack_frame`` may call this, directly: the slice
    drops this function's frame and theirs, so ``frames_to_skip`` counts from their caller.
    Returns ``None`` when stack walking fails or the window is empty.
    """
    try:
        # context=0 (zero source lines per frame) is the cheapest walk.
        raw_stack = inspect.stack(context=0)
    except Exception:
        return None
    return pick_caller_frame(raw_stack[_WALKER_FRAMES + frames_to_skip :], limit)


def pick_caller_frame(frames: list[Any], limit: int | None) -> Any:
    """Return the first non-hassette ``FrameInfo`` in ``frames`` (already past any skipped frames).

    ``limit`` bounds the window AFTER the skip: applying it before would let internal frames
    consume the whole window and silently misattribute to a hassette frame. Falls back to the
    window's last frame when every frame in it is internal, and ``None`` for an empty window.
    """
    if limit is not None:
        frames = frames[:limit]
    for frame_info in frames:
        # FrameInfo from inspect.stack() has a .frame attribute with f_globals.
        # In tests we also pass SimpleNamespace objects directly — handle both.
        raw_frame = getattr(frame_info, "frame", frame_info)
        if not is_internal_frame(raw_frame):
            return frame_info
    return frames[-1] if frames else None


def capture_source_location(*, frames_to_skip: int = 0, limit: int | None = DEFAULT_FRAME_LIMIT) -> str:
    """Capture only the ``"<file>:<lineno>"`` of the calling frame — no file read, no AST parse.

    The cheap path for call sites with no DB-record telemetry (api fire-and-forget
    methods, ``add_listener``): they need only warning attribution and would
    discard the ``registration_source`` snippet that
    ``capture_registration_source`` computes.
    """
    filename, lineno = find_caller_frame(frames_to_skip=frames_to_skip, limit=limit)
    return f"{filename}:{lineno}"


def capture_registration_source(
    *, frames_to_skip: int = 0, limit: int | None = DEFAULT_FRAME_LIMIT
) -> tuple[str, str | None]:
    """Capture the source location and code of the calling registration.

    Walks the call stack, skips internal hassette frames (identified by
    ``f_globals["__name__"]`` starting with ``"hassette."``), and returns
    information about the first app-level (non-hassette) frame.

    Attribution uses the module-name check, not filesystem path fragments, so
    it works from site-packages, on Windows, and with any directory layout.

    Runs synchronously on the caller's thread — the event loop — for every registration,
    including runtime ones made from handlers, not just during initialization. The stack
    walk is always done; the snippet lookup is cached, so the file is read and parsed once
    per modification (``SOURCE_CACHE_MAX_SIZE`` files) and each call site's snippet is
    extracted once per modification (``CALL_SOURCE_CACHE_MAX_SIZE`` sites). Repeat calls
    from an unchanged line cost one ``stat`` plus a cache lookup.

    This function never raises — ``find_caller_frame`` catches stack-walk
    failures and ``find_call_source`` catches AST failures.  Any failure
    results in ``registration_source=None`` while ``source_location`` is still
    returned from the best available frame.

    Args:
        frames_to_skip: Additional frames at the top of the stack to skip
            before applying the hassette-internal filter.  Defaults to 0.
        limit: Maximum number of stack frames to inspect, counted from this function's
            frame after skipping ``frames_to_skip``.  Defaults to ``DEFAULT_FRAME_LIMIT``,
            which is sufficient for all public registration/scheduling/fire
            methods (user code is 1-3 frames from the public def).  Pass
            ``None`` for an unbounded walk.  Note: ``inspect.stack``'s
            ``context`` parameter controls source lines per frame, not frame
            count; this limit is applied by slicing the result.

    Returns:
        A tuple of ``(source_location, registration_source)`` where:

        - ``source_location`` is ``"<filename>:<lineno>"``
        - ``registration_source`` is the source snippet of the Call node, or
          ``None`` if unavailable.
    """
    filename, lineno = find_caller_frame(frames_to_skip=frames_to_skip, limit=limit)
    source_location = f"{filename}:{lineno}"

    # Only try AST lookup for real files (not REPL or frozen modules)
    if filename.startswith("<") or not filename:
        return (source_location, None)

    registration_source = find_call_source(filename, lineno)
    return (source_location, registration_source)
