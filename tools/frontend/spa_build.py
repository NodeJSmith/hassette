"""Decide which npm steps bring the built SPA up to date with the frontend sources.

Shared by the ``e2e`` nox session and e2e's ``ensure_spa_built`` fixture, so local e2e runs against the
current frontend (and the build's absolute-path check in ``frontend/no-absolute-paths.ts`` runs on it)
instead of reusing a build from before the last frontend change. CI always builds fresh.

Staleness is by mtime: a checkout that bumps mtimes causes a spurious rebuild (safe); only clock skew
can cause a missed one.
"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
SPA_INDEX = REPO_ROOT / "src" / "hassette" / "web" / "static" / "spa" / "index.html"

_SOURCE_DIRS = ("src", "public")
_SOURCE_FILES = ("index.html", "vite.config.ts", "no-absolute-paths.ts", "package.json", "package-lock.json")


def newest_mtime(frontend_dir: Path) -> float:
    """The newest mtime among the frontend's build inputs."""
    files = [frontend_dir / name for name in _SOURCE_FILES]
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


def main() -> int:
    """Run whichever steps the SPA needs. The ``e2e`` nox session runs this file as a script."""
    for step in spa_build_steps():
        print("+", " ".join(step), flush=True)
        subprocess.run(step, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
