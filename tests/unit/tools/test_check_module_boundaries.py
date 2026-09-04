"""Characterization tests for tools/check_module_boundaries.py.

Pin the boundary rules in ``RULES`` (test-helpers-isolation, api-no-core,
utils-no-events, web-no-core, bus-no-core, resources-no-task_bucket,
scheduler-no-core, state_manager-no-core, bus-no-ha-events): the governed layer must not import
the forbidden package at runtime, while type-only imports under ``TYPE_CHECKING``
and a layer importing itself are exempt.

Also pin the private-attr reach-through rule (#1091): ``hassette._foo`` /
``self.hassette._foo`` is flagged outside ``core/`` and ``testing/``, own-private
``self._foo`` and non-private/dunder access are not, and ``PRIVATE_ATTR_ALLOWLIST``
entries are suppressed by (path, attr). Ungoverned cross-layer imports still exist
(e.g. ``conversion`` → ``models``, #892) but are not tested here.

Also pins the ``testing-isolation`` rule (#1333): ``hassette.testing`` must never import
``tests.support`` at runtime — the one-way dependency that keeps ``hassette.testing`` importable
from an installed wheel where ``tests/support/`` does not exist.
"""

import textwrap

from check_module_boundaries import PRIVATE_ATTR_MSG_TEMPLATE, check_source


def reach_through_msg(attr: str) -> str:
    return PRIVATE_ATTR_MSG_TEMPLATE.format(attr=attr)


def test_production_import_of_testing_flagged() -> None:
    src = "from hassette.testing import build_fake_ws\n"
    assert check_source(src, "core") == [
        (
            1,
            "test-helpers-isolation: imports hassette.testing — "
            "production code must not import test helpers from hassette.testing",
        )
    ]


def test_submodule_import_flagged() -> None:
    src = "import hassette.testing.ws_mocks\n"
    assert check_source(src, "bus") == [
        (
            1,
            "test-helpers-isolation: imports hassette.testing.ws_mocks — "
            "production code must not import test helpers from hassette.testing",
        )
    ]


def test_testing_importing_itself_not_flagged() -> None:
    src = "from hassette.testing.helpers import wire_up\n"
    assert check_source(src, "testing") == []


def test_bare_hassette_import_of_testing_flagged() -> None:
    # ``from hassette import testing`` records "hassette" as the module — the
    # imported alias is the real boundary target and must still be flagged.
    src = "from hassette import testing\n"
    assert check_source(src, "core") == [
        (
            1,
            "test-helpers-isolation: imports hassette.testing — "
            "production code must not import test helpers from hassette.testing",
        )
    ]


def test_type_checking_import_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from hassette.testing import RecordingApi
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
            from hassette.testing import build_fake_ws
        """
    )
    assert check_source(src, "core") == [
        (
            6,
            "test-helpers-isolation: imports hassette.testing — "
            "production code must not import test helpers from hassette.testing",
        )
    ]


def test_relative_import_of_testing_module_flagged() -> None:
    # ``from ..testing import x`` inside hassette.core resolves to hassette.testing.
    src = "from ..testing import build_fake_ws\n"
    assert check_source(src, "core", package="hassette.core") == [
        (
            1,
            "test-helpers-isolation: imports hassette.testing — "
            "production code must not import test helpers from hassette.testing",
        )
    ]


def test_relative_bare_import_of_testing_flagged() -> None:
    # ``from .. import testing`` inside hassette.core: the alias is the submodule.
    src = "from .. import testing\n"
    assert check_source(src, "core", package="hassette.core") == [
        (
            1,
            "test-helpers-isolation: imports hassette.testing — "
            "production code must not import test helpers from hassette.testing",
        )
    ]


def test_relative_import_to_sibling_testing_not_flagged() -> None:
    # ``from .testing import x`` resolves to hassette.core.testing, a different
    # package than the real hassette.testing — no false positive.
    src = "from .testing import x\n"
    assert check_source(src, "core", package="hassette.core") == []


def test_relative_import_above_root_not_flagged() -> None:
    # ``from ..testing import x`` from a single-component package climbs above the
    # root — invalid Python, so it resolves to nothing rather than a bogus match.
    src = "from ..testing import build_fake_ws\n"
    assert check_source(src, "core", package="hassette") == []


def test_relative_import_skipped_without_package() -> None:
    # With no package to anchor resolution, relative imports can't be resolved and
    # are skipped rather than guessed at.
    src = "from ..testing import build_fake_ws\n"
    assert check_source(src, "core") == []


def test_state_manager_import_of_core_flagged() -> None:
    src = "from hassette.core.state_proxy import StateProxy\n"
    assert check_source(src, "state_manager") == [
        (
            1,
            "state_manager-no-core: imports hassette.core.state_proxy — "
            "state_manager must not import core at runtime; StateProxy is consumed via StateReader (#1079)",
        )
    ]


def test_state_manager_import_of_core_submodule_flagged() -> None:
    src = "from hassette.core import Hassette\n"
    assert check_source(src, "state_manager") == [
        (
            1,
            "state_manager-no-core: imports hassette.core — "
            "state_manager must not import core at runtime; StateProxy is consumed via StateReader (#1079)",
        )
    ]


def test_state_manager_type_checking_core_import_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from hassette.core.state_proxy import StateProxy
        """
    )
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


