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

from tests.coverage_integrity import RECEIPT_DIR, SAVED_SUFFIX, STARTED_SUFFIX, find_problems, main

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

# Kills the process after pytest_configure (so a .started receipt exists) but before
# pytest_sessionfinish (so no .saved receipt follows). That is the real "worker died
# mid-run" shape, which the plugin cannot save its way out of and the checker must catch.
EARLY_KILL_CONFTEST = """\
import os
import sys


def pytest_collection(session):
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
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


def run_killed_session(workspace: Path, *, load_plugin: bool, expect_completion: bool = True) -> SubprocessRun:
    """Run the workspace's pytest session, optionally with the integrity plugin loaded.

    Set ``expect_completion=False`` for workspaces whose conftest kills the process before the
    session can finish.
    """
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
    if expect_completion:
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


@pytest.mark.integration
def test_checker_catches_a_process_killed_before_it_could_save(coverage_workspace: Path, capsys):
    """The guard, induced end to end rather than asserted on hand-built receipts.

    Saving at session finish cannot help a process that dies before session finish, so the
    checker has to notice. This is issue #1558's acceptance criterion that the guard be
    watched catching the thing it exists to catch.
    """
    (coverage_workspace / "conftest.py").write_text(EARLY_KILL_CONFTEST)

    result = run_killed_session(coverage_workspace, load_plugin=True, expect_completion=False)
    assert result.part_files == [], "the process was supposed to die before saving anything"

    exit_code = main(["--receipt-dir", str(coverage_workspace / RECEIPT_DIR)])

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "COVERAGE DATA INCOMPLETE" in stderr
    assert "not a coverage regression" in stderr, "the message must not be mistaken for a threshold failure"
    assert "killed mid-run" in stderr


def write_started(receipt_dir: Path, pid: int, label: str) -> None:
    (receipt_dir / f"{pid}{STARTED_SUFFIX}").write_text(label)


def write_saved(receipt_dir: Path, pid: int, part_file: Path) -> None:
    (receipt_dir / f"{pid}{SAVED_SUFFIX}").write_text(str(part_file))


@pytest.fixture
def receipt_dir(tmp_path: Path) -> Path:
    path = tmp_path / RECEIPT_DIR
    path.mkdir()
    return path


def test_find_problems_accepts_a_run_where_every_process_saved(receipt_dir: Path, tmp_path: Path):
    for pid, label in ((1, "controller"), (2, "gw0")):
        part_file = tmp_path / f"part-{pid}"
        part_file.write_text("data")
        write_started(receipt_dir, pid, label)
        write_saved(receipt_dir, pid, part_file)

    assert find_problems(receipt_dir) == []


def test_find_problems_reports_a_process_that_never_saved(receipt_dir: Path, tmp_path: Path):
    part_file = tmp_path / "part-1"
    part_file.write_text("data")
    write_started(receipt_dir, 1, "controller")
    write_saved(receipt_dir, 1, part_file)
    write_started(receipt_dir, 2, "gw0")

    problems = find_problems(receipt_dir)

    assert len(problems) == 1
    assert "gw0 (pid 2)" in problems[0]
    assert "killed mid-run" in problems[0]


def test_find_problems_reports_a_part_file_that_vanished(receipt_dir: Path, tmp_path: Path):
    write_started(receipt_dir, 7, "gw3")
    write_saved(receipt_dir, 7, tmp_path / "never-created")

    problems = find_problems(receipt_dir)

    assert len(problems) == 1
    assert "gw3 (pid 7)" in problems[0]
    assert "now missing" in problems[0]


def test_find_problems_reports_an_unmeasured_run_rather_than_passing_it(tmp_path: Path):
    """An empty receipt directory means the plugin never loaded, which must not read as success."""
    problems = find_problems(tmp_path / "absent")

    assert len(problems) == 1
    assert "tests.coverage_integrity" in problems[0]


def test_main_resets_receipts_from_a_previous_run(receipt_dir: Path):
    write_started(receipt_dir, 1, "controller")

    assert main(["--receipt-dir", str(receipt_dir), "--reset"]) == 0
    assert not receipt_dir.exists()
