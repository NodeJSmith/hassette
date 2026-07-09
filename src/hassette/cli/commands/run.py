"""Run command — starts the Hassette framework server."""

import asyncio
import errno
from logging import getLogger
from typing import Annotated, Any

from cyclopts import Parameter

from hassette.config.config import HassetteConfig
from hassette.exceptions import AppPrecheckFailedError, FatalError
from hassette.server import main as run_server

LOGGER = getLogger("hassette.cli")


def cmd_run(
    token: Annotated[str | None, Parameter(name=["--token", "-t"], help="Home Assistant access token.")] = None,
    base_url: Annotated[
        str | None, Parameter(name=["--base-url", "-u", "--url"], help="Base URL of the Home Assistant instance.")
    ] = None,
    verify_ssl: Annotated[
        bool | None,
        Parameter(name=["--verify-ssl"], help="Whether to verify SSL certificates.", negative=[]),
    ] = None,
    dev_mode: Annotated[
        bool | None,
        Parameter(name=["--dev-mode"], help="Enable developer mode.", negative=[]),
    ] = None,
) -> None:
    """Start the Hassette framework server."""
    init_kwargs: dict[str, Any] = {}
    if token is not None:
        init_kwargs["token"] = token
    if base_url is not None:
        init_kwargs["base_url"] = base_url
    if verify_ssl is not None:
        init_kwargs["verify_ssl"] = verify_ssl
    if dev_mode is not None:
        init_kwargs["dev_mode"] = dev_mode

    config = HassetteConfig(**init_kwargs)

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received, shutting down")
    except AppPrecheckFailedError as exc:
        LOGGER.error("App precheck failed: %s", exc)
        LOGGER.error("Hassette is shutting down due to app precheck failure")
        raise SystemExit(1) from None
    except FatalError as exc:
        LOGGER.error("Fatal error occurred: %s", exc)
        LOGGER.error("Hassette is shutting down due to a fatal error")
        raise SystemExit(1) from None
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            LOGGER.error("Port %s is already in use — is another hassette instance running?", config.web_api.port)
            raise SystemExit(1) from None
        LOGGER.exception("OS error in Hassette: %s", exc)
        raise
    except Exception as exc:
        LOGGER.exception("Unexpected error in Hassette: %s", exc)
        raise
