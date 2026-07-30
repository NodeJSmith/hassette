"""Topic-derived default priority tiers for bus listeners.

A listener that does not pass an explicit ``event_priority=`` gets its tier from its
topic, resolved once at registration time by :func:`classify_topic`. The table below is
the per-topic half of the priority configuration; the per-listener half is the
``event_priority=`` keyword on every ``Bus`` registration method.

Classification is deliberately a small, explicit table rather than a pattern language.
Every topic hassette itself publishes is listed; anything unrecognized (including
user topics passed to ``Bus.emit``) lands on ``NORMAL``, so an unknown topic is never
shed under load.
"""

from hassette.types.enums import EventPriority, Topic

_STATE_CHANGED_PREFIX = f"{Topic.HASS_EVENT_STATE_CHANGED!s}."
"""Prefix of an expanded state-change route (``hass.event.state_changed.light.office``)."""

LOW_CHURN_STATE_DOMAINS: frozenset[str] = frozenset({"sensor"})
"""Entity domains whose state changes classify as ``LOW``.

``sensor`` only. It is by far the highest-volume domain in a typical Home Assistant
install (power meters, uptime counters, per-device diagnostics) and its values are
cumulative — the next reading supersedes a shed one. ``binary_sensor`` is deliberately
absent: motion and door contacts are edge-triggered, so a shed event is lost information.
"""

TOPIC_PRIORITIES: dict[str, EventPriority] = {
    # Connectivity and service health: shedding these hides the outage that caused the load.
    Topic.HASSETTE_EVENT_SERVICE_STATUS: EventPriority.CRITICAL,
    Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED: EventPriority.CRITICAL,
    Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED: EventPriority.CRITICAL,
    Topic.HASSETTE_EVENT_APP_STATE_CHANGED: EventPriority.CRITICAL,
    # Deliberate actions — a person pressed something, or an automation ran.
    Topic.HASS_EVENT_CALL_SERVICE: EventPriority.HIGH,
    Topic.HASS_EVENT_AUTOMATION_TRIGGERED: EventPriority.HIGH,
    Topic.HASS_EVENT_SCRIPT_STARTED: EventPriority.HIGH,
    Topic.HASSETTE_EVENT_FILE_WATCHER: EventPriority.HIGH,
    Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED: EventPriority.HIGH,
    # One telemetry event per handler execution, so this scales with the very load that
    # saturates dispatch. Shedding it costs a dashboard refresh, not behavior.
    Topic.HASSETTE_EVENT_EXECUTION_COMPLETED: EventPriority.LOW,
}
"""Exact-topic tier assignments. Consulted after the state-change prefix check."""


def classify_topic(topic: str) -> EventPriority:
    """Return the default priority tier for a listener subscribed to ``topic``.

    State-change routes are classified by entity domain (``sensor`` is ``LOW``, everything
    else ``NORMAL``); all other topics come from :data:`TOPIC_PRIORITIES`, defaulting to
    ``NORMAL``.

    Args:
        topic: The listener's topic. May be a bare topic (``hass.event.call_service``), an
            expanded state route (``hass.event.state_changed.light.office``), or a domain
            glob (``hass.event.state_changed.sensor.*``).

    Returns:
        The tier to use when the registration did not specify ``event_priority=``.
    """
    if topic.startswith(_STATE_CHANGED_PREFIX):
        domain = topic[len(_STATE_CHANGED_PREFIX) :].split(".", 1)[0]
        return EventPriority.LOW if domain in LOW_CHURN_STATE_DOMAINS else EventPriority.NORMAL

    return TOPIC_PRIORITIES.get(topic, EventPriority.NORMAL)
