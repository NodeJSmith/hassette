"""Integration tests for resource dependency ordering."""

import asyncio
from typing import ClassVar

from hassette import Hassette
from hassette.resources.base import Resource


async def test_shutdown_order_is_reverse_init_order(hassette_instance: Hassette) -> None:
    """_ordered_children_for_shutdown returns instances in reverse _init_order type sequence."""
    shutdown_order: list[Resource] = hassette_instance._ordered_children_for_shutdown()
    init_order: list[type[Resource]] = hassette_instance._init_order

    type_to_instance = {type(c): c for c in hassette_instance.children}
    expected = [type_to_instance[t] for t in reversed(init_order) if t in type_to_instance]

    assert shutdown_order == expected, (
        f"Shutdown order types {[type(r).__name__ for r in shutdown_order]} "
        f"do not match reverse init order {[type(r).__name__ for r in expected]}"
    )


async def test_shutdown_order_covers_all_children(hassette_instance: Hassette) -> None:
    """_ordered_children_for_shutdown covers exactly the same set as children."""
    shutdown_order = hassette_instance._ordered_children_for_shutdown()
    assert set(shutdown_order) == set(hassette_instance.children), "Shutdown order must include every registered child"


async def test_shutdown_order_has_no_duplicates(hassette_instance: Hassette) -> None:
    """_ordered_children_for_shutdown contains each child instance at most once."""
    shutdown_order = hassette_instance._ordered_children_for_shutdown()
    assert len(shutdown_order) == len({id(r) for r in shutdown_order}), "Shutdown order must not contain duplicates"


# ---------------------------------------------------------------------------
# Gate-pattern: auto-wait runtime behavior
# ---------------------------------------------------------------------------


async def test_service_with_depends_on_waits_for_dep(hassette_instance: Hassette) -> None:
    """A service with depends_on does not proceed to on_initialize until its dep is ready.

    Uses asyncio.Event gate pattern (per CLAUDE.md regression test patterns).
    GatedDep is registered as a child of hassette_instance so that
    _auto_wait_dependencies finds it via the real children lookup.
    """

    class _GatedDep(Resource):
        """Dependency whose readiness is manually controlled by the test."""

        async def on_initialize(self) -> None:
            pass

    class _DependentService(Resource):
        """Declares a dependency on _GatedDep."""

        depends_on: ClassVar[list[type[Resource]]] = [_GatedDep]
        initialized: ClassVar[asyncio.Event]

        async def on_initialize(self) -> None:
            _DependentService.initialized.set()

    _DependentService.initialized = asyncio.Event()

    # Register both stubs as children of the real Hassette instance so that
    # _auto_wait_dependencies can find _GatedDep in hassette_instance.children.
    gated = hassette_instance.add_child(_GatedDep)
    dependent = hassette_instance.add_child(_DependentService)

    # Start the dependent service — it must block on _GatedDep.ready_event.
    task = asyncio.create_task(dependent.initialize())
    await asyncio.sleep(0)  # yield to let the task run until it blocks on the gate

    assert not _DependentService.initialized.is_set(), "on_initialize must not run before dependency is ready"
    assert not task.done(), "initialize() task must still be waiting for the gate"

    # Release the gate — mark the dependency ready.
    gated.mark_ready("test: gate released")

    await asyncio.wait_for(task, timeout=2.0)

    assert _DependentService.initialized.is_set(), "on_initialize must have run after dependency became ready"


async def test_service_without_depends_on_proceeds_immediately(hassette_instance: Hassette) -> None:
    """A service with no depends_on proceeds to on_initialize without any blocking."""

    class _NoDepsService(Resource):
        """Declares no dependencies; must initialize without waiting."""

        initialized: ClassVar[asyncio.Event]

        async def on_initialize(self) -> None:
            _NoDepsService.initialized.set()

    _NoDepsService.initialized = asyncio.Event()

    service = hassette_instance.add_child(_NoDepsService)

    task = asyncio.create_task(service.initialize())
    await asyncio.sleep(0)  # one yield is enough if there is no blocking wait

    # Drive task to completion (it may need one more yield for handle_running).
    await asyncio.wait_for(task, timeout=1.0)

    assert _NoDepsService.initialized.is_set(), "on_initialize must have run without any blocking dependency wait"
