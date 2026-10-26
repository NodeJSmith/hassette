import asyncio
import logging
import typing
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

if typing.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from hassette.resources.base import Resource


ASYNCIO_DIR = str(Path(asyncio.__file__).parent)
"""asyncio's package directory; frames from it are skipped when locating where a task waits."""


class Color(Enum):
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
        """Resolve declared deps to concrete types in input order using issubclass."""
        resolved: list[type] = []
        for d in raw_deps:
            if d in type_set:
                resolved.append(d)
            else:
                resolved.extend(t for t in types if issubclass(t, d))
        return resolved

    color: dict[type, Color] = dict.fromkeys(types, Color.WHITE)
    result: list[type] = []

    # Iterative DFS.  Each work item is (node, iterator_over_its_deps).
    # The ``path`` list mirrors the call stack for cycle reconstruction.
    for start in types:
        if color[start] is not Color.WHITE:
            continue

        # Stack entries: (node, dep_iterator, index_in_path)
        # We push a node when we first visit it (WHITE→GRAY), pop when done (GRAY→BLACK).
        dep_iters: list[tuple[type, typing.Iterator[type]]] = []
        path: list[type] = []

        color[start] = Color.GRAY
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
                color[node] = Color.BLACK
                result.append(node)
                continue

            if color.get(dep, Color.BLACK) is Color.GRAY:
                # Back edge → cycle.  Reconstruct path from first occurrence of dep.
                cycle_start = path.index(dep)
                cycle_path = [*path[cycle_start:], dep]
                cycle_str = " → ".join(t.__name__ for t in cycle_path)
                raise ValueError(f"Cycle detected: {cycle_str}")

            if color.get(dep, Color.BLACK) is Color.WHITE:
                color[dep] = Color.GRAY
                path.append(dep)
                dep_iters.append((dep, iter(_resolve_deps(getattr(dep, "depends_on", [])))))

    return result


def validate_dependency_graph(types: "list[type[Resource]]") -> None:
    """Validate that every ``depends_on`` reference resolves to a type in *types*.

    Raises:
        ValueError: If a declared dependency has no matching type (via issubclass).
    """
    type_set: set[type] = set(types)
    for child_type in types:
        for dep_type in getattr(child_type, "depends_on", []):
            if not any(issubclass(t, dep_type) for t in type_set):
                raise ValueError(
                    f"{child_type.__name__} declares depends_on=[{dep_type.__name__}] "
                    f"but no matching child type found in Hassette"
                )


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
        return [t for t in sorted_types if issubclass(t, d)]

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


async def cancel_and_drain(task: "asyncio.Task[typing.Any] | None") -> None:
    """Cancel ``task`` if present and await its completion, absorbing its ``CancelledError``.

    ``gather(..., return_exceptions=True)`` is required: awaiting a cancelled task directly would
    raise ``CancelledError`` into the caller's shutdown path. It also absorbs any exception the task
    already raised, so a failed background task cannot abort teardown.

    The caller still owns resetting whatever field held the task.

    Args:
        task: The task to cancel, or ``None`` (a no-op).
    """
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


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

    wait_task = asyncio.create_task(_wait_all())
    shutdown_task = asyncio.create_task(shutdown_event.wait())
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


class WaveOutcome(Enum):
    """How a startup wave ended; see ``wait_for_wave()``."""

    OK = auto()
    SHUTDOWN = auto()
    FAILED = auto()
    TIMEOUT = auto()


@dataclass(frozen=True)
class WaveResult:
    """A startup wave's outcome, with the members that caused it.

    ``resources`` holds the members whose attempt failed (``FAILED``) or that never finished and
    became ready (``TIMEOUT``), and is empty for ``OK`` and ``SHUTDOWN``. For ``FAILED``, ``errors``
    holds each of those members' exceptions in the same order, ``None`` for a cancelled attempt.
    """

    outcome: WaveOutcome
    resources: "tuple[Resource, ...]" = ()
    errors: "tuple[BaseException | None, ...]" = ()


