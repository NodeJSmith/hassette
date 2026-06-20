"""Live execution count snapshot for bus listeners.

Extracted from ``hassette.core.bus_service`` so that both ``core`` (producer)
and ``web`` (consumer) can import it without a ``web → core`` cycle.
"""

from typing import NamedTuple


class LiveCounts(NamedTuple):
    """Live execution count snapshot for a single listener.

    All three counters are in-memory only and reset on restart.
    """

    suppressed: int
    """Events dropped by the single-mode guard while a prior invocation was running."""

    dropped: int
    """Events dropped by the queued-mode guard when the queue cap was reached."""

    backpressure_dropped: int
    """Events dropped at the dispatch acquire gate due to DROP_NEWEST backpressure."""


__all__ = ["LiveCounts"]
