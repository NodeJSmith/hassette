"""Tests for the Home Assistant add-on image's Dockerfile and glue (docker/addon/)."""

import os
import re
import shlex
from pathlib import Path

import pytest

from hassette.config.config import HassetteConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
ADDON_DOCKERFILE = REPO_ROOT / "docker" / "addon" / "Dockerfile"
ADDON_RUN_SH = REPO_ROOT / "docker" / "addon" / "run.sh"
ADDON_BACKUP_PRE_SH = REPO_ROOT / "docker" / "addon" / "backup_pre.sh"
DOCKER_START_SH = REPO_ROOT / "scripts" / "docker_start.sh"

# run.sh's unconditional hassette settings: literal single-line exports at the start of a line. The value is
# shell-quoted, so shlex.split recovers it as the shell would.
HASSETTE_EXPORT = re.compile(r"^export (HASSETTE__\w+)=(.+)$", re.MULTILINE)
UV_TIMEOUT_CONSTANT = re.compile(r"^(UV_\w+_TIMEOUT_SECS)=(\d+)$", re.MULTILINE)
# Every uv step goes through one of these, with its timeout as the first argument.
UV_STEP_CALL = re.compile(r"^\s*(?:run_uv_install|run_uv_pip_install_guarded) (\S+)", re.MULTILINE)
# Each uv step can wait out its timeout twice: online, then again on the add-on's --offline retry.
ATTEMPTS_PER_UV_STEP = 2
# Room for hassette to start serving once the installs are done.
STARTUP_ALLOWANCE_SECS = 60
BANNER_RULE = "─" * 57
BANNER_TITLE = "HASSETTE CAN'T START: "


def start_period_seconds() -> int:
    match = re.search(r"--start-period=(\d+)([smh])", ADDON_DOCKERFILE.read_text(encoding="utf-8"))
    assert match is not None, "docker/addon/Dockerfile has no HEALTHCHECK --start-period"
    return int(match.group(1)) * {"s": 1, "m": 60, "h": 3600}[match.group(2)]


def test_start_period_outlasts_the_slowest_start() -> None:
    """Supervisor marks the add-on failed if the healthcheck fails after the start period, so the slowest start
    must fit inside it: every uv step timing out online and offline, then hassette's own startup (D14).
    """
    timeouts = [int(seconds) for _, seconds in UV_TIMEOUT_CONSTANT.findall(DOCKER_START_SH.read_text(encoding="utf-8"))]
    assert timeouts, "found no UV_*_TIMEOUT_SECS constants in scripts/docker_start.sh"

    assert start_period_seconds() >= ATTEMPTS_PER_UV_STEP * sum(timeouts) + STARTUP_ALLOWANCE_SECS


def test_every_uv_step_takes_a_named_timeout() -> None:
    """The start-period test sums the UV_*_TIMEOUT_SECS constants, so a uv step timed any other way would
    escape it.
    """
    script = DOCKER_START_SH.read_text(encoding="utf-8")
    constants = {f'"${name}"' for name, _ in UV_TIMEOUT_CONSTANT.findall(script)}
    forwarded = '"${timeout_secs}"'  # a helper passing its caller's timeout through

    timeout_args = UV_STEP_CALL.findall(script)
    assert timeout_args, "found no uv step calls in scripts/docker_start.sh"

    assert set(timeout_args) <= constants | {forwarded}


def test_glue_banner_matches_docker_start_halt() -> None:
    """A start that fails in the glue reads like one that fails in docker_start.sh (D4)."""
    for script in (ADDON_RUN_SH, DOCKER_START_SH):
        text = script.read_text(encoding="utf-8")
        assert BANNER_RULE in text, script
        assert f'echo "  {BANNER_TITLE}' in text, script


def test_pinned_settings_outrank_hassette_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """run.sh's exports are all real settings, and they win over a hassette.toml that sets each one differently
    (D6-D8, D10).
    """
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-token")
    exports = HASSETTE_EXPORT.findall(ADDON_RUN_SH.read_text(encoding="utf-8"))
    assert exports, "found no HASSETTE__ exports in docker/addon/run.sh"
    for name, value in exports:
        monkeypatch.setenv(name, os.path.expandvars(shlex.split(value)[0]))
    monkeypatch.setenv("HASSETTE__CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("HASSETTE__DATA_DIR", str(tmp_path / "data"))

    toml = tmp_path / "hassette.toml"
    toml.write_text(
        "[hassette]\n"
        'base_url = "http://homeassistant.local:8123"\n'
        'token = "toml-token"\n'
        "[hassette.database]\n"
        'path = "/config/other.db"\n'
        'shutdown_snapshot_path = "/config/other-snapshot.db"\n'
        "[hassette.web_api]\n"
        'host = "127.0.0.1"\n'
        "port = 9999\n"
        "run = false\n"
        "run_ui = false\n"
        "auth_enabled = false\n"
        'trusted_proxies = ["10.0.0.1"]\n'
        'token_file = "/config/other_token"\n',
        encoding="utf-8",
    )

    class AddonConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": str(toml),
            "env_file": None,
        }

    config = AddonConfig()
    web_api = config.web_api

    assert config.base_url == "http://supervisor/core"
    assert config.token is not None
    assert config.token.get_secret_value() == "supervisor-token"
    assert config.database.path == Path("/data/hassette.db")
    assert config.database.shutdown_snapshot_path == Path("/data/backup/hassette-snapshot.db")
    assert (web_api.host, web_api.port) == ("0.0.0.0", 8126)
    assert web_api.run
    assert web_api.run_ui
    assert web_api.auth_enabled
    assert list(web_api.trusted_proxies) == ["172.30.32.2"]
    assert web_api.token_file == Path("/config/.web_api_token")


def test_backup_hook_snapshots_the_paths_run_sh_pins() -> None:
    """backup_pre.sh runs with the image's environment, not run.sh's exports, so its literal paths must name the
    database hassette opens and the snapshot run.sh restores (D10).
    """
    pins = dict(HASSETTE_EXPORT.findall(ADDON_RUN_SH.read_text(encoding="utf-8")))
    hook = ADDON_BACKUP_PRE_SH.read_text(encoding="utf-8")

    assert f'DB_PATH="{pins["HASSETTE__DATABASE__PATH"]}"' in hook
    assert f'SNAPSHOT_PATH="{pins["HASSETTE__DATABASE__SHUTDOWN_SNAPSHOT_PATH"]}"' in hook
    assert os.access(ADDON_BACKUP_PRE_SH, os.X_OK), "Supervisor execs backup_pre.sh directly"


def test_snapshot_restore_runs_before_hassette_starts() -> None:
    """A restored snapshot has to be in place before hassette opens (or creates) the database (D10)."""
    script = ADDON_RUN_SH.read_text(encoding="utf-8")

    restore = script.index('"${VENV_PYTHON}" -m hassette.core.database_snapshot_cli restore')

    assert restore < script.index("exec /app/scripts/docker_start.sh")
