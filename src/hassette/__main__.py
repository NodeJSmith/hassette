import asyncio
from argparse import ArgumentParser
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.exceptions import AppPrecheckFailedError

name = "hassette.hass_main" if __name__ == "__main__" else __name__

LOGGER = getLogger(name)


def get_parser() -> ArgumentParser:
    """
    Parse command line arguments for the Hassette application.
    """
    parser = ArgumentParser(description="Hassette - A Home Assistant integration", add_help=False)
    parser.add_argument(
        "--config-file",
        "-c",
        type=str,
        default=None,
        help="Path to the settings file",
        dest="config_file",
    )
    parser.add_argument(
        "--env-file",
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

    if args.env_file:
        HassetteConfig.model_config["env_file"] = args.env_file

    if args.config_file:
        HassetteConfig.model_config["toml_file"] = args.config_file

    config = HassetteConfig()

    core = Hassette(config=config)
    core.logger.info("Starting Hassette...")

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
    except AppPrecheckFailedError as e:
        LOGGER.error("App precheck failed: %s", e)
        LOGGER.error("Hassette is shutting down due to app precheck failure")
    except Exception as e:
        LOGGER.exception("Unexpected error in Hassette: %s", e)
        raise


if __name__ == "__main__":
    entrypoint()
