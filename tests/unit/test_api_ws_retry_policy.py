"""Which Api methods let a WebSocket response timeout re-send the command.

Writes (``fire_event``) pass ``retry_on_timeout=False`` so a lost response envelope can't apply
the command twice. Reads keep ``ws_send_and_wait``'s retrying default. ``call_service`` is covered
in ``test_api_call_service.py`` and helper CRUD in ``tests/integration/test_api_helpers.py``.
"""

from unittest.mock import AsyncMock

import pytest

from tests.unit.conftest import make_api


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


async def test_fire_event_does_not_retry_on_timeout() -> None:
    api = make_api()

    await api.fire_event("doorbell_pressed", {"zone": "front"})

    assert api.ws_send_and_wait.await_args.kwargs["retry_on_timeout"] is False


@pytest.mark.parametrize(
    ("method", "return_value"),
    [("get_states_raw", []), ("get_config", {}), ("get_services", {}), ("get_panels", {})],
)
async def test_reads_keep_retrying_default(method: str, return_value: object) -> None:
    api = make_api()
    api.ws_send_and_wait = AsyncMock(return_value=return_value)

    await getattr(api, method)()

    assert api.ws_send_and_wait.await_args.kwargs.get("retry_on_timeout", True) is True
