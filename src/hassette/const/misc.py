from typing import Literal

from typing_extensions import Sentinel

MISSING_VALUE = Sentinel("MISSING_VALUE")
"""Sentinel value to indicate a missing value."""

NOT_PROVIDED = Sentinel("NOT_PROVIDED")
"""Sentinel value to indicate a value was not provided."""

LOG_LEVELS = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""
