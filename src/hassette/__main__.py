import asyncio
from argparse import ArgumentParser
from logging import getLogger

from hassette import Hassette, HassetteConfig
from hassette.config.helpers import get_log_level
from hassette.exceptions import AppPrecheckFailedError, FatalError
from hassette.logging_ import enable_logging

name = "hassette.__main__" if __name__ == "__main__" else __name__

LOGGER = getLogger(name)


def get_parser() -> ArgumentParser:
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
    LOGGER.info("Starting Hassette...")

    args = get_parser().parse_known_args()[0]

    if args.env_file:
        HassetteConfig.model_config["env_file"] = args.env_file

    if args.config_file:
        HassetteConfig.model_config["toml_file"] = args.config_file

    config = HassetteConfig()
    core = Hassette(config=config)

    await core.run_forever()


def entrypoint() -> None:
    enable_logging(get_log_level())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received, shutting down")
    except AppPrecheckFailedError as e:
        LOGGER.error("App precheck failed: %s", e)
        LOGGER.error("Hassette is shutting down due to app precheck failure")
    except FatalError as e:
        LOGGER.error("Fatal error occurred: %s", e)
        LOGGER.error("Hassette is shutting down due to a fatal error")
    except Exception as e:
        LOGGER.exception("Unexpected error in Hassette: %s", e)
        raise


if __name__ == "__main__":
    entrypoint()
