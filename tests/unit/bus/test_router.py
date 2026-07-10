"""Unit tests for the Router class (extracted to hassette.bus.router)."""

import importlib.util
import pathlib

from hassette.bus.router import Router
from hassette.test_utils.helpers import create_listener


class TestRouterImport:
    def test_router_importable_from_bus_router(self) -> None:
        """Router is importable from hassette.bus.router."""
        assert Router is not None

    def test_router_has_no_core_imports(self) -> None:
        """router.py has zero imports from hassette.core or any service-layer module."""
        spec = importlib.util.find_spec("hassette.bus.router")
        assert spec is not None
        assert spec.origin is not None
        source = pathlib.Path(spec.origin).read_text()

        assert "hassette.core" not in source, "router.py must not import from hassette.core"
        assert "bus_service" not in source, "router.py must not import from bus_service"


class TestRouterAddRouteExactMatch:
    def test_add_route_exact_match_found(self) -> None:
        """add_route + get_topic_listeners returns listener for exact topic match."""
        router = Router()
        listener = create_listener(topic="state_changed")

        router.add_route("state_changed", listener)
        result = router.get_topic_listeners("state_changed")

        assert listener in result

    def test_add_route_exact_match_not_found_for_different_topic(self) -> None:
        """Exact-match listener is not returned for a different topic."""
        router = Router()
        listener = create_listener(topic="state_changed")

        router.add_route("state_changed", listener)
        result = router.get_topic_listeners("call_service")

        assert listener not in result

    def test_add_route_multiple_listeners_same_topic(self) -> None:
        """Multiple listeners on the same topic are all returned."""
        router = Router()
        l1 = create_listener(topic="state_changed", owner_id="owner1")
        l2 = create_listener(topic="state_changed", owner_id="owner2")

        router.add_route("state_changed", l1)
        router.add_route("state_changed", l2)
        result = router.get_topic_listeners("state_changed")

        assert l1 in result
        assert l2 in result


class TestRouterGlobMatch:
    def test_add_route_glob_match_wildcard(self) -> None:
        """Glob pattern matches topic with wildcard."""
        router = Router()
        listener = create_listener(topic="state_changed/*")

        router.add_route("state_changed/*", listener)
        result = router.get_topic_listeners("state_changed/light.kitchen")

        assert listener in result

    def test_add_route_glob_match_question_mark(self) -> None:
        """Glob pattern with ? wildcard matches single character."""
        router = Router()
        listener = create_listener(topic="light.?itchen")

        router.add_route("light.?itchen", listener)
        result = router.get_topic_listeners("light.kitchen")

        assert listener in result

    def test_add_route_glob_does_not_match_non_matching_topic(self) -> None:
        """Glob pattern does not match non-matching topic."""
        router = Router()
        listener = create_listener(topic="state_changed/*")

        router.add_route("state_changed/*", listener)
        result = router.get_topic_listeners("call_service/light.kitchen")

        assert listener not in result

    def test_glob_listener_stored_in_globs_bucket(self) -> None:
        """Glob topic is stored in the globs bucket, not exact."""
        router = Router()
        listener = create_listener(topic="*")

        router.add_route("*", listener)

        assert "*" in router.globs
        assert "*" not in router.exact


class TestRouterPriority:
    def test_get_topic_listeners_sorted_by_priority_descending(self) -> None:
        """get_topic_listeners returns listeners sorted by priority highest-first."""
        router = Router()
        low = create_listener(topic="state_changed", owner_id="low", priority=0)
        high = create_listener(topic="state_changed", owner_id="high", priority=10)
        medium = create_listener(topic="state_changed", owner_id="medium", priority=5)

        router.add_route("state_changed", low)
        router.add_route("state_changed", high)
        router.add_route("state_changed", medium)
        result = router.get_topic_listeners("state_changed")

        assert result[0] is high
        assert result[1] is medium
        assert result[2] is low


