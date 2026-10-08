"""Async client for the Hassette HTTP API.

:class:`HassetteClient` sends requests over an ``aiohttp.ClientSession`` the caller owns, returns
``hassette_wire`` models, and raises a :class:`HassetteClientError` subclass for every network or
server failure. Responses parse leniently, so this client keeps working against a newer server;
:func:`check_server_version` checks that the server's API schema isn't older than :data:`MIN_API_SCHEMA_VERSION`.
"""

from hassette_client.client import HassetteClient
from hassette_client.errors import (
    ActionFailedError,
    AppBlockedError,
    AppNotFoundError,
    AuthenticationError,
    BadRequestError,
    BootstrapNotReleasedError,
    ConflictError,
    ForbiddenError,
    GatewayError,
    HassetteClientError,
    HassetteConnectionError,
    HassetteHTTPError,
    HassetteTimeoutError,
    InstanceNotFoundError,
    InvalidAppKeyError,
    JobNotRegisteredError,
    NotFoundError,
    PathTraversalError,
    RedirectError,
    RequestValidationError,
    ResponseValidationError,
    ServerError,
    ServiceUnavailableError,
    SourceNotFoundError,
    SourceUnavailableError,
    TelemetryUnavailableError,
    UnexpectedResponseError,
    UnsupportedServerVersionError,
)
from hassette_client.parsing import parse_response
from hassette_client.transport import DEFAULT_REQUEST_TIMEOUT
from hassette_client.version import MIN_API_SCHEMA_VERSION, check_server_version

__all__ = [
    "DEFAULT_REQUEST_TIMEOUT",
    "MIN_API_SCHEMA_VERSION",
    "ActionFailedError",
    "AppBlockedError",
    "AppNotFoundError",
    "AuthenticationError",
    "BadRequestError",
    "BootstrapNotReleasedError",
    "ConflictError",
    "ForbiddenError",
    "GatewayError",
    "HassetteClient",
    "HassetteClientError",
    "HassetteConnectionError",
    "HassetteHTTPError",
    "HassetteTimeoutError",
    "InstanceNotFoundError",
    "InvalidAppKeyError",
    "JobNotRegisteredError",
    "NotFoundError",
    "PathTraversalError",
    "RedirectError",
    "RequestValidationError",
    "ResponseValidationError",
    "ServerError",
    "ServiceUnavailableError",
    "SourceNotFoundError",
    "SourceUnavailableError",
    "TelemetryUnavailableError",
    "UnexpectedResponseError",
    "UnsupportedServerVersionError",
    "check_server_version",
    "parse_response",
]
