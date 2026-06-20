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
        "auto",
        "--dist",
        "loadscope",
        "-v",
        "--tb=short",
        "--reruns",
        "2",
        external=True,
    )


@nox.session(python=["3.11", "3.13", "3.14"])
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
        "auto",
        "--dist",
        "loadscope",
        "-v",
        "--tb=line",
        # Fail a hung test instead of letting CI hang until the job is cancelled.
        # thread method dumps every thread's stack then os._exit()s — it catches
        # C-level/lock hangs that the signal method can't interrupt.
        "--timeout",
        "60",
        "--timeout-method",
        "thread",
        "--reruns",
        "2",
        external=True,
    )


@nox.session(python=["3.11", "3.13", "3.14"])
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


@nox.session(python=["3.13", "3.14"])
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


@nox.session(python=["3.13", "3.14"])
def system_with_coverage(session: "Session"):
    """System tests with coverage collection for Codecov."""
    session.env["COVERAGE_FILE"] = f".coverage.system.{session.python}"
    _run_system_tests(
        session,
        marker="system and not system_destructive",
        extra_args=["--cov=hassette", "--cov-branch", "--cov-report=xml:coverage.system.xml"],
    )
    _run_system_tests(
        session,
        marker="system_destructive",
        extra_args=["--cov=hassette", "--cov-branch", "--cov-append", "--cov-report=xml:coverage.system.xml"],
    )


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
        "--reruns",
        "2",
        "--reruns-delay",
        "5",
        *(extra_args or []),
        external=True,
    )


@nox.session(python=["3.11", "3.13", "3.14"], tags=["coverage"])
def tests_with_coverage(session: "Session"):
    session.env["COVERAGE_FILE"] = f".coverage.{session.python}"
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
        "auto",
        "--dist",
        "loadscope",
        "--cov=hassette",
        "--cov-branch",
        "--cov-report=term-missing:skip-covered",
        "--cov-report=xml",
        "--cov-report=html",
        "--tb=line",
        # See `tests` session: thread method dumps stacks then os._exit()s, catching
        # hangs the signal method can't. Safe under coverage — it does not inject
        # async exceptions (no SetAsyncExc), so it cannot trigger the settrace deadlock.
        "--timeout",
        "60",
        "--timeout-method",
        "thread",
        "--reruns",
        "2",
        external=True,
    )
