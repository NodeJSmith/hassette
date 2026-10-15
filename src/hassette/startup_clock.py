"""Package-import reference point for the startup log.

``hassette/__init__.py`` imports this module before anything else, so ``IMPORT_START`` is read
before the package's eager imports. Time a host process spends before its first ``import hassette``
(interpreter boot, or an embedding application's own work) is not counted.
"""

import time

IMPORT_START = time.monotonic()
"""``time.monotonic()`` as of the first import of the ``hassette`` package."""


def seconds_since_import() -> float:
    """Return the seconds elapsed since the ``hassette`` package was first imported."""
    return time.monotonic() - IMPORT_START
