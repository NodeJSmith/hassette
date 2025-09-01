import traceback
from logging import getLogger

import aiohttp

LOGGER = getLogger(__name__)


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
