"""A Service's serve task starts only after its whole initialization body completes (spec 134 D1, D7)."""

import pytest
from hassette_wire import ResourceStatus

from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from tests.support.helpers import block_until_cancelled
from tests.support.mock_hassette import make_mock_hassette
from tests.unit.resources.conftest import wait_for_running


class SpawnOrderService(Service):
    """Service that records whether its serve task existed while after_initialize ran."""

    restart_spec = RestartSpec()
    serve = block_until_cancelled  # bound as instance method via the descriptor protocol
    serve_spawned_during_after_initialize: bool | None = None

    async def after_initialize(self) -> None:
        self.serve_spawned_during_after_initialize = self._serve_task is not None


class FailingAfterInitializeService(Service):
    restart_spec = RestartSpec()
    serve = block_until_cancelled  # bound as instance method via the descriptor protocol

    async def after_initialize(self) -> None:
        raise RuntimeError("after_initialize failed")


class FailingChild(Resource):
    async def on_initialize(self) -> None:
        raise RuntimeError("child failed")


async def test_serve_not_spawned_until_after_initialize_completes():
    svc = SpawnOrderService(make_mock_hassette(sealed=False))

    await svc.initialize()
    await wait_for_running(svc)

    assert svc.serve_spawned_during_after_initialize is False, "serve must start after after_initialize()"
    await svc.shutdown()


async def test_after_initialize_failure_never_starts_serve():
    svc = FailingAfterInitializeService(make_mock_hassette(sealed=False))

    with pytest.raises(RuntimeError, match="after_initialize failed"):
        await svc.initialize()

    assert svc._serve_task is None, "a failed initialization body must not start serve()"
    assert svc.status == ResourceStatus.FAILED
    await svc.shutdown()


async def test_child_initialization_failure_never_starts_serve():
    svc = SpawnOrderService(make_mock_hassette(sealed=False))
    svc.add_child(FailingChild)

    with pytest.raises(RuntimeError, match="child failed"):
        await svc.initialize()

    assert svc._serve_task is None, "a failed child initialization must not start the parent's serve()"
    assert svc.status != ResourceStatus.RUNNING
    await svc.shutdown()
