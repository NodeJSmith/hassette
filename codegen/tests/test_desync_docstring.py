"""Unit tests for desync_docstring — the async-phrasing stripper for sync facades.

Each case is a real phrasing used in Bus/Scheduler/Api docstrings. When adding a
new "must be awaited" variant to those docstrings, add a matching pattern in
ast_utils.py AND a case here — the drift gate only detects changes to generated
output, not phrasings the regex misses.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.sync_facade.ast_utils import desync_docstring

CASES = [
    pytest.param(
        "Do the thing.\n\nThis method is ``async`` and must be awaited.\nMore detail follows.",
        "Do the thing.\n\nMore detail follows.",
        id="async-sentence-at-paragraph-start",
    ),
    pytest.param(
        "Do the thing. This method is ``async`` and must be awaited. More detail.",
        "Do the thing.\nMore detail.",
        id="async-sentence-mid-paragraph",
    ),
    pytest.param(
        "The job is awaited inline by the caller.",
        "The job completes inline by the caller.",
        id="awaited-inline-phrase-mutation",
    ),
    pytest.param(
        "Fire an event.\n\nMust be awaited — a forgotten ``await`` is reported per "
        "``forgotten_await_behavior`` (default: warn).\n\nReturns the response.",
        "Fire an event.\n\nReturns the response.",
        id="api-forgotten-await-paragraph",
    ),
    pytest.param(
        "Fire an event.\n\nMust be awaited — a forgotten ``await`` is reported per "
        "``forgotten_await_behavior`` (default: warn).",
        "Fire an event.",
        id="api-forgotten-await-paragraph-at-end",
    ),
    pytest.param(
        "Subscribe to a topic.\n\nMust be awaited. Registration completes before the call returns.",
        "Subscribe to a topic.\n\nRegistration completes before the call returns.",
        id="bus-scheduler-prefix-keeps-completion-sentence",
    ),
    pytest.param(
        "Subscribe to raw topic subscriptions. Must be awaited.\nMore detail.",
        "Subscribe to raw topic subscriptions.\nMore detail.",
        id="bus-on-sentence-suffix",
    ),
]


@pytest.mark.parametrize(("source", "expected"), CASES)
def test_desync_docstring_strips_async_phrasing(source: str, expected: str) -> None:
    result = desync_docstring(source)
    assert result == expected
    assert "must be awaited" not in result.lower()


def test_plain_docstring_unchanged() -> None:
    doc = "Get the current state.\n\nReturns the typed state object."
    assert desync_docstring(doc) == doc
