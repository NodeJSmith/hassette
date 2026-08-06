"""CLI target and credential resolution.

Decides *where* the CLI connects (:func:`resolve_server_target`) and *which* bearer credential,
if any, it may attach to outgoing requests (:func:`resolve_cli_auth_token`). Kept out of
``cli/client.py`` because that module already mixes transport, error rendering, and app-routing
concerns — resolution is pure and independently testable without an HTTP client.

Neither function takes ``CLIContext``: it is a cyclopts-only carrier type built by the meta
launcher, and taking it here would make these functions untestable without fabricating one.
``make_client(ctx)`` in ``cli/client.py`` is the single place that unpacks a ``CLIContext`` into
the keyword arguments these functions accept.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from yarl import URL

from hassette.cli.client import format_host, substitute_host
from hassette.config.config import HassetteConfig
from hassette.exceptions import CredentialResolutionError, ServerUrlApiSuffixError, ServerUrlSchemeRequiredError
from hassette.utils.net_utils import is_loopback_host
from hassette.web.auth import TOKEN_FILENAME


@dataclass(frozen=True)
class ServerTarget:
    """The resolved connect target for a single CLI invocation."""

    base_url: str
    is_loopback: bool
    verify_ssl: bool


@dataclass(frozen=True)
class CredentialInputs:
    """Everything a :class:`CredentialSource` resolver needs to attempt resolution."""

    config: HassetteConfig
    token_file_flag: Path | None


@dataclass(frozen=True)
class CredentialSource:
    """One entry in the credential precedence chain.

    ``scope`` is the data model, not documentation: ``resolve_cli_auth_token`` skips any
    ``"server"``-scoped source once the target is non-loopback by reading this field, never by
    naming individual sources. A source added later only has to declare its scope correctly for
    the gate to apply — it cannot forget to extend a hand-written skip condition.
    """

    name: str
    scope: Literal["cli", "server"]
    resolve: Callable[[CredentialInputs], str | None]


def _blank_to_none(value: str | None) -> str | None:
    """Treat a blank/whitespace-only string the same as unset."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize(url: URL, path: str) -> URL:
    """Strip query/fragment and set ``path``, without forcing an explicit '/' onto a bare origin.

    Calling ``URL.with_path("/")`` on a URL that never had an explicit path (e.g. ``http://h:8126``)
    forces a trailing slash to render that wasn't there before. Only calling ``with_path`` when the
    target path actually differs avoids that — a no-op comparison is cheap and keeps a bare origin
    bare.
    """
    normalized = url.with_query(None).with_fragment(None)
    if normalized.path != path:
        normalized = normalized.with_path(path)
    return normalized


def _resolve_explicit_target(raw_url: str, *, verify_ssl: bool) -> ServerTarget:
    """Parse and normalize an explicitly supplied server URL (flag or config)."""
    cleaned = raw_url.strip().strip("'\"")
    yurl = URL(cleaned)

    if not yurl.scheme:
        raise ServerUrlSchemeRequiredError(f"server_url must include a scheme (http:// or https://), got: {cleaned}")

    stripped_path = yurl.path.rstrip("/")

    if stripped_path.endswith("/api"):
        corrected_path = stripped_path[: -len("/api")]
        corrected = str(_normalize(yurl, corrected_path))
        raise ServerUrlApiSuffixError(
            "server_url must not end in '/api' — command paths already start with /api "
            f"(e.g. {corrected}/api/health). Use {corrected!r} instead of {cleaned!r}."
        )

    normalized = _normalize(yurl, stripped_path)
    is_loopback = is_loopback_host(yurl.host or "")
    return ServerTarget(base_url=str(normalized), is_loopback=is_loopback, verify_ssl=verify_ssl)


def _resolve_derived_target(config: HassetteConfig, *, verify_ssl: bool) -> ServerTarget:
    """Derive the connect target from the server's own bind settings.

    Must stay byte-identical to today's ``f"http://{host}:{port}"`` construction — this is the
    zero-config local path, and ``TestBaseUrl``'s four existing tests pin it.
    """
    host = format_host(config.web_api.host)
    port = config.web_api.port
    base_url = f"http://{host}:{port}"
    is_loopback = is_loopback_host(substitute_host(config.web_api.host))
    return ServerTarget(base_url=base_url, is_loopback=is_loopback, verify_ssl=verify_ssl)


def resolve_server_target(
    config: HassetteConfig, *, server_url_flag: str | None = None, verify_ssl_flag: bool | None = None
) -> ServerTarget:
    """Resolve the CLI's connect target.

    Precedence: ``server_url_flag`` -> ``config.cli.server_url`` -> derived from
    ``web_api.host``/``web_api.port``. A blank/whitespace-only value at either of the first two
    tiers is treated as unset and falls through to the next.

    Raises:
        ServerUrlSchemeRequiredError: An explicit URL has no scheme.
        ServerUrlApiSuffixError: An explicit URL's path ends in ``/api``.
    """
    verify_ssl = verify_ssl_flag if verify_ssl_flag is not None else config.cli.verify_ssl

    raw_url = _blank_to_none(server_url_flag) or _blank_to_none(config.cli.server_url)
    if raw_url is not None:
        return _resolve_explicit_target(raw_url, verify_ssl=verify_ssl)

    return _resolve_derived_target(config, verify_ssl=verify_ssl)


