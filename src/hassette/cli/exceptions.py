"""Exceptions raised by :mod:`hassette.cli.target`'s server-URL and credential resolution."""

from hassette.exceptions import FatalError


class ServerUrlError(FatalError):
    """Base class for every way a CLI ``--server-url``/``cli.server_url`` target fails to resolve.

    Raised before the CLI opens any network connection to the target.

    Kept as one base rather than folding every failure mode into a single exception, so a caller
    that only cares "did the server-url resolve" can catch one type, while a caller that wants to
    render a distinct message per failure mode can catch the specific subclass.
    """


class ServerUrlSchemeRequiredError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` must include a scheme (http:// or https://).

    Distinct from :class:`SchemeRequiredInBaseUrlError`, which covers ``HassetteConfig.base_url``
    (the Home Assistant connection target) — this covers ``cli.server_url``/``--server-url``
    (the target the CLI itself connects to), a different config field with a different audience.
    """


class ServerUrlApiSuffixError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` path ends in ``/api``.

    Every command path already starts with ``/api/...``, so a ``server_url`` ending in ``/api``
    would double up (``/api/api/health``). The message names the corrected form so a user who
    copied a URL like ``https://hassette.example.com/hassette/api`` straight out of an issue or
    doc knows exactly what to drop.
    """


class ServerUrlParseError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` could not be parsed at all.

    Raised when constructing a ``yarl.URL`` from the cleaned ``server_url`` string raises
    ``ValueError`` (e.g. a non-numeric port like ``host:notnum``, or malformed IPv6 brackets like
    ``[bad]``). Wraps the ``yarl`` parse failure with the CLI's structured usage-error path
    (``error_usage()``) instead of letting it propagate as a bare, unhandled traceback.
    """


class ServerUrlHostRequiredError(ServerUrlError):
    """Custom exception to indicate that a CLI ``server_url`` has a valid scheme but no usable host.

    Covers URLs like ``https:///foo``, which parse successfully and have an accepted http/https
    scheme but resolve to an empty/``None`` host — a URL that would otherwise silently build an
    unusable base URL rather than failing with a clear, attributable message.
    """


class CredentialResolutionError(FatalError):
    """Custom exception to indicate that a CLI bearer credential could not be resolved.

    Raised by :func:`hassette.cli.target.resolve_cli_auth_token`'s helpers for both of its
    user-attributable failure modes: an unreadable ``--token-file`` and a credential value that
    is not safe for use as an HTTP header (non-ASCII or containing control characters). Kept as
    its own typed exception — rather than a bare ``ValueError`` — so a caller can catch this
    specific failure and route it through ``error_usage()`` without also swallowing unrelated
    ``ValueError``s raised deeper in the call chain (e.g. from Pydantic validation), matching the
    same convention :class:`ServerUrlSchemeRequiredError`/:class:`ServerUrlApiSuffixError`
    already establish for the URL-resolution side of the same module.
    """
