"""Characterization tests for tools/frontend/check_internal_anchor_links.py.

Pin which native `<a href=...>` usages the guard flags as internal-route
navigation that should use wouter's `<Link>` instead — literal internal hrefs,
dynamic expression hrefs, multi-line opening tags — and which it leaves alone
(external URLs, mailto/tel/fragment links, `.test.tsx` files, EXEMPTIONS
entries), using an isolated tmp_path frontend tree.
"""

from pathlib import Path

import check_internal_anchor_links
import pytest
from check_internal_anchor_links import _check_tag, is_exempt, main, scan_file

from tests.unit.tools.conftest import make_frontend_src

# Each case: (id, opening-tag text, expected reported href or None).
CHECK_TAG_CASES: list[tuple[str, str, str | None]] = [
    ("internal_literal_href_flagged", '<a href="/settings">', '"/settings"'),
    ("external_https_not_flagged", '<a href="https://example.com">', None),
    ("external_http_not_flagged", '<a href="http://example.com">', None),
    ("mailto_not_flagged", '<a href="mailto:a@b.com">', None),
    ("tel_not_flagged", '<a href="tel:12345">', None),
    ("hash_fragment_not_flagged", '<a href="#top">', None),
    ("dynamic_expr_flagged", "<a href={appUrl}>", "{appUrl}"),
    ("dynamic_expr_external_template_not_flagged", "<a href={`https://x.com/${id}`}>", None),
    ("dynamic_expr_external_string_not_flagged", '<a href={"https://x.com"}>', None),
    ("dynamic_expr_fragment_template_not_flagged", "<a href={`#${MAIN_CONTENT_ID}`}>", None),
    ("dynamic_expr_fragment_string_not_flagged", '<a href={"#top"}>', None),
]


def check_tag_href(tag: str) -> str | None:
    """Return just the reported href text (or None) for a given opening-tag string."""
    result = _check_tag(tag, Path("x.tsx"), 1)
    return None if result is None else result[2]


@pytest.mark.parametrize(
    ("tag", "expected"), [(c[1], c[2]) for c in CHECK_TAG_CASES], ids=[c[0] for c in CHECK_TAG_CASES]
)
def test_check_tag(tag: str, expected: str | None) -> None:
    assert check_tag_href(tag) == expected


def test_is_exempt_matches_configured_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_internal_anchor_links, "EXEMPTIONS", {"frontend/src/App.tsx:10": "reason"})
    assert is_exempt("frontend/src/App.tsx", 10) is True


def test_is_exempt_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_internal_anchor_links, "EXEMPTIONS", {})
    assert is_exempt("frontend/src/App.tsx", 10) is False


def test_scan_file_flags_internal_href(tmp_path: Path) -> None:
    f = tmp_path / "Page.tsx"
    f.write_text('export const Page = () => <a href="/apps">Apps</a>;\n')
    assert scan_file(f) == [(f, 1, '"/apps"')]


def test_scan_file_ignores_external_href(tmp_path: Path) -> None:
    f = tmp_path / "Page.tsx"
    f.write_text('export const Page = () => <a href="https://x.com">X</a>;\n')
    assert scan_file(f) == []


def test_scan_file_ignores_non_anchor_tags(tmp_path: Path) -> None:
    f = tmp_path / "Page.tsx"
    f.write_text('export const Page = () => <Link href="/apps">Apps</Link>;\n')
    assert scan_file(f) == []


def test_scan_file_handles_multiline_opening_tag(tmp_path: Path) -> None:
    f = tmp_path / "Page.tsx"
    f.write_text(
        'export const Page = () => (\n  <a\n    href="/apps"\n    className="link"\n  >\n    Apps\n  </a>\n);\n'
    )
    assert scan_file(f) == [(f, 2, '"/apps"')]


@pytest.fixture
def frontend_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module's path constants at an isolated tmp_path frontend tree."""
    src = make_frontend_src(tmp_path, monkeypatch, check_internal_anchor_links)
    monkeypatch.setattr(check_internal_anchor_links, "EXEMPTIONS", {})
    return src


def test_main_ok_when_no_native_internal_anchors(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "Page.tsx").write_text('<Link href="/apps">Apps</Link>\n')
    assert main() == 0
    assert "OK" in capsys.readouterr().out


def test_main_fails_on_native_internal_anchor(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "Page.tsx").write_text('<a href="/apps">Apps</a>\n')
    assert main() == 1
    assert "Page.tsx:1" in capsys.readouterr().out


def test_main_skips_test_files(frontend_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (frontend_env / "Page.test.tsx").write_text('<a href="/apps">Apps</a>\n')
    assert main() == 0
    assert "OK" in capsys.readouterr().out


def test_main_respects_exemptions(
    frontend_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (frontend_env / "Page.tsx").write_text('<a href="/apps">Apps</a>\n')
    monkeypatch.setattr(check_internal_anchor_links, "EXEMPTIONS", {"frontend/src/Page.tsx:1": "legacy redirect page"})
    assert main() == 0
    assert "1 exempted" in capsys.readouterr().out
