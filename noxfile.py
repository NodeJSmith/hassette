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
        "not docker and not e2e and not smoke",
        "-n",
        "auto",
        "--dist",
        "loadscope",
        "--tb=short",
        external=True,
    )


@nox.session(python=["3.11", "3.12", "3.13"])
def tests(session: "Session"):
    session.run(
        "uv",
        "run",
        "--active",
        "--reinstall-package",
        "hassette",
        "pytest",
        "-m",
        "not docker and not e2e and not smoke",
        "-n",
        "auto",
        "--dist",
        "loadscope",
        "-W",
        "error",
        "--tb=line",
        external=True,
    )


@nox.session(python=["3.13"])
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
        "-W",
        "error",
        "--tb=line",
        external=True,
    )


@nox.session(python=["3.13"])
def smoke(session: "Session"):
    """Startup smoke tests against a real HA Docker container.

    The ``ha_container`` pytest fixture manages Docker automatically —
    it starts the container before the session and tears it down after.
    """
    session.run(
        "uv",
        "run",
        "--active",
        "--reinstall-package",
        "hassette",
        "pytest",
        "-m",
        "smoke",
        "-v",
        "-x",
        "-n",
        "0",
        "--tb=short",
        external=True,
    )


@nox.session(python=["3.11", "3.12", "3.13"], tags=["coverage"])
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
        "not docker and not e2e and not smoke",
        "-n",
        "auto",
        "--dist",
        "loadscope",
        "-W",
        "error",
        "--cov=hassette",
        "--cov-branch",
        "--cov-report=term-missing:skip-covered",
        "--cov-report=xml",
        "--cov-report=html",
        "--tb=line",
        external=True,
    )
