"""Build a :class:`~hassette_client.HassetteClient` for one CLI invocation.

Kept apart from ``cli/context.py`` for the same reason as ``cli/target.py``: it takes the resolved
:class:`ServerTarget` and credential directly rather than a ``CLIContext``, so it's testable
without fabricating one.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiohttp
from hassette_client import HassetteClient

from hassette.cli.target import ResolvedCredential, ServerTarget


@asynccontextmanager
async def open_client(target: ServerTarget, credential: ResolvedCredential | None) -> AsyncIterator[HassetteClient]:
    """Yield a client for ``target`` over a session this context owns and closes on exit.

    Authentication needs no handling here: aiohttp sends ``user:password@`` userinfo in
    ``target.base_url`` as Basic auth, and the client sends ``credential`` as a bearer token.
    Credential resolution already rejects a token alongside userinfo.

    Args:
        target: Where to connect. With ``verify_ssl`` false, the session skips TLS certificate checks.
        credential: The bearer credential to send, or ``None`` to send no token.
    """
    # ssl=True is aiohttp's default (verify certificates); ssl=False disables verification.
    connector = aiohttp.TCPConnector(ssl=target.verify_ssl)
    async with aiohttp.ClientSession(connector=connector) as session:
        yield HassetteClient(session, target.base_url, token=credential.token if credential else None)
