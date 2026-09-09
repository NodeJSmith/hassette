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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from yarl import URL

from hassette.config.config import HassetteConfig
from hassette.exceptions import (
    CredentialResolutionError,
    ServerUrlApiSuffixError,
    ServerUrlHostRequiredError,
    ServerUrlParseError,
    ServerUrlSchemeRequiredError,
)
from hassette.utils.net_utils import format_host, is_loopback_host, substitute_host
from hassette.web.auth.tokens import TOKEN_FILENAME

SERVER_SCOPE_QUALIFIER = "this machine's instance"
"""What a ``scope="server"`` source's qualifier has to say beyond naming the setting.

Both server-scoped sources describe the instance running on *this* host, which is the whole
diagnosis when the CLI is pointed at a second instance on the same machine. Naming the fragment
once keeps the two messages phrased identically.
"""


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
class ResolvedCredential:
    """A credential plus the human-facing name of the source it came from.

    ``source`` exists so an auth failure can say *which* credential was sent, not just that one
    was. It is built by the resolver that produced the value, so a file-backed source can name
    the concrete path it read rather than the generic setting name — the difference between
    "some token was attached" and "the local instance's ``/data/.web_api_token`` was attached",
    which is the whole diagnosis when the CLI is pointed at a second instance on the same host.

    Every source names itself as ``<setting> (<qualifier>)`` via :func:`_format_source` so the
    strings read the same when spliced mid-sentence into an auth-failure message. The qualifier
    carries whatever the setting name alone leaves out — the concrete path a file-backed source
    read, the equivalent environment variable, or that a server-scoped value describes this
    machine's instance.
    """

    # repr=False keeps the plaintext credential out of any traceback or debugger frame dump that
    # renders this object; only ``source`` is ever safe to display.
    token: str = field(repr=False)
    source: str


