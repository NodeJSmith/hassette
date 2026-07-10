"""Characterization tests for tools/check_test_factories.py.

Pin which local factory definitions the guard flags as shadowing a shared
factory, and which it leaves alone (no registry match, or exempted via
'# factory-local:').
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_test_factories import check_file, iter_paths


def test_local_factory_shadows_shared_flagged(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        def make_mock_event():
            return None
        """
    )
    violations = check_file(path)
    assert len(violations) == 1
    lineno, message = violations[0]
    assert lineno == 1
    assert message == (
        "Local 'make_mock_event()' shadows shared factory — "
        "use 'from hassette.test_utils.factories import make_mock_event'"
    )


def test_local_factory_no_shared_counterpart_not_flagged(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        def make_special_widget():
            return None
        """
    )
    assert check_file(path) == []


def test_exempted_local_factory_not_flagged(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        def make_mock_event():  # factory-local: returns SimpleNamespace
            return None
        """
    )
    assert check_file(path) == []


def test_empty_annotation_does_not_exempt(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        def make_mock_event():  # factory-local:
            return None
        """
    )
    assert len(check_file(path)) == 1


def test_async_def_flagged(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        async def noop():
            pass
        """
    )
    violations = check_file(path)
    assert len(violations) == 1
    lineno, message = violations[0]
    assert lineno == 1
    assert message == ("Local 'noop()' shadows shared factory — use 'from hassette.test_utils.helpers import noop'")


def test_async_def_exempted_not_flagged(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        async def noop():  # factory-local: sync-facade helper needs a real coroutine
            pass
        """
    )
    assert check_file(path) == []


def test_nested_method_shadow_flagged(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        class Helper:
            def make_manifest(self):
                return None
        """
    )
    violations = check_file(path)
    assert len(violations) == 1
    assert violations[0][0] == 2


def test_annotation_must_be_on_def_line_not_preceding_comment(write_sample: Callable[[str], Path]) -> None:
    # Unlike the lazy-import guard, this one only checks the def's own line —
    # a preceding comment-only line does not exempt.
    path = write_sample(
        """\
        # factory-local: not on the def line
        def make_mock_event():
            return None
        """
    )
    assert len(check_file(path)) == 1


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_repo_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
