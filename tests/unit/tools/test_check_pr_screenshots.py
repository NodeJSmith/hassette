"""Characterization tests for tools/frontend/check_pr_screenshots.py.

Pin the decision logic with synthetic inputs: when the guard triggers, and which
of the three evidence paths satisfy it.
"""

import pytest
from check_pr_screenshots import evaluate, has_visual_evidence, is_rendering_file


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
