# dup-ignore-file: delegates Api methods through resource wrapper, shares signatures by design
import asyncio
import logging
import typing
from asyncio import CancelledError
from collections.abc import Callable
from contextlib import AsyncExitStack
from http import HTTPStatus
from typing import Any, ClassVar

import aiohttp
from hassette_wire import LogLevel
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.core.retry_policy import MAX_RETRY_ATTEMPTS
from hassette.exceptions import (
    CommandNotSentError,
    EntityNotFoundError,
    HttpRequestError,
    InvalidAuthError,
    ResponseLostError,
    ResponseTimeoutError,
)
from hassette.models.history import normalize_history
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.utils.request_utils import clean_kwargs, format_time_param, orjson_dump, unwrap_secrets
from hassette.utils.url_utils import resolve_rest_path

_SSL_SHUTDOWN_DELAY = 0.25

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.websocket_service import WebsocketService


NOT_RETRYABLE = (
    EntityNotFoundError,
    InvalidAuthError,
    RuntimeError,
    TypeError,
    AttributeError,
    CancelledError,
)
"""Failures a GET never retries; anything else, such as a timeout, is retried. Other methods retry only not-sent."""

RETRYABLE_CLIENT_ERROR_STATUSES = frozenset({HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS})
"""The 4xx statuses that describe a passing condition; every other 4xx repeats if the request is re-sent."""