def test_resources_import_of_task_bucket_flagged() -> None:
    src = "from hassette.task_bucket import TaskBucket\n"
    assert check_source(src, "resources") == [
        (
            1,
            "resources-no-task_bucket: imports hassette.task_bucket — "
            "resources sits below task_bucket; TaskBucket is injected via register_task_bucket_factory (#1079)",
        )
    ]


def test_resources_import_of_task_bucket_submodule_flagged() -> None:
    src = "from hassette.task_bucket.task_bucket import TaskBucket\n"
    assert check_source(src, "resources") == [
        (
            1,
            "resources-no-task_bucket: imports hassette.task_bucket.task_bucket — "
            "resources sits below task_bucket; TaskBucket is injected via register_task_bucket_factory (#1079)",
        )
    ]


def test_resources_type_checking_task_bucket_import_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from hassette.task_bucket import TaskBucket
        """
    )
    assert check_source(src, "resources") == []


def test_scheduler_import_of_core_flagged() -> None:
    src = "from hassette.core import Hassette\n"
    assert check_source(src, "scheduler") == [
        (
            1,
            "scheduler-no-core: imports hassette.core — "
            "scheduler must not runtime-import core; SchedulerService consumed via SchedulerServiceProtocol (#1079)",
        )
    ]


def test_scheduler_import_of_core_submodule_flagged() -> None:
    src = "from hassette.core.scheduler_service import SchedulerService\n"
    assert check_source(src, "scheduler") == [
        (
            1,
            "scheduler-no-core: imports hassette.core.scheduler_service — "
            "scheduler must not runtime-import core; SchedulerService consumed via SchedulerServiceProtocol (#1079)",
        )
    ]


def test_scheduler_type_checking_core_import_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from hassette.core.scheduler_service import SchedulerService
        """
    )
    assert check_source(src, "scheduler") == []


def test_bus_import_of_ha_events_flagged() -> None:
    src = "from hassette.events.hass.hass import RawStateChangeEvent\n"
    assert check_source(src, "bus") == [
        (
            1,
            "bus-no-ha-events: imports hassette.events.hass.hass — "
            "bus is a generic pub/sub kernel; HA event types are injected from core (#1136)",
        )
    ]


def test_bus_import_of_ha_events_submodule_flagged() -> None:
    src = "from hassette.events.hass.raw import HassStateDict\n"
    assert check_source(src, "bus") == [
        (
            1,
            "bus-no-ha-events: imports hassette.events.hass.raw — "
            "bus is a generic pub/sub kernel; HA event types are injected from core (#1136)",
        )
    ]


