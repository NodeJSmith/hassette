import asyncio
import traceback
import typing
from logging import getLogger

import aiohttp
import anyio

if typing.TYPE_CHECKING:
    from hassette.core.classes import Resource

LOGGER = getLogger(__name__)


async def wait_for_resources_running_or_raise(
    resources: list["Resource"],
    poll_interval: float = 0.1,
    timeout: int = 20,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Block until all dependent resources are running or shutdown is requested.

    Args:
        resources (list[Resource]): The resources to wait for.
        poll_interval (float): The interval to poll for resource status.
        timeout (int): The timeout for the wait operation.
        shutdown_event (asyncio.Event | None): Optional event to signal shutdown.

    Raises:
        RuntimeError: If any resource fails to start or timeout occurs.
    """
    results = await wait_for_resources_running(
        resources, poll_interval=poll_interval, timeout=timeout, shutdown_event=shutdown_event
    )
    if not results:
        failed_to_start = [r.class_name for r in resources if r.status != "running"]
        LOGGER.error("One or more resources failed to start: %s", ", ".join(failed_to_start))
        raise RuntimeError(f"One or more resources failed to start: {', '.join(failed_to_start)}")


async def wait_for_resources_running(
    resources: list["Resource"],
    poll_interval: float = 0.1,
    timeout: int = 20,
    shutdown_event: asyncio.Event | None = None,
) -> bool:
    """Block until all dependent resources are running or shutdown is requested.

    Args:
        resources (list[Resource]): The resources to wait for.
        poll_interval (float): The interval to poll for resource status.
        timeout (int): The timeout for the wait operation.
        shutdown_event (asyncio.Event | None): Optional event to signal shutdown.

    Returns:
        bool: True if all resources are running, False if shutdown is requested.
    """
    futures = [
        wait_for_resource_running(resource, poll_interval=poll_interval, timeout=timeout, shutdown_event=shutdown_event)
        for resource in resources
    ]

    results = await asyncio.gather(*futures)
    return all(results)


async def wait_for_resource_running(
    resource: "Resource", poll_interval: float = 0.1, timeout: int = 20, shutdown_event: asyncio.Event | None = None
) -> bool:
    """Block until a dependent resource is running or shutdown is requested.

    Args:
        resource (Resource): The resource to wait for.
        poll_interval (float): The interval to poll for resource status.
        timeout (int): The timeout for the wait operation.
        shutdown_event (asyncio.Event | None): Optional event to signal shutdown.

    Returns:
        bool: True if the resource is running, False if shutdown.
    """
    from hassette.core.classes import ResourceStatus

    with anyio.move_on_after(timeout) as cancel_scope:
        while resource.status != ResourceStatus.RUNNING:
            if shutdown_event and shutdown_event.is_set():
                LOGGER.warning("Shutdown in progress, aborting app watcher")
                return False
            await asyncio.sleep(poll_interval)

    if cancel_scope.cancel_called:
        LOGGER.error("Timeout waiting for resource '%s' to start after %d seconds", resource.class_name, timeout)
        return False

    if resource.status != ResourceStatus.RUNNING:
        LOGGER.error("Resource '%s' is not running", resource.class_name)
        return False

    return True


def get_traceback_string(exception: Exception) -> str:
    """Get a formatted traceback string from an exception."""

    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))


def capture_to_file(path: str):
    """Captures `aiohttp.ClientResponse.json` to a file.

    Args:
        path (str): The file path where the JSON response will be saved.

    Usage:
        async with capture_to_file("response.json"):
            response = await api.get_history(...)
    """

    original_json = aiohttp.ClientResponse.json

    async def wrapped_json(self, *args, **kwargs):  # noqa
        raw = await self.read()
        with open(path, "wb") as f:
            f.write(raw)
        # Now parse JSON from the already-read raw data
        import json

        return json.loads(raw.decode("utf-8"))

    aiohttp.ClientResponse.json = wrapped_json
    try:
        yield
    finally:
        aiohttp.ClientResponse.json = original_json
