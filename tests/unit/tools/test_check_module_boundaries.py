"""Characterization tests for tools/check_module_boundaries.py.

Pin the boundary rules in ``RULES`` (test_utils-isolation, api-no-core,
utils-no-events, web-no-core, bus-no-core): the governed layer must not import
the forbidden package at runtime, while type-only imports under
``TYPE_CHECKING`` and a layer importing itself are exempt. Still-ungoverned
cross-layer imports (e.g. ``state_manager → core``) are allowed.

Also pin the private-attr reach-through rule (#1091): ``hassette._foo`` /
``self.hassette._foo`` is flagged outside ``core/`` and ``test_utils/``, own-private
``self._foo`` and non-private/dunder access are not, and ``PRIVATE_ATTR_ALLOWLIST``
entries are suppressed by (path, attr).
"""

import textwrap
from pathlib import Path

import pytest
from check_module_boundaries import PRIVATE_ATTR_MSG_TEMPLATE, check_file, check_source, iter_paths


def reach_through_msg(attr: str) -> str:
    return PRIVATE_ATTR_MSG_TEMPLATE.format(attr=attr)


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


def test_bare_hassette_private_access_flagged() -> None:
    src = "x = hassette._scheduler_service\n"
    assert check_source(src, "scheduler") == [(1, reach_through_msg("_scheduler_service"))]


def test_self_hassette_private_access_flagged() -> None:
    # The common shape: a resource reaching through its `self.hassette` reference.
    src = "x = self.hassette._bus_service\n"
    assert check_source(src, "bus") == [(1, reach_through_msg("_bus_service"))]


def test_own_private_access_not_flagged() -> None:
    # `self._foo` is ordinary intra-object privacy, not a reach-through into the core object.
    assert check_source("x = self._bus_service\n", "bus") == []


def test_non_private_hassette_attr_not_flagged() -> None:
    assert check_source("x = self.hassette.config\n", "bus") == []


def test_dunder_hassette_attr_not_flagged() -> None:
    # Dunder/mangled access is not the single-underscore reach-through the rule targets.
    assert check_source("x = hassette.__class__\n", "bus") == []


def test_private_access_in_core_exempt() -> None:
    # core owns Hassette; reading its private slots there is not a reach-through.
    assert check_source("x = self.hassette._state_proxy\n", "core") == []


def test_private_access_in_test_utils_exempt() -> None:
    # The test harness assembles real components from private slots — that is its job.
    assert check_source("x = hassette._loop_thread_id\n", "test_utils") == []


def test_allowlisted_path_attr_suppressed() -> None:
    src = "x = self.hassette._should_skip_dependency_check()\n"
    assert check_source(src, "resources", rel_path="resources/base.py") == []


def test_allowlist_scoped_to_path() -> None:
    # The same attr in a different file is still flagged — the allowlist is (path, attr)-scoped.
    src = "x = self.hassette._should_skip_dependency_check()\n"
    assert check_source(src, "resources", rel_path="resources/other.py") == [
        (1, reach_through_msg("_should_skip_dependency_check"))
    ]


def test_allowlist_not_consulted_without_rel_path() -> None:
    # With no rel_path, nothing can be allowlisted, so even allowlisted content is flagged.
    # This pins the "flag by default" semantics so they can't drift silently.
    src = "x = self.hassette._bus_service\n"
    assert check_source(src, "bus") == [(1, reach_through_msg("_bus_service"))]


def test_chained_private_access_flagged_once() -> None:
    # `hassette._state_proxy.states` — only the private hop is flagged, not the trailing `.states`.
    src = "x = self.hassette._state_proxy.states\n"
    assert check_source(src, "state_manager") == [(1, reach_through_msg("_state_proxy"))]


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_src_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