def test_bus_type_checking_ha_events_import_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from hassette.events.hass.raw import HassStateDict
        """
    )
    assert check_source(src, "bus") == []


def test_bus_import_of_base_events_not_flagged() -> None:
    """Bus may import generic event types from hassette.events and hassette.events.base."""
    src = "from hassette.events.base import Event\n"
    assert check_source(src, "bus") == []


def test_testing_import_of_tests_support_flagged() -> None:
    src = "from tests.support.factories import make_scheduled_job\n"
    assert check_source(src, "testing") == [
        (
            1,
            "testing-isolation: imports tests.support.factories — "
            "hassette.testing must not import tests.support (one-way dependency, #1333)",
        )
    ]


def test_testing_bare_import_of_tests_support_flagged() -> None:
    src = "import tests.support.helpers\n"
    assert check_source(src, "testing") == [
        (
            1,
            "testing-isolation: imports tests.support.helpers — "
            "hassette.testing must not import tests.support (one-way dependency, #1333)",
        )
    ]


def test_testing_import_of_bare_tests_support_flagged() -> None:
    src = "from tests.support import factories\n"
    assert check_source(src, "testing") == [
        (
            1,
            "testing-isolation: imports tests.support — "
            "hassette.testing must not import tests.support (one-way dependency, #1333)",
        )
    ]


def test_testing_bare_parent_import_of_tests_support_flagged() -> None:
    # ``from tests import support`` — the bare-parent form, analogous to ``from hassette
    # import testing`` in runtime_imports() — must be caught even though ``node.module``
    # resolves to ``"tests"``, not ``"tests.support"``.
    src = "from tests import support\n"
    assert check_source(src, "testing") == [
        (
            1,
            "testing-isolation: imports tests.support — "
            "hassette.testing must not import tests.support (one-way dependency, #1333)",
        )
    ]


def test_testing_dynamic_import_module_literal_flagged() -> None:
    # importlib.import_module("tests.support...") bypasses every static import/from form —
    # runtime_imports()'s dynamic-import handling must still catch it (#1333 "no escape hatch").
    src = textwrap.dedent(
        """\
        import importlib

        def f():
            importlib.import_module("tests.support.mock_hassette")
        """
    )
    assert check_source(src, "testing") == [
        (
            4,
            "testing-isolation: imports tests.support.mock_hassette — "
            "hassette.testing must not import tests.support (one-way dependency, #1333)",
        )
    ]


def test_testing_dynamic_bare_import_literal_flagged() -> None:
    # Bare __import__("tests.support...") is the same escape hatch as importlib.import_module.
    src = textwrap.dedent(
        """\
        def f():
            __import__("tests.support.mock_hassette")
        """
    )
    assert check_source(src, "testing") == [
        (
            2,
            "testing-isolation: imports tests.support.mock_hassette — "
            "hassette.testing must not import tests.support (one-way dependency, #1333)",
        )
    ]


def test_testing_dynamic_import_bound_name_flagged() -> None:
    # `from importlib import import_module` then calling the bound name has an ast.Name
    # callee, not the ast.Attribute form `importlib.import_module(...)` matches — this is
    # the same escape hatch, just via a different import form (PR #1881 review finding).
    src = textwrap.dedent(
        """\
        from importlib import import_module

        def f():
            import_module("tests.support.mock_hassette")
        """
    )
    assert check_source(src, "testing") == [
        (
            4,
            "testing-isolation: imports tests.support.mock_hassette — "
            "hassette.testing must not import tests.support (one-way dependency, #1333)",
        )
    ]


def test_testing_dynamic_import_non_literal_arg_not_flagged() -> None:
    # A dynamic import whose target isn't a string literal can't be resolved statically —
    # not a false positive, just outside what an AST walker can verify.
    src = textwrap.dedent(
        """\
        import importlib

        def f(mod_name):
            importlib.import_module(mod_name)
        """
    )
    assert check_source(src, "testing") == []


def test_testing_isolation_type_checking_exempt() -> None:
    src = textwrap.dedent(
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from tests.support.factories import make_scheduled_job
        """
    )
    assert check_source(src, "testing") == []


def test_testing_import_of_private_module_not_flagged() -> None:
    # hassette.testing importing its own private submodules is fine.
    src = "from hassette.testing._factories import make_state_dict\n"
    assert check_source(src, "testing") == []


def test_testing_isolation_not_applied_outside_testing_layer() -> None:
    # tests.support imports are only forbidden inside hassette.testing itself.
    src = "from tests.support.factories import make_scheduled_job\n"
    assert check_source(src, "core") == []
