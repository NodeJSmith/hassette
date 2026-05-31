import typing
from pathlib import Path

import nox

if typing.TYPE_CHECKING:
    from nox.sessions import Session

nox.options.default_venv_backend = "uv|virtualenv"

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
        "--reruns",
        "2",
        external=True,
    )


@nox.session(python=["3.13", "3.14"])
def e2e(session: "Session"):
    # Build frontend if not already built
    if not _SPA_INDEX.exists():
        session.run("npm", "ci", "--prefix", "frontend", external=True)
        session.run("npm", "run", "build", "--prefix", "frontend", external=True)
    session.run("uv", "run", "--active", "playwright", "install", "--with-deps", "chromium", external=True)
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
        "--reruns",
        "2",
        external=True,
    )
