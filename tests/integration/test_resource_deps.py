"""Integration tests for resource dependency ordering."""

import asyncio
from typing import ClassVar

from hassette import Hassette
from hassette.resources.base import Resource
from hassette.utils.service_utils import topological_levels, topological_sort


async def test_coordinator_uses_topological_sort(hassette_instance: Hassette) -> None:
    """Coordinator's stored init_order and init_waves match the pure-function output."""
    child_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
    expected_order = topological_sort(child_types)
    expected_waves = topological_levels(child_types)
    assert hassette_instance._init_order == expected_order  # coordinator-internal: pins wiring
    assert hassette_instance._init_waves == expected_waves  # coordinator-internal: pins wiring


async def test_init_waves_respect_dependency_ordering(hassette_instance: Hassette) -> None:
    """Every depends_on type appears in an earlier wave than its dependent."""
    child_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
    waves = topological_levels(child_types)
    type_set = {t for wave in waves for t in wave}
    wave_index = {t: i for i, wave in enumerate(waves) for t in wave}

    for t in type_set:
        for dep in t.depends_on:
            if dep in type_set:
                assert wave_index[dep] < wave_index[t], (
                    f"{t.__name__} (wave {wave_index[t]}) depends on {dep.__name__} "
                    f"(wave {wave_index[dep]}), but dep is not in an earlier wave"
                )


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
