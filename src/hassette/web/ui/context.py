"""Template context helpers for the Hassette Web UI.

All business logic has been extracted to ``hassette.web.telemetry_helpers``.
This module re-exports everything for backwards compatibility during the
Preact migration.  Once the Jinja2 UI layer is removed (WP07), this file
is deleted.
"""

# Re-export everything from the canonical location so existing imports
# like ``from hassette.web.ui.context import classify_error_rate`` still work.
from hassette.web.telemetry_helpers import (
    _ListenerLike as _ListenerLike,
)
from hassette.web.telemetry_helpers import (
    alert_context as alert_context,
)
from hassette.web.telemetry_helpers import (
    base_context as base_context,
)
from hassette.web.telemetry_helpers import (
    classify_error_rate as classify_error_rate,
)
from hassette.web.telemetry_helpers import (
    classify_health_bar as classify_health_bar,
)
from hassette.web.telemetry_helpers import (
    compute_app_grid_health as compute_app_grid_health,
)
from hassette.web.telemetry_helpers import (
    compute_health_metrics as compute_health_metrics,
)
from hassette.web.telemetry_helpers import (
    extract_entity_from_topic as extract_entity_from_topic,
)
from hassette.web.telemetry_helpers import (
    format_handler_summary as format_handler_summary,
)
from hassette.web.telemetry_helpers import (
    safe_session_id as safe_session_id,
)

__all__ = [
    "alert_context",
    "base_context",
    "classify_error_rate",
    "classify_health_bar",
    "compute_app_grid_health",
    "compute_health_metrics",
    "extract_entity_from_topic",
    "format_handler_summary",
    "safe_session_id",
]
