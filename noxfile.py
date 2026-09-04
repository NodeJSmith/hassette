import os
import typing
from pathlib import Path

import nox

if typing.TYPE_CHECKING:
    from nox.sessions import Session

nox.options.default_venv_backend = "uv|virtualenv"

# Reuse existing .nox venvs by default (the ``-r`` flag, made the default). This speeds up
# repeated local runs and avoids the "virtual environment already exists" error when a prior
# run left a venv behind. It is a no-op on fresh CI runners (no .nox to reuse), and each
# session's install steps still run, so dependencies stay current. To force a clean rebuild
# after changing dependencies, pass ``--no-reuse-existing-virtualenvs`` or delete ``.nox/``.
nox.options.reuse_existing_virtualenvs = True

_SPA_INDEX = Path("src/hassette/web/static/spa/index.html")

# Explicit xdist worker count for every parallel test session, rather than ``-n auto``.
#
# ``-n auto`` resolves to the CPU count, which is 4 on CI's ubuntu-latest runners but 12+ on a
# developer box. Worker count decides how the suite is partitioned, so that gap makes reproducing
# a CI-only failure locally largely a matter of luck. Pinning the number also stops a many-core
# box from spawning one heavy worker per core.
#
# The trade: ``-n auto`` tracked the runner's core count by itself, and this constant does not.
# It currently equals what CI resolves to, so it changes nothing today — but if GitHub resizes the
# ubuntu-latest runner, nothing here fails loudly; the suite just runs under- or over-subscribed
# until someone updates this line. Re-check against a CI run's ``created: N/N workers`` line.
XDIST_WORKERS = "4"


@nox.session(python=False)
def frontend(session: "Session"):
    """Build the Preact SPA."""
    session.run("npm", "ci", "--prefix", "frontend", external=True)
    session.run("npm", "run", "build", "--prefix", "frontend", external=True)


@nox.session(python=False)
def dev(session: "Session"):
    """Fast local test run — uses the current interpreter, no reinstall."""
    if not _SPA_INDEX.exists():
        session.warn("SPA not built — run `nox -s frontend` first (e2e tests will fail)")
    session.run(
        "uv",
        "run",
        "pytest",
        "-m",
        "not docker and not e2e and not system and not system_destructive",
        "-n",
        XDIST_WORKERS,
        "--dist",
        "loadscope",
        "-v",
        "--tb=short",
        external=True,
    )


@nox.session(python="3.11")
def wheel_smoke(session: "Session"):
    """Build the wheel and verify the hassette.testing / hassette.test_utils boundary.

    Installs the built wheel into this session's isolated venv (no editable install, no
    ``tests/`` on the path) and checks both directions of the boundary: Tier 1 symbols
    are importable from ``hassette.testing``, and ``hassette.test_utils`` — deleted from
    the source tree — is not importable at all.
    """
    dist_dir = Path("dist")
    if dist_dir.exists():
        for stale in dist_dir.glob("hassette-*.whl"):
            stale.unlink()
    session.run("uv", "build", "--wheel", external=True)
    wheel = next(dist_dir.glob("hassette-*.whl"))
    # ``[test]`` is the documented optional-dependency extra for app authors using
    # hassette.testing — hassette.testing.fixtures imports pytest at module level.
    session.install(f"{wheel}[test]")
    session.run("python", "-c", "from hassette.testing import AppTestHarness")
    session.run(
        "python",
        "-c",
        "import importlib\n"
        "try:\n"
        "    importlib.import_module('hassette.test_utils')\n"
        "except ModuleNotFoundError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('hassette.test_utils should not be importable')\n",
    )


