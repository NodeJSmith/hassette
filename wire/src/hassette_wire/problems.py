from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from hassette_wire.lenient import LenientValue, UnknownValue


class ProblemCode(StrEnum):
    """Machine-readable reason carried in the ``code`` member of every web API error body.

    Each code maps to exactly one HTTP status, except ``http_error``, which carries whatever
    status the underlying error had. Before 1.0, renaming or removing a code, or changing its
    status, is a breaking change and is flagged as one; adding a code is not.
    """

    INVALID_APP_KEY = "invalid_app_key"
    """400: the app key in the path is not a syntactically valid app key."""

    APP_NOT_FOUND = "app_not_found"
    """404: no app with this key is configured."""

    INSTANCE_NOT_FOUND = "instance_not_found"
    """404: the instance index is out of range for the app's current config."""

    BOOTSTRAP_NOT_RELEASED = "bootstrap_not_released"
    """409: app bootstrap prerequisites are not ready yet. Retry later."""

    APP_BLOCKED = "app_blocked"
    """409: the app is excluded by the ``--app`` filter. Retrying won't help."""

    ACTION_IN_PROGRESS = "action_in_progress"
    """409: another start, stop, or reload on this app is still running. Nothing was done."""

    ACTION_FAILED = "action_failed"
    """500: the start, stop, or reload ran but failed, or left a targeted instance failed."""

    TELEMETRY_UNAVAILABLE = "telemetry_unavailable"
    """503: the telemetry store could not be read."""

    SOURCE_NOT_FOUND = "source_not_found"
    """404: the app's source file does not exist."""

    PATH_TRAVERSAL = "path_traversal"
    """403: the app's source path resolves outside its app directory."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    """500: the app's source file exists but could not be read."""

    INVALID_TOKEN = "invalid_token"  # noqa: S105 - an error code, not a credential
    """401: the token presented to the login exchange is wrong."""

    NOT_AUTHENTICATED = "not_authenticated"
    """401: the request carried no valid credential."""

    JOB_NOT_REGISTERED = "job_not_registered"
    """409: the scheduled job has no live registration."""

    VALIDATION_FAILED = "validation_failed"
    """422: a path, query, or body value failed validation."""

    BODY_TOO_LARGE = "body_too_large"
    """413: the request body exceeds the server's size limit."""

    NOT_FOUND = "not_found"
    """404: no resource exists at this path."""

    METHOD_NOT_ALLOWED = "method_not_allowed"
    """405: the path exists but does not accept this method."""

    HTTP_ERROR = "http_error"
    """Any other HTTP error; its status is the response status."""

    INTERNAL_ERROR = "internal_error"
    """500: an unexpected server error."""


OpenProblemCode = Annotated[ProblemCode | UnknownValue, LenientValue("ProblemCode")]


class ProblemDetail(BaseModel):
    """RFC 9457 problem details body returned, as ``application/problem+json``, for every web API error."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    type: str = "about:blank"
    """Problem type URI. Always ``about:blank``: ``code`` carries the specific meaning."""

    title: str
    """The HTTP reason phrase for ``status``."""

    status: int
    """The HTTP status code of the response."""

    detail: str
    """Human-readable explanation of this occurrence."""

    code: OpenProblemCode
    """Machine-readable reason for the error."""
