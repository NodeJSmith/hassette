"""Characterization tests for tools/frontend/check_frontend_section_dividers.py.

Pins which line shapes the guard flags as decorated section dividers in .ts/.tsx files —
bare `// ----` rules and wrapped `// --- Label ---` / `{/* --- Label --- */}` forms — and
which it leaves alone (plain labels, ordinary comments), using an isolated tmp_path
frontend tree.
"""

from pathlib import Path

import check_frontend_section_dividers
import pytest
from check_frontend_section_dividers import check_file, main

from tests.unit.tools.conftest import make_frontend_src

# Each case: (id, source line, expected message or None).
CHECK_FILE_CASES: list[tuple[str, str, str | None]] = [
    ("bare_line_comment_rule_flagged", "// --------", "section-divider comment - '// --------'"),
    (
        "wrapped_line_comment_flagged",
        "// --- Helpers ---",
        "section-divider comment - '// --- Helpers ---'",
    ),
    (
        "indented_wrapped_line_comment_flagged",
        "  // --- connection ---",
        "section-divider comment - '// --- connection ---'",
    ),
    (
        "bare_jsx_comment_flagged",
        "{/* -------- */}",
        "section-divider comment - '{/* -------- */}'",
    ),
    (
        "wrapped_jsx_comment_flagged",
        "{/* --- Section --- */}",
        "section-divider comment - '{/* --- Section --- */}'",
    ),
    ("plain_label_not_flagged", "// Helpers", None),
    ("ordinary_comment_not_flagged", "// this explains something", None),
    ("short_dash_run_not_flagged", "// ---", None),
    ("code_line_not_flagged", 'const x = "---";', None),
]


@pytest.mark.parametrize(
    ("line", "expected"), [(c[1], c[2]) for c in CHECK_FILE_CASES], ids=[c[0] for c in CHECK_FILE_CASES]
)
def test_check_file(line: str, expected: str | None, tmp_path: Path) -> None:
    f = tmp_path / "sample.tsx"
    f.write_text(f"const a = 1;\n{line}\nconst b = 2;\n")
    result = check_file(f)
    assert result == ([] if expected is None else [(2, expected)])


@pytest.fixture
def frontend_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_frontend_src(tmp_path, monkeypatch, check_frontend_section_dividers)


def test_main_ok_when_no_dividers(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "Page.tsx").write_text("// a plain comment\nconst x = 1;\n")
    assert main() == 0
    assert "OK" in capsys.readouterr().out


def test_main_fails_on_divider(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "Page.tsx").write_text("// --- Helpers ---\nconst x = 1;\n")
    assert main() == 1
    assert "Page.tsx:1" in capsys.readouterr().out


def test_main_skips_generated_d_ts_files(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "generated.d.ts").write_text("// --- Helpers ---\n")
    assert main() == 0
    assert "OK" in capsys.readouterr().out