@nox.session(python=["3.11", "3.12", "3.13", "3.14"])
def tests(session: "Session"):
    session.run(
        "uv",
        "run",
        "--active",
        "--reinstall-package",
        "hassette",
        "pytest",
        "-m",
        "not docker and not e2e and not system and not system_destructive",
        "-n",
        XDIST_WORKERS,
        "--dist",
        "loadscope",
        "--tb=line",
        # Fail a hung test instead of letting CI hang until the job is cancelled.
        # thread method dumps every thread's stack then os._exit()s — it catches
        # C-level/lock hangs that the signal method can't interrupt.
        "--timeout",
        "60",
        "--timeout-method",
        "thread",
        external=True,
    )


@nox.session(python=["3.11", "3.12", "3.13", "3.14"])
def e2e(session: "Session"):
    # Build frontend if not already built
    if not _SPA_INDEX.exists():
        session.run("npm", "ci", "--prefix", "frontend", external=True)
        session.run("npm", "run", "build", "--prefix", "frontend", external=True)
    # ``--with-deps`` installs system libraries via apt, which needs root. CI runners have
    # passwordless sudo, so keep it there; locally it would prompt for a password with no TTY
    # and fail even when the deps are already present. Locally, install just the browser binary
    # (idempotent, no root) — system deps are a one-time manual ``sudo playwright install-deps``.
    deps_flag = ["--with-deps"] if os.environ.get("CI") else []
    session.run("uv", "run", "--active", "playwright", "install", *deps_flag, "chromium", external=True)
    session.run(
        "uv",
        "run",
        "--active",
        "--reinstall-package",
        "hassette",
        "pytest",
        "-m",
        "e2e",
        "-v",
        "--tracing",
        "retain-on-failure",
        "--output",
        "test-results",
        "--tb=line",
        # Browser tests can stall on a never-resolving wait; fail the test instead
        # of letting the whole job run to its timeout. 120s is well above the
        # slowest real e2e test (single digits of seconds). See `tests` session.
        "--timeout",
        "120",
        "--timeout-method",
        "thread",
        external=True,
    )


@nox.session(python=["3.11", "3.12", "3.13", "3.14"])
def system(session: "Session"):
    """System tests against a real HA Docker container.

    Runs non-destructive system tests first, then destructive tests
    (docker restart, failure injection) in a separate invocation so
    they cannot contaminate the shared event loop.
    """
    _run_system_tests(session, marker="system and not system_destructive")
    _run_system_tests(session, marker="system_destructive")


@nox.session(python=False)
def screenshots(session: "Session"):
    """Capture all documentation screenshots via the YAML manifest."""
    session.run("uv", "run", "python", "scripts/capture_screenshots.py", external=True)


@nox.session(python=["3.11", "3.12", "3.13", "3.14"])
def system_with_coverage(session: "Session"):
    """System tests with coverage collection for Codecov."""
    session.env["COVERAGE_FILE"] = f".coverage.system.{session.python}"
    _install_coverage_pth(session)
    session.env["COVERAGE_PROCESS_START"] = "pyproject.toml"
    _reset_coverage_receipts(session)
    _run_system_tests(session, marker="system and not system_destructive")
    _run_system_tests(session, marker="system_destructive")
    _check_coverage_complete(session)
    session.run("uv", "run", "--active", "coverage", "combine", external=True)
    session.run(
        "uv", "run", "--active", "coverage", "xml", "--fail-under=0", "-o", "coverage.system.xml", external=True
    )


def _reset_coverage_receipts(session: "Session") -> None:
    """Drop receipts and coverage data left by an earlier run.

    Without this, a run that stopped before ``coverage combine`` leaves its ``COVERAGE_FILE``
    data files on disk, and the next run's ``combine`` picks up both, silently blending a stale
    run's data into the new report. ``coverage erase`` reads ``parallel = true`` from
    ``pyproject.toml`` and removes those suffixed files along with the base file, not just the
    receipts that back the integrity check.
    """
    session.run("uv", "run", "--active", "python", "-m", "tests.coverage_integrity", "--reset", external=True)
    session.run("uv", "run", "--active", "coverage", "erase", external=True)


