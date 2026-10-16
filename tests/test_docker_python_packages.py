"""Integration tests for the add-on's python_packages install step in the Docker entrypoint.

The add-on glue passes the option as ``HASSETTE_DOCKER_PYTHON_PACKAGES``, one requirement per line
(design/specs/129-ha-addon-v01, D9). The container's args default to ``--check``, so the final ``hassette run``
exits after the installs instead of starting the server.
"""

import shutil
from pathlib import Path

import pytest

from tests.support.docker import (
    ADDON,
    CONFLICTING_REQUIREMENT,
    DEGRADED_BANNER,
    HALT_BANNER,
    NETWORK_DOWN_UV_SHIM,
    NO_RETRY,
    OFFLINE_RETRY_MESSAGE,
    UV_FAIL_FAST,
    run_hassette_container,
    write_requirements,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker,
    pytest.mark.skipif(shutil.which("docker") is None, reason="Docker not installed"),
]

STEP_STARTED = "python_packages install: starting"


def packages_env(*requirements: str) -> dict[str, str]:
    """The add-on runtime with ``requirements`` as its python_packages option."""
    return {**ADDON, "HASSETTE_DOCKER_PYTHON_PACKAGES": "\n".join(requirements)}


def test_addon_installs_each_python_package():
    # neither is in the image's venv, so uv lists both as installed
    result, output = run_hassette_container(env=packages_env("tabulate", "requests-toolbelt"))

    assert result.returncode == 0, output
    assert f"{STEP_STARTED} (2 package(s))" in output
    assert "+ tabulate" in output
    assert "+ requests-toolbelt" in output


def test_python_packages_install_after_the_project_and_requirements_steps(tmp_path: Path):
    """The project and requirements.txt installs run first, so neither can remove or downgrade what the option
    installs.
    """
    apps_dir = write_requirements(tmp_path, "six")

    result, output = run_hassette_container(
        volumes=[f"{apps_dir}:/config/apps:ro"],
        env={"HASSETTE_DOCKER_INSTALL_DEPS": "1", **packages_env("tabulate")},
    )

    assert result.returncode == 0, output
    assert output.index("project install: skipped") < output.index(STEP_STARTED)
    assert output.index("requirements install: complete") < output.index(STEP_STARTED)


def test_an_entry_that_looks_like_an_option_is_a_requirement_not_a_uv_flag():
    """Entries follow `--`, so `--help` is a bad requirement that halts, not uv's help text."""
    result, output = run_hassette_container(env=packages_env("six", "--help"))

    assert result.returncode == 1, output
    assert HALT_BANNER in output
    assert "Expected package name starting with an alphanumeric character" in output
    assert "Usage: uv pip install" not in output


@pytest.mark.parametrize("packages", ["", "\n\n"], ids=["empty", "blank-lines"])
def test_an_empty_option_skips_the_step(packages: str):
    result, output = run_hassette_container(env={**ADDON, "HASSETTE_DOCKER_PYTHON_PACKAGES": packages})

    assert result.returncode == 0, output
    assert "python_packages install: skipped (the option is empty)" in output
    assert STEP_STARTED not in output


def test_outside_the_addon_the_option_is_ignored_with_a_warning():
    result, output = run_hassette_container(env={**NO_RETRY, "HASSETTE_DOCKER_PYTHON_PACKAGES": "tabulate"})

    assert result.returncode == 0, output
    assert "HASSETTE_DOCKER_PYTHON_PACKAGES is ignored outside the Home Assistant add-on" in output
    assert STEP_STARTED not in output
    assert "+ tabulate" not in output


def test_a_conflicting_package_halts_with_the_option_named_in_the_remedy():
    # CONFLICTING_REQUIREMENT pins below hassette's own aiohttp requirement
    result, output = run_hassette_container(env=packages_env(CONFLICTING_REQUIREMENT))

    assert result.returncode == 1, output
    assert "A package in the add-on's python_packages option" in output  # one line of the banner
    assert "in the add-on's Configuration tab), then restart the add-on from its page" in output
    assert OFFLINE_RETRY_MESSAGE not in output


def test_with_no_network_the_addon_starts_degraded_naming_the_option():
    result, output = run_hassette_container(env={**packages_env("tabulate"), **UV_FAIL_FAST}, network="none")

    assert result.returncode == 0, output
    assert OFFLINE_RETRY_MESSAGE in output
    assert DEGRADED_BANNER in output
    assert "    - the python_packages option" in output
    assert "python_packages install: skipped (the offline install failed)" in output


def test_with_the_index_unreachable_a_cached_package_installs_offline(tmp_path: Path):
    """The offline retry keeps --offline ahead of the `--` that ends the uv args, so it can succeed."""
    shim = tmp_path / "uv"
    shim.write_text(NETWORK_DOWN_UV_SHIM)
    shim.chmod(0o755)

    # pydantic is in the image's venv, so the offline retry passes with an empty cache
    result, output = run_hassette_container(volumes=[f"{shim}:/app/.venv/bin/uv:ro"], env=packages_env("pydantic"))

    assert result.returncode == 0, output
    assert OFFLINE_RETRY_MESSAGE in output
    assert "Installed from the uv cache." in output
    assert DEGRADED_BANNER not in output
