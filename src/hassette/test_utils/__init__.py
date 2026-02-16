"""These are quick and dirty fixtures for testing during internal development.

They currently are not meant to be used by external users and will likely not be supported (e.g. bug requests).
However, if you find them useful, knock yourself out.
"""

from .fixtures import (
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
from .harness import HassetteHarness, preserve_config, wait_for
from .helpers import (
    create_app_manifest,
    create_call_service_event,
    create_state_change_event,
    make_full_state_change_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_dict,
    make_switch_state_dict,
    write_app_toml,
    write_test_app_with_decorator,
)
from .mock_hassette import create_mock_data_sync_service, create_mock_hassette, create_test_fastapi_app
from .test_server import SimpleTestServer
from .web_helpers import (
    make_full_snapshot,
    make_job,
    make_listener_metric,
    make_manifest,
    make_old_app_instance,
    make_old_snapshot,
    setup_registry,
)

__all__ = [
    "HassetteHarness",
    "SimpleTestServer",
    "build_harness",
    "create_app_manifest",
    "create_call_service_event",
    "create_mock_data_sync_service",
    "create_mock_hassette",
    "create_state_change_event",
    "create_test_fastapi_app",
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
    "make_sensor_state_dict",
    "make_state_dict",
    "make_switch_state_dict",
    "preserve_config",
    "run_hassette_startup_tasks",
    "setup_registry",
    "wait_for",
    "write_app_toml",
    "write_test_app_with_decorator",
]
