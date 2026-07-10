"""Test utilities for hassette apps.

Tier 1 APIs (AppTestHarness, RecordingApi, make_test_config, event factories)
are stable and documented for end users.

Tier 2 symbols (HassetteHarness, SimpleTestServer, fixtures, web helpers, etc.)
are re-exported from ``hassette.test_utils._internal`` for backward compatibility
with hassette's own internal test suite. WebSocket stubs (``build_fake_ws``) come
from ``hassette.test_utils.ws_mocks``. They are not in ``__all__`` and may
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
from ._internal import hassette_harness as hassette_harness
from ._internal import hassette_with_app_handler as hassette_with_app_handler
from ._internal import hassette_with_bus as hassette_with_bus
from ._internal import hassette_with_file_watcher as hassette_with_file_watcher
from ._internal import hassette_with_mock_api as hassette_with_mock_api
from ._internal import hassette_with_scheduler as hassette_with_scheduler
from ._internal import hassette_with_state_proxy as hassette_with_state_proxy
from ._internal import make_full_snapshot as make_full_snapshot
from ._internal import make_full_state_change_event as make_full_state_change_event
from ._internal import make_hassette_event as make_hassette_event
from ._internal import make_job as make_job
from ._internal import make_manifest as make_manifest
from ._internal import make_mock_event as make_mock_event
from ._internal import make_mock_executor as make_mock_executor
from ._internal import make_mock_parent as make_mock_parent
from ._internal import make_real_job as make_real_job
from ._internal import make_recording_api as make_recording_api
from ._internal import make_scheduled_job as make_scheduled_job
from ._internal import make_service_failed_event as make_service_failed_event
from ._internal import make_service_running_event as make_service_running_event
from ._internal import preserve_config as preserve_config
from ._internal import run_hassette_startup_tasks as run_hassette_startup_tasks
from ._internal import wait_for as wait_for
from ._internal import wire_up_app_running_listener as wire_up_app_running_listener
from ._internal import wire_up_app_state_listener as wire_up_app_state_listener
from ._internal import write_app_toml as write_app_toml
from ._internal import write_test_app_with_decorator as write_test_app_with_decorator
from .api_call import ApiCall
from .app_harness import AppConfigurationError, AppTestHarness
from .config import make_test_config as make_test_config
from .exceptions import DrainError, DrainFailure, DrainTimeout
from .helpers import (
    create_call_service_event,
    create_state_change_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_dict,
    make_switch_state_dict,
    make_typed_state,
)
from .helpers import create_listener as create_listener
from .helpers import make_task_bucket as make_task_bucket
from .mock_hassette import make_mock_hassette as make_mock_hassette
from .mock_hassette import make_ws_hassette_stub as make_ws_hassette_stub
from .recording_api import RecordingApi
from .ws_mocks import build_fake_ws as build_fake_ws

__all__ = [
    # Tier 1 only
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    "DrainError",
    "DrainFailure",
    "DrainTimeout",
    "RecordingApi",
    "create_call_service_event",
    "create_state_change_event",
    "make_light_state_dict",
    "make_mock_hassette",
    "make_sensor_state_dict",
    "make_state_dict",
    "make_switch_state_dict",
    "make_test_config",
    "make_typed_state",
]
