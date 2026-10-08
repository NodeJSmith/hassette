"""The oldest hassette server this client release supports, and the check against it."""

import logging

from hassette_wire import SystemStatusResponse
from packaging.version import InvalidVersion, Version

from hassette_client.errors import UnsupportedServerVersionError

LOGGER = logging.getLogger(__name__)

MIN_SERVER_VERSION = "0.55.0"
"""The oldest hassette server version this client release works with.

Every route, method and query parameter the client sends exists on a server of this version. A CI
check on each release PR runs the client's OpenAPI coverage test against this version's committed
``openapi.json``, so a release that starts depending on newer server API can't ship until this is
raised. release-please doesn't bump it: it only moves when the client needs it to.
"""


def check_server_version(health: SystemStatusResponse) -> None:
    """Raise if the server is older than :data:`MIN_SERVER_VERSION`.

    Call it once a connection is set up, such as during an integration's setup and config flow. No
    method calls it for you, so :meth:`~hassette_client.HassetteClient.get_health` and the rest keep
    working against an older server for status reporting.

    Versions compare by PEP 440, so a pre-release or dev build of the minimum version, such as
    ``0.55.0.dev3``, counts as older. A newer server passes. A server whose version is empty,
    ``"unknown"`` (a source checkout) or otherwise not a PEP 440 version also passes, because
    there's nothing to compare; tell the user you couldn't check the version.

    Args:
        health: The result of :meth:`~hassette_client.HassetteClient.get_health`.

    Raises:
        UnsupportedServerVersionError: The server reports a version older than
            :data:`MIN_SERVER_VERSION`.
    """
    try:
        server = Version(health.version)
    except InvalidVersion:
        LOGGER.debug("Server version %r isn't a PEP 440 version; skipping the minimum version check", health.version)
        return
    if server < Version(MIN_SERVER_VERSION):
        LOGGER.debug("Raising UnsupportedServerVersionError: server %s < minimum %s", server, MIN_SERVER_VERSION)
        raise UnsupportedServerVersionError(server_version=health.version, min_version=MIN_SERVER_VERSION)
