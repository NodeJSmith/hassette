from typing import Literal

SourceTier = Literal["app", "framework"]
"""Identifies whether a telemetry record originates from a user app or the framework itself."""

LOG_LEVEL_TYPE = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""

QuerySourceTier = Literal["app", "framework", "all"]
"""Valid source_tier values for query-side filtering. 'all' disables the filter."""
