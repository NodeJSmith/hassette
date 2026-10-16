"""Shared helpers for the Docker entrypoint integration tests (``tests/test_docker_*.py``)."""

import os
import subprocess
from pathlib import Path

DEFAULT_DOCKER_IMAGE = "hassette:test"
DOCKER_IMAGE = os.getenv("HASSETTE_TEST_IMAGE", DEFAULT_DOCKER_IMAGE)

CONTAINER_TIMEOUT = 60
PROJECT_CONTAINER_TIMEOUT = 120
UV_LOCK_TIMEOUT = 60
DOCKER_CLEANUP_TIMEOUT = 30
# `docker stop` grace period, and how fast a halted container must stop within it
DOCKER_STOP_GRACE_SECS = 30
MAX_HALT_STOP_SECS = 10

BASE_CONTAINER_ENV = {
    "HASSETTE__TOKEN": "test_token",
    "HASSETTE__BASE_URL": "http://test",
}
NO_RETRY = {"HASSETTE_DOCKER_RETRY_DELAY": "0"}
# What the add-on glue sets (design/specs/129-ha-addon-v01 D4)
ADDON = {"HASSETTE_DOCKER_RUNTIME": "addon", "HASSETTE_DOCKER_PRUNE_UV_CACHE": "0", **NO_RETRY}
# With `--network none`, uv fails a fetch at once instead of retrying it for ~25s
UV_FAIL_FAST = {"UV_HTTP_RETRIES": "0"}
ADDON_REMEDY = "restart the add-on from its page"
HALT_BANNER = "HASSETTE CAN'T START"
DEGRADED_BANNER = "HASSETTE IS STARTING WITHOUT SOME DEPENDENCIES"
OFFLINE_RETRY_MESSAGE = "retrying from the uv cache (--offline)"
# A uv stand-in that fails every online run with uv's connection error and passes --offline runs to the real uv,
# so a test can exercise the offline retry without a stale cache (uv trusts a freshly cached index page offline).
# It's mounted over /app/.venv/bin/uv, which the activated venv puts ahead of the image's real uv at /bin/uv. The
# error text must match UV_NETWORK_ERROR_PATTERN in scripts/docker_start.sh.
NETWORK_DOWN_UV_SHIM = """#!/bin/sh
for arg in "$@"; do
    [ "$arg" = "--offline" ] && exec /bin/uv "$@"
done
echo "error: Request failed after 3 retries"
echo "  Caused by: Failed to fetch: \\`https://pypi.org/simple/pydantic/\\`"
echo "  Caused by: error sending request for url (https://pypi.org/simple/pydantic/)"
exit 2
"""


# aiohttp==3.0.0 conflicts with hassette's aiohttp>=3.9 constraint
CONFLICTING_REQUIREMENT = "aiohttp==3.0.0"


def run_hassette_container(
    *,
    volumes: list[str] | None = None,
    env: dict[str, str] | None = None,
    timeout: int = CONTAINER_TIMEOUT,
    name: str | None = None,
    remove: bool = True,
    args: list[str] | None = None,
    network: str | None = None,
    detach: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the hassette Docker image with `args` (default ``--check``), returning (result, combined output).

    Pass ``name`` and ``remove=False`` to keep the stopped container around for inspection
    (e.g. via ``docker diff``) instead of letting ``--rm`` discard it on exit. ``network="none"``
    cuts the container off from the package index. ``detach=True`` returns once the container starts,
    with the container ID as the output; read its log with ``docker_logs(name)``.
    """
    cmd = ["docker", "run"]
    if remove:
        cmd.append("--rm")
    if detach:
        cmd.append("-d")
    if name:
        cmd.extend(["--name", name])
    if network:
        cmd.extend(["--network", network])
    for vol in volumes or []:
        cmd.extend(["-v", vol])
    merged_env = {**BASE_CONTAINER_ENV, **(env or {})}
    for key, value in merged_env.items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.extend([DOCKER_IMAGE, *(args if args is not None else ["--check"])])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result, result.stderr + result.stdout


def write_requirements(tmp_path: Path, requirement: str) -> Path:
    """Create ``tmp_path/apps`` holding a one-line requirements.txt, and return the apps dir."""
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    (apps_dir / "requirements.txt").write_text(f"{requirement}\n")
    return apps_dir
