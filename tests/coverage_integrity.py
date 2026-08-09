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

Loaded with ``-p tests.coverage_integrity`` so it reaches both the xdist controller and every
worker. Run as ``python -m tests.coverage_integrity`` before ``coverage combine`` to verify the
result. Both are wired up in the noxfile coverage sessions. Every hook is a no-op when coverage
was not started this way, so ordinary pytest runs are unaffected.

See issue #1558.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

import coverage
import pytest

RECEIPT_DIR = Path(".coverage-receipts")
STARTED_SUFFIX = ".started"
SAVED_SUFFIX = ".saved"
CONTROLLER_LABEL = "controller"


def active_coverage() -> coverage.Coverage | None:
    """Return the Coverage instance auto-started by the ``.pth`` file, or None.

    ``process_startup()`` annotates itself with the instance it created. coverage.py reaches
    for it the same way in ``_prevent_sub_process_measurement()``.
    """
    return getattr(coverage.process_startup, "coverage", None)


def write_receipt(path: Path, contents: str) -> None:
    """Write a receipt and fsync it.

    Without the fsync a receipt can still be sitting in the page cache when the process is
    killed, which would read back as a process that never started.
    """
    with path.open("w") as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())


def read_receipts(receipt_dir: Path, suffix: str) -> dict[int, str]:
    """Map pid to receipt contents for every receipt of the given kind."""
    receipts: dict[int, str] = {}
    for path in receipt_dir.glob(f"*{suffix}"):
        try:
            pid = int(path.name.removesuffix(suffix))
        except ValueError:
            continue
        receipts[pid] = path.read_text().strip()
    return receipts


def find_problems(receipt_dir: Path) -> list[str]:
    """Return one description per process whose coverage data did not reach disk."""
    started = read_receipts(receipt_dir, STARTED_SUFFIX)
    saved = read_receipts(receipt_dir, SAVED_SUFFIX)

    if not started:
        return [
            f"no receipts found in {receipt_dir}/, so no process recorded its coverage data. "
            "The pytest run probably did not load the plugin (-p tests.coverage_integrity)."
        ]

    problems: list[str] = []
    for pid, label in sorted(started.items()):
        if pid not in saved:
            problems.append(f"{label} (pid {pid}) started but never saved its coverage data; it was killed mid-run")
            continue
        part_file = Path(saved[pid])
        if not part_file.exists():
            problems.append(f"{label} (pid {pid}) saved coverage data to {part_file}, but that file is now missing")
    return problems


def pytest_configure(config: pytest.Config) -> None:
    """Record that this process started, so a mid-run kill can be told from a clean run."""
    if active_coverage() is None:
        return

    label = getattr(config, "workerinput", {}).get("workerid", CONTROLLER_LABEL)
    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    write_receipt(RECEIPT_DIR / f"{os.getpid()}{STARTED_SUFFIX}", label)


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
    write_receipt(RECEIPT_DIR / f"{os.getpid()}{SAVED_SUFFIX}", str(cov.get_data().data_filename()))


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
