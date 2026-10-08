"""HTTP mechanics behind :class:`~hassette_client.HassetteClient`: a request in, a parsed model or an exception out.

Every response is classified once, by its ``Content-Type``, and that classification decides what the
body is: a model to parse, a hassette problem, or something that didn't come from hassette.
"""

import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, TypeVar, overload
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp
from hassette_wire import ProblemDetail
from pydantic import BaseModel

from hassette_client.errors import (
    PROBLEM_MEDIA_TYPE,
    HassetteConnectionError,
    HassetteHTTPError,
    HassetteTimeoutError,
    RedirectError,
    ResponseValidationError,
    UnexpectedResponseError,
    error_class_for,
)
from hassette_client.parsing import parse_payload, type_name

LOGGER = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 10.0
"""Seconds allowed for one request, from connecting to reading the whole body."""

MAX_ERROR_BODY_BYTES = 4096
"""How much of an error body that isn't a hassette problem the client reads, such as a proxy's HTML page."""

MAX_BODY_EXCERPT_BYTES = 200
"""How many bytes of a body that isn't a parsed problem an exception keeps, decoded, in ``body_excerpt``."""

JSON_MEDIA_TYPE = re.compile(r"^application/(?:[\w.+-]+?\+)?json")
"""aiohttp's own test for a JSON media type in ``ClientResponse.json()``."""

DOT_SEGMENTS = frozenset({".", ".."})
"""Path segments that URL normalization drops or climbs."""

HttpMethod = Literal["GET", "POST", "PUT"]

T = TypeVar("T")
ErrorT = TypeVar("ErrorT", bound=Exception)


class MediaKind(StrEnum):
    """What a response's ``Content-Type`` says its body is."""

    PROBLEM = "problem"
    JSON = "json"
    OTHER = "other"
    MISSING = "missing"


@dataclass(frozen=True)
class RawResponse:
    """One response as read off the wire, before it's parsed or raised.

    ``payload`` is the whole body, except that it stops at ``MAX_ERROR_BODY_BYTES`` when ``truncated``.
    """

    status: int
    media_type: str | None
    kind: MediaKind
    payload: bytes
    truncated: bool
    location: str | None

    def excerpt(self) -> str:
        return self.payload[:MAX_BODY_EXCERPT_BYTES].decode("utf-8", errors="replace")


