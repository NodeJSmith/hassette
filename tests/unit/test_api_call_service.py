"""Unit tests for Api.call_service's send-path routing.

Three routes exist, selected by ``return_response`` and ``wait_for_ack``:

- default — fire-and-forget via ``ws_send_json``
- ``wait_for_ack=True`` — waits on HA's result envelope via ``ws_send_and_wait``, without
  asking for response data (regression coverage for #1851: HA rejects
  ``return_response=True`` for services that return no response, e.g. ``counter.increment``)
- ``return_response=True`` — waits and parses the response into a ``ServiceResponse``
"""

from unittest.mock import AsyncMock

import pytest

from hassette.exceptions import FailedMessageError
from hassette.models.services import ServiceResponse
from tests.unit.conftest import make_api


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


async def test_call_service_defaults_to_fire_and_forget() -> None:
    """Without wait_for_ack or return_response, the payload goes out via ws_send_json."""
    api = make_api()

    result = await api.call_service("counter", "increment", target={"entity_id": "counter.motion"})

    assert result is None
    api.ws_send_and_wait.assert_not_awaited()
    payload = api.ws_send_json.await_args.kwargs
    assert payload["type"] == "call_service"
    assert payload["domain"] == "counter"
    assert payload["service"] == "increment"


async def test_call_service_wait_for_ack_waits_without_requesting_response() -> None:
    """wait_for_ack routes through ws_send_and_wait and leaves return_response False.

    Regression test for #1851 — counter.increment/decrement/reset are declared as returning
    no response, so a payload carrying return_response=True is rejected by Home Assistant.
    """
    api = make_api()

    result = await api.call_service("counter", "increment", target={"entity_id": "counter.motion"}, wait_for_ack=True)

    assert result is None
    api.ws_send_json.assert_not_awaited()
    payload = api.ws_send_and_wait.await_args.kwargs
    assert payload["type"] == "call_service"
    assert payload["return_response"] is False


async def test_call_service_wait_for_ack_surfaces_ha_errors() -> None:
    """A failed result envelope reaches the caller instead of being silently dropped."""
    api = make_api()
    error = FailedMessageError("no such entity", code="service_validation_error")
    api.ws_send_and_wait = AsyncMock(side_effect=error)

    with pytest.raises(FailedMessageError) as exc_info:
        await api.call_service("counter", "increment", target={"entity_id": "counter.nope"}, wait_for_ack=True)

    assert exc_info.value is error


async def test_call_service_return_response_still_parses_response() -> None:
    """return_response=True keeps its existing behavior when wait_for_ack is also set."""
    api = make_api()
    api.ws_send_and_wait = AsyncMock(return_value={"response": {}, "context": {}})

    result = await api.call_service("calendar", "get_events", return_response=True, wait_for_ack=True)

    assert isinstance(result, ServiceResponse)
    api.ws_send_json.assert_not_awaited()
    assert api.ws_send_and_wait.await_args.kwargs["return_response"] is True
