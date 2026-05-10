"""Unit tests for hassette_codegen.output — shared ruff/validation/drift utilities."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.output import atomic_write, check_drift, format_via_ruff


class TestFormatViaRuff:
    def test_produces_valid_python(self) -> None:
        raw = "x=1\ny=2\n"
        result = format_via_ruff(raw)
        assert "x = 1" in result
        compile(result, "<test>", "exec")

    def test_sorts_imports(self) -> None:
        raw = "import sys\nimport os\nx = 1\n"
        result = format_via_ruff(raw)
        lines = result.strip().splitlines()
        import_lines = [line for line in lines if line.startswith("import")]
        assert import_lines == sorted(import_lines)


class TestAtomicWrite:
    def test_creates_file_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.py"
        result = atomic_write(target, "x = 1\n")
        assert result is True
        assert target.exists()
        content = target.read_text()
        assert "x = 1" in content

    def test_skips_file_on_syntax_error(self, tmp_path: Path) -> None:
        target = tmp_path / "bad.py"
        result = atomic_write(target, "def foo(\n")
        assert result is False
        assert not target.exists()

    def test_retains_previous_version_on_failure(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.py"
        target.write_text("original = True\n")
        result = atomic_write(target, "def broken(\n")
        assert result is False
        assert target.read_text() == "original = True\n"


class TestCheckDrift:
    def test_returns_true_when_content_matches(self, tmp_path: Path) -> None:
        target = tmp_path / "match.py"
        content = "x = 1\n"
        target.write_text(content)
        assert check_drift(target, content) is True

    def test_returns_false_when_content_differs(self, tmp_path: Path) -> None:
        target = tmp_path / "differ.py"
        target.write_text("x = 1\n")
        assert check_drift(target, "x = 2\n") is False

    def test_returns_false_when_file_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "missing.py"
        assert check_drift(target, "x = 1\n") is False

    def test_ignores_formatting_differences(self, tmp_path: Path) -> None:
        target = tmp_path / "fmt.py"
        target.write_text("x=1\n")
        assert check_drift(target, "x = 1\n") is True
