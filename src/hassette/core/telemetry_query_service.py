"""Re-export shim — implementation lives in hassette.core.telemetry.

T16 can redirect all importers and remove this shim.
"""

from hassette.core.telemetry.execution_queries import DEFAULT_QUERY_LIMIT
from hassette.core.telemetry.helpers import (
    AppHealthAggregates,
    _build_app_summaries,
    _row_to_dict,
    _since_clause,
    _source_tier_clause,
)
from hassette.core.telemetry.query_service import TelemetryQueryService

__all__ = [
    "DEFAULT_QUERY_LIMIT",
    "AppHealthAggregates",
    "TelemetryQueryService",
    "_build_app_summaries",
    "_row_to_dict",
    "_since_clause",
    "_source_tier_clause",
]
