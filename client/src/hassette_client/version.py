"""The oldest hassette API schema this client release supports, and the check against it."""

import logging

from hassette_wire import SystemStatusResponse

from hassette_client.errors import UnsupportedServerVersionError

LOGGER = logging.getLogger(__name__)

MIN_API_SCHEMA_VERSION = 1
"""The oldest API schema a hassette server may report for this client release to work with it.

A server reports its schema as ``api_schema_version`` in :meth:`~hassette_client.HassetteClient.get_health`,
from ``hassette_wire.API_SCHEMA_VERSION``. Every route, method and query parameter the client sends, and
every response field it requires, with the type it requires, exists on the oldest release reporting at least
this schema.

The bump rule, which ``tools/check_client_floor.py`` enforces on every pull request: a change that makes
the client depend on server API that release lacks (a route, method or query parameter, or a response field
the client now requires or whose type it now needs) does two things in the same pull request.

1. Raise ``API_SCHEMA_VERSION`` (``wire/src/hassette_wire/health.py``) by one, unless it is already above
   the latest release's value (``git show <latest v* tag>:wire/src/hassette_wire/health.py``). Releases
   are what servers run, so one bump per release is enough: a second bump before the next release would
   name the same release as the floor.
2. Set this constant to ``API_SCHEMA_VERSION``.
"""


def check_server_version(health: SystemStatusResponse) -> None:
    """Raise if the server's API schema is older than :data:`MIN_API_SCHEMA_VERSION`.

    "Version" here is the server's integer API schema, not its release number.

    Call it once a connection is set up, such as during an integration's setup and config flow. No
    method calls it for you, so :meth:`~hassette_client.HassetteClient.get_health` and the rest keep
    working against an older server for status reporting.

    A server released before the API schema existed doesn't report one, so it reads as schema ``0`` and
    raises: it predates every route this client may need.

    Args:
        health: The result of :meth:`~hassette_client.HassetteClient.get_health`.

    Raises:
        UnsupportedServerVersionError: The server's ``api_schema_version`` is below
            :data:`MIN_API_SCHEMA_VERSION`.
    """
    if health.api_schema_version >= MIN_API_SCHEMA_VERSION:
        return
    LOGGER.debug(
        "Raising UnsupportedServerVersionError: server API schema %d < minimum %d",
        health.api_schema_version,
        MIN_API_SCHEMA_VERSION,
    )
    raise UnsupportedServerVersionError(
        server_version=health.version,
        api_schema_version=health.api_schema_version,
        min_api_schema_version=MIN_API_SCHEMA_VERSION,
    )
