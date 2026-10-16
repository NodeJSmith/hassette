import importlib.util
from pathlib import Path

CHECKER_PATH = Path(__file__).resolve().parents[3] / "tools" / "docs" / "check_snippet_orphans.py"
_spec = importlib.util.spec_from_file_location("check_snippet_orphans", CHECKER_PATH)
assert _spec is not None
assert _spec.loader is not None
check_snippet_orphans = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_snippet_orphans)


def test_single_line_includes_drop_the_section_marker() -> None:
    markdown = '--8<-- "pages/a/snippets/full.py"\n\n--8<-- "pages/a/snippets/part.py:usage"\n'

    assert check_snippet_orphans.included_files(markdown) == {"pages/a/snippets/full.py", "pages/a/snippets/part.py"}


def test_block_includes_count_every_line() -> None:
    markdown = (
        "```python\n--8<--\npages/web-ui/snippets/errors.py:imports\npages/web-ui/snippets/skew.py:check\n--8<--\n```\n"
    )

    assert check_snippet_orphans.included_files(markdown) == {
        "pages/web-ui/snippets/errors.py",
        "pages/web-ui/snippets/skew.py",
    }


def test_commented_out_block_line_is_not_an_include() -> None:
    markdown = "--8<--\npages/a/snippets/kept.py\n;pages/a/snippets/disabled.py\n--8<--\n"

    assert check_snippet_orphans.included_files(markdown) == {"pages/a/snippets/kept.py"}
