import logging
import typing
from asyncio import CancelledError
from contextlib import AsyncExitStack
from logging import getLogger
from typing import Any

import aiohttp
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from whenever import Date, PlainDateTime, ZonedDateTime

from hassette.exceptions import (
    ConnectionClosedError,
    EntityNotFoundError,
    InvalidAuthError,
    ResourceNotReadyError,
)
from hassette.models.history import normalize_history
from hassette.resources.base import Resource
from hassette.utils.request_utils import clean_kwargs, orjson_dump

if typing.TYPE_CHECKING:
    from hassette import Hassette


LOGGER = getLogger(__name__)
NOT_RETRYABLE = (
    EntityNotFoundError,
    InvalidAuthError,
    RuntimeError,
    ConnectionClosedError,
    TypeError,
    AttributeError,
    CancelledError,
)
RETRYABLE = (aiohttp.ClientError, ResourceNotReadyError)


class ApiResource(Resource):
    _stack: AsyncExitStack
    """Async context stack for managing resources."""

    _session: aiohttp.ClientSession | None
    """HTTP client session for making requests."""

    @classmethod
    def create(cls, hassette: "Hassette"):
        inst = cls(hassette, parent=hassette)
        inst._stack = AsyncExitStack()
        inst._session = None
        return inst

    async def on_initialize(self):
        """
        Start the API service.
        """
        await self._stack.__aenter__()
        self._session = await self._stack.enter_async_context(
            aiohttp.ClientSession(headers=self._headers, base_url=self._rest_url)
        )
        await self.hassette.wait_for_ready(self.hassette._websocket_service)
        self.mark_ready(reason="API session initialized")

    async def on_shutdown(self, *args, **kwargs) -> None:
        await self._stack.aclose()

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.log_level

    @property
    def _headers(self) -> dict[str, str]:
        """Get the headers for this API instance."""
        return self.hassette.config.headers

    @property
    def _rest_url(self) -> str:
        """Get the REST URL for this API instance."""
        return self.hassette.rest_url

    @property
    def _ws_conn(self):
        """Get the WebSocket connection for this API instance."""
        return self.hassette._websocket_service

    async def _rest_request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        suppress_error_message: bool = False,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """Make a REST request to the Home Assistant API."""

        # inner function to allow retry decorator to use `self`
        @retry(
            retry=(retry_if_not_exception_type(NOT_RETRYABLE) | retry_if_exception_type(RETRYABLE)),
            wait=wait_exponential_jitter(),
            stop=stop_after_attempt(5),
            before_sleep=before_sleep_log(self.logger, logging.WARNING),
            reraise=True,
        )
        async def _inner_request(
            method: str,
            url: str,
            params: dict[str, Any] | None = None,
            data: dict[str, Any] | None = None,
            suppress_error_message: bool = False,
            **kwargs,
        ) -> aiohttp.ClientResponse:
            if self._session is None:
                raise RuntimeError("Client session is not connected")

            params = clean_kwargs(**(params or {}))
            str_data = orjson_dump(data or {})

            request_kwargs = {}

            if str_data:
                request_kwargs["data"] = str_data
                request_kwargs["headers"] = {"Content-Type": "application/json"}

            if params:
                request_kwargs["params"] = params

            try:
                response = await self._session.request(
                    method, url, ssl=self.hassette.config.verify_ssl, **request_kwargs, **kwargs
                )
                self.logger.debug("Making %s request to %s with data %s", method, response.real_url, str_data)
                response.raise_for_status()

                return response
            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    if not suppress_error_message:
                        self.logger.error(
                            "Error occurred while making %s request to %s: %s", method, url, e, stacklevel=2
                        )

                    raise EntityNotFoundError(f"Entity not found: {url}") from None
                raise

            except aiohttp.ClientError as e:
                if not suppress_error_message:
                    self.logger.error("Error occurred while making %s request to %s: %s", method, url, e, stacklevel=2)

                raise

        return await _inner_request(
            method, url, params=params, data=data, suppress_error_message=suppress_error_message, **kwargs
        )

    async def _get_history_raw(
        self,
        entity_id: str,
        start_time: PlainDateTime | ZonedDateTime | Date | str,
        end_time: PlainDateTime | ZonedDateTime | Date | str | None = None,
        significant_changes_only: bool = False,
        minimal_response: bool = False,
        no_attributes: bool = False,
    ) -> list[list[dict[str, Any]]]:
        """Get the history of a specific entity."""

        url = f"history/period/{start_time}"

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

        response = await self._rest_request("GET", url, params=params)

        entries = await response.json()

        normalized = normalize_history(entries)

        return normalized
