"""How ``ApiResource`` maps REST transport failures onto delivery states, and which it retries per method.

The integration counterpart, ``tests/integration/test_api_rest_retry.py``, drives real requests at a stub
server; these tests pin the mapping order for the aiohttp classes a stub can't easily produce.
"""

import pytest
from aiohttp import (
    ClientConnectionResetError,
    ClientConnectorDNSError,
    ClientConnectorError,
    ClientOSError,
    ClientPayloadError,
    ConnectionTimeoutError,
    InvalidURL,
    ServerDisconnectedError,
    ServerTimeoutError,
    SocketTimeoutError,
    TooManyRedirects,
)
from aiohttp.client_reqrep import ConnectionKey

from hassette.core.api_resource import delivery_state_error, is_retryable_rest_failure
from hassette.exceptions import (
    CommandNotSentError,
    CommandRejectedError,
    EntityNotFoundError,
    HttpRequestError,
    ResponseLostError,
    ResponseTimeoutError,
)

CONNECTION_KEY = ConnectionKey("ha.local", 8123, False, True, None, None, None)

ALL_FAILURES = [
    pytest.param(CommandNotSentError("x"), id="not_sent"),
    pytest.param(ResponseTimeoutError("x"), id="timeout"),
    pytest.param(ResponseLostError("x"), id="lost"),
    pytest.param(HttpRequestError(503, "Service Unavailable", method="POST", url="states"), id="503"),
    pytest.param(HttpRequestError(429, "Too Many Requests", method="POST", url="states"), id="429"),
    pytest.param(HttpRequestError(400, "Bad Request", method="POST", url="states"), id="400"),
    pytest.param(EntityNotFoundError("missing"), id="404"),
    pytest.param(CommandRejectedError("x"), id="rejected"),
]


def connector_error(cls: type[ClientConnectorError] = ClientConnectorError) -> ClientConnectorError:
    return cls(CONNECTION_KEY, OSError(111, "Connection refused"))


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        pytest.param(connector_error(), CommandNotSentError, id="connector"),
        pytest.param(connector_error(ClientConnectorDNSError), CommandNotSentError, id="dns"),
        pytest.param(ConnectionTimeoutError("connect"), ResponseTimeoutError, id="connect_timeout"),
        pytest.param(SocketTimeoutError("read"), ResponseTimeoutError, id="read_timeout"),
        pytest.param(ServerTimeoutError("read"), ResponseTimeoutError, id="server_timeout"),
        pytest.param(TimeoutError(), ResponseTimeoutError, id="total_timeout"),
        pytest.param(ServerDisconnectedError(), ResponseLostError, id="disconnected"),
        pytest.param(ClientConnectionResetError("reset"), ResponseLostError, id="reset"),
        pytest.param(ClientOSError(104, "reset by peer"), ResponseLostError, id="os_error"),
    ],
)
def test_transport_failures_map_to_their_delivery_state(exc: BaseException, expected: type[Exception]) -> None:
    mapped = delivery_state_error(exc, method="POST", url="states/light.kitchen", deadline="30s")

    assert type(mapped) is expected
    assert "POST states/light.kitchen" in str(mapped)


@pytest.mark.parametrize(
    "exc",
    [InvalidURL("not a url"), ClientPayloadError("truncated"), TooManyRedirects(None, ())],  # pyright: ignore[reportArgumentType]
    ids=["invalid_url", "payload", "redirects"],
)
def test_other_client_errors_stay_raw(exc: BaseException) -> None:
    """A caller bug or a response Home Assistant already sent isn't a delivery-state failure."""
    assert delivery_state_error(exc, method="GET", url="states", deadline="30s") is None


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT", "post"])
@pytest.mark.parametrize("exc", ALL_FAILURES)
def test_non_get_retries_only_not_sent(method: str, exc: BaseException) -> None:
    assert is_retryable_rest_failure(exc, method) is isinstance(exc, CommandNotSentError)


@pytest.mark.parametrize(
    ("exc", "retryable"),
    [
        pytest.param(CommandNotSentError("x"), True, id="not_sent"),
        pytest.param(ResponseTimeoutError("x"), True, id="timeout"),
        pytest.param(ResponseLostError("x"), True, id="lost"),
        pytest.param(HttpRequestError(503, "Service Unavailable", method="GET", url="states"), True, id="503"),
        pytest.param(HttpRequestError(400, "Bad Request", method="GET", url="states"), False, id="400"),
        pytest.param(EntityNotFoundError("missing"), False, id="404"),
    ],
)
def test_get_retries_transport_failures_and_transient_statuses(exc: BaseException, retryable: bool) -> None:
    assert is_retryable_rest_failure(exc, "GET") is retryable
