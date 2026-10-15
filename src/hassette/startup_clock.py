"""Process-start reference point for the startup log.

``hassette/__init__.py`` imports this module before anything else, so ``PROCESS_START`` is read
before the package's eager imports, which make up nearly all of the time between interpreter start
and ``Hassette.wire_services()``. Only the interpreter's own boot (well under 100ms) precedes it.
"""

import time

PROCESS_START = time.monotonic()
"""``time.monotonic()`` as of the first import of the ``hassette`` package."""


def seconds_since_process_start() -> float:
    """Return the seconds elapsed since the ``hassette`` package was first imported."""
    return time.monotonic() - PROCESS_START
