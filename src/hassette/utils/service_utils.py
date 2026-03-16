import asyncio
import typing

if typing.TYPE_CHECKING:
    from hassette.resources.base import Resource


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
