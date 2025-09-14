import asyncio
from argparse import ArgumentParser
from logging import getLogger

from hassette.config import HassetteConfig
from hassette.core.core import Hassette

name = "hassette.hass_main" if __name__ == "__main__" else __name__

LOGGER = getLogger(name)


def get_parser() -> ArgumentParser:
    """
    Parse command line arguments for the Hassette application.
    """
    parser = ArgumentParser(description="Hassette - A Home Assistant integration")
    parser.add_argument(
        "--config-file",
        "--config_file",
        "-c",
        "--hassette-config",
        "--hassette_config",
        type=str,
        default=None,
        help="Path to the settings file",
        dest="config_file",
    )
    parser.add_argument(
        "--env-file",
        "--env_file",
        "--env",
        "-e",
        type=str,
        default=None,
        help="Path to the environment file (default: .env)",
        dest="env_file",
    )
    return parser


async def main() -> None:
    """Main function to run the Hassette application."""

    args = get_parser().parse_known_args()[0]

    # using type: ignore because there's no good way to tell pyright that these are being passed in for
    # the base settings superclass and not for the HassetteConfig class itself
    # (well, there may be, but I can't think of it off the top of my head)
    # note: _env_file is natively supported, but we are passing as env_file to avoid overriding to an empty value
    config = HassetteConfig(env_file=args.env_file, config_file=args.config_file)  # type: ignore

    core = Hassette(config=config)

    await core.run_forever()


def entrypoint() -> None:
    """
    This is the entry point for the Home Assistant integration.
    It initializes the HASS_CONTEXT and starts the event loop.
    """

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received, shutting down")
    except Exception as e:
        LOGGER.exception("Unexpected error in Hassette: %s", e)
        raise


if __name__ == "__main__":
    entrypoint()
