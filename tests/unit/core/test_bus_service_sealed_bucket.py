"""Regression tests for bulk listener removal against a sealed task bucket (#1810).

``Listener.cancel()`` spawns ``release_guard()`` onto the listener's own task bucket. A
force-terminal teardown seals that bucket without running shutdown hooks, so a later removal
of the stale listeners used to hit ``TaskBucket.spawn()``'s sealed-bucket ``RuntimeError``.
That raise aborted ``remove_listeners_by_owner``'s loop part-way: the routes were already
cleared, but the remaining listeners were left uncancelled with their removal callbacks
unfired. ``cancel()`` now absorbs ``TaskBucketSealedError`` with a debug log instead.

The rejection is caught at the spawn boundary rather than pre-checked via ``is_sealed``: a
sync handler on a worker thread can observe an open bucket and still be rejected when the
loop thread seals it before the cross-thread spawn lands.
"""

import pytest

from tests.support.helpers import create_listener, make_rejecting_task_bucket

from .conftest import make_bus_service

OWNER = "sealed_owner"


class TestRemoveListenersByOwnerWithSealedBucket:
    async def test_cancel_does_not_raise_on_sealed_bucket(self) -> None:
        """Listener.cancel() must never raise out — the bulk-removal loop depends on it."""
        listener = create_listener(owner_id=OWNER, task_bucket=make_rejecting_task_bucket())

        listener.cancel()

        assert listener.is_cancelled is True
        listener.invoker.task_bucket.spawn.assert_called_once()

    async def test_remove_listeners_by_owner_completes_full_loop(self) -> None:
        """Every listener is cancelled and every removal callback fires despite the seal."""
        svc = make_bus_service()
        svc._removal_callbacks = {}
        listeners = [
            create_listener(owner_id=OWNER, topic=f"state_changed.light.l{i}", task_bucket=make_rejecting_task_bucket())
            for i in range(3)
        ]
        for listener in listeners:
            svc.router.add_route(listener.topic, listener)

        fired: list[int] = []
        svc.register_removal_callback(OWNER, lambda listener: fired.append(listener.listener_id))

        svc.remove_listeners_by_owner(OWNER)

        assert all(listener.is_cancelled for listener in listeners), "every listener must be cancelled"
        assert fired == [listener.listener_id for listener in listeners], "every callback must fire"
        assert svc.router.get_listeners_by_owner(OWNER) == []

    async def test_cancel_still_propagates_unrelated_spawn_failures(self) -> None:
        """Only the sealed rejection is absorbed — other spawn failures must surface."""
        bucket = make_rejecting_task_bucket(RuntimeError("loop is congested"))
        listener = create_listener(owner_id=OWNER, task_bucket=bucket)

        with pytest.raises(RuntimeError, match="congested"):
            listener.cancel()
