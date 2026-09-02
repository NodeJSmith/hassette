"""Hassette framework server entry point."""

import asyncio
import signal
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.exceptions import FatalError
from hassette.resources.lifecycle import request_shutdown

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
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_shutdown, core, f"{sig.name} received")
        except NotImplementedError:
            LOGGER.warning("%s handler registration is not supported on this platform/event loop", sig.name)

    await core.run_forever()
