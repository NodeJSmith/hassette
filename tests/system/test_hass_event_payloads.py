"""Typed Home Assistant event payloads must parse what the pinned Home Assistant actually sends.

Typed payloads drop keys they don't declare and record each one in ``reported_unknown_keys``; a
payload missing a key it requires fails to parse, and the event is dropped with an ERROR log. The
test drives HA into firing one event of each typed kind below, then checks two things:

1. Arrival: at least one typed event of each kind reached the bus. A removed required key drops the
   event, so this is the check that catches it; the unknown-key check alone would pass.
2. Unknown keys: every (payload class, key) pair dropped during the run is on ``UNKNOWN_KEY_ALLOWLIST``,
   and every allowlist entry was dropped. An entry HA no longer sends fails as stale, so remove it.
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from hassette.events import AnyEvent
from hassette.events.hass import hass as hass_events
from hassette.events.hass.hass import (
    AutomationTriggeredEvent,
    CallServiceEvent,
    LogbookEntryEvent,
    ScriptStartedEvent,
)
from hassette.testing import wait_for
from hassette.types import Topic

from .conftest import make_event_collector, make_system_config, startup_context

pytestmark = [pytest.mark.system]

EVENT_TIMEOUT_SECONDS = 15.0

# Both carry an `id:` in the fixture config, so HA 2026.11+ sends item_id and run_id with their events.
AUTOMATION = "automation.state_model_automation"
SCRIPT = "script.state_model"

UNKNOWN_KEY_ALLOWLIST: dict[tuple[str, str], str] = {}
"""(payload class, key) pairs the pinned HA sends that the payload deliberately doesn't declare, each
with the reason. An entry that is no longer reported fails the test as stale, so remove it."""

TYPED_EVENTS: dict[Topic, type[AnyEvent]] = {
    Topic.HASS_EVENT_AUTOMATION_TRIGGERED: AutomationTriggeredEvent,
    Topic.HASS_EVENT_SCRIPT_STARTED: ScriptStartedEvent,
    Topic.HASS_EVENT_LOGBOOK_ENTRY: LogbookEntryEvent,
    Topic.HASS_EVENT_CALL_SERVICE: CallServiceEvent,
}


# Turning the shared script on and off is not idempotent mid-run, and a rerun would also see the
# unknown keys the first attempt already reported, so report the first failure instead of retrying.
@pytest.mark.flaky(reruns=0)
async def test_live_hass_events_parse_into_typed_payloads(ha_container: str, tmp_path: Path) -> None:
    """Each typed event kind arrives from a live HA, and no unexpected key is dropped from its payload."""
    hass_events.reported_unknown_keys.clear()
    config = make_system_config(ha_container, tmp_path)
    received: dict[Topic, list[Any]] = {}

    async with startup_context(config) as instance:
        for topic, event_cls in TYPED_EVENTS.items():
            received[topic], capture = make_event_collector(event_cls)
            await instance.bus.on(topic=topic, handler=capture, name=f"payloads_{topic.value}")

        api = instance.api

        async def arrived(topic: Topic, match: Callable[[Any], bool]) -> None:
            await wait_for(
                lambda: any(match(event.payload.data) for event in received[topic]),
                timeout=EVENT_TIMEOUT_SECONDS,
                desc=f"a typed {topic.value} event",
            )

        async def drive(topic: Topic, call: Callable[[], Awaitable[Any]], match: Callable[[Any], bool]) -> None:
            await call()
            await arrived(topic, match)

        await drive(
            Topic.HASS_EVENT_AUTOMATION_TRIGGERED,
            lambda: api.call_service("automation", "trigger", {"entity_id": AUTOMATION}, wait_for_ack=True),
            lambda data: data.entity_id == AUTOMATION,
        )
        try:
            await drive(
                Topic.HASS_EVENT_SCRIPT_STARTED,
                lambda: api.call_service("script", "turn_on", {"entity_id": SCRIPT}, wait_for_ack=True),
                lambda data: data.entity_id == SCRIPT,
            )
        finally:
            # The script holds on a long delay; stop it even when its typed event never arrives, so later
            # tests start from an idle script.
            await api.call_service("script", "turn_off", {"entity_id": SCRIPT}, wait_for_ack=True)
        await arrived(Topic.HASS_EVENT_CALL_SERVICE, lambda data: (data.domain, data.service) == ("script", "turn_off"))
        await drive(
            Topic.HASS_EVENT_LOGBOOK_ENTRY,
            lambda: api.call_service(
                "logbook", "log", wait_for_ack=True, name="Hassette", message="event payload check", entity_id=SCRIPT
            ),
            lambda data: data.message == "event payload check",
        )

    reported = set(hass_events.reported_unknown_keys)
    unexpected = sorted(reported - set(UNKNOWN_KEY_ALLOWLIST))
    stale = sorted(set(UNKNOWN_KEY_ALLOWLIST) - reported)
    failures = [
        *(
            f"{cls}.{key}: Home Assistant sends it but the payload drops it; declare the field "
            "or allowlist it in UNKNOWN_KEY_ALLOWLIST with a reason"
            for cls, key in unexpected
        ),
        *(f"{cls}.{key}: no longer sent; remove its UNKNOWN_KEY_ALLOWLIST entry" for cls, key in stale),
    ]
    assert not failures, f"{len(failures)} unknown-key check(s) failed:\n" + "\n".join(failures)
