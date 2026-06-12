"""Utilities for capturing the source location and code of a registration call."""

import ast
import functools
import inspect
from pathlib import Path
from typing import Any

# Per-file source/AST cache entries kept before LRU eviction.
SOURCE_CACHE_MAX_SIZE = 256
# Stack frames inspected after skipping internal frames — user code is 1-3 frames
# from the public def, so 8 leaves generous headroom.
DEFAULT_FRAME_LIMIT = 8


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
        with open(filename, encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=filename)
        return source, tree
    except Exception:
        return None


def find_call_source(filename: str, lineno: int) -> str | None:
    """Find the source snippet of the Call node at *lineno* in *filename*.

    Returns the source segment string, or None if unavailable.
    """
    try:
        mtime: int | None = Path(filename).stat().st_mtime_ns
    except OSError:
        mtime = None
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
    try:
        # Always walk with context=0 (zero source lines per frame) — cheapest possible.
        # inspect.stack's only parameter is `context` (source lines per frame), not a
        # frame-count limit; slicing here gives the real frame-count bound.
        raw_stack = inspect.stack(context=0)
    except Exception:
        return ("<unknown>", 0)

    # Skip our own frame plus any caller-requested frames FIRST, then bound the
    # window. Applying the limit before the skip would let internal frames consume
    # the whole window and silently misattribute to a hassette frame.
    frames = raw_stack[1 + frames_to_skip :]
    if limit is not None:
        frames = frames[:limit]

    # Look for the first non-internal frame
    chosen: Any = None
    for frame_info in frames:
        # FrameInfo from inspect.stack() has a .frame attribute with f_globals.
        # In tests we also pass SimpleNamespace objects directly — handle both.
        raw_frame = getattr(frame_info, "frame", frame_info)
        if not is_internal_frame(raw_frame):
            chosen = frame_info
            break

    # Fall back to the last frame if everything is internal (unlikely but safe)
    if chosen is None and frames:
        chosen = frames[-1]

    if chosen is None:
        return ("<unknown>", 0)

    filename = getattr(chosen, "filename", "<unknown>") or "<unknown>"
    lineno: int = getattr(chosen, "lineno", 0) or 0
    return (filename, lineno)


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

    The per-file AST and source are cached (LRU, ``SOURCE_CACHE_MAX_SIZE`` entries) so repeated
    calls from the same file only read and parse the file once.

    This function never raises — ``find_caller_frame`` catches stack-walk
    failures and ``find_call_source`` catches AST failures.  Any failure
    results in ``registration_source=None`` while ``source_location`` is still
    returned from the best available frame.

    Args:
        frames_to_skip: Additional frames at the top of the stack to skip
            before applying the hassette-internal filter.  Defaults to 0.
        limit: Maximum number of stack frames to inspect, counted *after*
            skipping our own frame and ``frames_to_skip``.  Defaults to ``DEFAULT_FRAME_LIMIT``,
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
