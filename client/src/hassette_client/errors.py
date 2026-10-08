"""Exceptions raised by :class:`~hassette_client.HassetteClient`.

Every network or server failure surfaces as a :class:`HassetteClientError`, never as a raw ``aiohttp``
or ``pydantic`` exception. Catch the specific subclass a caller can act on, or ``HassetteClientError``
for all of them. Invalid arguments raise ``ValueError`` instead, and a closed session raises aiohttp's
own ``RuntimeError``: both are bugs in the calling code, not failures to recover from.

An error response resolves to its exception class in three steps:

1. A problem-details body whose ``code`` is in :data:`CODE_ERRORS` raises that code's class.
2. Otherwise the HTTP status picks the class, by :data:`STATUS_ERRORS`, then by family: any 3xx is
   :class:`RedirectError` and any other 5xx is :class:`ServerError`.
3. Anything else raises :class:`HassetteHTTPError` itself.

A body that isn't a hassette problem, such as a reverse proxy's HTML error page, or a ``code`` newer
than this client, skips step 1.

The classes say what failed, not whether to try again; the client never retries. The docs page "Call
the API from Python" lists which failures are worth retrying and which leave a write's outcome unknown.
"""

import inspect
from collections.abc import Mapping
from typing import Any

from hassette_wire import ProblemCode, ProblemDetail, UnknownValue

PROBLEM_MEDIA_TYPE = "application/problem+json"

GENERIC_CODES: frozenset[ProblemCode] = frozenset(
    {
        ProblemCode.INVALID_TOKEN,
        ProblemCode.NOT_AUTHENTICATED,
        ProblemCode.VALIDATION_FAILED,
        ProblemCode.BODY_TOO_LARGE,
        ProblemCode.NOT_FOUND,
        ProblemCode.METHOD_NOT_ALLOWED,
        ProblemCode.HTTP_ERROR,
        ProblemCode.INTERNAL_ERROR,
    }
)
"""The problem codes that deliberately resolve by status alone.

Each says nothing a caller can act on beyond what its status already says. Every ``ProblemCode`` is
in exactly one of this set and :data:`CODE_ERRORS` (below), so a code added on the server fails the client's
tests until someone decides which it belongs to.
"""


class HassetteClientError(Exception):
    """Base class for every network or server failure :class:`~hassette_client.HassetteClient` raises."""

    def __reduce__(self) -> str | tuple[Any, ...]:
        # Default exception pickling calls ``cls(*self.args)``, which can't reach keyword-only
        # constructors. A class whose ``__init__`` takes keyword-only fields is rebuilt from them, so
        # each must be stored under its own name. The full instance state then overwrites the rebuilt
        # one, which sets those fields a second time (harmlessly) and restores ``__notes__`` and any
        # attribute added after construction. Both travel as arguments, so ``copy.deepcopy`` copies them.
        parameters = inspect.signature(type(self).__init__).parameters.values()
        fields = [p.name for p in parameters if p.kind is inspect.Parameter.KEYWORD_ONLY]
        if not fields:
            return super().__reduce__()
        return rebuild, (type(self), {name: getattr(self, name) for name in fields}), self.__dict__


class HassetteConnectionError(HassetteClientError):
    """The request never got a complete HTTP response: refused, reset, DNS or TLS failure, or a bad URL.

    A malformed ``base_url`` raises this too, so a config flow can treat it like an unreachable server.
    The server may or may not have received the request. A TLS or URL failure won't go away on its own.
    """


class HassetteTimeoutError(HassetteClientError):
    """The request didn't complete within the client's ``request_timeout``.

    The outcome is unknown: the server may have carried out the request, or may still be working on it.
    """


class ResponseValidationError(HassetteClientError):
    """A response body didn't match the model it should parse as.

    Unknown fields and unknown enum values never cause this; lenient parsing absorbs them. It means
    a field was renamed, retyped or removed, or the server isn't hassette. The message names the
    endpoint, the model and each failing field location, but never the values that failed, since
    those come from the server's payload. A 422 from the server is :class:`RequestValidationError`.

    On a 2xx response from hassette, the server has already done what was asked and only its answer
    failed to parse. A proxy in front of hassette can also answer 2xx, so on a write, check the
    outcome before sending it again.
    """

    def __init__(
        self,
        *,
        model: str,
        endpoint: str | None,
        problems: list[str],
        status: int | None = None,
        content_type: str | None = None,
    ) -> None:
        self.model = model
        """The name of the type the body was parsed as."""
        self.endpoint = endpoint
        """``"<METHOD> <path>"`` of the request, or ``None`` for a parse outside a request."""
        self.problems = problems
        """One ``"<location>: <error type>"`` entry per validation failure."""
        self.status = status
        """The response's HTTP status, or ``None`` for a parse outside a request."""
        self.content_type = content_type
        """The response's media type, or ``None`` when it had none or for a parse outside a request."""
        super().__init__(self.describe())

    def describe(self) -> str:
        """The exception's message. ``__init__`` calls it last, so an override can read every attribute."""
        where = f" from {self.endpoint}" if self.endpoint else ""
        return f"Response{where} does not match {self.model}: {'; '.join(self.problems)}"


