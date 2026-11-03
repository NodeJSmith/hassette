"""Tests for scripts/capture_screenshots.py's --against mode: argument rules and entry building.

The capture itself (cookie minting, shot-scraper) needs a running hassette and a browser, so it is
verified by running the script, not here.
"""

from pathlib import Path

import pytest
from capture_screenshots import ANIMATION_DISABLE_JS, against_entries, parse_args, url_slug


@pytest.mark.parametrize(
    ("path", "slug"),
    [
        ("/apps/pet_feeder", "apps-pet_feeder"),
        ("/apps", "apps"),
        ("/", "index"),
        ("/apps/x?tab=logs", "apps-x-tab-logs"),
    ],
)
def test_url_slug(path: str, slug: str) -> None:
    assert url_slug(path) == slug


def test_against_entries_target_the_port_and_output_dir(tmp_path: Path) -> None:
    entries = against_entries(["/apps/pet_feeder", "/apps"], 18799, tmp_path, 1200, 700, 1500)

    assert [e["url"] for e in entries] == ["http://localhost:18799/apps/pet_feeder", "http://localhost:18799/apps"]
    assert [e["output"] for e in entries] == [str(tmp_path / "apps-pet_feeder.png"), str(tmp_path / "apps.png")]
    assert all(e["width"] == 1200 and e["height"] == 700 and e["wait"] == 1500 for e in entries)
    assert all(str(e["javascript"]).startswith(ANIMATION_DISABLE_JS) for e in entries)


def test_against_entries_reject_a_url_without_leading_slash(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="starting with '/'"):
        against_entries(["apps"], 1, tmp_path, 1, 1, 0)


def test_against_entries_reject_urls_with_the_same_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"both write apps-x\.png"):
        against_entries(["/apps/x", "/apps-x"], 1, tmp_path, 1, 1, 0)


def test_against_requires_token_file_url_and_out(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--against", "18799", "--url", "/apps"])

    assert "--against needs --token-file, --out" in capsys.readouterr().err


def test_against_flags_without_against_are_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--url", "/apps"])

    assert "--url: valid only with --against" in capsys.readouterr().err


def test_only_is_refused_with_against(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--against", "1", "--token-file", "t", "--url", "/", "--out", "o", "--only", "apps"])

    assert "doesn't apply with --against" in capsys.readouterr().err


def test_docs_mode_args_still_parse() -> None:
    args = parse_args(["--only", "web_ui_apps", "--timeout", "60000"])

    assert (args.against, args.only, args.timeout) == (None, "web_ui_apps", 60000)
