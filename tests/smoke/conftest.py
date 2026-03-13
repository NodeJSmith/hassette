"""Smoke test fixtures."""

import asyncio
import subprocess
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic_settings import SettingsConfigDict

from hassette import Hassette
from hassette.config.config import HassetteConfig

# pyproject.toml sets filterwarnings=["error"] globally.
# Smoke tests run against external containers (HA, httpx) that may emit
# DeprecationWarnings we cannot control. Downgrade them to warnings, not errors.
pytestmark = pytest.mark.filterwarnings("default::DeprecationWarning")

COMPOSE_FILE = Path(__file__).parent / "docker-compose.yml"
HA_URL = "http://localhost:18123"
HA_TOKEN = "hassette-smoke-test-token"
STARTUP_TIMEOUT = 60  # seconds


class _SmokeConfig(HassetteConfig):
    """HassetteConfig subclass that disables CLI arg parsing for smoke tests."""

    model_config = HassetteConfig.model_config.copy() | SettingsConfigDict(
        cli_parse_args=False,
        env_file=None,
        toml_file=None,
    )

    def model_post_init(self, *args):
        # Skip default overrides applied in production config.
        pass


@pytest.fixture(scope="session")
def ha_container() -> str:
    """Start the HA Docker container for the test session and tear it down after.

    Yields the base URL for the running Home Assistant instance.
    """
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "homeassistant"],
        check=True,
    )
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            try:
                r = httpx.get(
                    f"{HA_URL}/api/",
                    headers={"Authorization": f"Bearer {HA_TOKEN}"},
                    timeout=3,
                )
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            pytest.fail(f"HA did not become ready within {STARTUP_TIMEOUT}s")

        yield HA_URL
    finally:
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down"],
            check=False,
        )


@asynccontextmanager
async def startup_context(config: HassetteConfig, timeout: int = 30) -> AsyncIterator[Hassette]:
    """Run Hassette.run_forever() in a background task until ready, then yield for assertions.

    Args:
        config: The HassetteConfig to use when constructing the Hassette instance.
        timeout: Maximum seconds to wait for Hassette to reach a running state.

    Yields:
        The running Hassette instance.

    Raises:
        TimeoutError: If Hassette does not reach running state within ``timeout`` seconds.
    """
    hassette = Hassette(config)
    task = asyncio.create_task(hassette.run_forever())
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while hassette._session_id is None or hassette._session_id <= 0:
            if asyncio.get_event_loop().time() > deadline:
                task.cancel()
                raise TimeoutError(f"Hassette did not reach running state within {timeout}s")
            await asyncio.sleep(0.1)
        yield hassette
    finally:
        hassette.shutdown_event.set()
        try:
            await task
        except asyncio.CancelledError:
            pass


def make_smoke_config(ha_url: str, tmp_path: Path) -> HassetteConfig:
    """Build a minimal HassetteConfig pointing at the smoke test HA container.

    Args:
        ha_url: Base URL of the running Home Assistant instance.
        tmp_path: Per-test temporary directory used for ``data_dir`` and ``app_dir``.

    Returns:
        A configured HassetteConfig instance.
    """
    app_dir = tmp_path / "apps"
    app_dir.mkdir(exist_ok=True)

    return _SmokeConfig(
        base_url=ha_url,
        token=HA_TOKEN,
        data_dir=tmp_path / "data",
        app_dir=app_dir,
        run_web_api=False,
        autodetect_apps=False,
        startup_timeout_seconds=30,
    )
