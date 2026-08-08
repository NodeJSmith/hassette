"""Characterization tests for tools/frontend/check_dead_tokens.py.

Pin the token-extraction logic (source tokens under `:root` and
`[data-theme="dark"]`, stopping before the shadcn alias block), the
reference-scanning logic (word-boundary matching so `--accent` isn't counted
referenced by `--accent-hover`), and the pass/fail/warning outcomes of
`main()`, using an isolated tmp_path frontend tree.
"""

import textwrap
from pathlib import Path

import check_dead_tokens
import pytest
from check_dead_tokens import (
    build_corpus,
    extract_block,
    extract_token_definitions,
    find_frontend_files,
    is_referenced,
    main,
)

# Each case: (id, css_text, selector, expected block body).
EXTRACT_BLOCK_CASES: list[tuple[str, str, str, str]] = [
    (
        "root_block_found",
        ":root {\n  --a: 1;\n}\n",
        ":root",
        "\n  --a: 1;\n",
    ),
    (
        "nested_braces_stay_balanced",
        ":root {\n  --a: var(--b);\n}\n",
        ":root",
        "\n  --a: var(--b);\n",
    ),
    (
        "selector_missing_returns_empty",
        ":root {\n  --a: 1;\n}\n",
        '[data-theme="dark"]',
        "",
    ),
    (
        "unbalanced_braces_returns_empty",
        ":root {\n  --a: 1;\n",
        ":root",
        "",
    ),
]


# Each case: (id, token, corpus, expected is_referenced).
IS_REFERENCED_CASES: list[tuple[str, str, str, bool]] = [
    ("referenced_elsewhere", "--accent", "color: var(--accent);", True),
    ("not_referenced_at_all", "--accent", "color: red;", False),
    ("prefix_collision_not_counted", "--accent", "color: var(--accent-hover);", False),
    ("only_in_own_definition_line_not_referenced", "--accent", "  --accent: #fff;", False),
]


@pytest.mark.parametrize(
    ("css_text", "selector", "expected"),
    [(c[1], c[2], c[3]) for c in EXTRACT_BLOCK_CASES],
    ids=[c[0] for c in EXTRACT_BLOCK_CASES],
)
def test_extract_block(css_text: str, selector: str, expected: str) -> None:
    assert extract_block(css_text, selector) == expected


def test_extract_token_definitions_stops_before_shadcn_aliases() -> None:
    css_text = textwrap.dedent(
        """\
        :root {
          --bg-page: #fff;
          --ink-1: #000;
          --background: var(--bg-page);
        }
        """
    )
    assert extract_token_definitions(css_text) == ["--bg-page", "--ink-1"]


def test_extract_token_definitions_includes_dark_theme_block() -> None:
    css_text = textwrap.dedent(
        """\
        :root {
          --bg-page: #fff;
          --background: var(--bg-page);
        }
        [data-theme="dark"] {
          --bg-page-dark: #000;
          --primary: oklch(0.5 0 0);
        }
        """
    )
    assert extract_token_definitions(css_text) == ["--bg-page", "--bg-page-dark"]


def test_extract_token_definitions_dedupes_repeated_names() -> None:
    css_text = textwrap.dedent(
        """\
        :root {
          --bg-page: #fff;
          --bg-page: #eee;
          --background: var(--bg-page);
        }
        """
    )
    assert extract_token_definitions(css_text) == ["--bg-page"]


@pytest.mark.parametrize(
    ("token", "corpus", "expected"),
    [(c[1], c[2], c[3]) for c in IS_REFERENCED_CASES],
    ids=[c[0] for c in IS_REFERENCED_CASES],
)
def test_is_referenced(token: str, corpus: str, expected: bool) -> None:
    assert is_referenced(token, corpus) == expected


@pytest.fixture
def frontend_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module's path constants at an isolated tmp_path frontend tree."""
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True)
    monkeypatch.setattr(check_dead_tokens, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_dead_tokens, "FRONTEND_SRC", src)
    monkeypatch.setattr(check_dead_tokens, "GLOBAL_CSS", src / "global.css")
    return src


def test_find_frontend_files_excludes_declaration_files(frontend_env: Path) -> None:
    (frontend_env / "global.css").write_text("body {}\n")
    (frontend_env / "App.tsx").write_text("export {};\n")
    (frontend_env / "types.d.ts").write_text("declare module 'x';\n")
    names = {p.name for p in find_frontend_files()}
    assert names == {"global.css", "App.tsx"}


def test_build_corpus_concatenates_file_contents(tmp_path: Path) -> None:
    a = tmp_path / "a.css"
    b = tmp_path / "b.tsx"
    a.write_text("body { color: red; }")
    b.write_text("export const x = 1;")
    corpus = build_corpus([a, b])
    assert "color: red" in corpus
    assert "export const x" in corpus


def test_main_ok_when_all_tokens_referenced(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "global.css").write_text(
        textwrap.dedent(
            """\
            :root {
              --bg-page: #fff;
              --background: var(--bg-page);
            }
            """
        )
    )
    (frontend_env / "App.tsx").write_text("const x = 'var(--bg-page)';\n")
    assert main() == 0
    assert "OK" in capsys.readouterr().out


def test_main_fails_on_unreferenced_token(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "global.css").write_text(
        textwrap.dedent(
            """\
            :root {
              --bg-page: #fff;
              --ink-1: #000;
              --background: var(--bg-page);
            }
            """
        )
    )
    (frontend_env / "App.tsx").write_text("const x = 'var(--bg-page)';\n")
    assert main() == 1
    assert "--ink-1" in capsys.readouterr().out


@pytest.mark.usefixtures("frontend_env")
def test_main_missing_global_css_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 1
    assert "not found" in capsys.readouterr().err


def test_main_warns_when_no_source_files_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # GLOBAL_CSS deliberately lives outside FRONTEND_SRC so the source-file glob
    # comes back empty even though the token file itself exists and parses fine.
    outside_css = tmp_path / "outside" / "global.css"
    outside_css.parent.mkdir(parents=True)
    outside_css.write_text(
        textwrap.dedent(
            """\
            :root {
              --bg-page: #fff;
              --background: var(--bg-page);
            }
            """
        )
    )
    empty_src = tmp_path / "frontend" / "src"
    empty_src.mkdir(parents=True)
    monkeypatch.setattr(check_dead_tokens, "GLOBAL_CSS", outside_css)
    monkeypatch.setattr(check_dead_tokens, "FRONTEND_SRC", empty_src)
    assert main() == 0
    assert "No .css/.ts/.tsx files" in capsys.readouterr().err
