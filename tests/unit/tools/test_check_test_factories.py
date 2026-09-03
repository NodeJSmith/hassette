"""Characterization tests for tools/check_test_factories.py.

Pin which local factory definitions the guard flags as shadowing a shared
factory, and which it leaves alone (no registry match, or exempted via
'# factory-local:').
"""

from collections.abc import Callable
from pathlib import Path

import check_test_factories
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
        "Local 'make_mock_event()' shadows shared factory — use 'from tests.support.factories import make_mock_event'"
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
    assert message == ("Local 'noop()' shadows shared factory — use 'from tests.support.helpers import noop'")


def test_async_def_exempted_not_flagged(write_sample: Callable[[str], Path]) -> None:
    path = write_sample(
        """\
        async def noop():  # factory-local: sync-facade helper needs a real coroutine
            pass
        """
    )
    assert check_file(path) == []


def test_class_method_shadow_not_flagged(write_sample: Callable[[str], Path]) -> None:
    """A class method sharing a registry name is not a top-level shadow -- it isn't importable
    as a drop-in replacement for the shared factory, so it carries none of the duplication risk
    this guard exists to catch.
    """
    path = write_sample(
        """\
        class Helper:
            def make_manifest(self):
                return None
        """
    )
    assert check_file(path) == []


def test_nested_function_shadow_not_flagged(write_sample: Callable[[str], Path]) -> None:
    """A closure nested inside another function is scoped to its enclosing call, not a
    module-level duplicate of the shared factory.
    """
    path = write_sample(
        """\
        def outer():
            def noop():
                pass
            return noop
        """
    )
    assert check_file(path) == []


def test_conditional_def_shadow_flagged(write_sample: Callable[[str], Path]) -> None:
    """A def inside an if/try/with block is still bound at module level -- and just as
    importable as a bare top-level def -- so it must still be flagged.
    """
    path = write_sample(
        """\
        if True:
            def make_execution_record():
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


def test_canonical_definition_not_flagged_as_self_shadow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A factory def written to the file SHARED_FACTORIES names as its own canonical module is
    not flagged as shadowing itself. Uses a fabricated repo root (monkeypatched REPO_ROOT)
    rather than tmp_path directly, since ``_dotted_module_path`` returns None -- and every def
    is treated as a shadow candidate -- for paths outside REPO_ROOT.
    """
    monkeypatch.setattr(check_test_factories, "REPO_ROOT", tmp_path)
    canonical = tmp_path / "tests" / "support" / "factories.py"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("def make_scheduled_job():\n    return None\n")

    assert check_file(canonical) == []


def test_same_name_in_different_file_still_flagged_as_shadow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The same factory name defined outside its canonical module is still a shadow, even
    though both files resolve under the same fabricated REPO_ROOT -- self-exemption only
    suppresses the canonical module's own definition, not any file sharing the def name.
    """
    monkeypatch.setattr(check_test_factories, "REPO_ROOT", tmp_path)
    other = tmp_path / "tests" / "unit" / "test_something.py"
    other.parent.mkdir(parents=True)
    other.write_text("def make_scheduled_job():\n    return None\n")

    violations = check_file(other)
    assert len(violations) == 1
    lineno, message = violations[0]
    assert lineno == 1
    assert message == (
        "Local 'make_scheduled_job()' shadows shared factory — "
        "use 'from tests.support.factories import make_scheduled_job'"
    )


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_repo_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
