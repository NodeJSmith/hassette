import tracemalloc
from pathlib import Path

import pytest

from hassette.config.core_config import HassetteConfig

tracemalloc.start()

TEST_DATA_PATH = Path.cwd().joinpath("tests", "data")
ENV_FILE = TEST_DATA_PATH.joinpath(".env")
TEST_TOML_FILE = TEST_DATA_PATH.joinpath("hassette.toml")
APPS_TOML_TEMPLATE = TEST_DATA_PATH.joinpath("hassette_apps.toml")

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

    tc = TestConfig(
        websocket_timeout_seconds=1, run_sync_timeout_seconds=2, health_service_port=port, app_dir=TEST_DATA_PATH
    )

    return tc


@pytest.fixture
def env_file_path():
    """
    Provide the path to the test environment file.
    This is used to ensure the environment is set up correctly for tests.
    """
    return ENV_FILE


@pytest.fixture
def test_data_path():
    """
    Provide the path to the test data directory.
    This is used to access any test-specific files needed during testing.
    """
    return TEST_DATA_PATH


@pytest.fixture
def apps_config_file(tmp_path_factory):
    """Return a temporary hassette.toml populated with app definitions for app-centric tests."""

    tmp_dir = tmp_path_factory.mktemp("hassette_apps")
    toml_path = tmp_dir / "hassette.toml"
    toml_path.write_text(APPS_TOML_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return toml_path


@pytest.fixture
def test_config_with_apps(apps_config_file):
    """Provide a HassetteConfig instance that loads apps from a temporary hassette.toml."""

    class AppsTestConfig(TestConfig):
        model_config = TestConfig.model_config.copy() | {
            "toml_file": [apps_config_file],
            "env_file": [ENV_FILE],
        }

    previous_instance: HassetteConfig | None = getattr(HassetteConfig, "_instance", None)
    config = AppsTestConfig(
        websocket_timeout_seconds=1,
        run_sync_timeout_seconds=2,
        run_health_service=False,
        app_dir=TEST_DATA_PATH,
    )

    HassetteConfig._instance = config

    try:
        yield config
    finally:
        HassetteConfig._instance = previous_instance or HassetteConfig._instance


@pytest.fixture
def my_app_class():
    """
    Provide the MyApp class for testing.
    This is used to ensure the MyApp class is available for tests that require it.
    """
    from data.my_app import MyApp

    return MyApp
