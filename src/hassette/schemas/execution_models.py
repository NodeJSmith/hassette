"""Pydantic models for unified execution telemetry DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

See ``schemas/__init__.py`` for the domain-file map.
"""

from typing import NamedTuple


class AppLastError(NamedTuple):
    error_message: str
    error_type: str | None
    timestamp: float
