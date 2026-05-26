"""Standalone event filter for bus exclusion and system_log suppression.

Snapshots exclusion config at construction time; reconstruct to pick up config changes.
This class has NO dependency on Resource or Service — it is a plain utility.
"""

import logging
from typing import TYPE_CHECKING, Any

from hassette.events import Event, HassPayload
from hassette.utils.glob_utils import matches_globs, split_exact_and_glob

if TYPE_CHECKING:
    from hassette.events import EventPayload

_SYSTEM_LOG_SKIP_EVENT_TYPE = "call_service"
_SYSTEM_LOG_SKIP_DOMAIN = "system_log"
_SYSTEM_LOG_SKIP_LEVEL = "debug"


class EventFilter:
    """Determines whether an event should be skipped during bus dispatch.

    Snapshots exclusion config at construction time; does not observe config changes after init.
    """

    def __init__(
        self,
        excluded_domains: tuple[str, ...] | None,
        excluded_entities: tuple[str, ...] | None,
        logger: logging.Logger,
    ) -> None:
        self.logger = logger
        self.setup(excluded_domains or (), excluded_entities or ())

    def setup(self, domains: tuple[str, ...], entities: tuple[str, ...]) -> None:
        """Parse domain and entity exclusion config into exact/glob sets."""
        self._excluded_domains_exact, self._excluded_domain_globs = split_exact_and_glob(domains)
        self._excluded_entities_exact, self._excluded_entity_globs = split_exact_and_glob(entities)

        self._has_exclusions = bool(
            self._excluded_domains_exact
            or self._excluded_domain_globs
            or self._excluded_entities_exact
            or self._excluded_entity_globs
        )

        if self._has_exclusions:
            self.logger.debug(
                "Configured bus exclusions: domains=%s domain_globs=%s entities=%s entity_globs=%s",
                sorted(self._excluded_domains_exact),
                self._excluded_domain_globs,
                sorted(self._excluded_entities_exact),
                self._excluded_entity_globs,
            )

    def should_skip(self, topic: str, event: "Event[EventPayload[Any]]") -> bool:
        """Return True if the event should be dropped from dispatch.

        Only Home Assistant events (HassPayload) are subject to exclusion filtering.
        Non-HA events and events with no payload are always passed through.
        """
        if not event.payload:
            return False

        # Non-HA events are never filtered — we only filter HA events.
        if not isinstance(event.payload, HassPayload):
            return False

        payload = event.payload
        entity_id = getattr(payload, "entity_id", None)
        domain = getattr(payload, "domain", None)

        try:
            if (
                payload.event_type == _SYSTEM_LOG_SKIP_EVENT_TYPE
                and payload.data.domain == _SYSTEM_LOG_SKIP_DOMAIN
                and payload.data.service_data.get("level") == _SYSTEM_LOG_SKIP_LEVEL
            ):
                return True
        except AttributeError:
            self.logger.debug("Unexpected payload shape in system_log skip check for topic=%s", topic)

        if not self._has_exclusions:
            return False

        if not entity_id or not domain:
            return False

        if isinstance(entity_id, str):
            if entity_id in self._excluded_entities_exact or matches_globs(entity_id, self._excluded_entity_globs):
                self.logger.debug("Skipping dispatch for %s due to entity exclusion (%s)", topic, entity_id)
                return True

        if isinstance(domain, str) and domain:
            if domain in self._excluded_domains_exact or matches_globs(domain, self._excluded_domain_globs):
                self.logger.debug("Skipping dispatch for %s due to domain exclusion (%s)", topic, domain)
                return True

        return False
