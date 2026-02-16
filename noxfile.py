import typing

import nox

if typing.TYPE_CHECKING:
    from nox.sessions import Session

nox.options.default_venv_backend = "uv|virtualenv"


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
        "not e2e",
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
        "not e2e",
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
