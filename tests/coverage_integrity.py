"""Stop test processes from silently losing their coverage data, and fail loudly if any does.

The nox coverage sessions start coverage with a ``.pth`` file plus ``COVERAGE_PROCESS_START``
rather than pytest-cov, because pytest-cov attaches during ``pytest_configure``, after conftest
has already imported hassette at module scope. That permanently hides every module-level
statement and under-reports by tens of percentage points. See ``tests_with_coverage`` in
``noxfile.py``.

That trade has a cost, which this module pays back. ``coverage.process_startup()`` sets
``_auto_save = True``, and that flag is read in exactly one place: ``Coverage._atexit``. So a
``.pth``-started process persists its data only at interpreter shutdown, and xdist does not
promise its workers ever reach one. ``WorkerManager.teardown_nodes()`` calls
``group.terminate(EXIT_TIMEOUT)``, documented as killing subprocesses once the timeout expires,
and execnet has its own ``os._exit(1)`` path. Both skip atexit. Measured on this suite, the
worker that reports session finish last loses everything it collected on essentially every
parallel run, so reported coverage is understated by a module-shaped amount that changes from
run to run.

pytest-cov never has this problem because it never waits for atexit: ``DistWorker.finish()``
calls ``cov.save()`` during the run. This module does the same for the ``.pth`` setup, then
checks that every process which started actually got its data to disk.

Registered in ``tests/conftest.py``'s ``pytest_plugins``, which is how this repo loads plugins
that have to reach the xdist controller and every worker. Run
``python -m tests.coverage_integrity`` before ``coverage combine`` to verify the result; the
noxfile coverage sessions do. Every hook is a no-op when coverage was not started this way, so
ordinary pytest runs are unaffected.

See issue #1558.
"""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import coverage
import pytest

RECEIPT_DIR = Path(".coverage-receipts")
STARTED_SUFFIX = ".started"
SAVED_SUFFIX = ".saved"
PARTIAL_SUFFIX = ".partial"
CONTROLLER_LABEL = "controller"

# Identifies this process's receipts. A bare pid is not enough: system_with_coverage runs two
# pytest invocations against one receipt directory, and if the OS recycled the first
# invocation's pid, the second would overwrite its receipts and erase the evidence of a drop.
RUN_KEY = f"{os.getpid()}-{time.time_ns()}"


def active_coverage() -> coverage.Coverage | None:
    """Return the Coverage instance auto-started by the ``.pth`` file, or None.

    ``process_startup()`` annotates itself with the instance it created, and coverage.py reads
    it back the same way in ``_prevent_sub_process_measurement()``. That attribute is private
    and unversioned, so if this ever returns None during a real coverage run, check whether
    coverage.py renamed it. The symptom is indistinguishable from the plugin not being loaded:
    every hook here quietly no-ops.
    """
    return getattr(coverage.process_startup, "coverage", None)


def write_receipt(path: Path, contents: str) -> None:
    """Write a receipt atomically and fsync it.

    Both halves matter, because the process can be killed at any point. Without the fsync a
    receipt can still be in the page cache, reading back as a process that never started.
    Without the rename, a kill between truncation and write leaves an empty receipt, which
    reads back as a successful save.
    """
    partial = path.with_name(f"{path.name}{PARTIAL_SUFFIX}")
    with partial.open("w") as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
    partial.replace(path)


def read_receipts(receipt_dir: Path, suffix: str) -> dict[str, str]:
    """Map run key to receipt contents for every receipt of the given kind."""
    return {
        path.name.removesuffix(suffix): path.read_text().strip()
        for path in receipt_dir.glob(f"*{suffix}")
        if not path.name.endswith(PARTIAL_SUFFIX)
    }


def find_problems(receipt_dir: Path) -> list[str]:
    """Return one description per process whose coverage data did not reach disk."""
    started = read_receipts(receipt_dir, STARTED_SUFFIX)
    saved = read_receipts(receipt_dir, SAVED_SUFFIX)

    if not started:
        return [
            f"no receipts found in {receipt_dir}/, so no process recorded its coverage data. "
            "The pytest run probably did not load the tests.coverage_integrity plugin."
        ]

    problems: list[str] = []
    for run_key, label in sorted(started.items()):
        recorded = saved.get(run_key)
        if recorded is None:
            problems.append(f"{label} started but never saved its coverage data; it was killed mid-run")
        elif not recorded or not Path(recorded).is_absolute():
            problems.append(f"{label} left an unusable save receipt ({recorded!r}); its data cannot be confirmed")
        elif not Path(recorded).exists():
            problems.append(f"{label} saved coverage data to {recorded}, but that file is now missing")
    return problems


def pytest_configure(config: pytest.Config) -> None:
    """Record that this process started, so a mid-run kill can be told from a clean run."""
    if active_coverage() is None:
        return

    worker = getattr(config, "workerinput", {}).get("workerid", CONTROLLER_LABEL)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    write_receipt(RECEIPT_DIR / f"{RUN_KEY}{STARTED_SUFFIX}", f"{worker} (pid {os.getpid()})")


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish() -> None:
    """Persist coverage while the process is still alive, rather than leaving it to atexit.

    Runs ``trylast`` so other plugins' session-finish work is measured too. Coverage stays
    started afterwards, so a process that does reach interpreter shutdown saves again through
    atexit and picks up anything executed after this point. That second save reuses the same
    data file rather than creating a duplicate.
    """
    cov = active_coverage()
    if cov is None:
        return

    cov.save()
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    write_receipt(RECEIPT_DIR / f"{RUN_KEY}{SAVED_SUFFIX}", str(cov.get_data().data_filename()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify every test process wrote its coverage data.")
    parser.add_argument("--receipt-dir", type=Path, default=RECEIPT_DIR, help="where receipts were recorded")
    parser.add_argument("--reset", action="store_true", help="delete receipts from a previous run and exit")
    args = parser.parse_args(argv)

    if args.reset:
        shutil.rmtree(args.receipt_dir, ignore_errors=True)
        return 0

    problems = find_problems(args.receipt_dir)
    if not problems:
        return 0

    print("COVERAGE DATA INCOMPLETE: test processes lost data. This is not a coverage regression.", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(
        "\nCombining now would report a coverage number lower than the code actually has. "
        "Failing instead of publishing it. See issue #1558.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
