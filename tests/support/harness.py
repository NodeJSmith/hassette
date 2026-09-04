"""Tier 2 test-harness helpers that are not part of the public test API."""

import contextlib
from collections.abc import Generator

from hassette import HassetteConfig


@contextlib.contextmanager
def preserve_config(config: HassetteConfig) -> Generator[None, None, None]:
    """Snapshot and restore config values around a test.

    Enables module-scoped hassette reuse when tests mutate config.

    Uses :meth:`~pydantic.BaseModel.model_copy` with ``deep=True`` so that
    ``SecretStr`` fields are preserved as their original objects rather than
    being serialised to the masked placeholder (``"**********"``).  Restoring
    via ``model_dump()`` would poison a ``SecretStr`` token to that masked
    string, which Pydantic would then coerce back to a ``SecretStr`` holding
    the wrong value under ``validate_assignment=True``.
    """
    snapshot = config.model_copy(deep=True)
    try:
        yield
    finally:
        for key in type(config).model_fields:
            setattr(config, key, getattr(snapshot, key))
