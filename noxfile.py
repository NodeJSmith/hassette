import json
import shutil
import tomllib
import typing
from pathlib import Path

import nox
from packaging.requirements import Requirement

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

# Oldest Python allowed by requires-python in pyproject.toml, wire/pyproject.toml and client/pyproject.toml;
# SUPPORTED_PYTHONS is the full range the test sessions cover.
FLOOR_PYTHON = "3.11"
SUPPORTED_PYTHONS = [FLOOR_PYTHON, "3.12", "3.13", "3.14"]


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


def run_member_tests(session: "Session", member: str) -> None:
    """Run a workspace member's tests on the locked dependencies, then on its declared floors.

    The floor run pins each of the member's direct dependencies to its ``>=`` floor in an isolated,
    project-less environment, so ``uv.lock`` stays untouched. It can't use ``--resolution
    lowest-direct`` inside the workspace: that resolves the root package's requirements too, so a
    member floor below the root's own floor would never be installed. It pins the oldest Python in
    ``requires-python``, because old pydantic-core releases have no wheels for the newest Pythons.
    """
    member_pytest = ("--directory", member, "pytest", "-q")
    session.run("uv", "run", *member_pytest, external=True)
    session.run(
        "uv",
        "run",
        "--isolated",
        "--no-project",
        "--python",
        FLOOR_PYTHON,
        "--directory",
        member,
        *floor_requirements(member),
        "pytest",
        "-q",
        external=True,
    )


def floor_requirements(member: str) -> list[str]:
    """``uv run --with`` arguments installing ``member`` with every direct dependency at its floor.

    Covers ``[project].dependencies`` and the ``dev`` dependency group, if any; optional extras
    aren't installed. A workspace member is installed from its directory instead, since it isn't on
    PyPI at this version yet. Paths are relative to ``member``'s directory, where the floor run
    executes.

    Raises:
        ValueError: A non-workspace dependency has no single ``>=`` floor to pin, or carries extras
            or an environment marker, which a plain ``name==floor`` pin would silently drop.
    """
    pyproject = read_pyproject(member)
    requirements = [*pyproject["project"]["dependencies"], *pyproject.get("dependency-groups", {}).get("dev", [])]
    member_dirs = workspace_member_dirs()
    # Editable, so the run tests the current source: uv caches a built path dependency until its
    # pyproject.toml changes, and would otherwise reuse a stale wheel.
    args = ["--with-editable", "."]
    for raw in requirements:
        requirement = Requirement(raw)
        if requirement.name in member_dirs:
            args += ["--with-editable", f"../{member_dirs[requirement.name]}"]
            continue
        if requirement.extras:
            raise ValueError(f"{member}: {raw!r} has extras, which a plain floor pin would drop")
        if requirement.marker is not None:
            raise ValueError(f"{member}: {raw!r} has an environment marker, which a plain floor pin would ignore")
        floors = [spec.version for spec in requirement.specifier if spec.operator == ">="]
        if len(floors) != 1:
            raise ValueError(f"{member}: {raw!r} needs exactly one >= floor for the floor run")
        args += ["--with", f"{requirement.name}=={floors[0]}"]
    return args


def workspace_member_dirs() -> dict[str, str]:
    """Map each uv workspace member's distribution name to its directory."""
    members = read_pyproject(".")["tool"]["uv"]["workspace"]["members"]
    return {read_pyproject(directory)["project"]["name"]: directory for directory in members}


def read_pyproject(directory: str) -> dict[str, typing.Any]:
    return tomllib.loads(Path(directory, "pyproject.toml").read_text())


@nox.session(python=False)
def wire(session: "Session"):
    """Run the hassette-wire workspace member's own tests, on locked and floor dependencies."""
    run_member_tests(session, "wire")


@nox.session(python=False)
def client(session: "Session"):
    """Run the hassette-client workspace member's own tests, on locked and floor dependencies."""
    run_member_tests(session, "client")


@nox.session(python=False)
def client_compat(session: "Session"):
    """Parse HEAD's web API responses with the latest released hassette-client.

    Generates fixtures from seeded scenarios with ``tools/generate_client_compat_fixtures.py``, typed by
    the latest ``v*`` tag reachable from HEAD, then checks them with ``tools/check_client_compat.py`` in
    an isolated venv holding that release's ``hassette-client`` (and the ``hassette-wire`` it pins)
    from PyPI instead of the workspace copies. Needs the release tags fetched. Between a release's tag and its
    PyPI publish, the install fails until the publish jobs finish.
    """
    fixtures = Path(session.create_tmp()) / "client-compat-fixtures"
    if fixtures.exists():
        shutil.rmtree(fixtures)
    session.run(
        "uv", "run", "python", "tools/generate_client_compat_fixtures.py", "--output", str(fixtures), external=True
    )
    release = json.loads((fixtures / "release.json").read_text())["version"]
    session.run(
        "uv",
        "run",
        "--isolated",
        "--no-project",
        "--with",
        f"hassette-client=={release}",
        "python",
        "tools/check_client_compat.py",
        str(fixtures),
        external=True,
    )


@nox.session(python=FLOOR_PYTHON)
def wheel_smoke(session: "Session"):
    """Build the wheels and verify the hassette.testing / hassette.test_utils boundary.

    Installs the built wheels into this session's isolated venv (no editable install, no
    ``tests/`` on the path) and checks both directions of the boundary: Tier 1 symbols
    are importable from ``hassette.testing``, and ``hassette.test_utils`` — deleted from
    the source tree — is not importable at all.

    All three workspace wheels are built and installed together: the hassette wheel pins
    ``hassette-wire`` and ``hassette-client`` to its own version, which are not on PyPI until
    the release train publishes them.
    """
    dist_dir = Path("dist")
    if dist_dir.exists():
        for stale in dist_dir.glob("*.whl"):
            stale.unlink()
    session.run("uv", "build", "--all-packages", "--wheel", external=True)
    # Wheel filenames normalize "-" to "_", so this glob matches only the hassette wheel and
    # skips hassette_wire-*/hassette_client-*; everything else in dist/ is a member wheel.
    wheel = next(dist_dir.glob("hassette-*.whl"))
    member_wheels = [str(w) for w in dist_dir.glob("*.whl") if w != wheel]
    # ``[test]`` is the documented optional-dependency extra for app authors using
    # hassette.testing — hassette.testing.fixtures imports pytest at module level.
    session.install(f"{wheel}[test]", *member_wheels)
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


@nox.session(python=SUPPORTED_PYTHONS)
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


@nox.session(python=SUPPORTED_PYTHONS)
def e2e(session: "Session"):
    # Build frontend if not already built
    if not _SPA_INDEX.exists():
        session.run("npm", "ci", "--prefix", "frontend", external=True)
        session.run("npm", "run", "build", "--prefix", "frontend", external=True)
    # Install just the browser binary: idempotent, no root, and a no-op when it's already in
    # ``~/.cache/ms-playwright``. System libraries need root, so they're installed separately —
    # by the e2e workflow in CI (which also caches the browser), and locally as a one-time
    # manual ``playwright install-deps``.
    session.run("uv", "run", "--active", "playwright", "install", "chromium", external=True)
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


@nox.session(python=SUPPORTED_PYTHONS)
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


@nox.session(python=SUPPORTED_PYTHONS)
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


@nox.session(python=SUPPORTED_PYTHONS, tags=["coverage"])
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
