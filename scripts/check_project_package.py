#!/usr/bin/env python3
"""Report a user project whose installed distribution ships no Python modules.

docker_start.sh runs this after installing the project in /config. A build backend pointed at the
wrong place (module-name, module-root) can install an empty package while every step exits 0. Only
the empty case is detectable: a distribution may legitimately ship a package named differently from
[project].name, so the check never guesses import names.

Prints one problem description to stdout, or nothing when the package looks fine.

Usage:
    python -P scripts/check_project_package.py <pyproject.toml path>
"""

import importlib.metadata
import sys
import tomllib
from pathlib import Path

MODULE_SUFFIXES = (".py", ".so", ".pyd")


def find_problem(pyproject: Path) -> str | None:
    """Return a description of what's wrong with the project's installed distribution, if anything."""
    with pyproject.open("rb") as fh:
        name = tomllib.load(fh).get("project", {}).get("name")
    if not name:
        return None
    try:
        files = importlib.metadata.distribution(name).files or []
    except importlib.metadata.PackageNotFoundError:
        return f"distribution {name!r} is not installed"
    # ".." entries live outside site-packages (console scripts in bin/). The project is installed with
    # --no-editable; an editable install records only a .pth file and would look empty here.
    if not any(path.suffix in MODULE_SUFFIXES and path.parts[0] != ".." for path in files):
        return f"distribution {name!r} contains no Python modules"
    return None


def main() -> None:
    problem = find_problem(Path(sys.argv[1]))
    if problem:
        print(problem)


if __name__ == "__main__":
    main()
