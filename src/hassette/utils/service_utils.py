import asyncio
import typing

if typing.TYPE_CHECKING:
    from hassette.resources.base import Resource


async def wait_for_ready(
    resources: "list[Resource] | Resource",
    poll_interval: float = 0.1,
    timeout: int = 20,
    shutdown_event: asyncio.Event | None = None,
) -> bool:
    """Block until all dependent resources are ready or shutdown is requested.

    Args:
        resources: The resources to wait for.
        poll_interval: The interval to poll for resource status.
        timeout: The timeout for the wait operation.

    Returns:
        True if all resources are ready, False if timeout or shutdown.

    Raises:
        CancelledError: If the wait operation is cancelled.
        TimeoutError: If the wait operation times out.
    """

    resources = resources if isinstance(resources, list) else [resources]
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        if shutdown_event and shutdown_event.is_set():
            return False
        if all(r.is_ready() for r in resources):
            return True
        if asyncio.get_event_loop().time() >= deadline:
            return False
        await asyncio.sleep(poll_interval)
