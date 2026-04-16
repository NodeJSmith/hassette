"""Internal test utilities for hassette's own test suite.

These symbols are not part of the public API and may change without notice.
External users should use the Tier 1 API from ``hassette.test_utils`` instead.

This package exists solely to provide backward-compatible re-exports so that
hassette's own 200+ internal tests continue to work after the public API
restructure in WP05.
"""

from hassette.test_utils.fixtures import (
    build_harness,
    hassette_harness,
    hassette_with_app_handler,
    hassette_with_bus,
    hassette_with_file_watcher,
    hassette_with_mock_api,
    hassette_with_scheduler,
    hassette_with_state_proxy,
    run_hassette_startup_tasks,
)
from hassette.test_utils.harness import HassetteHarness, preserve_config, wait_for
from hassette.test_utils.helpers import (
    create_app_manifest,
    create_call_service_event,
    create_state_change_event,
    emit_file_change_event,
    emit_service_event,
    make_full_state_change_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_service_failed_event,
    make_service_running_event,
    make_state_dict,
    make_switch_state_dict,
    wire_up_app_running_listener,
    wire_up_app_state_listener,
    write_app_toml,
    write_test_app_with_decorator,
)
from hassette.test_utils.test_server import SimpleTestServer
from hassette.test_utils.web_helpers import (
    make_full_snapshot,
    make_job,
    make_listener_metric,
    make_manifest,
    make_old_app_instance,
    make_old_snapshot,
    make_real_job,
    setup_registry,
)
from hassette.test_utils.web_mocks import (
    create_hassette_stub,
    create_mock_runtime_query_service,
    create_test_fastapi_app,
)

__all__ = [
    "HassetteHarness",
    "SimpleTestServer",
    "build_harness",
    "create_app_manifest",
    "create_call_service_event",
    "create_hassette_stub",
    "create_mock_runtime_query_service",
    "create_state_change_event",
    "create_test_fastapi_app",
    "emit_file_change_event",
    "emit_service_event",
    "hassette_harness",
    "hassette_with_app_handler",
    "hassette_with_bus",
    "hassette_with_file_watcher",
    "hassette_with_mock_api",
    "hassette_with_scheduler",
    "hassette_with_state_proxy",
    "make_full_snapshot",
    "make_full_state_change_event",
    "make_job",
    "make_light_state_dict",
    "make_listener_metric",
    "make_manifest",
    "make_old_app_instance",
    "make_old_snapshot",
    "make_real_job",
    "make_sensor_state_dict",
    "make_service_failed_event",
    "make_service_running_event",
    "make_state_dict",
    "make_switch_state_dict",
    "preserve_config",
    "run_hassette_startup_tasks",
    "setup_registry",
    "wait_for",
    "wire_up_app_running_listener",
    "wire_up_app_state_listener",
    "write_app_toml",
    "write_test_app_with_decorator",
]
