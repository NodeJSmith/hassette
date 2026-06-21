"""Characterization tests for tools/check_module_boundaries.py.

Pin the boundary rules in ``RULES`` (test_utils-isolation, api-no-core,
utils-no-events, web-no-core, bus-no-core): the governed layer must not import
the forbidden package at runtime, while type-only imports under
``TYPE_CHECKING`` and a layer importing itself are exempt. Still-ungoverned
cross-layer imports (e.g. ``state_manager → core``) are allowed.
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


def test_relative_import_of_test_utils_module_flagged() -> None:
    # ``from ..test_utils import x`` inside hassette.core resolves to hassette.test_utils.
    src = "from ..test_utils import build_fake_ws\n"
    assert check_source(src, "core", package="hassette.core") == [
        (
            1,
            "test_utils-isolation: imports hassette.test_utils — "
            "production code must not import test helpers from hassette.test_utils",
        )
    ]


def test_relative_bare_import_of_test_utils_flagged() -> None:
    # ``from .. import test_utils`` inside hassette.core: the alias is the submodule.
    src = "from .. import test_utils\n"
    assert check_source(src, "core", package="hassette.core") == [
        (
            1,
            "test_utils-isolation: imports hassette.test_utils — "
            "production code must not import test helpers from hassette.test_utils",
        )
    ]


def test_relative_import_to_sibling_test_utils_not_flagged() -> None:
    # ``from .test_utils import x`` resolves to hassette.core.test_utils, a different
    # package than the real hassette.test_utils — no false positive.
    src = "from .test_utils import x\n"
    assert check_source(src, "core", package="hassette.core") == []


def test_relative_import_above_root_not_flagged() -> None:
    # ``from ..test_utils import x`` from a single-component package climbs above the
    # root — invalid Python, so it resolves to nothing rather than a bogus match.
    src = "from ..test_utils import build_fake_ws\n"
    assert check_source(src, "core", package="hassette") == []


def test_relative_import_skipped_without_package() -> None:
    # With no package to anchor resolution, relative imports can't be resolved and
    # are skipped rather than guessed at.
    src = "from ..test_utils import build_fake_ws\n"
    assert check_source(src, "core") == []


def test_state_manager_import_of_core_not_yet_governed() -> None:
    # state_manager → core is a still-ungoverned cross-layer import (tracked under
    # #1079); until a rule governs it, the checker returns no violation.
    src = "from hassette.core.state_proxy import StateProxy\n"
    assert check_source(src, "state_manager") == []


def test_bus_import_of_core_flagged() -> None:
    src = "from hassette.core import Hassette\n"
    assert check_source(src, "bus") == [
        (
            1,
            "bus-no-core: imports hassette.core — "
            "bus must not import core at runtime; core sits above the service layer (#1089)",
        )
    ]


def test_bus_import_of_core_submodule_flagged() -> None:
    # A submodule import must be flagged too, not just a bare ``hassette.core``
    # import — the two are matched by different parts of the rule, so both are tested.
    src = "from hassette.core.logging_service import LoggingService\n"
    assert check_source(src, "bus") == [
        (
            1,
            "bus-no-core: imports hassette.core.logging_service — "
            "bus must not import core at runtime; core sits above the service layer (#1089)",
        )
    ]


def test_bus_type_checking_core_import_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from hassette.core import Hassette
        """
    )
    assert check_source(src, "bus") == []


def test_non_hassette_import_ignored() -> None:
    assert check_source("import os\nfrom collections import abc\n", "core") == []


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_src_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
