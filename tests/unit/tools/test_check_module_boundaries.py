"""Characterization tests for tools/check_module_boundaries.py.

Pin the test_utils-isolation rule: production layers must not import the test
helper package at runtime, while type-only imports and test_utils itself are
exempt.
"""

import textwrap
from pathlib import Path

import pytest
from check_module_boundaries import check_file, check_source, iter_paths


def test_production_import_of_test_utils_flagged() -> None:
    src = "from hassette.test_utils import build_fake_ws\n"
    assert check_source(src, "core") == [
        (
            1,
            "test_utils-isolation: imports hassette.test_utils — "
            "production code must not import test helpers from hassette.test_utils",
        )
    ]


def test_submodule_import_flagged() -> None:
    src = "import hassette.test_utils.ws_mocks\n"
    assert check_source(src, "bus") == [
        (
            1,
            "test_utils-isolation: imports hassette.test_utils.ws_mocks — "
            "production code must not import test helpers from hassette.test_utils",
        )
    ]


def test_test_utils_importing_itself_not_flagged() -> None:
    src = "from hassette.test_utils.helpers import wire_up\n"
    assert check_source(src, "test_utils") == []


def test_bare_hassette_import_of_test_utils_flagged() -> None:
    # ``from hassette import test_utils`` records "hassette" as the module — the
    # imported alias is the real boundary target and must still be flagged.
    src = "from hassette import test_utils\n"
    assert check_source(src, "core") == [
        (
            1,
            "test_utils-isolation: imports hassette.test_utils — "
            "production code must not import test helpers from hassette.test_utils",
        )
    ]


def test_type_checking_import_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from hassette.test_utils import RecordingApi
        """
    )
    assert check_source(src, "core") == []


def test_runtime_import_in_type_checking_else_not_exempt() -> None:
    # Only the ``if TYPE_CHECKING`` body is exempt; the ``else`` runs at runtime.
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            pass
        else:
            from hassette.test_utils import build_fake_ws
        """
    )
    assert check_source(src, "core") == [
        (
            6,
            "test_utils-isolation: imports hassette.test_utils — "
            "production code must not import test helpers from hassette.test_utils",
        )
    ]


def test_other_cross_layer_imports_not_yet_governed() -> None:
    # Only test_utils isolation is enforced today; importing core is allowed.
    src = "from hassette.core import Hassette\n"
    assert check_source(src, "bus") == []


def test_non_hassette_import_ignored() -> None:
    assert check_source("import os\nfrom collections import abc\n", "core") == []


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_src_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
