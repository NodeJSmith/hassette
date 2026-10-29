"""Public re-exports for resource lifecycle and structural-operation functions."""

from hassette.resources.lifecycle import (
    cancel,
    create_service_status_event,
    handle_crash,
    handle_failed,
    handle_running,
    handle_starting,
    handle_stop,
    mark_not_ready,
    mark_ready,
    request_shutdown,
    start,
)
from hassette.resources.operations import (
    ordered_children_for_shutdown,
    register_task_bucket_factory,
    run_hooks,
    start_children_and_wait,
)
from hassette.resources.shutdown_outcome import ShutdownOutcome, ShutdownResult

__all__ = [
    "ShutdownOutcome",
    "ShutdownResult",
    "cancel",
    "create_service_status_event",
    "handle_crash",
    "handle_failed",
    "handle_running",
    "handle_starting",
    "handle_stop",
    "mark_not_ready",
    "mark_ready",
    "ordered_children_for_shutdown",
    "register_task_bucket_factory",
    "request_shutdown",
    "run_hooks",
    "start",
    "start_children_and_wait",
]
