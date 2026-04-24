import asyncio
import typing
from enum import Enum, auto

if typing.TYPE_CHECKING:
    from hassette.resources.base import Resource


class _Color(Enum):
    WHITE = auto()  # not yet visited
    GRAY = auto()  # on the current DFS path (ancestors of current node)
    BLACK = auto()  # fully processed


def topological_sort(types: "list[type[Resource]]") -> "list[type[Resource]]":
    """Return *types* in valid initialization order (dependencies before dependents).

    Uses iterative DFS with three-color (WHITE/GRAY/BLACK) marking and an
    explicit ``path`` stack for cycle-path reconstruction.  Only nodes present
    in *types* are considered — transitive dependencies not in the input list
    are silently ignored.

    Args:
        types: Resource types to sort.  Order is preserved for nodes that have
            no ordering constraint between them (stable sort property).

    Returns:
        A new list with the same elements as *types*, ordered so that every
        dependency appears before the nodes that depend on it.

    Raises:
        ValueError: If a cycle is detected.  The message includes the full
            cycle path, e.g. ``"Cycle detected: A → B → A"``.
    """
    if not types:
        return []

    # Restrict dependency resolution to the provided types.
    type_set: set[type] = set(types)

    color: dict[type, _Color] = {t: _Color.WHITE for t in types}
    result: list[type] = []

    # Iterative DFS.  Each work item is (node, iterator_over_its_deps).
    # The ``path`` list mirrors the call stack for cycle reconstruction.
    for start in types:
        if color[start] is not _Color.WHITE:
            continue

        # Stack entries: (node, dep_iterator, index_in_path)
        # We push a node when we first visit it (WHITE→GRAY), pop when done (GRAY→BLACK).
        dep_iters: list[tuple[type, typing.Iterator[type]]] = []
        path: list[type] = []

        color[start] = _Color.GRAY
        path.append(start)
        raw_deps = getattr(start, "depends_on", [])
        dep_iters.append((start, iter([d for d in raw_deps if d in type_set])))

        while dep_iters:
            node, deps = dep_iters[-1]

            try:
                dep = next(deps)
            except StopIteration:
                # All deps of *node* are processed — finalise *node*.
                dep_iters.pop()
                path.pop()
                color[node] = _Color.BLACK
                result.append(node)
                continue

            if color.get(dep, _Color.BLACK) is _Color.GRAY:
                # Back edge → cycle.  Reconstruct path from first occurrence of dep.
                cycle_start = path.index(dep)
                cycle_path = [*path[cycle_start:], dep]
                cycle_str = " → ".join(t.__name__ for t in cycle_path)
                raise ValueError(f"Cycle detected: {cycle_str}")

            if color.get(dep, _Color.BLACK) is _Color.WHITE:
                color[dep] = _Color.GRAY
                path.append(dep)
                raw_dep_deps = getattr(dep, "depends_on", [])
                dep_iters.append((dep, iter([d for d in raw_dep_deps if d in type_set])))

    return result


async def wait_for_ready(
    resources: "list[Resource] | Resource",
    timeout: float = 20,
    shutdown_event: asyncio.Event | None = None,
) -> bool:
    """Block until all dependent resources are ready or shutdown is requested.

    Uses event-driven waits (``Resource.wait_ready``) instead of polling,
    so readiness is detected immediately when ``mark_ready()`` is called.

    Args:
        resources: The resource(s) to wait for.
        timeout: The timeout in seconds for the wait operation.
        shutdown_event: If set before all resources are ready, returns False.

    Returns:
        True if all resources are ready, False if timeout or shutdown.

    Raises:
        CancelledError: If the calling task is cancelled while waiting.
    """
    resources = resources if isinstance(resources, list) else [resources]
    resources = [r for r in resources if r is not None]

    if not resources:
        return True

    if shutdown_event is None:
        try:
            await asyncio.gather(*(r.wait_ready(timeout=timeout) for r in resources))
        except TimeoutError:
            return False
        return True

    # Race: wait for all resources OR shutdown signal.
    # The outer asyncio.wait enforces the deadline; individual wait_ready
    # calls use timeout=None so they don't race with the outer timeout.
    async def _wait_all() -> bool:
        await asyncio.gather(*(r.wait_ready(timeout=None) for r in resources))
        return True

    wait_task = asyncio.ensure_future(_wait_all())
    shutdown_task = asyncio.ensure_future(shutdown_event.wait())
    try:
        done, _ = await asyncio.wait(
            {wait_task, shutdown_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if shutdown_task in done:
            return False
        if wait_task in done:
            return wait_task.result()
        # Timeout with neither completing
        return False
    finally:
        for task in (wait_task, shutdown_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(wait_task, shutdown_task, return_exceptions=True)
