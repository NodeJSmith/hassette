"""Shared free functions and constants for the cache package.

Module-level functions used by both :class:`~hassette.cache.wrapper.AsyncCache` and
:class:`~hassette.cache.sync.SyncCache`. Neither class inherits from a shared base --
async/sync makes direct inheritance awkward, so DDL, TTL resolution, serialization, and
key validation live here as free functions that both import and call directly.
"""

import asyncio
import logging
import pickle

logger = logging.getLogger(__name__)

DESERIALIZE_FAILED = object()
"""Sentinel returned by :func:`deserialize` when unpickling fails.

Distinct from ``None`` -- callers may have legitimately cached a ``None`` value, and
that must round-trip as ``None`` rather than be mistaken for a failed deserialize.
"""

MISSING = object()
"""Sentinel used by ``get_or_set()`` implementations to distinguish a cache miss from a
legitimately-stored ``None`` value.

``get()`` returns ``None`` for both a missing key and a stored ``None`` value, so
``get_or_set()`` cannot use ``is not None`` to detect a hit -- doing so would re-invoke
the creator (and overwrite the cache) every time a caller stores ``None``. Passing
``default=MISSING`` and checking ``is not MISSING`` distinguishes the two cases.
"""

BUSY_TIMEOUT_MS = 5000
"""SQLite busy_timeout (ms) applied to every cache connection (async and sync),
matching the convention in ``database_service.py``'s ``_BUSY_TIMEOUT_MS``."""

SCHEMA_DDL = (
    "PRAGMA auto_vacuum = INCREMENTAL",
    "CREATE TABLE IF NOT EXISTS cache_entries (key TEXT PRIMARY KEY, value BLOB NOT NULL, expires_at REAL)",
)
"""DDL statements to run during cache initialization, in order.

``PRAGMA auto_vacuum = INCREMENTAL`` must run before ``CREATE TABLE`` -- it is a
no-op once a database already has tables, so ordering matters here.
"""


def resolve_ttl(ttl: int | None, default_ttl: int | None) -> int | None:
    """Resolve the effective TTL (seconds) for a ``set()`` call.

    Resolution order: per-call ``ttl`` -> instance ``default_ttl`` -> ``None`` (persist
    indefinitely). ``ttl=0`` is passed through unchanged -- callers special-case it as
    "delete any existing entry, don't store the new value".
    """
    if ttl is not None:
        return ttl
    return default_ttl


def serialize(value: object) -> bytes:
    """Pickle *value* for storage in the ``cache_entries.value`` BLOB column."""
    return pickle.dumps(value)


def deserialize(blob: bytes, key: str) -> object:
    """Unpickle a cached blob.

    Returns the unpickled value, or the :data:`DESERIALIZE_FAILED` sentinel (after
    logging a warning) if the blob can't be unpickled. Cached classes can be renamed,
    moved, or have their fields changed between restarts, and arbitrary corrupt bytes
    can fail in a variety of ways depending on exactly where the pickle stream breaks
    -- rather than crash, treat any of these as a cache miss. The caller is responsible
    for checking for the sentinel (not ``None`` -- a stored value can legitimately be
    ``None``) and deleting the stale row.
    """
    try:
        return pickle.loads(blob)  # noqa: S301 -- trusted local cache storage, not external input
    except (
        pickle.PickleError,
        AttributeError,
        ModuleNotFoundError,
        EOFError,
        ValueError,
        TypeError,
        IndexError,
        KeyError,
        ImportError,
        UnicodeDecodeError,
    ):
        logger.warning("Failed to deserialize cached value for key %r; treating as cache miss", key)
        return DESERIALIZE_FAILED


def validate_key(key: str) -> None:
    """Validate a cache key.

    Raises:
        ValueError: If *key* is not a non-empty string.
    """
    if not isinstance(key, str) or not key:
        raise ValueError(f"Cache key must be a non-empty string, got {key!r}")


def guard_not_in_event_loop(label: str) -> None:
    """Raise RuntimeError if called from inside a running event loop.

    Shared by :class:`~hassette.cache.sync.SyncCache` and
    :class:`~hassette.cache.dummy.DummySyncCache` so both sync facades enforce the
    same loop-safety contract from one implementation instead of two copies that can
    drift independently. Adapted from the loop-safety guard in ``task_bucket.py``'s
    ``run_sync()``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # not in a loop -> safe to run synchronously
    else:
        raise RuntimeError(
            f"This sync method ({label}) was called from within an event loop. Use the async method instead."
        )
