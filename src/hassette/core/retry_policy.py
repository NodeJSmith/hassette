"""Shared retry-attempt budget for a request/reply exchange with Home Assistant.

Used by both :mod:`hassette.core.api_resource` (REST) and :mod:`hassette.core.websocket_service`
(``subscribe_events``/``send_and_wait``) — same concept, "how many times to retry a single HA
request/reply round-trip before giving up," just over different transports. Not shared with
``StateProxy``'s sync retry, which paces itself with ``websocket_reconnect.fast_backoff_delay``
instead of a fixed attempt budget.
"""

MAX_RETRY_ATTEMPTS = 5
"""Standard retry budget for one HA request/reply exchange, over REST or the WebSocket."""

SINGLE_ATTEMPT = 1
"""Attempt budget for an exchange that must not be retried (e.g. a non-idempotent WebSocket command)."""
