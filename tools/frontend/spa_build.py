"""Decide which npm steps bring the built SPA up to date with the frontend sources, and run them.

Shared by the ``e2e`` nox session and e2e's ``ensure_spa_built`` fixture, so local e2e runs against the
current frontend (and the build's absolute-path check in ``frontend/no-absolute-paths.ts`` runs on it)
instead of reusing a build from before the last frontend change. CI always builds fresh. The steps run
under a per-checkout file lock, so concurrent xdist workers and nox sessions build one at a time.

Staleness is by mtime: a checkout that bumps mtimes causes a spurious rebuild (safe); only clock skew
can cause a missed one.
"""

import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path

from filelock import FileLock

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
SPA_INDEX = REPO_ROOT / "src" / "hassette" / "web" / "static" / "spa" / "index.html"

# One lock per checkout, outside the repo: pytest-xdist workers and nox sessions of a checkout all build into
# its node_modules and static/spa directories, and Vite's emptyOutDir would delete files another build is
# writing. Keyed on the SPA output path so separate worktrees don't serialize against each other.
_CHECKOUT_KEY = sha256(str(SPA_INDEX).encode()).hexdigest()[:12]
BUILD_LOCK_PATH = Path(tempfile.gettempdir()) / f"hassette-spa-build-{_CHECKOUT_KEY}.lock"
# A cold `npm ci` plus the Vite build can take several minutes; waiters only need to outlast one build.
BUILD_LOCK_TIMEOUT_SECONDS = 30 * 60

_SOURCE_DIRS = ("src", "public")


def newest_mtime(frontend_dir: Path) -> float:
    """The newest mtime among the frontend's build inputs.

    Every top-level file counts (configs, ``vite.config.ts`` and the modules it imports, the lockfile), so a
    new build input needs no list update; a top-level file the build ignores only costs a spurious rebuild.
    """
    files = [p for p in frontend_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    for directory in _SOURCE_DIRS:
        files.extend(p for p in (frontend_dir / directory).rglob("*") if p.is_file())
    return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)


def spa_build_steps(frontend_dir: Path = FRONTEND_DIR, spa_index: Path = SPA_INDEX) -> list[list[str]]:
    """The npm commands needed to make ``spa_index`` current, in order; empty when it already is.

    ``npm ci`` runs only when ``node_modules`` is missing or older than the lockfile; ``npm run build``
    whenever the built ``index.html`` is missing or older than any build input (the lockfile included).
    """
    steps: list[list[str]] = []
    # npm rewrites this file on every install, so its mtime says when node_modules last matched a lockfile.
    installed = frontend_dir / "node_modules" / ".package-lock.json"
    lockfile = frontend_dir / "package-lock.json"
    if not installed.exists() or lockfile.stat().st_mtime > installed.stat().st_mtime:
        steps.append(["npm", "ci", "--prefix", str(frontend_dir)])
    if not spa_index.exists() or newest_mtime(frontend_dir) > spa_index.stat().st_mtime:
        steps.append(["npm", "run", "build", "--prefix", str(frontend_dir)])
    return steps


def build_spa_if_stale(
    frontend_dir: Path = FRONTEND_DIR,
    spa_index: Path = SPA_INDEX,
    lock_path: Path = BUILD_LOCK_PATH,
    lock_timeout: float = BUILD_LOCK_TIMEOUT_SECONDS,
) -> list[list[str]]:
    """Run whichever steps the SPA needs, serialized across processes; return the steps that ran.

    The steps are computed after the lock is acquired, so a caller that waited on another build finds the
    SPA already current and runs nothing.
    """
    with FileLock(lock_path, timeout=lock_timeout):
        steps = spa_build_steps(frontend_dir, spa_index)
        for step in steps:
            print("+", " ".join(step), flush=True)
            subprocess.run(step, check=True)
    return steps


def main() -> int:
    """Bring the SPA up to date. The ``e2e`` nox session runs this file as a script."""
    build_spa_if_stale()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
