"""Unit tests for hassette.test_utils.reset."""

import logging
import re

import pytest

from hassette.resources.teardown import TeardownCause, TeardownReport
from hassette.testing._reset import _reject_tree_if_active_or_reported, reset_hassette_lifecycle, reset_resource_flags
from tests.support.factories import make_mock_hassette
from tests.unit.resources.conftest import ConcreteResource


class TestRejectTreeIfActiveOrReported:
    def test_validates_whole_tree_before_reset_resource_flags_mutates_anything(self) -> None:
        """Regression: a descendant that fails validation deep in the tree must be caught by a
        full up-front tree walk before reset_resource_flags() clears anything -- not partway
        through that same recursive walk, after earlier siblings already had their
        shutdown_event cleared.

        Before the fix, reset_hassette_lifecycle() validated only the root up front and left
        reset_resource_flags() to validate (and mutate) each descendant one at a time in the
        same pass. A grandchild failing validation would raise only after the root and every
        earlier sibling had already been cleared, leaving the instance half-reset -- exactly
        what this module's docstrings say must never happen. This test exercises the two
        functions in the same order reset_hassette_lifecycle() now does: validate the whole
        tree first, then (separately) mutate.
        """
        hassette = make_mock_hassette(sealed=False)
        root = ConcreteResource(hassette)
        sibling = root.add_child(ConcreteResource)
        sibling.shutdown_event.set()
        child = root.add_child(ConcreteResource)
        grandchild = child.add_child(ConcreteResource)

        # Simulate a completed teardown attempt on the grandchild -- validation must refuse to
        # proceed anywhere in the tree once this is found, however deep it is.
        grandchild._teardown_report = TeardownReport(causes=(TeardownCause.FORCED_TERMINAL,))

        with pytest.raises(RuntimeError, match=re.escape(grandchild.unique_name)):
            _reject_tree_if_active_or_reported(root)

        # Validation alone must not have mutated anything, and reset_resource_flags() must
        # never be reached at all when validation fails -- the caller (reset_hassette_lifecycle)
        # only calls it after validation succeeds.
        assert sibling.shutdown_event.is_set(), "sibling shutdown_event must be untouched"

    def test_clean_tree_passes_validation_and_resets_normally(self) -> None:
        """Sanity check: a tree with no active or reported descendants passes validation, and
        reset_resource_flags() then clears every descendant's shutdown_event.
        """
        hassette = make_mock_hassette(sealed=False)
        root = ConcreteResource(hassette)
        child = root.add_child(ConcreteResource)
        child.shutdown_event.set()
        grandchild = child.add_child(ConcreteResource)
        grandchild.shutdown_event.set()

        _reject_tree_if_active_or_reported(root)
        reset_resource_flags(root)

        assert not child.shutdown_event.is_set()
        assert not grandchild.shutdown_event.is_set()


class TestResetHassetteLifecycleOriginalChildren:
    async def test_original_children_restore_happens_before_validation(self) -> None:
        """Regression: original_children must be restored BEFORE tree validation runs, not
        after -- a test that dynamically adds its own children (e.g. dummy services for a
        restart-budget scenario) relies on reset_hassette_lifecycle() discarding them via
        original_children. If validation ran first, a test-added child with a stored teardown
        report (a completely normal outcome for a dummy service exercised through a real
        restart/exhaustion cycle) would make reset_hassette_lifecycle() raise even though that
        child is about to be dropped from the tree entirely and its state is therefore
        irrelevant to whether reset can proceed.
        """
        hassette = make_mock_hassette(sealed=False)
        hassette._shutdown_task = None
        hassette._teardown_report = None
        # reset_hassette_lifecycle() calls mark_ready(hassette, ...), which logs via
        # resource.logger.debug(...). A plain AsyncMock's un-configured attribute chains are
        # themselves AsyncMock (unlike MagicMock, whose children default to MagicMock), so an
        # untouched `.logger` here would make that debug() call return an unawaited coroutine
        # instead of actually logging synchronously, like the real Resource logger it stands in
        # for.
        hassette.logger = logging.getLogger("test.fake_hassette")
        original_child = ConcreteResource(hassette)
        hassette.children.append(original_child)
        snapshot = list(hassette.children)

        # A test dynamically adds its own child with a completed (unsafe) teardown report --
        # e.g. a dummy service that exhausted its restart budget during the test body.
        test_added_child = ConcreteResource(hassette)
        test_added_child._teardown_report = TeardownReport(causes=(TeardownCause.FORCED_TERMINAL,))
        hassette.children.append(test_added_child)

        await reset_hassette_lifecycle(hassette, original_children=snapshot)

        assert hassette.children == [original_child], (
            "children must be restored to the original snapshot, dropping the test-added child"
        )
        assert not hassette.shutdown_event.is_set()

    async def test_original_child_still_validated(self) -> None:
        """A genuine original child (one that survives the original_children restore) with a
        stored teardown report must still block reset -- only test-added, about-to-be-discarded
        children are exempt.
        """
        hassette = make_mock_hassette(sealed=False)
        hassette._shutdown_task = None
        hassette._teardown_report = None
        original_child = ConcreteResource(hassette)
        original_child._teardown_report = TeardownReport(causes=(TeardownCause.FORCED_TERMINAL,))
        hassette.children.append(original_child)
        snapshot = list(hassette.children)

        with pytest.raises(RuntimeError, match=re.escape(original_child.unique_name)):
            await reset_hassette_lifecycle(hassette, original_children=snapshot)
