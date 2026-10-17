"""Tier 2 test-harness helpers that are not part of the public test API."""

import contextlib
from collections.abc import Generator
from typing import TYPE_CHECKING

from hassette import HassetteConfig
from hassette.testing import make_full_state_change_event, wait_for

if TYPE_CHECKING:
    from hassette.testing import HassetteHarness


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


async def send_and_wait(
    hassette: "HassetteHarness", entity_id: str, old_state: dict | None, new_state: dict | None
) -> None:
    """Send a state change event and wait for the proxy to record the entity."""
    event = make_full_state_change_event(entity_id, old_state, new_state)
    await hassette.send_event(event)
    await wait_for(
        lambda: hassette.state_proxy.get_state(entity_id) is not None,
        desc=f"{entity_id} state arrived",
    )
