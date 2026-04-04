#!/usr/bin/env python3
"""Generate a pip-constraints file from hassette's declared dependencies.

Reads [project].dependencies from pyproject.toml, strips extras syntax
(e.g. uvicorn[standard]>=0.30 → uvicorn>=0.30), and appends an exact
hassette pin sourced from importlib.metadata.

Output goes to stdout; caller redirects to /app/constraints.txt.

Usage:
    python tools/generate_constraints.py [pyproject.toml path]
"""

import importlib.metadata
import re
import sys
import tomllib
from pathlib import Path


def _strip_extras(dep: str) -> str:
    """Remove extras from a PEP 508 dependency string.

    Examples:
        uvicorn[standard]>=0.34.0  →  uvicorn>=0.34.0
        pydantic[email]>=2.0,<3    →  pydantic>=2.0,<3
        aiohttp>=3.11.18           →  aiohttp>=3.11.18
    """
    return re.sub(r"\[.*?\]", "", dep)


def generate_lines(pyproject_path: Path) -> list[str]:
    """Return the constraints file lines (without trailing newlines).

    Args:
        pyproject_path: Path to the pyproject.toml file to read.

    Returns:
        List of strings, starting with a header comment followed by one
        dependency specifier per line.  hassette itself is appended last
        as an exact pin sourced from importlib.metadata.
    """
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    try:
        declared: list[str] = data["project"]["dependencies"]
    except KeyError as e:
        print(f"ERROR: missing key in pyproject.toml: {e}", file=sys.stderr)
        sys.exit(1)
    hassette_version = importlib.metadata.version("hassette")

    lines: list[str] = ["# Auto-generated from hassette pyproject.toml — do not edit"]

    lines.extend(_strip_extras(dep) for dep in declared)

    lines.append(f"hassette=={hassette_version}")
    return lines


def main() -> None:
    pyproject_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "pyproject.toml"

    lines = generate_lines(pyproject_path)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
