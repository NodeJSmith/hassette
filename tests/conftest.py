import asyncio
import tracemalloc
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import tomli_w
from pydantic import Field

from hassette import HassetteConfig
from hassette.config.models import (
    AppConfig,
    FileWatcherConfig,
    LifecycleConfig,
    LoggingConfig,
    SchedulerConfig,
    WebApiConfig,
    WebSocketConfig,
)
from hassette.conversion.state_registry import StateRegistry
from hassette.conversion.type_registry import TypeRegistry
from hassette.task_bucket import TaskBucket

if TYPE_CHECKING:
    from hassette.test_utils.harness import HassetteHarness

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


def _test_file_watcher() -> FileWatcherConfig:
    return FileWatcherConfig(debounce_milliseconds=1, step_milliseconds=5)


def _test_websocket() -> WebSocketConfig:
    return WebSocketConfig(
        connection_timeout_seconds=1,
        authentication_timeout_seconds=1,
        total_timeout_seconds=2,
        response_timeout_seconds=1,
        heartbeat_interval_seconds=5,
    )


def _test_lifecycle() -> LifecycleConfig:
    return LifecycleConfig(
        startup_timeout_seconds=3,
        run_sync_timeout_seconds=2,
        task_cancellation_timeout_seconds=0.5,
    )


def _test_scheduler() -> SchedulerConfig:
    return SchedulerConfig(
        default_delay_seconds=1,
        min_delay_seconds=0.1,
        max_delay_seconds=3,
    )


def _test_logging() -> LoggingConfig:
    return LoggingConfig(task_bucket="DEBUG")


def _test_app() -> AppConfig:
    return AppConfig(directory=TEST_APPS_PATH, autodetect=False)


def _test_web_api() -> WebApiConfig:
    return WebApiConfig(run=False)


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

    file_watcher: FileWatcherConfig = Field(default_factory=_test_file_watcher)
    websocket: WebSocketConfig = Field(default_factory=_test_websocket)
    lifecycle: LifecycleConfig = Field(default_factory=_test_lifecycle)
    scheduler: SchedulerConfig = Field(default_factory=_test_scheduler)
    logging: LoggingConfig = Field(default_factory=_test_logging)
    app: AppConfig = Field(default_factory=_test_app)
    web_api: WebApiConfig = Field(default_factory=_test_web_api)

    def model_post_init(self, *args: Any) -> None:
        # override this to avoid values being set by defaults.py
        pass


@pytest.fixture(scope="session")
def test_config_class() -> type[HassetteConfig]:
    """
    Provide the TestConfig class for testing.
    This is used to ensure the configuration class is available for tests that require it.
    """
    return TestConfig


@pytest.fixture(scope="session")
def test_config(unused_tcp_port_factory) -> HassetteConfig:
    """
    Provide a HassetteConfig instance for testing.
    This is used to ensure the configuration is set up correctly for tests.
    """

    port = unused_tcp_port_factory()

    tc = TestConfig(web_api={"port": port})

    return tc


@pytest.fixture(scope="session")
def test_config_with_temp_path(tmp_path_factory: pytest.TempPathFactory) -> HassetteConfig:
    """
    Provide a HassetteConfig instance for testing.
    This is used to ensure the configuration is set up correctly for tests.
    """

    temp_dir = tmp_path_factory.mktemp("hassette_test_config")
    temp_path = Path(temp_dir)
    toml_path = temp_path / "hassette.toml"

    app_dir = temp_dir / "apps"
    app_dir.mkdir()

    toml_dict = {"hassette": {"dev_mode": True, "app": {"directory": app_dir.as_posix()}}}

    toml_path.write_text(tomli_w.dumps(toml_dict), encoding="utf-8")

    class MyTestConfig(TestConfig):
        model_config = TestConfig.model_config.copy() | {"toml_file": [toml_path], "env_file": [ENV_FILE]}

    return MyTestConfig()


@pytest.fixture
def env_file_path() -> Path:
    """
    Provide the path to the test environment file.
    This is used to ensure the environment is set up correctly for tests.
    """
    return ENV_FILE


@pytest.fixture(scope="session")
def test_events_path() -> Path:
    """Provide the path to the test events directory."""
    return TEST_EVENTS_PATH


@pytest.fixture(scope="session")
def apps_config_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a temporary hassette.toml populated with app definitions for app-centric tests."""

    tmp_dir = tmp_path_factory.mktemp("hassette_apps")
    toml_path = tmp_dir / "hassette.toml"
    toml_path.write_text(APPS_TOML_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    return toml_path


@pytest.fixture(scope="session")
def test_config_with_apps(apps_config_file: Path) -> HassetteConfig:
    """Provide a HassetteConfig instance that loads apps from a temporary hassette.toml."""

    class AppsTestConfig(TestConfig):
        model_config = TestConfig.model_config.copy() | {
            "toml_file": [apps_config_file],
            "env_file": [ENV_FILE],
        }

    config = AppsTestConfig()

    return config


@pytest.fixture
def my_app_class() -> type:
    """
    Provide the MyApp class for testing.
    This is used to ensure the MyApp class is available for tests that require it.
    """
    from data.apps.my_app import MyApp

    return MyApp


@pytest.fixture(autouse=True)
def _isolate_registries():
    """Snapshot and restore StateRegistry and TypeRegistry to prevent cross-test pollution."""
    state_snap = StateRegistry.snapshot()
    type_snap = TypeRegistry.snapshot()
    yield
    StateRegistry.restore(state_snap)
    TypeRegistry.restore(type_snap)


@pytest.fixture
async def bucket_fixture(hassette_with_nothing: "HassetteHarness") -> AsyncIterator[TaskBucket]:
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
