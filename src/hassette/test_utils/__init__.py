"""These are quick and dirty fixtures for testing during internal development.

They currently are not meant to be used by external users and will likely not be supported (e.g. bug requests).
However, if you find them useful, knock yourself out.
"""

from .fixtures import (
    hassette_harness,
    hassette_with_app_handler,
    hassette_with_bus,
    hassette_with_file_watcher,
    hassette_with_mock_api,
    hassette_with_scheduler,
    hassette_with_state_proxy,
)
from .harness import HassetteHarness, preserve_config
from .mock_hassette import create_mock_data_sync_service, create_mock_hassette, create_test_fastapi_app
from .test_server import SimpleTestServer
from .web_helpers import make_full_snapshot, make_listener_metric, make_manifest, setup_registry

__all__ = [
    "HassetteHarness",
    "SimpleTestServer",
    "create_mock_data_sync_service",
    "create_mock_hassette",
    "create_test_fastapi_app",
    "hassette_harness",
    "hassette_with_app_handler",
    "hassette_with_bus",
    "hassette_with_file_watcher",
    "hassette_with_mock_api",
    "hassette_with_scheduler",
    "hassette_with_state_proxy",
    "make_full_snapshot",
    "make_listener_metric",
    "make_manifest",
    "preserve_config",
    "setup_registry",
]

# TODO: clean these up and make them user facing
