import asyncio
import signal
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.config.helpers import get_log_level
from hassette.exceptions import FatalError
from hassette.logging_ import enable_logging

name = "hassette.__main__" if __name__ == "__main__" else __name__

LOGGER = getLogger(name)


async def main(config: HassetteConfig) -> None:
    """Start the Hassette framework server with the provided configuration."""
    if config.token is None:
        raise FatalError(
            "HA token is required for server startup. Set HASSETTE__TOKEN or HA_TOKEN in your environment or .env file."
        )

    core = Hassette(config=config)
    core.wire_services()

    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, core.request_shutdown, "SIGTERM received")
    except NotImplementedError:
        LOGGER.warning("SIGTERM handler registration is not supported on this platform/event loop")

    await core.run_forever()


def entrypoint() -> None:
    # Pre-config fallback — Hassette.__init__ re-calls with the full config (including log_format)
    enable_logging(get_log_level(), log_format="auto")

    from hassette.cli import app  # deferred to break circular import at module level

    app()


if __name__ == "__main__":
    entrypoint()