def _check_coverage_complete(session: "Session") -> None:
    """Fail before combining if any test process lost its coverage data.

    Coverage started by _install_coverage_pth() persists only at interpreter shutdown, and
    xdist kills workers that have not got there yet, so a silently truncated run reports a
    plausible but wrong number. The plugin doing the saving is registered in
    tests/conftest.py. See tests/coverage_integrity.py and issue #1558.
    """
    session.run("uv", "run", "--active", "python", "-m", "tests.coverage_integrity", external=True)


def _install_coverage_pth(session: "Session") -> None:
    """Install a .pth file that starts coverage tracing at interpreter startup.

    This ensures coverage sees module-level statements that execute during conftest
    import — before pytest-cov would normally attach. Works for both the main process
    and xdist worker subprocesses (each gets its own Python interpreter startup).
    """
    result = session.run(
        "uv",
        "run",
        "--active",
        "python",
        "-c",
        "import site; print(site.getsitepackages()[0])",
        external=True,
        silent=True,
    )
    if not result:
        session.error("failed to detect site-packages path")
    site_dir = result.strip().splitlines()[-1]
    pth_path = Path(site_dir) / "coverage_subprocess.pth"
    pth_path.write_text("import coverage; coverage.process_startup()\n")


def _run_system_tests(session: "Session", *, marker: str, extra_args: list[str] | None = None) -> None:
    session.env["PYTHONTRACEMALLOC"] = "1"
    session.env["PYTHONASYNCIODEBUG"] = "1"
    session.run(
        "uv",
        "run",
        "--active",
        "--reinstall-package",
        "hassette",
        "pytest",
        "-m",
        marker,
        "-v",
        "-x",
        "-n",
        "0",
        "--tb=short",
        # Fail a hung test (e.g. a reconnect that never completes) instead of
        # stalling the job. 120s covers docker restart + reconnect backoff. See
        # `tests` session for why the thread method is used.
        "--timeout",
        "120",
        "--timeout-method",
        "thread",
        # System tests hit real Docker/HA — retry genuine infra flakiness.
        # Unit/integration sessions intentionally have no reruns (see #1322).
        "--reruns",
        "2",
        "--reruns-delay",
        "5",
        *(extra_args or []),
        external=True,
    )


@nox.session(python=["3.11", "3.12", "3.13", "3.14"], tags=["coverage"])
def tests_with_coverage(session: "Session"):
    # Uses COVERAGE_PROCESS_START + a .pth file instead of pytest --cov.
    # pytest-cov starts tracing in pytest_configure — after conftest.py has already
    # imported hassette at module scope, leaving all module-level statements permanently
    # invisible to coverage. The .pth file starts tracing at interpreter startup, before
    # anything else loads, so both the main process and xdist workers see full coverage.
    session.env["COVERAGE_FILE"] = f".coverage.{session.python}"
    _install_coverage_pth(session)
    session.env["COVERAGE_PROCESS_START"] = "pyproject.toml"
    _reset_coverage_receipts(session)
    session.run(
        "uv",
        "run",
        "--active",
        "--reinstall-package",
        "hassette",
        "pytest",
        "-m",
        "not docker and not e2e and not system and not system_destructive",
        "-n",
        XDIST_WORKERS,
        "--dist",
        "loadscope",
        "--tb=line",
        # See `tests` session: thread method dumps stacks then os._exit()s, catching
        # hangs the signal method can't. Safe under coverage — it does not inject
        # async exceptions (no SetAsyncExc), so it cannot trigger the settrace deadlock.
        "--timeout",
        "60",
        "--timeout-method",
        "thread",
        external=True,
    )
    _check_coverage_complete(session)
    session.run("uv", "run", "--active", "coverage", "combine", external=True)
    session.run("uv", "run", "--active", "coverage", "report", "--show-missing", "--skip-covered", external=True)
    session.run("uv", "run", "--active", "coverage", "xml", external=True)
    session.run("uv", "run", "--active", "coverage", "html", external=True)
