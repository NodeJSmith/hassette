"""Unit tests for manifest-based file ownership tracking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.manifest import detect_orphans, is_owned, load_manifest, save_manifest


class TestManifestRoundTrip:
    def test_save_and_load(self, tmp_path: Path) -> None:
        files = {Path("src/hassette/models/states/fan.py"), Path("src/hassette/models/states/light.py")}
        save_manifest(tmp_path, files)
        loaded = load_manifest(tmp_path)
        assert loaded == files

    def test_sorted_output(self, tmp_path: Path) -> None:
        files = {Path("z.py"), Path("a.py"), Path("m.py")}
        save_manifest(tmp_path, files)
        content = (tmp_path / ".generated-manifest").read_text()
        lines = [line for line in content.strip().splitlines() if not line.startswith("#")]
        assert lines == sorted(lines)

    def test_empty_manifest(self, tmp_path: Path) -> None:
        loaded = load_manifest(tmp_path)
        assert loaded == set()


class TestOrphanDetection:
    def test_detects_removed_files(self) -> None:
        previous = {Path("a.py"), Path("b.py"), Path("c.py")}
        current = {Path("a.py"), Path("c.py")}
        orphans = detect_orphans(previous, current)
        assert orphans == {Path("b.py")}

    def test_no_orphans_when_same(self) -> None:
        files = {Path("a.py"), Path("b.py")}
        assert detect_orphans(files, files) == set()


class TestIsOwned:
    def test_owned_file(self) -> None:
        manifest = {Path("src/foo.py")}
        assert is_owned(Path("src/foo.py"), manifest) is True

    def test_unowned_file(self) -> None:
        manifest = {Path("src/foo.py")}
        assert is_owned(Path("src/bar.py"), manifest) is False
