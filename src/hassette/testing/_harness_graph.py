"""Component dependency graph for the test harness and the startup order derived from it."""

import typing

from hassette.core.app_bootstrap_coordinator import AppBootstrapCoordinator
from hassette.core.app_handler import AppHandler
from hassette.core.bus_service import BusService
from hassette.core.scheduler_service import SchedulerService
from hassette.core.state_proxy import StateProxy
from hassette.core.sync_executor_service import SyncExecutorService
from hassette.resources.base import Resource

DEPENDENCIES: dict[str, set[str]] = {
    "sync_executor": set(),
    "bus": {"sync_executor"},
    "scheduler": {"sync_executor", "bus"},
    "file_watcher": set(),
    "api_mock": set(),
    "app_bootstrap_coordinator": {"bus", "scheduler", "state_proxy", "sync_executor"},
    "app_handler": {"app_bootstrap_coordinator"},
    "state_proxy": {"bus", "scheduler"},
    "state_registry": set(),
}
# Maps harness component names to the corresponding real framework service class.
# Used by the harness consistency test to verify DEPENDENCIES stays in sync with
# real service depends_on declarations.
#
# Omitted entries:
#   "file_watcher"   — FileWatcherService has no depends_on (empty list), so consistency
#                      checks would be vacuous.  Omitting avoids false-positive drift.
#   "state_registry" — StateRegistry is not a Resource subclass; it is a plain dataclass
#                      registry with no depends_on concept.
COMPONENT_CLASS_MAP: dict[str, type[Resource]] = {
    "sync_executor": SyncExecutorService,
    "bus": BusService,
    "scheduler": SchedulerService,
    "app_bootstrap_coordinator": AppBootstrapCoordinator,
    "app_handler": AppHandler,
    "state_proxy": StateProxy,
}


def sort_harness_graph(graph: dict[str, set[str]]) -> list[str]:
    """Return node names from *graph* in valid initialization order (deps before dependents).

    Uses iterative DFS with three-color (white/gray/black) marking.  Only nodes
    present as keys in *graph* are included in the output; dependency references
    to nodes not in *graph* are silently ignored.

    Args:
        graph: Adjacency map of node name → set of dependency names.

    Returns:
        A list of all node names ordered so that every dependency appears before
        the nodes that depend on it.

    Raises:
        ValueError: If a cycle is detected.
    """
    if not graph:
        return []

    white, gray, black = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph, white)
    result: list[str] = []

    for start in graph:
        if color[start] != white:
            continue

        stack: list[tuple[str, typing.Iterator[str]]] = []
        path: list[str] = []

        color[start] = gray
        path.append(start)
        stack.append((start, iter(dep for dep in graph[start] if dep in graph)))

        while stack:
            node, deps = stack[-1]
            try:
                dep = next(deps)
            except StopIteration:
                stack.pop()
                path.pop()
                color[node] = black
                result.append(node)
                continue

            if color.get(dep, black) == gray:
                cycle_start = path.index(dep)
                cycle_path = [*path[cycle_start:], dep]
                raise ValueError("Cycle detected: " + " → ".join(cycle_path))

            if color.get(dep, black) == white:
                color[dep] = gray
                path.append(dep)
                stack.append((dep, iter(d for d in graph[dep] if d in graph)))

    return result


# Startup order derived from the dependency graph — no manual maintenance required.
STARTUP_ORDER: list[str] = sort_harness_graph(DEPENDENCIES)