class Transport:
    """Sends requests to one hassette server over a session the caller owns."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        token: str | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.display_url = redact_userinfo(self.base_url)
        self.request_timeout = request_timeout
        # No token means no header at all: an empty bearer would fail closed, while a request with
        # no Authorization header can still be admitted by the server's trusted-proxy peer check.
        self.headers: Mapping[str, str] = {"Authorization": f"Bearer {token}"} if token else {}

    @overload
    async def request(
        self,
        method: HttpMethod,
        path: str,
        response_type: type[T],
        *,
        params: Mapping[str, str | int | float | None] | None = None,
        body: BaseModel | None = None,
        status_model_on_503: bool = False,
    ) -> T: ...

    @overload
    async def request(
        self,
        method: HttpMethod,
        path: str,
        response_type: Any,
        *,
        params: Mapping[str, str | int | float | None] | None = None,
        body: BaseModel | None = None,
        status_model_on_503: bool = False,
    ) -> Any: ...

    async def request(
        self,
        method: HttpMethod,
        path: str,
        response_type: Any,
        *,
        params: Mapping[str, str | int | float | None] | None = None,
        body: BaseModel | None = None,
        status_model_on_503: bool = False,
    ) -> Any:
        """Send one request and parse a successful body into ``response_type``.

        Args:
            method: The HTTP method.
            path: The request path, starting with ``/api``, with path parameters already quoted.
            response_type: What a successful body parses as.
            params: Query parameters. ``None`` values are left out, so the server applies its default.
            body: A request model, sent as JSON.
            status_model_on_503: Parse a JSON or untyped 503 body into ``response_type`` too, for the probe
                endpoints whose 503 answer is a status model rather than an error.

        Raises:
            HassetteTimeoutError: The request didn't complete in time.
            HassetteConnectionError: The request failed below HTTP.
            HassetteHTTPError: The status isn't a success for this request; the subclass is picked by
                ``errors.error_class_for``.
            UnexpectedResponseError: A 2xx body isn't JSON.
            ResponseValidationError: A 2xx JSON body didn't parse as ``response_type``.
        """
        endpoint = f"{method} {path}"
        query = {key: value for key, value in (params or {}).items() if value is not None}
        LOGGER.debug(
            "Sending %s (query parameters: %s, timeout %ss)",
            endpoint,
            ", ".join(sorted(query)) or "none",
            self.request_timeout,
        )
        started = time.perf_counter()
        response = await self.send(method, path, endpoint, query, body, status_model_on_503)
        LOGGER.debug(
            "%s returned %s (%s, %s%d bytes) in %.0f ms",
            endpoint,
            response.status,
            response.media_type or "no Content-Type",
            "over " if response.truncated else "",
            len(response.payload),
            (time.perf_counter() - started) * 1000,
        )
        return interpret_response(response, response_type, endpoint, status_model_on_503=status_model_on_503)

    async def send(
        self,
        method: HttpMethod,
        path: str,
        endpoint: str,
        query: Mapping[str, str | int | float],
        body: BaseModel | None,
        status_model_on_503: bool,
    ) -> RawResponse:
        try:
            async with self.session.request(
                method,
                self.base_url + path,
                params=query,
                json=body.model_dump(mode="json") if body is not None else None,
                headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=self.request_timeout),
                # Following a redirect would hide the forward-auth login page a proxy sent it to.
                allow_redirects=False,
            ) as response:
                media_type = parse_media_type(response.headers.get("Content-Type"))
                kind = media_kind(media_type)
                if is_excerpt_only(response.status, kind, status_model_on_503=status_model_on_503):
                    payload, truncated = await read_capped(response, MAX_ERROR_BODY_BYTES)
                    if truncated:
                        LOGGER.debug(
                            "Stopped reading %s's %s error body at %d bytes",
                            endpoint,
                            media_type or "untyped",
                            MAX_ERROR_BODY_BYTES,
                        )
                else:
                    payload, truncated = await response.read(), False
                return RawResponse(
                    response.status, media_type, kind, payload, truncated, response.headers.get("Location")
                )
        except TimeoutError as exc:
            error = HassetteTimeoutError(f"{endpoint} to {self.display_url} timed out after {self.request_timeout}s")
            raise log_raising(error, cause=exc) from exc
        except aiohttp.InvalidURL as exc:
            # Before ClientError, its base class. InvalidURL's own message is the URL, which can carry userinfo.
            error = HassetteConnectionError(f"{endpoint} to {self.display_url} failed: the URL is invalid")
            raise log_raising(error, cause=exc) from exc
        except aiohttp.ClientResponseError as exc:
            # Its message includes the request URL, userinfo and all, so only the type and status are kept.
            error = HassetteConnectionError(
                f"{endpoint} to {self.display_url} failed: {type(exc).__name__} ({exc.status})"
            )
            raise log_raising(error, cause=exc) from exc
        except aiohttp.ClientError as exc:
            error = HassetteConnectionError(f"{endpoint} to {self.display_url} failed: {exc}")
            raise log_raising(error, cause=exc) from exc


def interpret_response(response: RawResponse, response_type: Any, endpoint: str, *, status_model_on_503: bool) -> Any:
    """Turn a response into the parsed model, or raise the exception it calls for."""
    status, kind = response.status, response.kind
    if 200 <= status < 300:
        if kind is MediaKind.PROBLEM or kind is MediaKind.OTHER:
            raise log_raising(
                UnexpectedResponseError(
                    model=type_name(response_type),
                    endpoint=endpoint,
                    status=status,
                    content_type=response.media_type,
                    body_size=len(response.payload),
                    body_excerpt=response.excerpt(),
                )
            )
        if kind is MediaKind.MISSING:
            LOGGER.debug("%s sent no Content-Type; parsing the body as JSON anyway", endpoint)
        return parse_success_body(response_type, response, endpoint)
    if 300 <= status < 400:
        raise log_raising(http_error(RedirectError, response, endpoint, problem=None))
    if is_probe_status_body(status, kind, status_model_on_503=status_model_on_503):
        if kind is MediaKind.MISSING:
            LOGGER.debug("%s sent a 503 with no Content-Type; trying it as the status model", endpoint)
        probe_status = try_parse_probe_status(response_type, response, endpoint)
        if probe_status is not None:
            return probe_status
    problem = try_parse_problem(response, endpoint) if kind is MediaKind.PROBLEM else None
    raise log_raising(http_error(error_class_for(status, problem), response, endpoint, problem=problem))


def parse_success_body(response_type: Any, response: RawResponse, endpoint: str) -> Any:
    try:
        return parse_payload(
            response_type,
            response.payload,
            endpoint=endpoint,
            status=response.status,
            content_type=response.media_type,
        )
    except ResponseValidationError as exc:
        # `from None`, as in parse_payload: the chain would only lead back into this same error.
        raise log_raising(exc) from None


def try_parse_probe_status(response_type: Any, response: RawResponse, endpoint: str) -> Any | None:
    """A probe's 503 status model, or ``None`` when the body is something else.

    A JSON or untyped 503 that isn't the status model came from something else, such as a proxy whose
    upstream is down, and raises like any other unavailable response.
    """
    try:
        return parse_payload(response_type, response.payload, endpoint=endpoint)
    except ResponseValidationError:
        LOGGER.debug("%s's 503 body isn't a %s; raising it as unavailable", endpoint, type_name(response_type))
        return None


def try_parse_problem(response: RawResponse, endpoint: str) -> ProblemDetail | None:
    try:
        return parse_payload(ProblemDetail, response.payload, endpoint=endpoint)
    except ResponseValidationError:
        LOGGER.debug("%s sent a malformed problem body; classing it by status %s", endpoint, response.status)
        return None


def http_error(
    error_class: type[HassetteHTTPError], response: RawResponse, endpoint: str, *, problem: ProblemDetail | None
) -> HassetteHTTPError:
    return error_class(
        status=response.status,
        endpoint=endpoint,
        problem=problem,
        content_type=response.media_type,
        body_size=len(response.payload),
        body_truncated=response.truncated,
        body_excerpt=response.excerpt() if problem is None and response.payload else None,
        location=response.location,
    )


def log_raising(error: ErrorT, *, cause: BaseException | None = None) -> ErrorT:
    """Log ``error`` at DEBUG where it is raised, and return it so the call site can raise it.

    DEBUG only: the caller decides whether a failure is worse than that.
    """
    status = getattr(error, "status", None)
    code = getattr(error, "code", None)
    LOGGER.debug(
        "Raising %s (status %s, problem code %s%s): %s",
        type(error).__name__,
        status,
        code,
        f", from {type(cause).__module__}.{type(cause).__name__}" if cause is not None else "",
        error,
    )
    return error


def is_probe_status_body(status: int, kind: MediaKind, *, status_model_on_503: bool) -> bool:
    """Whether a response may be a probe's status model, which its route sends as a JSON 503.

    A 503 with no Content-Type qualifies too, as on a 2xx; parsing it confirms or rejects it.
    """
    return status == 503 and status_model_on_503 and kind in (MediaKind.JSON, MediaKind.MISSING)


def is_excerpt_only(status: int, kind: MediaKind, *, status_model_on_503: bool) -> bool:
    """Whether only an excerpt of the body is ever kept, so reading all of it is waste.

    Success bodies are parsed. A hassette problem is read whole, since truncating it would lose its
    code, and so is a body that may be a probe's status model.
    """
    whole_body_needed = (
        200 <= status < 300
        or kind is MediaKind.PROBLEM
        or is_probe_status_body(status, kind, status_model_on_503=status_model_on_503)
    )
    return not whole_body_needed


async def read_capped(response: aiohttp.ClientResponse, limit: int) -> tuple[bytes, bool]:
    """Read at most ``limit`` bytes of the body, and whether there was more."""
    # Reads one byte past the limit: getting it is how a longer body shows it was truncated.
    buffer = bytearray()
    while len(buffer) <= limit:
        chunk = await response.content.read(limit + 1 - len(buffer))
        if not chunk:
            break
        buffer += chunk
    return bytes(buffer[:limit]), len(buffer) > limit


def parse_media_type(header: str | None) -> str | None:
    """The media type of a ``Content-Type`` header, lowercased and without parameters."""
    if header is None:
        return None
    media_type = header.split(";", 1)[0].strip().lower()
    return media_type or None


def media_kind(media_type: str | None) -> MediaKind:
    if media_type is None:
        return MediaKind.MISSING
    if media_type == PROBLEM_MEDIA_TYPE:
        return MediaKind.PROBLEM
    if JSON_MEDIA_TYPE.match(media_type):
        return MediaKind.JSON
    return MediaKind.OTHER


def redact_userinfo(url: str) -> str:
    """``url`` without any ``user:password@``, for messages and logs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid URL>"
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


def path_segment(value: str | int) -> str:
    """Quote ``value`` for use as one path segment.

    Raises:
        ValueError: ``value`` is empty, ``.`` or ``..``, or contains ``/``. An empty segment collapses
            into its neighbors, URL normalization would drop or climb a dot segment, and the server
            decodes ``%2F`` before routing, so each would send the request to a route the caller
            didn't name.
    """
    text = str(value)
    if not text or text in DOT_SEGMENTS or "/" in text:
        raise ValueError(f"{text!r} can't be used as a path parameter")
    return quote(text, safe="")
