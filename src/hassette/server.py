"""Hassette framework server entry point."""

import asyncio
import signal
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.exceptions import FatalError

LOGGER = getLogger(__name__)


async def main(config: HassetteConfig) -> None:
    """Start the Hassette framework server with the provided configuration."""
    if not config.token:
        raise FatalError(
            "HA token is required for server startup. Set HASSETTE__TOKEN or HA_TOKEN in your environment or .env file."
        )

    config.ensure_directories()
    core = Hassette(config=config)
    core.wire_services()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, core.request_shutdown, "SIGTERM received")
    except NotImplementedError:
        LOGGER.warning("SIGTERM handler registration is not supported on this platform/event loop")

    await core.run_forever()
