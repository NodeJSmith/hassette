import asyncio
import logging
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

    def _resolve_deps(raw_deps: list[type]) -> list[type]:
        """Resolve declared deps to concrete types in type_set using issubclass."""
        resolved: list[type] = []
        for d in raw_deps:
            if d in type_set:
                resolved.append(d)
            else:
                resolved.extend(t for t in type_set if issubclass(t, d))
        return resolved

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
        dep_iters.append((start, iter(_resolve_deps(getattr(start, "depends_on", [])))))

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
                dep_iters.append((dep, iter(_resolve_deps(getattr(dep, "depends_on", [])))))

    return result


def topological_levels(types: "list[type[Resource]]") -> "list[list[type[Resource]]]":
    """Group *types* into dependency levels for wave-based startup/shutdown.

    Level 0 contains types with no dependencies (or whose deps are not in the
    input set).  Level N contains types whose deps are all in levels 0..N-1.

    Within each level, insertion order from *types* is preserved so that
    deterministic startup/shutdown ordering is maintained for peers with no
    ordering constraint.

    Delegates to :func:`topological_sort` for cycle detection.  Callers
    should validate the graph with ``topological_sort`` first (this function
    re-validates as a defensive measure).

    Args:
        types: Resource types to partition.

    Returns:
        A list of lists where each inner list is a wave of types that can
        run concurrently.  Waves must execute sequentially (level 0 first
        for startup, last for shutdown).

    Raises:
        ValueError: If a cycle is detected (propagated from ``topological_sort``).
    """
    if not types:
        return []

    sorted_types = topological_sort(types)
    type_set: set[type] = set(types)

    def _resolve(d: type) -> list[type]:
        if d in type_set:
            return [d]
        return [t for t in type_set if issubclass(t, d)]

    level_of: dict[type, int] = {}
    for t in sorted_types:
        deps_in_set = [r for d in getattr(t, "depends_on", []) for r in _resolve(d)]
        if not deps_in_set:
            level_of[t] = 0
        else:
            level_of[t] = max(level_of[d] for d in deps_in_set) + 1

    max_level = max(level_of.values()) if level_of else 0
    levels: list[list[type]] = [[] for _ in range(max_level + 1)]
    for t in sorted_types:
        levels[level_of[t]].append(t)

    return levels


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
            if wait_task in done:
                logging.getLogger("hassette").warning(
                    "Dependencies became ready simultaneously with shutdown — startup aborted"
                )
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