class ApiResource(Resource):
    depends_on: ClassVar[list[type[Resource]]] = []

    _stack: AsyncExitStack
    """Async context stack for managing resources."""

    _session: aiohttp.ClientSession | None
    """HTTP client session for making requests."""

    _session_rest_url: str
    """The ``base_url`` the session was created with; root-relative raw paths are resolved against it."""

    def __init__(
        self,
        hassette: "Hassette",
        *,
        parent: "Resource | None" = None,
        rest_url: str | None = None,
        headers_factory: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        super().__init__(hassette, parent=parent)
        self._stack = AsyncExitStack()
        self._session = None
        self._session_rest_url = ""
        self._rest_url_override: str | None = rest_url
        self._headers_factory: Callable[[], dict[str, str]] | None = headers_factory

    async def on_initialize(self) -> None:
        """Start the API service."""
        # Use injected overrides when provided; fall back to config-derived properties.
        rest_url = self._rest_url_override if self._rest_url_override is not None else self.rest_url
        headers = self._headers_factory() if self._headers_factory is not None else self.headers
        self._session_rest_url = rest_url
        await self._stack.__aenter__()
        self._session = await self._stack.enter_async_context(aiohttp.ClientSession(headers=headers, base_url=rest_url))
        mark_ready(self, reason="API session initialized")

    async def on_shutdown(self) -> None:
        """Close the HTTP session, pausing briefly when SSL verification is on so TLS transports can finish closing."""
        await self._stack.aclose()
        await asyncio.sleep(_SSL_SHUTDOWN_DELAY if self.hassette.config.verify_ssl else 0)

    @property
    def config_log_level(self) -> LogLevel:
        """Return the configured log level for the API resource (``logging.api``)."""
        return self.hassette.config.logging.api

    @property
    def headers(self) -> dict[str, str]:
        """Get the headers for this API instance."""
        return self.hassette.config.headers

    @property
    def rest_url(self) -> str:
        """Get the REST URL for this API instance."""
        return self.hassette.rest_url

    @property
    def ws_conn(self) -> "WebsocketService":
        """Get the WebSocket connection for this API instance."""
        return self.hassette.websocket_service

    async def rest_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        suppress_error_message: bool = False,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """Make a REST request to the Home Assistant API.

        Transport failures are mapped onto delivery states: a refused, DNS or TLS connect failure or a
        closed session raises ``CommandNotSentError``, a timeout (including one while connecting) raises
        ``ResponseTimeoutError``, and a connection dropped before the response headers arrived raises
        ``ResponseLostError``. A 404 raises ``EntityNotFoundError`` and any other error status
        ``HttpRequestError``. A failure while the caller reads the response body is not mapped.

        A GET is retried on any of these except a 4xx other than 408/429 (and the ``NOT_RETRYABLE``
        types, such as a caller's ``TypeError``). Any other method is retried only on
        ``CommandNotSentError`` (see ``is_retryable_rest_failure``), so the class raised after retries
        describes the whole call.

        Raises:
            CommandNotSentError: If the request never reached Home Assistant.
            ResponseTimeoutError: If no response arrived in time; the request may or may not have applied.
            ResponseLostError: If the connection dropped while waiting; the request may or may not have applied.
            EntityNotFoundError: If Home Assistant answered 404.
            HttpRequestError: If Home Assistant answered with any other error status.
        """

        # inner function to allow retry decorator to use `self`
        @retry(
            retry=retry_if_exception(lambda exc: is_retryable_rest_failure(exc, method)),
            wait=wait_exponential_jitter(),
            stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
            before_sleep=before_sleep_log(self.logger, logging.WARNING),
            reraise=True,
        )
        async def inner_request(
            method: str,
            url: str,
            params: dict[str, Any] | None = None,
            data: dict[str, Any] | None = None,
            suppress_error_message: bool = False,
            **kwargs,
        ) -> aiohttp.ClientResponse:
            if self._session is None or self._session.closed:
                raise CommandNotSentError(f"{method} {url}: not sent, the REST client session is not connected")

            params = clean_kwargs(**(params or {}))
            # HA gets SecretStr plaintext; the DEBUG line below serializes the original payload, which masks it.
            str_data = orjson_dump(unwrap_secrets(data or {}))

            request_kwargs = {}

            if str_data:
                request_kwargs["data"] = str_data
                request_kwargs["headers"] = {"Content-Type": "application/json"}

            if params:
                request_kwargs["params"] = params

            if "timeout" in kwargs:
                deadline = "the caller's timeout"
            else:
                total = self.hassette.config.rest_request_timeout_seconds
                deadline = f"{total}s (rest_request_timeout_seconds)"
                request_kwargs["timeout"] = aiohttp.ClientTimeout(total=total)

            try:
                response = await self._session.request(
                    method,
                    resolve_rest_path(self._session_rest_url, url),
                    ssl=self.hassette.config.verify_ssl,
                    **request_kwargs,
                    **kwargs,
                )
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(
                        "Making %s request to %s with data %s", method, response.real_url, orjson_dump(data or {})
                    )
                response.raise_for_status()

                return response
            except aiohttp.ClientResponseError as exc:
                if exc.status == HTTPStatus.NOT_FOUND:
                    if not suppress_error_message:
                        self.logger.error(
                            "Error occurred while making %s request to %s: %s", method, url, exc, stacklevel=2
                        )

                    raise EntityNotFoundError(f"Entity not found: {url}") from None
                raise HttpRequestError(exc.status, exc.message, method=method, url=url) from exc

            except (aiohttp.ClientError, TimeoutError) as exc:
                if not suppress_error_message:
                    self.logger.error(
                        "Error occurred while making %s request to %s: %s", method, url, exc, stacklevel=2
                    )
                mapped = delivery_state_error(exc, method=method, url=url, deadline=deadline)
                if mapped is None:
                    raise
                raise mapped from exc

        return await inner_request(
            method, url, params=params, data=data, suppress_error_message=suppress_error_message, **kwargs
        )

    async def get_history_raw(
        self,
        entity_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Get the history of a specific entity."""
        url = f"history/period/{format_time_param(start_time)}"

        params = {
            "filter_entity_id": entity_id,
            "end_time": end_time,
            "significant_changes_only": significant_changes_only,
            "minimal_response": minimal_response,
            "no_attributes": no_attributes,
        }
        # having parameters like `minimal_response` in the parameters changes the response format
        # regardless of whether they are set to True or False
        # so we remove them if they are False
        params = {k: v for k, v in params.items() if v is not False}

        response = await self.rest_request("GET", url, params=params)

        entries = await response.json()

        normalized = normalize_history(entries)

        return normalized


def delivery_state_error(exc: BaseException, *, method: str, url: str, deadline: str) -> Exception | None:
    """Map a REST transport failure onto its delivery-state class, or None to let it propagate raw.

    ``ClientConnectorError`` (refused, DNS, TLS) is a ``ClientConnectionError``, so it comes first.
    A connect that times out is reported as a response timeout, not as not sent: telling the two
    apart would rest on how aiohttp labels its internal connect timer. Any other ``ClientError`` (an
    invalid URL, a redirect or payload error) is a caller bug or a response Home Assistant already sent.
    """
    if isinstance(exc, aiohttp.ClientConnectorError):
        return CommandNotSentError(f"{method} {url}: not sent, could not connect to Home Assistant")
    if isinstance(exc, TimeoutError):
        return ResponseTimeoutError(
            f"{method} {url}: no response within {deadline}; the request may or may not have applied"
        )
    if isinstance(exc, aiohttp.ClientConnectionError):
        return ResponseLostError(
            f"{method} {url}: connection lost while waiting for a response; the request may or may not have applied"
        )
    return None


def is_retryable_rest_failure(exc: BaseException, method: str) -> bool:
    """Return whether a failed REST attempt may be sent again.

    Any method other than GET retries only a request that never reached Home Assistant, so Hassette never
    re-sends a write after it may have applied or after Home Assistant answered it. aiohttp's own retry of
    an idempotent method (DELETE, PUT) on a stale keep-alive connection sits below this and isn't covered.
    """
    if method.upper() != "GET":
        return isinstance(exc, CommandNotSentError)
    if isinstance(exc, HttpRequestError):
        is_client_error = HTTPStatus.BAD_REQUEST <= exc.status < HTTPStatus.INTERNAL_SERVER_ERROR
        return not is_client_error or exc.status in RETRYABLE_CLIENT_ERROR_STATUSES
    return not isinstance(exc, NOT_RETRYABLE)
