"""Telemetry query constants shared between core and web.

Extracted from ``hassette.core.telemetry.helpers`` so that ``hassette.web``
can import them without a ``web → core`` dependency.
"""

DEFAULT_QUERY_LIMIT = 50
"""Default row cap for telemetry list queries. Single source of truth across query modules."""

MAX_QUERY_LIMIT = 500
"""Upper bound on the row cap a client may request for telemetry list queries."""

DEFAULT_SPARKLINE_BUCKETS = 12
"""Default number of time buckets for per-app activity sparklines."""

__all__ = ["DEFAULT_QUERY_LIMIT", "DEFAULT_SPARKLINE_BUCKETS", "MAX_QUERY_LIMIT"]