class TestRouterRemoveListenerById:
    def test_remove_listener_by_id_removes_target(self) -> None:
        """remove_listener_by_id removes the specified listener by ID."""
        router = Router()
        listener = create_listener(topic="state_changed")

        router.add_route("state_changed", listener)
        router.remove_listener_by_id("state_changed", listener.listener_id)
        result = router.get_topic_listeners("state_changed")

        assert listener not in result

    def test_remove_listener_by_id_leaves_other_listeners(self) -> None:
        """remove_listener_by_id only removes the targeted listener."""
        router = Router()
        l1 = create_listener(topic="state_changed", owner_id="owner1")
        l2 = create_listener(topic="state_changed", owner_id="owner2")

        router.add_route("state_changed", l1)
        router.add_route("state_changed", l2)
        router.remove_listener_by_id("state_changed", l1.listener_id)
        result = router.get_topic_listeners("state_changed")

        assert l1 not in result
        assert l2 in result

    def test_remove_listener_by_id_nonexistent_id_is_noop(self) -> None:
        """remove_listener_by_id with a non-existent ID does not raise."""
        router = Router()
        listener = create_listener(topic="state_changed")

        router.add_route("state_changed", listener)
        router.remove_listener_by_id("state_changed", 99999)
        result = router.get_topic_listeners("state_changed")

        assert listener in result

    def test_remove_listener_by_id_cleans_owner_index(self) -> None:
        """Removing a listener also removes it from the owner index."""
        router = Router()
        listener = create_listener(topic="state_changed", owner_id="owner1")

        router.add_route("state_changed", listener)
        router.remove_listener_by_id("state_changed", listener.listener_id)
        owner_listeners = router.get_listeners_by_owner("owner1")

        assert listener not in owner_listeners


class TestRouterClearOwner:
    def test_clear_owner_removes_all_owner_listeners(self) -> None:
        """clear_owner removes all listeners for the given owner."""
        router = Router()
        l1 = create_listener(topic="state_changed", owner_id="owner1")
        l2 = create_listener(topic="call_service", owner_id="owner1")

        router.add_route("state_changed", l1)
        router.add_route("call_service", l2)
        removed = router.clear_owner("owner1")

        assert sorted([id(r) for r in removed]) == sorted([id(l1), id(l2)])
        assert router.get_topic_listeners("state_changed") == []
        assert router.get_topic_listeners("call_service") == []

    def test_clear_owner_leaves_other_owners(self) -> None:
        """clear_owner does not remove listeners for other owners."""
        router = Router()
        l1 = create_listener(topic="state_changed", owner_id="owner1")
        l2 = create_listener(topic="state_changed", owner_id="owner2")

        router.add_route("state_changed", l1)
        router.add_route("state_changed", l2)
        router.clear_owner("owner1")
        result = router.get_topic_listeners("state_changed")

        assert l1 not in result
        assert l2 in result

    def test_clear_owner_nonexistent_owner_returns_empty(self) -> None:
        """clear_owner with an unknown owner returns an empty list."""
        router = Router()
        removed = router.clear_owner("nonexistent")
        assert removed == []

    def test_clear_owner_removes_from_owners_index(self) -> None:
        """After clear_owner, get_listeners_by_owner returns empty list."""
        router = Router()
        listener = create_listener(topic="state_changed", owner_id="owner1")

        router.add_route("state_changed", listener)
        router.clear_owner("owner1")
        result = router.get_listeners_by_owner("owner1")

        assert result == []

    def test_clear_owner_glob_topic(self) -> None:
        """clear_owner also removes listeners with glob topics."""
        router = Router()
        listener = create_listener(topic="state_changed/*", owner_id="owner1")

        router.add_route("state_changed/*", listener)
        removed = router.clear_owner("owner1")

        assert listener in removed
        result = router.get_topic_listeners("state_changed/light.kitchen")
        assert listener not in result


class TestRouterGetListenersByOwner:
    def test_get_listeners_by_owner_returns_added_listeners(self) -> None:
        """get_listeners_by_owner returns listeners added for the given owner."""
        router = Router()
        l1 = create_listener(topic="state_changed", owner_id="owner1")
        l2 = create_listener(topic="call_service", owner_id="owner1")

        router.add_route("state_changed", l1)
        router.add_route("call_service", l2)
        result = router.get_listeners_by_owner("owner1")

        assert l1 in result
        assert l2 in result

    def test_get_listeners_by_owner_unknown_owner_returns_empty(self) -> None:
        """get_listeners_by_owner returns empty list for unknown owner."""
        router = Router()
        result = router.get_listeners_by_owner("no_such_owner")
        assert result == []

    def test_get_listeners_by_owner_does_not_return_other_owners(self) -> None:
        """get_listeners_by_owner is isolated by owner."""
        router = Router()
        l1 = create_listener(topic="state_changed", owner_id="owner1")
        l2 = create_listener(topic="state_changed", owner_id="owner2")

        router.add_route("state_changed", l1)
        router.add_route("state_changed", l2)
        result = router.get_listeners_by_owner("owner1")

        assert l1 in result
        assert l2 not in result