class UnexpectedResponseError(ResponseValidationError):
    """A 2xx response whose body isn't JSON, so it most likely didn't come from hassette.

    A login page from a proxy in front of hassette, or the web UI's HTML because ``base_url`` points
    at the wrong path. The outcome of a write is unknown: the request may never have reached hassette.
    """

    def __init__(
        self,
        *,
        model: str,
        endpoint: str | None,
        status: int | None,
        content_type: str | None,
        body_size: int,
        body_excerpt: str,
    ) -> None:
        # Set before super().__init__(), which builds the message from describe() below.
        self.body_size = body_size
        """The body's length in bytes."""
        self.body_excerpt = body_excerpt
        """The start of the body, for diagnosis. Kept out of the message, since it is the server's payload."""
        super().__init__(
            model=model,
            endpoint=endpoint,
            problems=[f"<body>: not_json ({content_type or 'no Content-Type'})"],
            status=status,
            content_type=content_type,
        )

    def describe(self) -> str:
        return (
            f"{self.endpoint} returned {self.status} with a non-JSON body "
            f"({self.content_type or 'no Content-Type'}, {self.body_size} bytes) where {self.model} was expected: "
            "check base_url, or whether a proxy answered"
        )


class UnsupportedServerVersionError(HassetteClientError):
    """The server's API schema is older than :data:`~hassette_client.MIN_API_SCHEMA_VERSION`.

    Raised only by :func:`~hassette_client.check_server_version`.
    """

    def __init__(self, *, server_version: str, api_schema_version: int, min_api_schema_version: int) -> None:
        self.server_version = server_version
        """The release version the server reported, for display."""
        self.api_schema_version = api_schema_version
        """The API schema the server reported, ``0`` for a server too old to report one."""
        self.min_api_schema_version = min_api_schema_version
        """The oldest API schema this client release supports."""
        served = f"serves API schema {api_schema_version}" if api_schema_version else "reports no API schema"
        super().__init__(
            f"hassette server {server_version or '(unknown version)'} {served}, older than "
            f"{min_api_schema_version}, the oldest this hassette-client supports: upgrade the hassette server, "
            "or install an older hassette-client"
        )


class HassetteHTTPError(HassetteClientError):
    """The server, or something in front of it, answered with a status this method doesn't treat as success.

    A hassette error carries its parsed ``problem``, and its ``detail`` is part of the message. Any other
    body is kept only as a short ``body_excerpt``, out of the message, since it is the server's payload.
    """

    def __init__(
        self,
        *,
        status: int,
        endpoint: str,
        problem: ProblemDetail | None,
        content_type: str | None = None,
        body_size: int = 0,
        body_truncated: bool = False,
        body_excerpt: str | None = None,
        location: str | None = None,
    ) -> None:
        self.status = status
        """The HTTP status code."""
        self.endpoint = endpoint
        """``"<METHOD> <path>"`` of the request."""
        self.problem = problem
        """The parsed problem-details body, or ``None`` when the body isn't one."""
        self.content_type = content_type
        """The response's media type, or ``None`` when it had none."""
        self.body_size = body_size
        """The bytes of body read. A lower bound when ``body_truncated``."""
        self.body_truncated = body_truncated
        """Whether the client stopped reading a long non-problem body early."""
        self.body_excerpt = body_excerpt
        """The start of a body that isn't a parsed problem, or ``None`` when ``problem`` is set."""
        self.location = location
        """The ``Location`` header, when the response carried one."""
        super().__init__(f"{endpoint} returned {status}{self.describe_body()}")

    @property
    def code(self) -> ProblemCode | UnknownValue | None:
        """The problem's ``code``, or ``None`` when the body isn't a problem."""
        return self.problem.code if self.problem is not None else None

    @property
    def detail(self) -> str | None:
        """The problem's ``detail``, or ``None`` when the body isn't a problem."""
        return self.problem.detail if self.problem is not None else None

    def describe_body(self) -> str:
        """The message's suffix after the status: the problem's detail, or the body's media type and size."""
        if self.problem is not None:
            return f": {self.problem.detail}" if self.problem.detail else ""
        if self.body_size == 0:
            return " (empty body)"
        size = f"more than {self.body_size}" if self.body_truncated else str(self.body_size)
        malformed = "malformed problem body, " if self.content_type == PROBLEM_MEDIA_TYPE else ""
        return f" ({malformed}{self.content_type or 'no Content-Type'}, {size} bytes)"


