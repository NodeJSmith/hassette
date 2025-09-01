import asyncio
from argparse import ArgumentParser
from logging import getLogger

from pydantic_settings import SettingsConfigDict

from hassette.config import HassetteConfig
from hassette.core.core import Hassette

name = "hassette.hass_main" if __name__ == "__main__" else __name__

LOGGER = getLogger(name)


def get_parser() -> ArgumentParser:
    """
    Parse command line arguments for the Hassette application.
    """
    parser = ArgumentParser(description="Hassette - A Home Assistant integration")
    parser.add_argument("--settings", "-s", type=str, default=None, help="Path to the settings file")
    parser.add_argument(
        "--env-file",
        "--env_file",
        "--env",
        "-e",
        type=str,
        default=None,
        help="Path to the environment file (default: .env)",
    )
    return parser


async def main() -> None:
    """Main function to run the Hassette application."""

    args = get_parser().parse_known_args()[0]
    has_args = any(vars(args).values())

    # kind of a hack to allow the settings to be loaded from the command line
    # i'm not sure if there's a better way, given that you can only pass _env_file and _secret_dir
    # not any other overrides
    class CustomSettings(HassetteConfig):
        model_config = SettingsConfigDict(
            env_prefix="hassette__",
            env_file=args.env_file,
            toml_file=args.settings,
            env_ignore_empty=True,
            extra="allow",
            env_nested_delimiter="__",
            nested_model_default_partial_update=True,
        )

    core = Hassette(config=CustomSettings()) if has_args else Hassette()

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