@dataclass(frozen=True)
class CredentialSource:
    """One entry in the credential precedence chain.

    ``scope`` is the data model, not documentation: ``resolve_cli_auth_token`` skips any
    ``"server"``-scoped source once the target is non-loopback by reading this field, never by
    naming individual sources. A source added later only has to declare its scope correctly for
    the gate to apply — it cannot forget to extend a hand-written skip condition.

    ``name`` serves the same purpose for prose. It is the bare setting identifier with no
    qualifier — the resolved-credential strings built by :func:`_ensure_header_safe` name one
    concrete source, whereas a message that reports *nothing* resolved has to list the whole
    chain. Deriving that list from this field (see :func:`credential_source_names`) is what
    keeps it from drifting when a source is added, renamed, or reordered here.
    """

    name: str
    scope: Literal["cli", "server"]
    resolve: Callable[[CredentialInputs], ResolvedCredential | None]


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
    try:
        yurl = URL(cleaned)
    except ValueError as exc:
        raise ServerUrlParseError(f"server_url could not be parsed: {cleaned} ({exc})") from exc

    if not yurl.scheme:
        raise ServerUrlSchemeRequiredError(f"server_url must include a scheme (http:// or https://), got: {cleaned}")
    if yurl.scheme not in ("http", "https"):
        raise ServerUrlSchemeRequiredError(
            f"server_url scheme must be http:// or https://, got {yurl.scheme!r} in: {cleaned}"
        )

    if not yurl.host:
        raise ServerUrlHostRequiredError(f"server_url must include a host, got: {cleaned}")

    stripped_path = yurl.path.rstrip("/")

    if stripped_path.endswith("/api"):
        corrected_path = stripped_path[: -len("/api")]
        corrected = str(_normalize(yurl, corrected_path))
        raise ServerUrlApiSuffixError(
            "server_url must not end in '/api' — command paths already start with /api "
            f"(e.g. {corrected}/api/health). Use {corrected!r} instead of {cleaned!r}."
        )

    normalized = _normalize(yurl, stripped_path)
    is_loopback = is_loopback_host(yurl.host)
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
        ServerUrlParseError: An explicit URL fails to parse (e.g. a non-numeric port or
            malformed IPv6 brackets).
        ServerUrlSchemeRequiredError: An explicit URL has no scheme, or a scheme other than
            ``http``/``https``.
        ServerUrlHostRequiredError: An explicit URL has an http/https scheme but no host
            (e.g. ``https:///foo``).
        ServerUrlApiSuffixError: An explicit URL's path ends in ``/api``.
    """
    verify_ssl = verify_ssl_flag if verify_ssl_flag is not None else config.cli.verify_ssl

    raw_url = _blank_to_none(server_url_flag) or _blank_to_none(config.cli.server_url)
    if raw_url is not None:
        return _resolve_explicit_target(raw_url, verify_ssl=verify_ssl)

    return _resolve_derived_target(config, verify_ssl=verify_ssl)


def _format_source(setting: str, qualifier: str) -> str:
    """Render a credential source as ``<setting> (<qualifier>)``.

    The shape is load-bearing: sources are spliced mid-sentence into an auth-failure message,
    so they have to read the same way whichever resolver produced them. Going through one
    formatter makes that a function signature rather than a convention a new resolver has to
    remember from :class:`ResolvedCredential`'s docstring.

    Args:
        setting: The bare identifier an operator would set — a flag, a config key, or a path
            template. Matches the corresponding :class:`CredentialSource` ``name``.
        qualifier: Whatever the setting name alone leaves out, phrased to read inside the
            parentheses. There is no single kind: a file-backed source passes the concrete
            path it read, a config field passes ``"or <ENV_VAR>"`` so the alternative spelling
            is discoverable, and a server-scoped source additionally says that the value
            describes this machine's instance. Pick whichever of those a reader would need to
            tell this source apart from the others in the chain.
    """
    return f"{setting} ({qualifier})"


def _ensure_header_safe(value: str, source: str) -> ResolvedCredential:
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
    return ResolvedCredential(token=value, source=source)


def _resolve_token_file_flag(inputs: CredentialInputs) -> ResolvedCredential | None:
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
    return _ensure_header_safe(content, _format_source("--token-file", str(path)))


def _read_token_file(path: Path, source: str) -> ResolvedCredential | None:
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
    return _ensure_header_safe(content, source)


def _resolve_cli_token_file(inputs: CredentialInputs) -> ResolvedCredential | None:
    """``cli.token_file``. Missing/unreadable falls through to the next source — a config path is
    reused unattended and goes stale in ways the operator isn't present to see.
    """
    path = inputs.config.cli.token_file
    if path is None:
        return None
    return _read_token_file(path, _format_source("cli.token_file", str(path)))


def _resolve_cli_auth_token_field(inputs: CredentialInputs) -> ResolvedCredential | None:
    """``cli.auth_token``. CLI-scoped: applies to any target."""
    token = inputs.config.cli.auth_token
    if token is None:
        return None
    value = token.get_secret_value().strip()
    if not value:
        return None
    return _ensure_header_safe(value, _format_source("cli.auth_token", "or HASSETTE__CLI__AUTH_TOKEN"))


def _resolve_web_api_auth_token(inputs: CredentialInputs) -> ResolvedCredential | None:
    """``web_api.auth_token``. Server-scoped: describes what the *local* instance validates
    against, so it is gated to loopback targets by ``resolve_cli_auth_token``.
    """
    token = inputs.config.web_api.auth_token
    if token is None:
        return None
    value = token.get_secret_value().strip()
    if not value:
        return None
    return _ensure_header_safe(
        value, _format_source("web_api.auth_token", f"or HASSETTE__WEB_API__AUTH_TOKEN — {SERVER_SCOPE_QUALIFIER}")
    )


def _resolve_data_dir_token_file(inputs: CredentialInputs) -> ResolvedCredential | None:
    """``<data_dir>/.web_api_token``. Server-scoped, same reasoning as ``web_api.auth_token``.

    Never generates a token: the CLI is a *consumer* of an already-resolved credential, not the
    service that owns generation — a CLI-minted token would never match what the running service
    actually validates against.
    """
    path = inputs.config.data_dir / TOKEN_FILENAME
    return _read_token_file(path, _format_source(f"<data_dir>/{TOKEN_FILENAME}", f"{path} — {SERVER_SCOPE_QUALIFIER}"))


CREDENTIAL_SOURCES: tuple[CredentialSource, ...] = (
    CredentialSource(name="--token-file", scope="cli", resolve=_resolve_token_file_flag),
    CredentialSource(name="cli.token_file", scope="cli", resolve=_resolve_cli_token_file),
    CredentialSource(name="cli.auth_token", scope="cli", resolve=_resolve_cli_auth_token_field),
    CredentialSource(name="web_api.auth_token", scope="server", resolve=_resolve_web_api_auth_token),
    CredentialSource(name=f"<data_dir>/{TOKEN_FILENAME}", scope="server", resolve=_resolve_data_dir_token_file),
)
"""Credential precedence chain, in the order documented by design/specs/092-cli-remote-url/design.md
(Architecture -> Credential scoping). See :class:`CredentialSource` for the scope gate."""


def credential_source_names(scope: Literal["cli", "server"] | None = None) -> str:
    """The credential sources' names in precedence order, comma-joined for use in a message.

    An auth failure that reports *nothing* resolved has to name the chain it walked, and that
    list is only useful if it matches the chain that actually ran. Deriving it here means a
    source added, renamed, or reordered in :data:`CREDENTIAL_SOURCES` updates every message
    that lists it, rather than leaving a hand-typed copy in another module to go stale.

    Args:
        scope: Restrict the list to sources of this scope. ``None`` lists the whole chain,
            which is what applies to a loopback target.
    """
    return ", ".join(source.name for source in CREDENTIAL_SOURCES if scope is None or source.scope == scope)


def resolve_cli_auth_token(
    config: HassetteConfig, target: ServerTarget, *, token_file_flag: Path | None = None
) -> ResolvedCredential | None:
    """Resolve the bearer credential the CLI should attach to outgoing requests.

    Walks :data:`CREDENTIAL_SOURCES` in precedence order, skipping any ``scope="server"`` entry
    when ``target.is_loopback`` is false — server-scoped sources describe what the *local*
    instance validates against, never a statement about what some other instance accepts.

    Returns:
        The resolved credential and the name of the source it came from, or ``None`` if no
        applicable source has one. The CLI never generates a token itself, and a non-loopback
        target with no credential still issues the request rather than failing before the
        network call (``trusted_proxies`` deployments need no bearer token at all).

    Raises:
        CredentialResolutionError: ``--token-file`` was supplied but could not be read, or a
            resolved credential value is not safe for use as an HTTP header (non-ASCII or
            containing control characters).
    """
    inputs = CredentialInputs(config=config, token_file_flag=token_file_flag)
    for source in CREDENTIAL_SOURCES:
        if source.scope == "server" and not target.is_loopback:
            continue
        credential = source.resolve(inputs)
        if credential is not None:
            return credential
    return None
