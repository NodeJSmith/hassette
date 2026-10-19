"""Table columns shared by more than one CLI command."""

from hassette.cli.formatters import fmt_duration_ms, fmt_relative_time
from hassette.cli.output import Column


def health_activity_columns(field_prefix: str = "") -> list[Column]:
    """Return the Handler Avg, Job Avg, and Last Active columns.

    Args:
        field_prefix: Dotted path prepended to each field name, for rows that nest the health
            fields (e.g. ``"activity.stats.health."``). Include the trailing dot.
    """
    return [
        Column(f"{field_prefix}handler_avg_duration_ms", "Handler Avg", max_width=11, formatter=fmt_duration_ms),
        Column(f"{field_prefix}job_avg_duration_ms", "Job Avg", max_width=9, formatter=fmt_duration_ms),
        Column(f"{field_prefix}last_activity_ts", "Last Active", max_width=11, formatter=fmt_relative_time),
    ]
