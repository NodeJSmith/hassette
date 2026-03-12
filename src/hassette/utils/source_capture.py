"""Utilities for capturing the source location and code of a registration call."""

import ast
import functools
import inspect
from typing import Any

# Path fragments that identify internal hassette frames to skip
_INTERNAL_PATH_FRAGMENTS = ("hassette/bus/", "hassette/scheduler/", "hassette/core/")


def _is_internal_frame(filename: str) -> bool:
    """Return True if the frame belongs to an internal hassette module."""
    return any(fragment in filename for fragment in _INTERNAL_PATH_FRAGMENTS)


@functools.lru_cache(maxsize=256)
def _get_source_and_ast(filename: str) -> tuple[str, ast.Module] | None:
    """Return a cached (source, AST) pair for *filename*.

    Uses ``functools.lru_cache`` (maxsize=256) so each file is read and parsed
    at most once.  Thread-safe via the lru_cache internal lock.

    Returns None if the file cannot be read or parsed.
    """
    try:
        with open(filename, encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=filename)
        return source, tree
    except Exception:
        return None


def _find_call_source(filename: str, lineno: int) -> str | None:
    """Find the source snippet of the Call node at *lineno* in *filename*.

    Returns the source segment string, or None if unavailable.
    """
    cached = _get_source_and_ast(filename)
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


def capture_registration_source(*, frames_to_skip: int = 0) -> tuple[str, str | None]:
    """Capture the source location and code of the calling registration.

    Walks the call stack, skips internal hassette frames (from
    ``hassette/bus/``, ``hassette/scheduler/``, or ``hassette/core/``), and
    returns information about the first app-level frame.

    The per-file AST and source are cached (LRU, maxsize=256) so repeated
    calls from the same file only read and parse the file once.

    This function never raises.  Any failure in stack walking or AST parsing
    results in ``registration_source=None`` while ``source_location`` is still
    returned from the best available frame.

    Args:
        frames_to_skip: Additional frames at the top of the stack to skip
            before applying the hassette-internal filter.  Defaults to 0.

    Returns:
        A tuple of ``(source_location, registration_source)`` where:

        - ``source_location`` is ``"<filename>:<lineno>"``
        - ``registration_source`` is the source snippet of the Call node, or
          ``None`` if unavailable.
    """
    try:
        stack = inspect.stack()
    except Exception:
        return ("<unknown>:0", None)

    # Skip our own frame plus any caller-requested frames
    frames = stack[1 + frames_to_skip :]

    # Look for the first non-internal frame
    chosen: Any = None
    for frame_info in frames:
        filename: str = getattr(frame_info, "filename", "") or ""
        if not _is_internal_frame(filename):
            chosen = frame_info
            break

    # Fall back to the last frame if everything is internal (unlikely but safe)
    if chosen is None and frames:
        chosen = frames[-1]

    if chosen is None:
        return ("<unknown>:0", None)

    filename = getattr(chosen, "filename", "<unknown>") or "<unknown>"
    lineno: int = getattr(chosen, "lineno", 0) or 0
    source_location = f"{filename}:{lineno}"

    # Only try AST lookup for real files (not REPL or frozen modules)
    if filename.startswith("<") or not filename:
        return (source_location, None)

    registration_source = _find_call_source(filename, lineno)
    return (source_location, registration_source)
