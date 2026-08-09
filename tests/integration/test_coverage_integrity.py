"""Verify tests/coverage_integrity.py — the plugin that stops a killed pytest process
from silently discarding its coverage data.

The real trigger is xdist killing a worker between ``pytest_sessionfinish`` and
interpreter shutdown, which is a race and cannot be asserted on directly. It is
reproduced deterministically here instead: a throwaway conftest calls ``os._exit()``
from ``pytest_unconfigure``, which lands in exactly that window — after session finish,
before atexit. Both the real kill and this one bypass atexit, which is the only thing
that matters to the mechanism. See issue #1558.

The subprocess mirrors the nox coverage sessions' setup (``COVERAGE_PROCESS_START`` plus
tracing started at interpreter startup) using ``sitecustomize.py`` in place of the
``.pth`` file, since a test must not write into site-packages. Both hooks run at the same
point in startup and call the same ``coverage.process_startup()``.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBPROCESS_TIMEOUT_SECONDS = 120

COVERAGERC = """\
[run]
parallel = True
relative_files = True
source = .
"""

# Starts tracing at interpreter startup, standing in for the .pth file the nox sessions
# install. Python imports sitecustomize automatically during site initialization.
SITECUSTOMIZE = """\
import coverage

coverage.process_startup()
"""

# os._exit() skips atexit entirely, the same way execnet's os._exit(1) and a SIGKILL from
# Group.terminate() do. pytest_unconfigure runs after pytest_sessionfinish, so a plugin
# that saves at session finish has already had its chance; one that relies on atexit has not.
#
# The flushes matter: os._exit() also discards unflushed stdio, and captured stdout is
# block-buffered, so without them the caller cannot tell a completed session from a
# session that died during startup. Only the atexit bypass is load-bearing here.
KILLING_CONFTEST = """\
import os
import sys


def pytest_unconfigure(config):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
"""

SAMPLE_MODULE = """\
def add(a, b):
    return a + b
"""

SAMPLE_TEST = """\
from sample_module import add


def test_add():
    assert add(1, 2) == 3
"""


@dataclass(frozen=True)
class SubprocessRun:
    returncode: int
    stdout: str
    stderr: str
    part_files: list[Path]


@pytest.fixture
def coverage_workspace(tmp_path: Path) -> Path:
    """A self-contained directory that runs one tiny pytest session under coverage
    and then kills itself before interpreter shutdown.
    """
    (tmp_path / ".coveragerc").write_text(COVERAGERC)
    (tmp_path / "sitecustomize.py").write_text(SITECUSTOMIZE)
    (tmp_path / "conftest.py").write_text(KILLING_CONFTEST)
    (tmp_path / "sample_module.py").write_text(SAMPLE_MODULE)
    (tmp_path / "test_sample.py").write_text(SAMPLE_TEST)
    return tmp_path


def run_killed_session(workspace: Path, *, load_plugin: bool) -> SubprocessRun:
    """Run the workspace's pytest session, optionally with the integrity plugin loaded."""
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if load_plugin:
        args += ["-p", "tests.coverage_integrity"]
    args.append("test_sample.py")

    env = {
        **os.environ,
        "COVERAGE_PROCESS_START": ".coveragerc",
        # Repo root so `-p tests.coverage_integrity` resolves; workspace so sitecustomize
        # and the sample module do. PYTHONPATH precedes site-packages, so the workspace
        # sitecustomize wins over any the venv ships.
        "PYTHONPATH": os.pathsep.join([str(PROJECT_ROOT), str(workspace)]),
    }
    env.pop("COVERAGE_FILE", None)

    proc = subprocess.run(
        args,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        check=False,
    )

    # Without this the tests pass for the wrong reason. If pytest bails early — a bad
    # `-p`, a collection error — it never reaches pytest_unconfigure, so the process is
    # never killed, atexit runs, and a part file appears. That looks identical to the
    # plugin working. Requiring the session to have actually completed rules it out.
    assert "1 passed" in proc.stdout, (
        "the pytest session did not run to completion, so the kill never happened and "
        f"this run proves nothing.\nargs: {args}\nreturncode: {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

    return SubprocessRun(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        part_files=sorted(workspace.glob(".coverage.*")),
    )


@pytest.mark.integration
def test_killed_process_loses_coverage_data_without_the_plugin(coverage_workspace: Path):
    """The bug itself: coverage.process_startup() saves only from its atexit hook, so a
    process killed before interpreter shutdown writes no data file at all.

    This asserts the loss still happens, which is what makes the plugin necessary. If it
    ever starts failing, coverage.py changed its save contract and the plugin may be
    redundant.
    """
    result = run_killed_session(coverage_workspace, load_plugin=False)

    assert result.part_files == [], (
        "expected the killed process to lose its coverage data, but a part file survived: "
        f"{result.part_files}\nstdout:\n{result.stdout}"
    )


@pytest.mark.integration
def test_plugin_saves_coverage_data_before_the_process_is_killed(coverage_workspace: Path):
    """The fix: saving at session finish means the data is already on disk when the kill lands."""
    result = run_killed_session(coverage_workspace, load_plugin=True)

    assert len(result.part_files) == 1, (
        "expected exactly one coverage part file to survive the kill, got "
        f"{result.part_files}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.part_files[0].stat().st_size > 0, "coverage part file is empty"