async def wait_for_wave(
    attempts: "Mapping[Resource, asyncio.Task[None] | None]",
    timeout: float,
    shutdown_event: asyncio.Event,
) -> WaveResult:
    """Wait until every member's initialization attempt has finished and every member is ready.

    Readiness alone doesn't prove an attempt finished: a resource can mark itself ready inside
    ``on_initialize()`` and still fail later in the same attempt (a child failing to initialize), so
    a failed attempt fails the wave at once, whatever its readiness. A normally returned attempt is
    finished, not ready: the member still has to become ready before the wave is. Readiness is read
    live, so a member that loses it mid-wave (a ``serve()`` failure) has to regain it.

    Shutdown wins over every other outcome, including a cancelled attempt, which counts as a failure
    only when no shutdown was requested. The attempts are never cancelled or awaited here, so a
    shutdown doesn't wait for an attempt that hangs; the attempt's own exception observer is what
    logs its failure.

    Args:
        attempts: Each member mapped to the task its initialization attempt runs on (from
            ``start()``), or ``None`` when there is no attempt to join.
        timeout: Seconds the whole wave may take, the attempts and readiness together.
        shutdown_event: Ends the wait with ``SHUTDOWN`` once set.

    Returns:
        The outcome, with the failed members and their exceptions (``FAILED``) or the unfinished
        members (``TIMEOUT``).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    attempt_tasks = [task for task in attempts.values() if task is not None]
    # Wake-up sources only, never read: shutdown, and each not-ready member becoming ready. The
    # checks at the top of the loop read the state directly.
    shutdown_waker = asyncio.create_task(shutdown_event.wait())
    ready_wakers: dict[Resource, asyncio.Task[None]] = {}
    try:
        while True:
            if shutdown_event.is_set():
                return WaveResult(WaveOutcome.SHUTDOWN)
            failed = [(member, task) for member, task in attempts.items() if task is not None and attempt_failed(task)]
            if failed:
                return WaveResult(
                    WaveOutcome.FAILED,
                    tuple(member for member, _ in failed),
                    tuple(None if task.cancelled() else task.exception() for _, task in failed),
                )
            unfinished = tuple(
                member
                for member, task in attempts.items()
                if (task is not None and not task.done()) or not member.is_ready()
            )
            if not unfinished:
                return WaveResult(WaveOutcome.OK)
            remaining = deadline - loop.time()
            if remaining <= 0:
                return WaveResult(WaveOutcome.TIMEOUT, unfinished)
            for member in attempts:
                waker = ready_wakers.get(member)
                if not member.is_ready() and (waker is None or waker.done()):
                    ready_wakers[member] = asyncio.create_task(member.wait_ready())
            watched = [task for task in (*attempt_tasks, shutdown_waker, *ready_wakers.values()) if not task.done()]
            await asyncio.wait(watched, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
    finally:
        wakers = [shutdown_waker, *ready_wakers.values()]
        for waker in wakers:
            waker.cancel()
        await asyncio.gather(*wakers, return_exceptions=True)


def attempt_failed(task: "asyncio.Task[None]") -> bool:
    """Return True when an initialization attempt's task ended in an exception or a cancellation."""
    if not task.done():
        return False
    # cancelled() first: exception() raises CancelledError on a cancelled task.
    return task.cancelled() or task.exception() is not None


def describe_children(resource: "Resource") -> str:
    """Return ``resource``'s children as ``Name(status)`` pairs, or ``"none"``."""
    return ", ".join(f"{c.class_name}({c.status.value})" for c in resource.children) or "none"


def describe_error(error: BaseException | None) -> str:
    """Return ``Type: message`` for a failed attempt's exception, or ``cancelled`` for a cancelled one."""
    if error is None:
        return "cancelled"
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


def describe_wave_causes(result: WaveResult) -> str:
    """Return ``Name (Type: message)`` for each member a FAILED wave names, comma-separated."""
    return ", ".join(
        f"{member.class_name} ({describe_error(error)})"
        for member, error in zip(result.resources, result.errors, strict=True)
    )


def describe_wave_failure(result: WaveResult, timeout: float) -> str:
    """Return the fatal startup reason for a FAILED or TIMEOUT wave, naming each resource and its cause."""
    if result.outcome is WaveOutcome.FAILED:
        return f"startup failure: failed to initialize: {describe_wave_causes(result)}"
    names = ", ".join(r.class_name for r in result.resources)
    return f"startup failure: did not finish starting within {timeout}s: {names}"


def describe_wave_members(resources: "Sequence[Resource]") -> str:
    """Describe each resource for a failed wave's log, one per line.

    The resource a wave names is not always the one to fix: a parent whose child hangs in
    initialization never finishes either, so the children's statuses point at the one stuck in
    STARTING, and a still-running initialization names the line it is waiting on.
    """
    lines = []
    for resource in resources:
        line = (
            f"  {resource.class_name}: status={resource.status.value}, ready={resource.is_ready()}, "
            f"ready_reason={resource._ready_reason!r}, children: {describe_children(resource)}"
        )
        init_task = resource._init_task
        if init_task is not None and not init_task.done():
            line += f", initialization waiting at {awaiting_location(init_task)}"
        lines.append(line)
    return "\n".join(lines)


def awaiting_location(task: "asyncio.Task[typing.Any]") -> str:
    """Return ``file:line in function`` for the innermost await a suspended task is blocked on.

    ``Task.get_stack()`` returns only the outermost frame of a suspended coroutine, so this follows
    the ``cr_await`` chain down to the coroutine that is actually waiting, skipping asyncio's own
    frames (an ``Event.wait()`` says nothing about who is waiting).
    """
    coro: typing.Any = task.get_coro()
    frame = None
    while coro is not None and getattr(coro, "cr_frame", None) is not None:
        if not coro.cr_frame.f_code.co_filename.startswith(ASYNCIO_DIR):
            frame = coro.cr_frame
        coro = getattr(coro, "cr_await", None)
    if frame is None:
        return "an unknown point"
    return f"{frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}"
