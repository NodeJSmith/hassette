"""SPA shell rendering: the per-request ``<base href>`` and the diagnostic page for a rejected base header.

The SPA's built ``index.html`` carries a literal ``<base href="/" />`` marker. Every response that serves
the shell substitutes it with the base resolved for that request, so the frontend's relative assets and
``document.baseURI``-derived URLs land under whatever prefix a trusted proxy stripped (HA ingress, or a
sub-path reverse proxy). See ``design/specs/130-ingress-base-path/design.md`` for the decisions this
implements.
"""

import enum
import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from starlette.datastructures import Headers
from starlette.responses import HTMLResponse

from hassette.web.auth.trusted_proxies import TrustedProxySet, is_trusted_peer

LOGGER = logging.getLogger(__name__)

BASE_MARKER = '<base href="/" />'
"""The exact tag source ``frontend/index.html`` carries; the backend substitutes it per request."""

INGRESS_PATH_HEADER = "X-Ingress-Path"
FORWARDED_PREFIX_HEADER = "X-Forwarded-Prefix"

_BASE_HEADER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (INGRESS_PATH_HEADER, re.compile(r"/api/hassio_ingress/[A-Za-z0-9_-]+")),
    (FORWARDED_PREFIX_HEADER, re.compile(r"(?:/[A-Za-z0-9_-][A-Za-z0-9._~-]*)+")),
)
"""Headers that may set the base, in precedence order, each with the full-match pattern its value must pass.

The segment rule (first character not ``.``) rules out empty, ``.`` and ``..`` segments and a leading ``//``.
"""

SHELL_HEADERS = {
    "Cache-Control": "no-cache",
    "Vary": ", ".join(name for name, _ in _BASE_HEADER_PATTERNS),
}
"""Caching headers on every shell and diagnostic response.

The body depends on the peer address as well as these headers, and ``Vary`` can't name a peer. ``no-cache``
with no ``ETag``/``Last-Modified`` is what stops a cache reusing one request's base for another; ``Vary`` only
keeps a shared cache from storing a single copy for every header value.
"""


