"""Shared retry-attempt budget for a request/reply exchange with Home Assistant.

Used by both :mod:`hassette.core.api_resource` (REST) and :mod:`hassette.core.websocket_service`
(``subscribe_events``/``send_and_wait``) — same concept, "how many times to retry a single HA
request/reply round-trip before giving up," just over different transports. Deliberately not
shared with :mod:`hassette.core.state_proxy`'s own retry budget, which retries local cache-read
methods on a much tighter, sub-second backoff — a coincidentally equal number for a materially
different concern (see that module's own constant and comment).
"""

MAX_RETRY_ATTEMPTS = 5
"""Standard retry budget for one HA request/reply exchange, over REST or the WebSocket."""
