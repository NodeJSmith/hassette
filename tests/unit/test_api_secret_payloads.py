"""Api write methods accept ``SecretStr`` anywhere in their payload (#3955).

Home Assistant gets the plaintext; the caller's payload, the ``call_service`` DEBUG line and
``RecordingApi`` records keep the masked ``SecretStr``.
"""

import logging

import orjson
import pytest
from pydantic import SecretStr

from hassette.utils.request_utils import unwrap_secrets
from tests.support.factories import make_recording_api
from tests.unit.conftest import awaited_kwargs, make_api

CODE = "1234"


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


def test_unwrap_secrets_recurses_without_mutating_input() -> None:
    """Nested SecretStr values are unwrapped into new containers; the input is left as passed."""
    secret = SecretStr(CODE)
    payload = {"code": secret, "nested": {"list": [secret, ("x", secret)]}, "n": 1}

    result = unwrap_secrets(payload)

    assert result == {"code": CODE, "nested": {"list": [CODE, ["x", CODE]]}, "n": 1}
    assert payload["code"] is secret
    assert payload["nested"]["list"][0] is secret


async def test_call_service_sends_plaintext_and_logs_masked(caplog: pytest.LogCaptureFixture) -> None:
    """SecretStr in keyword data and target reaches HA as plaintext; the DEBUG line stays masked."""
    api = make_api()
    api.logger.setLevel(logging.DEBUG)

    with caplog.at_level(logging.DEBUG, logger=api.logger.name):
        await api.call_service(
            "lock",
            "unlock",
            target={"entity_id": "lock.front"},
            code=SecretStr(CODE),
            extra={"pins": [SecretStr(CODE)]},
        )

    payload = awaited_kwargs(api.ws_send_json)
    assert payload["service_data"] == {"code": CODE, "extra": {"pins": [CODE]}}
    assert payload["target"] == {"entity_id": "lock.front"}
    orjson.dumps(payload)  # serializable as sent
    assert CODE not in caplog.text
    assert "Adding extra data to service call" in caplog.text


async def test_fire_event_sends_plaintext() -> None:
    """SecretStr in event_data reaches HA as plaintext."""
    api = make_api()

    await api.fire_event("custom", {"token": SecretStr(CODE)})

    assert awaited_kwargs(api.ws_send_and_wait)["event_data"] == {"token": CODE}


async def test_set_state_sends_plaintext() -> None:
    """SecretStr in state or attributes reaches HA as plaintext."""
    api = make_api()

    await api.set_state("sensor.test", SecretStr("on"), {"code": SecretStr(CODE)})

    assert awaited_kwargs(api.post_rest_request)["data"] == {"state": "on", "attributes": {"code": CODE}}


async def test_recording_api_records_secret_payloads() -> None:
    """RecordingApi records SecretStr-carrying writes, and assertions match on the SecretStr."""
    api = make_recording_api()
    secret = SecretStr(CODE)

    await api.call_service("lock", "unlock", target={"entity_id": "lock.front"}, code=secret)
    await api.fire_event("custom", {"token": secret})
    await api.set_state("sensor.test", "on", {"code": secret})

    api.assert_called("call_service", domain="lock", service="unlock", code=secret)
    api.assert_called("fire_event", event_type="custom", event_data={"token": secret})
    api.assert_called("set_state", entity_id="sensor.test", attributes={"code": secret})