_DIAGNOSTIC_PAGE = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Hassette: base path rejected</title>
    <style>
      body {{ font-family: system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; padding: 0 1rem;
             line-height: 1.5; color: #1f2328; background: #ffffff; }}
      @media (prefers-color-scheme: dark) {{ body {{ color: #e6edf3; background: #0d1117; }} }}
      code {{ font-size: 0.95em; }}
    </style>
  </head>
  <body>
    <h1>Hassette can't serve its UI under this path</h1>
    <p>The request carried a <code>{header}</code> header, but Hassette did not honor it. {cause}</p>
    <p><strong>To fix:</strong> {remedy}</p>
  </body>
</html>
"""


class BaseRejection(enum.Enum):
    """Why a present base header was not honored, in the order the checks run.

    Each member carries its log label and the cause and remedy the diagnostic page shows.
    """

    TRUST_INACTIVE = (
        "trust inactive",
        "Web API authentication is disabled, so no proxy is trusted to set the base path.",
        "Set <code>web_api.auth_enabled = true</code> and add the proxy to <code>web_api.trusted_proxies</code>.",
    )
    UNTRUSTED_PEER = (
        "untrusted peer",
        "The request came from a peer that is not in <code>web_api.trusted_proxies</code>.",
        "Add the proxy's address to <code>web_api.trusted_proxies</code>.",
    )
    MALFORMED_VALUE = (
        "malformed value",
        "The header's value is not a valid path prefix.",
        "Fix the prefix the proxy sends: one or more <code>/segment</code> parts, with no empty, "
        "<code>.</code> or <code>..</code> segments.",
    )

    def __init__(self, label: str, cause: str, remedy: str) -> None:
        self.label = label
        self.cause = cause
        self.remedy = remedy


@dataclass(frozen=True)
class Rejected:
    """A base header was present but not honored."""

    reason: BaseRejection
    header: str


BaseResolution = str | Rejected
"""What a request's base headers resolve to: the base (always ending in ``/``), or why a header was rejected."""


def resolve_base(
    headers: Headers, client_address: str | None, trusted: TrustedProxySet, *, auth_enabled: bool
) -> BaseResolution:
    """Resolve the ``<base href>`` for a request, or why its base header was rejected.

    The first base header present decides; one whose value is empty, whitespace-only or ``/`` counts as
    absent. A present header is then checked in a fixed order (trust inactive, untrusted peer, malformed
    value), so an untrusted peer's value is never parsed. A header that fails does not fall through to the
    next one.

    Returns:
        The base, always ending in ``/`` (``"/"`` when no base header is present), or a :class:`Rejected`.
    """
    for header, pattern in _BASE_HEADER_PATTERNS:
        value = (headers.get(header) or "").strip()
        if value in ("", "/"):
            continue
        if not auth_enabled:
            return Rejected(BaseRejection.TRUST_INACTIVE, header)
        if client_address is None or not is_trusted_peer(client_address, trusted):
            return Rejected(BaseRejection.UNTRUSTED_PEER, header)
        prefix = value.removesuffix("/")
        if not pattern.fullmatch(prefix):
            return Rejected(BaseRejection.MALFORMED_VALUE, header)
        base = f"{prefix}/"
        LOGGER.debug("Resolved SPA base from %s: %s", header, base)
        return base
    return "/"


@dataclass
class SpaShell:
    """The built ``index.html``, read once, and the renderer for every response that serves it."""

    template: str
    """The built ``index.html``, still carrying :data:`BASE_MARKER`."""
    warned: set[BaseRejection] = field(default_factory=set)
    """Rejection reasons already logged at WARNING; later occurrences log at DEBUG."""

    def render(self, resolution: BaseResolution, client_address: str | None) -> HTMLResponse:
        """The shell with its base substituted, or the diagnostic page (status 403) for a rejection.

        A rejection is also logged, via :meth:`log_rejection`.
        """
        if isinstance(resolution, Rejected):
            self.log_rejection(resolution, client_address)
            reason = resolution.reason
            body = _DIAGNOSTIC_PAGE.format(header=resolution.header, cause=reason.cause, remedy=reason.remedy)
            return HTMLResponse(body, status_code=403, headers=SHELL_HEADERS)
        tag = f'<base href="{html.escape(resolution)}" />'
        return HTMLResponse(self.template.replace(BASE_MARKER, tag, 1), headers=SHELL_HEADERS)

    def log_rejection(self, rejected: Rejected, client_address: str | None) -> None:
        """WARNING the first time each reason occurs, DEBUG after; never logs the header's value."""
        level = logging.DEBUG if rejected.reason in self.warned else logging.WARNING
        self.warned.add(rejected.reason)
        LOGGER.log(
            level,
            "Rejected %s header from %s (%s); serving the base-path diagnostic page",
            rejected.header,
            client_address or "unknown",
            rejected.reason.label,
        )


def load_spa_shell(spa_dir: Path) -> SpaShell | None:
    """Read the built ``index.html`` and check it carries the base marker.

    Returns:
        The shell, or ``None`` (after logging an ERROR) when ``index.html`` is missing or lacks the marker,
        in which case the caller mounts no SPA routes and the API keeps running.
    """
    index = spa_dir / "index.html"
    if not index.is_file():
        LOGGER.error("SPA build at %s has no index.html; rebuild the SPA. The web UI is not served.", spa_dir)
        return None
    text = index.read_text(encoding="utf-8")
    if BASE_MARKER not in text:
        LOGGER.error(
            "%s lacks the %s marker (a stale or foreign build); rebuild the SPA. The web UI is not served.",
            index,
            BASE_MARKER,
        )
        return None
    return SpaShell(template=text)
