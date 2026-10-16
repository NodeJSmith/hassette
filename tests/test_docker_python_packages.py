"""Integration tests for the add-on's python_packages install step in the Docker entrypoint.

The add-on glue passes the option as ``HASSETTE_DOCKER_PYTHON_PACKAGES``, one requirement per line
(design/specs/129-ha-addon-v01, D9). The container's args default to ``--check``, so the final ``hassette run``
exits after the installs instead of starting the server. What a run installed is read from ``docker diff``.
"""

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.support.docker import (
    ADDON,
    CONFLICTING_REQUIREMENT,
    DEGRADED_BANNER,
    DOCKER_CLEANUP_TIMEOUT,
    HALT_BANNER,
    NETWORK_DOWN_UV_SHIM,
    NO_RETRY,
    OFFLINE_RETRY_MESSAGE,
    PROJECT_CONTAINER_TIMEOUT,
    UV_FAIL_FAST,
    create_project_package,
    installed_distribution_versions,
    installed_distributions,
    project_pyproject,
    run_container_and_diff,
    run_hassette_container,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed"),
]

# Neither is in the image's venv, so a run that installs them adds their .dist-info directories.
ABSENT_PACKAGES = ("tabulate", "requests-toolbelt")
# The image's uv cache directory (UV_CACHE_DIR in the Dockerfile). A new named volume mounted there takes the
# directory's ownership, so the container's non-root user can write to it.
IMAGE_UV_CACHE_DIR = "/uv_cache"


def packages_env(*requirements: str) -> dict[str, str]:
    """The add-on runtime with ``requirements`` as its python_packages option."""
    return {**ADDON, "HASSETTE_DOCKER_PYTHON_PACKAGES": "\n".join(requirements)}


def test_addon_installs_each_python_package():
    result, output, diff_lines = run_container_and_diff(env=packages_env(*ABSENT_PACKAGES))

    assert result.returncode == 0, output
    assert {"tabulate", "requests_toolbelt"} <= installed_distributions(diff_lines)


def test_python_packages_win_over_the_project_and_requirements_installs(docker_project_dir: Path):
    """The option installs last: the project and requirements.txt pin older versions, and the option's newer
    versions are the ones left installed.
    """
    create_project_package(docker_project_dir, project_pyproject(["tabulate==0.8.10"]))
    (docker_project_dir / "apps").mkdir()
    (docker_project_dir / "apps" / "requirements.txt").write_text("requests-toolbelt==0.10.1\n")

    result, output, diff_lines = run_container_and_diff(
        volumes=[f"{docker_project_dir}:/config"],
        env={"HASSETTE_DOCKER_INSTALL_DEPS": "1", **packages_env("tabulate==0.9.0", "requests-toolbelt==1.0.0")},
        timeout=PROJECT_CONTAINER_TIMEOUT,
    )

    assert result.returncode == 0, output
    versions = installed_distribution_versions(diff_lines)
    assert versions["tabulate"] == "0.9.0"
    assert versions["requests_toolbelt"] == "1.0.0"


def test_an_entry_that_looks_like_an_option_is_a_requirement_not_a_uv_flag():
    """Entries follow `--`. Read as a flag, `--help` would print uv's help and pass; as a requirement it halts."""
    result, output = run_hassette_container(env=packages_env("six", "--help"))

    assert result.returncode == 1, output
    assert HALT_BANNER in output


@pytest.mark.parametrize("packages", ["", "\n\n"], ids=["empty", "blank-lines"])
def test_an_empty_option_installs_nothing(packages: str):
    result, output, diff_lines = run_container_and_diff(env={**ADDON, "HASSETTE_DOCKER_PYTHON_PACKAGES": packages})

    assert result.returncode == 0, output
    assert installed_distributions(diff_lines) == set()


def test_outside_the_addon_the_option_is_ignored_with_a_warning():
    result, output, diff_lines = run_container_and_diff(env={**NO_RETRY, "HASSETTE_DOCKER_PYTHON_PACKAGES": "tabulate"})

    assert result.returncode == 0, output
    assert "HASSETTE_DOCKER_PYTHON_PACKAGES is ignored outside the Home Assistant add-on" in output
    assert "tabulate" not in installed_distributions(diff_lines)


def test_a_conflicting_package_halts_with_the_option_named_in_the_remedy():
    # CONFLICTING_REQUIREMENT pins below hassette's own aiohttp requirement
    result, output = run_hassette_container(env=packages_env(CONFLICTING_REQUIREMENT))

    assert result.returncode == 1, output
    assert "A package in the add-on's python_packages option" in output  # one line of the banner
    assert "in the add-on's Configuration tab), then restart the add-on from its page" in output
    assert OFFLINE_RETRY_MESSAGE not in output


def test_with_no_network_and_an_empty_cache_the_addon_starts_degraded_naming_the_option():
    result, output = run_hassette_container(env={**packages_env("tabulate"), **UV_FAIL_FAST}, network="none")

    assert result.returncode == 0, output
    assert DEGRADED_BANNER in output
    assert "    - the python_packages option" in output


def test_with_the_index_unreachable_a_cached_package_installs_offline(tmp_path: Path):
    """A package an earlier start cached installs from the cache when the index is unreachable."""
    shim = tmp_path / "uv"
    shim.write_text(NETWORK_DOWN_UV_SHIM)
    shim.chmod(0o755)
    cache_volume = f"hassette-uv-cache-test-{uuid.uuid4().hex[:12]}"
    cache_mount = f"{cache_volume}:{IMAGE_UV_CACHE_DIR}"
    try:
        seed, seed_output = run_hassette_container(volumes=[cache_mount], env=packages_env("tabulate"))
        assert seed.returncode == 0, seed_output

        result, output, diff_lines = run_container_and_diff(
            volumes=[cache_mount, f"{shim}:/app/.venv/bin/uv:ro"], env=packages_env("tabulate")
        )
    finally:
        subprocess.run(
            ["docker", "volume", "rm", "-f", cache_volume], capture_output=True, timeout=DOCKER_CLEANUP_TIMEOUT
        )

    assert result.returncode == 0, output
    assert OFFLINE_RETRY_MESSAGE in output
    assert "tabulate" in installed_distributions(diff_lines)
    assert DEGRADED_BANNER not in output