def _ensure_header_safe(value: str, source: str) -> str:
    """Reject a credential value that is not safe for use as an HTTP header value.

    ``httpx.Client(headers={...})`` raises ``UnicodeEncodeError`` deep inside its constructor for
    a non-ASCII header value, before any of the CLI's error handling runs — a bare traceback for
    what is almost always a copy-paste mistake (a smart quote, an accented character) or the wrong
    file. Checking here, at the point a value is resolved, turns that into a clear usage error
    naming the offending source.
    """
    if not value.isascii() or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise CredentialResolutionError(
            f"Credential from {source} is not safe for use as an HTTP header value "
            "(must be ASCII with no control characters)."
        )
    return value


def _resolve_token_file_flag(inputs: CredentialInputs) -> str | None:
    """``--token-file``. Missing/unreadable raises — a path just typed on the command is a fresh,
    attributable mistake, so failing loudly beats a silent fall-through.
    """
    path = inputs.token_file_flag
    if path is None:
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise CredentialResolutionError(f"--token-file could not be read: {path} ({exc})") from exc
    if not content:
        return None
    return _ensure_header_safe(content, str(path))


def _read_token_file(path: Path) -> str | None:
    """Read and validate a token file, treating missing/unreadable/empty content as "no credential".

    Shared by ``cli.token_file`` and ``<data_dir>/.web_api_token`` resolution — both fall through
    to the next source on any read failure, unlike ``--token-file`` (:func:`_resolve_token_file_flag`),
    which raises instead.
    """
    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not content:
        return None
    return _ensure_header_safe(content, str(path))


def _resolve_cli_token_file(inputs: CredentialInputs) -> str | None:
    """``cli.token_file``. Missing/unreadable falls through to the next source — a config path is
    reused unattended and goes stale in ways the operator isn't present to see.
    """
    path = inputs.config.cli.token_file
    if path is None:
        return None
    return _read_token_file(path)


def _resolve_cli_auth_token_field(inputs: CredentialInputs) -> str | None:
    """``cli.auth_token``. CLI-scoped: applies to any target."""
    token = inputs.config.cli.auth_token
    if token is None:
        return None
    value = token.get_secret_value().strip()
    if not value:
        return None
    return _ensure_header_safe(value, "cli.auth_token")


def _resolve_web_api_auth_token(inputs: CredentialInputs) -> str | None:
    """``web_api.auth_token``. Server-scoped: describes what the *local* instance validates
    against, so it is gated to loopback targets by ``resolve_cli_auth_token``.
    """
    token = inputs.config.web_api.auth_token
    if token is None:
        return None
    value = token.get_secret_value().strip()
    if not value:
        return None
    return _ensure_header_safe(value, "web_api.auth_token")


def _resolve_data_dir_token_file(inputs: CredentialInputs) -> str | None:
    """``<data_dir>/.web_api_token``. Server-scoped, same reasoning as ``web_api.auth_token``.

    Never generates a token: the CLI is a *consumer* of an already-resolved credential, not the
    service that owns generation — a CLI-minted token would never match what the running service
    actually validates against.
    """
    return _read_token_file(inputs.config.data_dir / TOKEN_FILENAME)


CREDENTIAL_SOURCES: tuple[CredentialSource, ...] = (
    CredentialSource(name="--token-file", scope="cli", resolve=_resolve_token_file_flag),
    CredentialSource(name="cli.token_file", scope="cli", resolve=_resolve_cli_token_file),
    CredentialSource(name="cli.auth_token", scope="cli", resolve=_resolve_cli_auth_token_field),
    CredentialSource(name="web_api.auth_token", scope="server", resolve=_resolve_web_api_auth_token),
    CredentialSource(name="<data_dir>/.web_api_token", scope="server", resolve=_resolve_data_dir_token_file),
)
"""Credential precedence chain, in FR#7 order. See :class:`CredentialSource` for the scope gate."""


def resolve_cli_auth_token(
    config: HassetteConfig, target: ServerTarget, *, token_file_flag: Path | None = None
) -> str | None:
    """Resolve the bearer credential the CLI should attach to outgoing requests.

    Walks :data:`CREDENTIAL_SOURCES` in precedence order, skipping any ``scope="server"`` entry
    when ``target.is_loopback`` is false — server-scoped sources describe what the *local*
    instance validates against, never a statement about what some other instance accepts.

    Returns:
        The plaintext token, or ``None`` if no applicable source has one. The CLI never
        generates a token itself, and a non-loopback target with no credential still issues the
        request rather than failing before the network call (``trusted_proxies`` deployments
        need no bearer token at all).

    Raises:
        CredentialResolutionError: ``--token-file`` was supplied but could not be read, or a
            resolved credential value is not safe for use as an HTTP header (non-ASCII or
            containing control characters).
    """
    inputs = CredentialInputs(config=config, token_file_flag=token_file_flag)
    for source in CREDENTIAL_SOURCES:
        if source.scope == "server" and not target.is_loopback:
            continue
        value = source.resolve(inputs)
        if value:
            return value
    return None
