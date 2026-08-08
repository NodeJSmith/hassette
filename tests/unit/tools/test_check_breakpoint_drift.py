"""Characterization tests for tools/frontend/check_breakpoint_drift.py.

Pin the extraction logic for each of the four breakpoint sources (JS constants,
Tailwind `@theme` registrations, CSS `@media` queries, Tailwind responsive
utility prefixes) and the drift detection that compares them, using an
isolated tmp_path frontend tree so nothing depends on the real frontend/src
contents.
"""

import sys
from pathlib import Path

import check_breakpoint_drift
import pytest
from check_breakpoint_drift import (
    extract_css_breakpoints,
    extract_js_breakpoints,
    extract_tailwind_utility_breakpoints,
    extract_theme_breakpoints,
    find_frontend_source_files,
    find_missing_constants,
    main,
    theme_breakpoints_by_value,
)

# Each case: (id, js constants, css breakpoints, expected missing values).
FIND_MISSING_CASES: list[tuple[str, dict[int, str], dict[int, list[Path]], set[int]]] = [
    (
        "all_covered",
        {768: "BREAKPOINT_MOBILE"},
        {768: [Path("a.css")]},
        set(),
    ),
    (
        "one_missing",
        {768: "BREAKPOINT_MOBILE"},
        {768: [Path("a.css")], 600: [Path("b.css")]},
        {600},
    ),
    (
        "no_css_breakpoints",
        {768: "BREAKPOINT_MOBILE"},
        {},
        set(),
    ),
]


