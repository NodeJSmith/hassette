"""Characterization tests for tools/frontend/check_pr_screenshots.py.

Pin the decision logic with synthetic inputs: when the guard triggers, and which
of the three evidence paths satisfy it, including rejection of branch-scoped
raw.githubusercontent.com links that rot once the PR branch is deleted.
"""

import pytest
from check_pr_screenshots import branch_scoped_raw_prefixes, evaluate, has_visual_evidence, is_rendering_file

SHA = "5257d88b6a9fcdf7a5df250b6fda5f62ade45b3d"
RAW_BASE = "https://raw.githubusercontent.com/NodeJSmith/hassette"
BRANCH_URL = f"{RAW_BASE}/autofix/issue-2219/docs/pr-evidence/x.png"
MAIN_URL = f"{RAW_BASE}/main/docs/pr-evidence/x.png"
SHA_URL = f"{RAW_BASE}/{SHA}/docs/pr-evidence/x.png"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("frontend/src/App.tsx", True),
        ("frontend/src/styles/layout.css", True),
        ("frontend/src/App.test.tsx", False),
        ("frontend/src/api/generated-types.d.ts", False),
        ("frontend/src/foo.module.css.d.ts", False),
        ("frontend/src/util.ts", False),  # .ts is logic, not rendering
        ("src/hassette/core/core.py", False),
        ("docs/pages/index.md", False),
    ],
)
def test_is_rendering_file(path: str, expected: bool) -> None:
    assert is_rendering_file(path) == expected


def test_label_satisfies() -> None:
    assert has_visual_evidence("", [], ["no-visual-change"]) is True


def test_docs_png_satisfies() -> None:
    assert has_visual_evidence("", ["docs/_static/dashboard.png"], []) is True


@pytest.mark.parametrize(
    "body",
    [
        "## Screenshots\n\nbefore/after below",
        "### screenshot\n...",
        "Here it is: ![dashboard](https://example.com/x.png)",
        'Inline <img src="x.png" />',
    ],
)
def test_body_evidence_satisfies(body: str) -> None:
    assert has_visual_evidence(body, [], []) is True


def test_no_evidence_not_satisfied() -> None:
    assert has_visual_evidence("Just a description, no images.", ["frontend/src/App.tsx"], []) is False


def test_triggered_without_evidence_fails() -> None:
    assert evaluate(["frontend/src/App.tsx"], "no images", []) == (True, False)


def test_triggered_with_label_passes() -> None:
    assert evaluate(["frontend/src/App.tsx"], "", ["no-visual-change"]) == (True, True)


def test_only_test_file_not_triggered() -> None:
    assert evaluate(["frontend/src/App.test.tsx"], "", []) == (False, False)


def test_non_frontend_change_not_triggered() -> None:
    assert evaluate(["src/hassette/core/core.py"], "", []) == (False, False)


@pytest.mark.parametrize(
    "body",
    [
        f"## Screenshots\n\n![after]({BRANCH_URL})",
        f"![after]({MAIN_URL})",
        f'<img src="{BRANCH_URL}" />',
        f"![a]({SHA_URL})\n![b]({BRANCH_URL})",
    ],
)
def test_branch_scoped_raw_url_in_body_not_satisfied(body: str) -> None:
    assert has_visual_evidence(body, ["frontend/src/App.tsx"], []) is False
    assert evaluate(["frontend/src/App.tsx"], body, []) == (True, False)


def test_sha_pinned_raw_url_in_body_satisfies() -> None:
    assert has_visual_evidence(f"## Screenshots\n\n![after]({SHA_URL})", ["frontend/src/App.tsx"], []) is True


def test_branch_scoped_url_ignored_when_docs_png_committed() -> None:
    files = ["frontend/src/App.tsx", "docs/pr-evidence/x.png"]
    assert evaluate(files, f"![after]({BRANCH_URL})", []) == (True, True)


def test_branch_scoped_url_ignored_with_label() -> None:
    assert evaluate(["frontend/src/App.tsx"], f"![after]({BRANCH_URL})", ["no-visual-change"]) == (True, True)


def test_branch_scoped_raw_prefixes_reports_only_unpinned_once_each() -> None:
    body = f'![a]({SHA_URL}) ![b]({BRANCH_URL}) <img src="{MAIN_URL}"> ![c]({MAIN_URL})'
    assert branch_scoped_raw_prefixes(body) == [f"{RAW_BASE}/autofix/", f"{RAW_BASE}/main/"]


def test_refs_heads_raw_url_is_flagged() -> None:
    body = f"![after]({RAW_BASE}/refs/heads/autofix/issue-2219/docs/pr-evidence/x.png)"
    assert branch_scoped_raw_prefixes(body) == [f"{RAW_BASE}/refs/"]
    assert has_visual_evidence(body, ["frontend/src/App.tsx"], []) is False


def test_branch_scoped_filename_with_parentheses_is_flagged() -> None:
    body = f'## Screenshots\n\n<img src="{RAW_BASE}/main/docs/shot(1).png">'
    assert branch_scoped_raw_prefixes(body) == [f"{RAW_BASE}/main/"]
    assert has_visual_evidence(body, ["frontend/src/App.tsx"], []) is False


def test_protocol_relative_branch_scoped_url_is_flagged() -> None:
    body = '## Screenshots\n\n<img src="//raw.githubusercontent.com/o/r/main/docs/x.png">'
    assert branch_scoped_raw_prefixes(body) == ["//raw.githubusercontent.com/o/r/main/"]
    assert has_visual_evidence(body, ["frontend/src/App.tsx"], []) is False


def test_branch_scoped_non_image_raw_link_is_flagged() -> None:
    body = f"![after]({SHA_URL})\nConfig: {RAW_BASE}/main/mkdocs.yml"
    assert branch_scoped_raw_prefixes(body) == [f"{RAW_BASE}/main/"]
    assert has_visual_evidence(body, ["frontend/src/App.tsx"], []) is False


def test_uppercase_host_branch_scoped_url_is_flagged() -> None:
    url = MAIN_URL.replace("raw.githubusercontent.com", "RAW.GitHubUserContent.com")
    assert branch_scoped_raw_prefixes(f"![after]({url})") == [url.removesuffix("docs/pr-evidence/x.png")]
