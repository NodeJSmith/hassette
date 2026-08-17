"""Unit tests for Api.notify, Api.get_notify_services, and notifier normalization.

Tests cover:
- notify() sends a notify.<notifier> service call with the expected service_data
- Bare and fully-qualified notifier names normalize to the same service call
- Blank and wrong-domain notifiers raise ValueError at the call site
- title/data are omitted from the wire payload when None
- get_notify_services() returns sorted bare names, and [] when HA exposes no notifiers
"""

from unittest.mock import AsyncMock

import pytest

from hassette.api.api import normalize_notifier
from tests.unit.conftest import make_api


@pytest.fixture(autouse=True)
def _drain(drain_forgotten_await_handles: None) -> None:
    """Drain dropped handles after each test (shared fixture in tests/unit/conftest.py)."""


def sent_payload(api) -> dict:
    """Return the single payload passed to the mocked ws_send_json."""
    assert api.ws_send_json.await_count == 1, (
        f"Expected exactly one ws_send_json call, got {api.ws_send_json.await_count}"
    )
    return api.ws_send_json.await_args.kwargs


async def test_notify_calls_notify_domain_service() -> None:
    """notify() targets notify.<notifier> and passes message as service data."""
    api = make_api()

    await api.notify("The garage door is still open", "mobile_app_phone")

    payload = sent_payload(api)
    assert payload["type"] == "call_service"
    assert payload["domain"] == "notify"
    assert payload["service"] == "mobile_app_phone"
    assert payload["service_data"] == {"message": "The garage door is still open"}


async def test_notify_includes_title_and_data() -> None:
    """Title and data are forwarded as service data fields."""
    api = make_api()

    await api.notify(
        "Motion in the driveway",
        "mobile_app_phone",
        title="Security",
        data={"push": {"sound": "alarm.caf"}},
    )

    assert sent_payload(api)["service_data"] == {
        "message": "Motion in the driveway",
        "title": "Security",
        "data": {"push": {"sound": "alarm.caf"}},
    }


async def test_notify_omits_unset_title_and_data() -> None:
    """Unset title/data are dropped rather than sent as nulls."""
    api = make_api()

    await api.notify("hello", "mobile_app_phone")

    assert sent_payload(api)["service_data"] == {"message": "hello"}


async def test_notify_accepts_fully_qualified_notifier() -> None:
    """A 'notify.'-qualified notifier produces the same call as the bare name."""
    api = make_api()

    await api.notify("hello", "notify.mobile_app_phone")

    payload = sent_payload(api)
    assert payload["domain"] == "notify"
    assert payload["service"] == "mobile_app_phone"


@pytest.mark.parametrize("notifier", ["", "   ", "notify.", "light.kitchen", "notify.foo.bar"])
async def test_notify_rejects_invalid_notifier(notifier: str) -> None:
    """Blank or wrong-domain notifiers raise ValueError before anything is sent."""
    api = make_api()

    with pytest.raises(ValueError, match="notifier"):
        await api.notify("hello", notifier)

    assert api.ws_send_json.await_count == 0, "No service call should be sent for an invalid notifier"


@pytest.mark.parametrize(
    ("notifier", "expected"),
    [
        ("mobile_app_phone", "mobile_app_phone"),
        ("notify.mobile_app_phone", "mobile_app_phone"),
        ("  notify.persistent_notification  ", "persistent_notification"),
    ],
)
def test_normalize_notifier(notifier: str, expected: str) -> None:
    """normalize_notifier strips whitespace and the optional notify. prefix."""
    assert normalize_notifier(notifier) == expected


async def test_get_notify_services_returns_sorted_bare_names() -> None:
    """get_notify_services returns the notify domain's service names, sorted."""
    api = make_api()
    api.get_services = AsyncMock(
        return_value={
            "light": {"turn_on": {}},
            "notify": {"mobile_app_phone": {}, "persistent_notification": {}, "alexa_media": {}},
        }
    )

    assert await api.get_notify_services() == ["alexa_media", "mobile_app_phone", "persistent_notification"]


async def test_get_notify_services_without_notify_domain() -> None:
    """An instance with no notify services yields an empty list, not a KeyError."""
    api = make_api()
    api.get_services = AsyncMock(return_value={"light": {"turn_on": {}}})

    assert await api.get_notify_services() == []