class RedirectError(HassetteHTTPError):
    """A 3xx. Hassette's API never redirects, so something in front of it did.

    Usually a forward-auth proxy sending the request to its login page. ``location`` says where.
    """


class BadRequestError(HassetteHTTPError):
    """400: the server rejected the request as malformed."""


class InvalidAppKeyError(BadRequestError):
    """400 ``invalid_app_key``: the app key is not a syntactically valid app key."""


class AuthenticationError(HassetteHTTPError):
    """401: the request carried no credential the server accepts, or the token was wrong."""


class ForbiddenError(HassetteHTTPError):
    """403: the server refuses the request."""


class PathTraversalError(ForbiddenError):
    """403 ``path_traversal``: the app's source path resolves outside its app directory."""


class NotFoundError(HassetteHTTPError):
    """404: nothing exists at this path."""


class AppNotFoundError(NotFoundError):
    """404 ``app_not_found``: no app with this key is configured."""


class InstanceNotFoundError(NotFoundError):
    """404 ``instance_not_found``: the instance index is out of range for the app's config."""


class SourceNotFoundError(NotFoundError):
    """404 ``source_not_found``: the app's source file does not exist."""


class ConflictError(HassetteHTTPError):
    """409: the request conflicts with the server's current state."""


class BootstrapNotReleasedError(ConflictError):
    """409 ``bootstrap_not_released``: app bootstrap prerequisites aren't ready yet. Worth retrying later."""


class AppBlockedError(ConflictError):
    """409 ``app_blocked``: the server's ``--app`` filter excludes this app."""


class JobNotRegisteredError(ConflictError):
    """409 ``job_not_registered``: the scheduled job has no live registration."""


class RequestValidationError(HassetteHTTPError):
    """422: a path, query or body value failed the server's validation.

    A response the client can't parse is :class:`ResponseValidationError`.
    """


class ServerError(HassetteHTTPError):
    """5xx: the server, or a proxy in front of it, failed."""


class ActionFailedError(ServerError):
    """500 ``action_failed``: the start, stop or reload ran but failed, or left an instance failed."""


class SourceUnavailableError(ServerError):
    """500 ``source_unavailable``: the app's source file exists but couldn't be read."""


class GatewayError(ServerError):
    """502 or 504: a proxy in front of hassette couldn't get a response from it.

    hassette may still have received the request, and may still be working on it.
    """


class ServiceUnavailableError(ServerError):
    """503: the server can't serve this request right now.

    Worth retrying later on a read. Hassette never answers a write with 503, so on a write it came from
    a proxy and the outcome is unknown: check before sending it again.
    """


class TelemetryUnavailableError(ServiceUnavailableError):
    """503 ``telemetry_unavailable``: the telemetry store couldn't be read."""


CODE_ERRORS: Mapping[ProblemCode, type[HassetteHTTPError]] = {
    ProblemCode.INVALID_APP_KEY: InvalidAppKeyError,
    ProblemCode.APP_NOT_FOUND: AppNotFoundError,
    ProblemCode.INSTANCE_NOT_FOUND: InstanceNotFoundError,
    ProblemCode.BOOTSTRAP_NOT_RELEASED: BootstrapNotReleasedError,
    ProblemCode.APP_BLOCKED: AppBlockedError,
    ProblemCode.ACTION_FAILED: ActionFailedError,
    ProblemCode.TELEMETRY_UNAVAILABLE: TelemetryUnavailableError,
    ProblemCode.SOURCE_NOT_FOUND: SourceNotFoundError,
    ProblemCode.PATH_TRAVERSAL: PathTraversalError,
    ProblemCode.SOURCE_UNAVAILABLE: SourceUnavailableError,
    ProblemCode.JOB_NOT_REGISTERED: JobNotRegisteredError,
}
"""The problem codes that raise their own class. Every other code resolves by status."""

STATUS_ERRORS: Mapping[int, type[HassetteHTTPError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: RequestValidationError,
    502: GatewayError,
    503: ServiceUnavailableError,
    504: GatewayError,
}
"""The statuses with their own class when no problem code picks a more specific one."""


def error_class_for(status: int, problem: ProblemDetail | None) -> type[HassetteHTTPError]:
    """Return the exception class for an error response: by problem code, then status, then family."""
    if problem is not None and isinstance(problem.code, ProblemCode) and problem.code in CODE_ERRORS:
        return CODE_ERRORS[problem.code]
    if status in STATUS_ERRORS:
        return STATUS_ERRORS[status]
    if 300 <= status < 400:
        return RedirectError
    if 500 <= status < 600:
        return ServerError
    return HassetteHTTPError


def rebuild(error_class: type[HassetteClientError], fields: dict[str, Any]) -> HassetteClientError:
    """Reconstruct an exception from its keyword-only ``__init__`` fields, for ``pickle`` and ``copy``."""
    return error_class(**fields)
