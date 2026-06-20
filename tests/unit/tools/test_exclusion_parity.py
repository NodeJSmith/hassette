"""Guard: the two venv/cache exclusion sets stay in sync.

tools/check_for_missing_attribute.py duplicates lint_helpers.EXCLUDED_PARTS inline because it runs
as a standalone ``uv run --script`` (isolated env — it can't import lint_helpers). This test fails
if the copies drift, so the duplication can't silently diverge.
"""

from check_for_missing_attribute import EXCLUDED_PARTS as STANDALONE_EXCLUDED
from lint_helpers import EXCLUDED_PARTS as SHARED_EXCLUDED


def test_exclusion_sets_match() -> None:
    assert set(STANDALONE_EXCLUDED) == set(SHARED_EXCLUDED)
