import asyncio
import logging
import tracemalloc
from pathlib import Path

import pytest

from hassette import Hassette, HassetteConfig

tracemalloc.start()

TEST_DATA_PATH = Path.cwd().joinpath("tests", "data")
TEST_CONFIG_PATH = TEST_DATA_PATH / "config"
TEST_EVENTS_PATH = TEST_DATA_PATH / "events"
TEST_API_RESPONSES_PATH = TEST_DATA_PATH / "api_responses"
TEST_APPS_PATH = TEST_DATA_PATH / "apps"

ENV_FILE = TEST_CONFIG_PATH / ".env"
TEST_TOML_FILE = TEST_CONFIG_PATH / "hassette.toml"
APPS_TOML_TEMPLATE = TEST_CONFIG_PATH / "hassette_apps.toml"

assert ENV_FILE.exists(), f"Environment file {ENV_FILE} does not exist"
assert TEST_TOML_FILE.exists(), f"Test TOML file {TEST_TOML_FILE} does not exist"
assert APPS_TOML_TEMPLATE.exists(), f"Apps TOML template {APPS_TOML_TEMPLATE} does not exist"

# this wants package.nested_directories.final_file_name
# do not include the name of the fixture
pytest_plugins = ["hassette.test_utils.fixtures"]


class TestConfig(HassetteConfig):
    """
    A test configuration class that inherits from HassetteConfig.
    This is used to provide a specific configuration for testing purposes.
    """

    model_config = HassetteConfig.model_config.copy() | {
        "cli_parse_args": False,
        "toml_file": TEST_TOML_FILE,
        "env_file": ENV_FILE,
    }

    token: str = "test-token"

    file_watcher_debounce_milliseconds: int | float = 1
    file_watcher_step_milliseconds: int | float = 5
    websocket_connection_timeout_seconds: int | float = 1
    websocket_authentication_timeout_seconds: int | float = 1
    websocket_total_timeout_seconds: int | float = 2
    websocket_response_timeout_seconds: int | float = 1
    websocket_heartbeat_interval_seconds: int | float = 5
    run_sync_timeout_seconds: int | float = 2
    startup_timeout_seconds: int | float = 3
    scheduler_default_delay_seconds: int | float = 1
    scheduler_min_delay_seconds: int | float = 0.1
    scheduler_max_delay_seconds: int | float = 3
    task_cancellation_timeout_seconds: int | float = 0.5
    task_bucket_log_level: str = "DEBUG"
    autodetect_apps: bool = False

    app_dir: Path = TEST_APPS_PATH

    def model_post_init(self, *args):
        # override this to avoid values being set by defaults.py
        pass


@pytest.fixture(scope="session")
def test_config_class():
    """
    Provide the TestConfig class for testing.
    This is used to ensure the configuration class is available for tests that require it.
    """
    return TestConfig


@pytest.fixture(scope="session")
def test_config(unused_tcp_port_factory):
    """
    Provide a HassetteConfig instance for testing.
    This is used to ensure the configuration is set up correctly for tests.
    """

    port = unused_tcp_port_factory()

    tc = TestConfig(health_service_port=port)

    return tc


@pytest.fixture
def env_file_path():
    """
    Provide the path to the test environment file.
    This is used to ensure the environment is set up correctly for tests.
    """
    return ENV_FILE


@pytest.fixture(scope="session")
def test_data_path():
    """
    Provide the path to the test data directory.
    This is used to access any test-specific files needed during testing.
    """
    return TEST_DATA_PATH


@pytest.fixture(scope="session")
def test_config_path():
    """Provide the path to the test config directory."""
    return TEST_CONFIG_PATH


@pytest.fixture(scope="session")
def test_events_path():
    """Provide the path to the test events directory."""
    return TEST_EVENTS_PATH


@pytest.fixture(scope="session")
def test_api_responses_path():
    """Provide the path to the test API responses directory."""
    return TEST_API_RESPONSES_PATH


@pytest.fixture(scope="session")
def test_apps_path():
    """Provide the path to the test apps directory."""
    return TEST_APPS_PATH


@pytest.fixture(scope="session")
def apps_config_file(tmp_path_factory):
    """Return a temporary hassette.toml populated with app definitions for app-centric tests."""

    tmp_dir = tmp_path_factory.mktemp("hassette_apps")
    toml_path = tmp_dir / "hassette.toml"
    toml_path.write_text(APPS_TOML_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return toml_path


@pytest.fixture(scope="session")
def test_config_with_apps(apps_config_file):
    """Provide a HassetteConfig instance that loads apps from a temporary hassette.toml."""

    class AppsTestConfig(TestConfig):
        model_config = TestConfig.model_config.copy() | {
            "toml_file": [apps_config_file],
            "env_file": [ENV_FILE],
        }

    config = AppsTestConfig(run_health_service=False, app_dir=TEST_APPS_PATH)

    return config


@pytest.fixture
def my_app_class():
    """
    Provide the MyApp class for testing.
    This is used to ensure the MyApp class is available for tests that require it.
    """
    from data.apps.my_app import MyApp

    return MyApp


@pytest.fixture
def caplog_info(caplog):
    caplog.set_level(logging.INFO)
    return caplog


@pytest.fixture
async def bucket_fixture(hassette_with_nothing: Hassette):  # pytest-asyncio provides event_loop
    try:
        yield hassette_with_nothing.task_bucket
    finally:
        # hard cleanup if a test forgot
        await hassette_with_nothing.task_bucket.cancel_all()
        await asyncio.sleep(0)  # let cancellations propagate

        # last-resort parachute: fail if anything still running
        current = asyncio.current_task()
        leftovers = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        if leftovers:
            # cancel and wait briefly so the loop can unwind
            for t in leftovers:
                t.cancel()
            await asyncio.wait(leftovers, timeout=0.2)
            raise AssertionError(f"Leftover tasks after test: {[t.get_name() for t in leftovers]}")
