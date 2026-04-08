"""Test utilities for hassette apps.

Tier 1 APIs (AppTestHarness, RecordingApi, make_test_config, event factories)
are stable and documented for end users.

Tier 2 symbols (HassetteHarness, SimpleTestServer, fixtures, web helpers, etc.)
are re-exported from ``hassette.test_utils._internal`` for backward compatibility
with hassette's own internal test suite. They are not in ``__all__`` and may
change without notice.
"""

# Tier 1 — stable, documented, end-user API
# Tier 2 — backward-compatible re-exports from _internal (not in __all__).
# Self-alias pattern (`X as X`) signals to ruff/pyright that these are intentional re-exports.
from ._internal import HassetteHarness as HassetteHarness
from ._internal import SimpleTestServer as SimpleTestServer
from ._internal import build_harness as build_harness
from ._internal import create_app_manifest as create_app_manifest
from ._internal import create_hassette_stub as create_hassette_stub
from ._internal import create_mock_runtime_query_service as create_mock_runtime_query_service
from ._internal import create_test_fastapi_app as create_test_fastapi_app
from ._internal import emit_file_change_event as emit_file_change_event
from ._internal import emit_service_event as emit_service_event
from ._internal import hassette_harness as hassette_harness
from ._internal import hassette_with_app_handler as hassette_with_app_handler
from ._internal import hassette_with_bus as hassette_with_bus
from ._internal import hassette_with_file_watcher as hassette_with_file_watcher
from ._internal import hassette_with_mock_api as hassette_with_mock_api
from ._internal import hassette_with_scheduler as hassette_with_scheduler
from ._internal import hassette_with_state_proxy as hassette_with_state_proxy
from ._internal import make_full_snapshot as make_full_snapshot
from ._internal import make_full_state_change_event as make_full_state_change_event
from ._internal import make_job as make_job
from ._internal import make_listener_metric as make_listener_metric
from ._internal import make_manifest as make_manifest
from ._internal import make_old_app_instance as make_old_app_instance
from ._internal import make_old_snapshot as make_old_snapshot
from ._internal import make_service_failed_event as make_service_failed_event
from ._internal import make_service_running_event as make_service_running_event
from ._internal import preserve_config as preserve_config
from ._internal import run_hassette_startup_tasks as run_hassette_startup_tasks
from ._internal import setup_registry as setup_registry
from ._internal import wait_for as wait_for
from ._internal import wire_up_app_running_listener as wire_up_app_running_listener
from ._internal import wire_up_app_state_listener as wire_up_app_state_listener
from ._internal import write_app_toml as write_app_toml
from ._internal import write_test_app_with_decorator as write_test_app_with_decorator
from .app_harness import AppConfigurationError, AppTestHarness
from .config import make_test_config
from .helpers import (
    create_call_service_event,
    create_state_change_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_dict,
    make_switch_state_dict,
)
from .recording_api import ApiCall, RecordingApi

__all__ = [
    # Tier 1 only
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    "RecordingApi",
    "create_call_service_event",
    "create_state_change_event",
    "make_light_state_dict",
    "make_sensor_state_dict",
    "make_state_dict",
    "make_switch_state_dict",
    "make_test_config",
]
