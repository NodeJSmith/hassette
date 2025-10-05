import asyncio
import traceback
import typing
from logging import getLogger

import aiohttp
from whenever import OffsetDateTime, SystemDateTime, ZonedDateTime

if typing.TYPE_CHECKING:
    from hassette.core.classes import Resource

LOGGER = getLogger(__name__)


async def wait_for_ready(
    resources: "list[Resource] | Resource",
    poll_interval: float = 0.1,
    timeout: int = 20,
    shutdown_event: asyncio.Event | None = None,
) -> bool:
    """Block until all dependent resources are ready or shutdown is requested.

    Args:
        resources (list[Resource] | Resource): The resources to wait for.
        poll_interval (float): The interval to poll for resource status.
        timeout (int): The timeout for the wait operation.

    Returns:
        bool: True if all resources are ready, False if timeout or shutdown.

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


def convert_utc_timestamp_to_system_tz(timestamp: int | float) -> SystemDateTime:
    """Convert a UTC timestamp to SystemDateTime in system timezone.

    Args:
        timestamp (int | float): The UTC timestamp.

    Returns:
        SystemDateTime: The converted SystemDateTime.
    """
    return ZonedDateTime.from_timestamp(timestamp, tz="UTC").to_system_tz()


def convert_datetime_str_to_system_tz(value: str | SystemDateTime | None) -> SystemDateTime | None:
    """Convert an ISO 8601 datetime string to SystemDateTime in system timezone.

    Args:
        value (str | SystemDateTime | None): The ISO 8601 datetime string.

    Returns:
        SystemDateTime | None: The converted SystemDateTime or None if input is None.
    """
    if value is None or isinstance(value, SystemDateTime):
        return value
    return OffsetDateTime.parse_common_iso(value).to_system_tz()


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