@pytest.fixture
def frontend_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module's path constants at an isolated tmp_path frontend tree."""
    src = tmp_path / "frontend" / "src"
    (src / "hooks").mkdir(parents=True)
    monkeypatch.setattr(check_breakpoint_drift, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(check_breakpoint_drift, "FRONTEND_SRC", src)
    monkeypatch.setattr(check_breakpoint_drift, "MEDIA_QUERY_TS", src / "hooks" / "use-media-query.ts")
    monkeypatch.setattr(check_breakpoint_drift, "GLOBAL_CSS", src / "global.css")
    return src


@pytest.mark.parametrize(
    ("js", "css", "expected"),
    [(c[1], c[2], c[3]) for c in FIND_MISSING_CASES],
    ids=[c[0] for c in FIND_MISSING_CASES],
)
def test_find_missing_constants(js: dict[int, str], css: dict[int, list[Path]], expected: set[int]) -> None:
    assert find_missing_constants(js, css) == expected


def test_theme_breakpoints_by_value_groups_by_pixel_value(frontend_env: Path) -> None:
    result = theme_breakpoints_by_value({"mobile": 768, "tablet": 1024})
    assert result == {
        768: [frontend_env / "global.css"],
        1024: [frontend_env / "global.css"],
    }


def test_extract_js_breakpoints_parses_exported_constants(frontend_env: Path) -> None:
    (frontend_env / "hooks" / "use-media-query.ts").write_text(
        "export const BREAKPOINT_MOBILE = 768;\nexport const BREAKPOINT_TABLET = 1024;\n"
    )
    assert extract_js_breakpoints() == {768: "BREAKPOINT_MOBILE", 1024: "BREAKPOINT_TABLET"}


@pytest.mark.usefixtures("frontend_env")
def test_extract_js_breakpoints_missing_file_returns_empty() -> None:
    assert extract_js_breakpoints() == {}


def test_extract_css_breakpoints_finds_media_queries_across_files(frontend_env: Path) -> None:
    (frontend_env / "a.css").write_text("@media (max-width: 768px) { .x { color: red; } }\n")
    (frontend_env / "b.css").write_text("@media screen and (max-width: 900px) { .y {} }\n")
    result = extract_css_breakpoints()
    assert set(result) == {768, 900}


def test_extract_css_breakpoints_ignores_commented_out_media(frontend_env: Path) -> None:
    (frontend_env / "a.css").write_text("/* @media (max-width: 768px) { .x {} } */\n")
    assert extract_css_breakpoints() == {}


def test_extract_css_breakpoints_dedupes_same_file(frontend_env: Path) -> None:
    (frontend_env / "a.css").write_text("@media (max-width: 768px) { .x {} }\n@media (max-width: 768px) { .y {} }\n")
    result = extract_css_breakpoints()
    assert len(result[768]) == 1


def test_extract_theme_breakpoints_parses_registrations(frontend_env: Path) -> None:
    (frontend_env / "global.css").write_text("--breakpoint-mobile: 768px;\n--breakpoint-tablet: 1024px;\n")
    assert extract_theme_breakpoints() == {"mobile": 768, "tablet": 1024}


@pytest.mark.usefixtures("frontend_env")
def test_extract_theme_breakpoints_missing_file_returns_empty() -> None:
    assert extract_theme_breakpoints() == {}


def test_find_frontend_source_files_excludes_declaration_files(frontend_env: Path) -> None:
    (frontend_env / "App.tsx").write_text("export const App = () => null;\n")
    (frontend_env / "util.ts").write_text("export const x = 1;\n")
    (frontend_env / "types.d.ts").write_text("declare module 'x';\n")
    names = {p.name for p in find_frontend_source_files()}
    assert names == {"App.tsx", "util.ts"}


def test_extract_tailwind_utility_breakpoints_registered_screen(frontend_env: Path) -> None:
    target = frontend_env / "App.tsx"
    target.write_text('<div className="mobile:hidden" />\n')
    found, unknown = extract_tailwind_utility_breakpoints({"mobile": 768}, {768: "BREAKPOINT_MOBILE"})
    assert found == {768: [target]}
    assert unknown == {}


def test_extract_tailwind_utility_breakpoints_unknown_max_screen(frontend_env: Path) -> None:
    target = frontend_env / "App.tsx"
    target.write_text('<div className="max-widescreen:flex" />\n')
    found, unknown = extract_tailwind_utility_breakpoints({"mobile": 768}, {768: "BREAKPOINT_MOBILE"})
    assert found == {}
    assert unknown == {"widescreen": [target]}


def test_extract_tailwind_utility_breakpoints_arbitrary_max_px(frontend_env: Path) -> None:
    target = frontend_env / "App.tsx"
    target.write_text('<div className="max-[768px]:hidden" />\n')
    found, unknown = extract_tailwind_utility_breakpoints({}, {})
    assert found == {768: [target]}
    assert unknown == {}


def test_extract_tailwind_utility_breakpoints_min_arbitrary_folds_to_known_max(frontend_env: Path) -> None:
    # min-[769px] with 768 already a known JS breakpoint is the inclusive complement
    # of max-768 and folds into the existing bucket instead of reporting a new one.
    target = frontend_env / "App.tsx"
    target.write_text('<div className="min-[769px]:flex" />\n')
    found, unknown = extract_tailwind_utility_breakpoints({}, {768: "BREAKPOINT_MOBILE"})
    assert found == {768: [target]}
    assert unknown == {}


def test_main_ok_when_all_breakpoints_covered(frontend_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (frontend_env / "hooks" / "use-media-query.ts").write_text("export const BREAKPOINT_MOBILE = 768;\n")
    (frontend_env / "global.css").write_text("--breakpoint-mobile: 768px;\n")
    (frontend_env / "a.css").write_text("@media (max-width: 768px) { .x {} }\n")
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py"])
    assert main() == 0


def test_main_ok_prints_covered_breakpoints(
    frontend_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (frontend_env / "hooks" / "use-media-query.ts").write_text("export const BREAKPOINT_MOBILE = 768;\n")
    (frontend_env / "global.css").write_text("--breakpoint-mobile: 768px;\n")
    (frontend_env / "a.css").write_text("@media (max-width: 768px) { .x {} }\n")
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py"])
    main()
    assert "OK" in capsys.readouterr().out


def test_main_fails_when_css_breakpoint_has_no_js_constant(
    frontend_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (frontend_env / "hooks" / "use-media-query.ts").write_text("export const BREAKPOINT_MOBILE = 768;\n")
    (frontend_env / "global.css").write_text("--breakpoint-mobile: 768px;\n")
    (frontend_env / "a.css").write_text("@media (max-width: 768px) { .x {} }\n@media (max-width: 600px) { .y {} }\n")
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py"])
    assert main() == 1
    assert "600px" in capsys.readouterr().out


def test_main_fails_on_unregistered_tailwind_screen(
    frontend_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (frontend_env / "hooks" / "use-media-query.ts").write_text("export const BREAKPOINT_MOBILE = 768;\n")
    (frontend_env / "global.css").write_text("--breakpoint-mobile: 768px;\n")
    (frontend_env / "a.css").write_text("@media (max-width: 768px) { .x {} }\n")
    (frontend_env / "App.tsx").write_text('<div className="max-widescreen:flex" />\n')
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py"])
    assert main() == 1
    assert "widescreen" in capsys.readouterr().out


@pytest.mark.usefixtures("frontend_env")
def test_main_errors_when_no_js_constants_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py"])
    assert main() == 1
    assert "no BREAKPOINT_* constants" in capsys.readouterr().err


def test_main_errors_when_no_theme_registrations(
    frontend_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (frontend_env / "hooks" / "use-media-query.ts").write_text("export const BREAKPOINT_MOBILE = 768;\n")
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py"])
    assert main() == 1
    assert "no Tailwind @theme breakpoint registrations" in capsys.readouterr().err


def test_main_errors_when_no_media_queries(
    frontend_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (frontend_env / "hooks" / "use-media-query.ts").write_text("export const BREAKPOINT_MOBILE = 768;\n")
    (frontend_env / "global.css").write_text("--breakpoint-mobile: 768px;\n")
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py"])
    assert main() == 1
    assert "no @media (max-width: Npx) queries" in capsys.readouterr().err


def test_main_smoke_test_flag_passes(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["check_breakpoint_drift.py", "--smoke-test"])
    assert main() == 0
    assert "Smoke test passed." in capsys.readouterr().out
