import asyncio
import threading
import time
import tracemalloc
from contextlib import suppress
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import docker
import pytest
import requests
from docker.errors import NotFound
from docker.models.containers import Container
from pydantic_settings import SettingsConfigDict, TomlConfigSettingsSource

from hassette.config.core_config import HassetteConfig
from hassette.core.core import Hassette

tracemalloc.start()

TEST_DATA_PATH = Path.cwd().joinpath("tests", "data")
ENV_FILE = TEST_DATA_PATH.joinpath(".env")
TEST_TOML_FILE = TEST_DATA_PATH.joinpath("hassette.toml")

assert ENV_FILE.exists(), f"Environment file {ENV_FILE} does not exist"
assert TEST_TOML_FILE.exists(), f"Test TOML file {TEST_TOML_FILE} does not exist"

# this wants package.nested_directories.final_file_name
# do not include the name of the fixture
pytest_plugins = ["hassette.test_utils.fixtures"]

# TODO:
# figure out how to get websocket mocked for some tests but not others
# i think the fixtures/patch are clashing with each other


class TestConfig(HassetteConfig):
    """
    A test configuration class that inherits from HassetteConfig.
    This is used to provide a specific configuration for testing purposes.
    """

    model_config = SettingsConfigDict(
        env_prefix="hassette__",
        env_file=ENV_FILE.as_posix(),
        toml_file=TEST_TOML_FILE.as_posix(),
        env_ignore_empty=True,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        sources = (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )
        return sources


@pytest.fixture(scope="session")
def test_config():
    """
    Provide a HassetteConfig instance for testing.
    This is used to ensure the configuration is set up correctly for tests.
    """

    tc = TestConfig(websocket_timeout_seconds=1, run_sync_timeout_seconds=2)  # type: ignore

    assert tc.websocket_timeout_seconds == 1

    return tc


@pytest.fixture(scope="session")
def docker_client():
    client = docker.from_env()
    yield client
    client.close()


@pytest.fixture(scope="session")
def homeassistant_container(docker_client: docker.DockerClient):
    project_root = Path(__file__).parent.parent
    config_dir = project_root / "volumes" / "config"

    should_stop = True
    container = None

    try:
        resp = requests.get("http://localhost:8123/")
        resp.raise_for_status()
        container = docker_client.containers.get("test-homeassistant")
        should_stop = False
        print(f"Reusing existing Home Assistant container (status: {container.status})")

    except Exception:
        pass

    if not container:
        print("Starting new Home Assistant container...")

        with suppress(NotFound):
            container = docker_client.containers.get("test-homeassistant")
            if container.status == "exited":
                container.remove()
                time.sleep(0.5)

        container = docker_client.containers.run(
            "homeassistant/home-assistant:stable",
            name="test-homeassistant",
            ports={"8123/tcp": 8123},
            volumes={str(config_dir): {"bind": "/config", "mode": "rw"}},
            user="1000:1000",
            detach=True,
            remove=True,
        )

        while True:
            try:
                resp = requests.get("http://localhost:8123/")
                resp.raise_for_status()
                time.sleep(1)  # give it a moment to fully settle
                break
            except Exception:
                time.sleep(1)

    yield container

    if should_stop:
        container.stop()


@pytest.fixture(scope="session")
def hassette_logging(test_config: TestConfig):
    hassette = Hassette(config=test_config)
    return hassette


@pytest.fixture(scope="module")
async def hassette_core(test_config: TestConfig, homeassistant_container: Container):
    # this line is mostly here to keep pyright/ruff from complaining that we aren't using the variable
    assert homeassistant_container.status in ["created", "running"], (
        f"Home Assistant container is not running ({homeassistant_container.status})"
    )

    hassette = Hassette(config=test_config)
    hassette._health_service = AsyncMock()

    print("loop is", hassette._loop, id(hassette._loop))

    # Launch run_forever() which enters its own context
    task = asyncio.create_task(hassette.run_forever())

    while not hassette._websocket.connected:
        await asyncio.sleep(0.1)

    await hassette.ready_event.wait()

    yield hassette

    await asyncio.sleep(0.1)

    # shutdown and then pause for things to settle
    hassette.shutdown()
    await asyncio.sleep(0.1)
    await hassette._shutdown_event.wait()

    # cancel our task group to ensure all tasks are cleaned up
    task.cancel()

    with suppress(asyncio.CancelledError):
        await task


@pytest.fixture
def hassette_core_sync(test_config: TestConfig, homeassistant_container: Container):
    # this line is mostly here to keep pyright/ruff from complaining that we aren't using the variable
    assert homeassistant_container.status in ["created", "running"], (
        f"Home Assistant container is not running ({homeassistant_container.status})"
    )

    # mock health service in this one, as we will only actually test health service
    # from the other fixture
    with patch("hassette.core.core._HealthService", Mock()):
        hassette = Hassette(config=test_config)

    ready = threading.Event()

    def runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # ensure loop is captured on the right thread (see patch above)
        task = loop.create_task(hassette.run_forever())

        # stop the loop when Hassette stops
        task.add_done_callback(lambda _: loop.call_soon_threadsafe(loop.stop))

        # wait until Hassette signals ready
        def _mark_ready():
            ready.set()

        async def _wait_ready():
            await hassette.ready_event.wait()
            await asyncio.sleep(0.1)  # ensure we have some time for stuff to start up
            # TODO: replace above with an actual wait on websocket service event or status
            _mark_ready()

        wait_ready_task = loop.create_task(_wait_ready())
        assert wait_ready_task is not None, "here for the type checker"

        loop.run_forever()
        loop.close()

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    assert ready.wait(15), "Hassette did not become ready in time"

    try:
        yield hassette
    finally:
        hassette.shutdown()
        # give the runner thread a moment to exit cleanly
        t.join(timeout=5)


@pytest.fixture
async def hassette_core_no_ha(test_config: TestConfig):
    with patch("hassette.core.core._Websocket", Mock()) as websocket_mock:
        websocket_mock.shutdown = AsyncMock()
        hassette = Hassette(config=test_config)
        hassette._health_service = AsyncMock()

        # Launch run_forever() which enters its own context
        task = asyncio.create_task(hassette.run_forever())

        await hassette.ready_event.wait()

        yield hassette

        await asyncio.sleep(0.1)

        # shutdown and then pause for things to settle
        hassette.shutdown()
        await asyncio.sleep(0.1)
        await hassette._shutdown_event.wait()

        # cancel our task group to ensure all tasks are cleaned up
        task.cancel()

        with suppress(asyncio.CancelledError):
            await task


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
