"""Regression tests for bulk listener removal against a sealed task bucket (#1810).

``Listener.cancel()`` spawns ``release_guard()`` onto the listener's own task bucket. A
force-terminal teardown seals that bucket without running shutdown hooks, so a later removal
of the stale listeners used to hit ``TaskBucket.spawn()``'s sealed-bucket ``RuntimeError``.
That raise aborted ``remove_listeners_by_owner``'s loop part-way: the routes were already
cleared, but the remaining listeners were left uncancelled with their removal callbacks
unfired. ``cancel()`` now skips the spawn with a debug log instead.
"""

from unittest.mock import MagicMock

from tests.support.helpers import create_listener, make_task_bucket

from .conftest import make_bus_service

OWNER = "sealed_owner"


def make_sealed_bucket() -> MagicMock:
    """A task bucket that reports itself sealed and raises if anything is spawned on it."""
    bucket = make_task_bucket()
    bucket.is_sealed = True
    bucket.spawn = MagicMock(side_effect=RuntimeError("cannot spawn on a sealed bucket"))
    return bucket


class TestRemoveListenersByOwnerWithSealedBucket:
    async def test_cancel_does_not_raise_on_sealed_bucket(self) -> None:
        """Listener.cancel() must never raise out — the bulk-removal loop depends on it."""
        listener = create_listener(owner_id=OWNER, task_bucket=make_sealed_bucket())

        listener.cancel()

        assert listener.is_cancelled is True
        listener.invoker.task_bucket.spawn.assert_not_called()

    async def test_remove_listeners_by_owner_completes_full_loop(self) -> None:
        """Every listener is cancelled and every removal callback fires despite the seal."""
        svc = make_bus_service()
        svc._removal_callbacks = {}
        listeners = [
            create_listener(owner_id=OWNER, topic=f"state_changed.light.l{i}", task_bucket=make_sealed_bucket())
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
