"""Verify that built wheels include the SPA frontend assets."""

import contextlib
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPA_DIR = PROJECT_ROOT / "src" / "hassette" / "web" / "static" / "spa"

STUB_FILES = ("index.html", "assets/index-abc123.js", "assets/index-abc123.css")


@pytest.fixture
def stub_spa() -> Generator[Path, None, None]:
    """Create minimal stub SPA files so we can test packaging without Node."""
    SPA_DIR.mkdir(parents=True, exist_ok=True)
    assets_dir = SPA_DIR / "assets"
    assets_dir.mkdir(exist_ok=True)

    created: list[Path] = []
    try:
        for relative in STUB_FILES:
            f = SPA_DIR / relative
            f.write_text("<!-- stub -->" if relative.endswith(".html") else "/* stub */")
            created.append(f)
        yield SPA_DIR
    finally:
        for f in created:
            f.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            assets_dir.rmdir()
        with contextlib.suppress(OSError):
            SPA_DIR.rmdir()


@pytest.mark.integration
@pytest.mark.usefixtures("stub_spa")
def test_wheel_contains_spa_assets(tmp_path: Path) -> None:
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, f"uv build failed:\n{build.stderr}"

    check = subprocess.run(
        ["uv", "run", "./tools/check_wheel_spa.py", "--dist-dir", str(tmp_path)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert check.returncode == 0, f"SPA check failed:\n{check.stderr}"
