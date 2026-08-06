"""Shared network classification helpers.

Home to :func:`is_loopback_host`, used by both the web API service (to decide whether an
unauthenticated bind is acceptable) and the CLI (to decide whether a credential may be sent to a
resolved target). Both feed the same trust decision, so this lives below both callers in the
layer DAG rather than being duplicated.

Also home to :func:`substitute_host`/:func:`format_host`, the bind-all-address normalization used
when deriving a CLI connect target from ``web_api.host``/``web_api.port`` — kept alongside
``is_loopback_host`` since both ``cli/client.py`` and ``cli/target.py`` need this module, making it
a safe common dependency for both without creating a circular import between them.
"""

import ipaddress

_LOOPBACK_HOSTNAMES = frozenset({"localhost"})
"""Hostname spellings treated as loopback without DNS resolution — see is_loopback_host."""

_BIND_ALL_SUBSTITUTIONS: dict[str, str] = {
    "0.0.0.0": "127.0.0.1",
    "::": "::1",
}
"""Bind-all addresses that are not routable as connect targets."""


def is_loopback_host(host: str) -> bool:
    """Return whether ``host`` is a loopback address or the ``"localhost"`` hostname.

    ``WebApiConfig.host`` is a plain ``str`` with no format restriction: it can be an IP
    literal (``"127.0.0.1"``, ``"::1"``, ``"0.0.0.0"``) or the hostname ``"localhost"``.
    ``ipaddress.ip_address()`` raises ``ValueError`` on a hostname, so that case is handled
    separately rather than resolved via DNS — this check only needs to recognize the handful
    of conventional loopback spellings operators actually use, not arbitrary hostnames
    (mirrors this module's own bind-all substitution, ``_BIND_ALL_SUBSTITUTIONS``).

    Bracketed IPv6 literals (``"[::1]"``) are stripped to their unbracketed form before
    parsing, so a caller that passes ``yarl.URL.host`` (always unbracketed) and a caller that
    passes a raw bracketed literal both classify identically.

    An IPv4-mapped IPv6 address (``"::ffff:127.0.0.1"``) is checked twice: once directly, and
    once against its mapped IPv4 form. ``IPv6Address.is_loopback`` recognizes these addresses
    on Python 3.13+ but not on 3.12 (a CPython stdlib behavior difference, not a documented
    version floor) — this project supports 3.11-3.14, so the mapped-address fallback makes the
    classification version-independent instead of depending on which interpreter runs it.
    """
    host = host.strip("[]")
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host.lower() in _LOOPBACK_HOSTNAMES
    if addr.is_loopback:
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    return mapped is not None and mapped.is_loopback


def substitute_host(host: str) -> str:
    """Replace bind-all addresses with loopback equivalents."""
    return _BIND_ALL_SUBSTITUTIONS.get(host, host)


def format_host(host: str) -> str:
    """Wrap IPv6 addresses in brackets for use in URLs."""
    substituted = substitute_host(host)
    if ":" in substituted:
        return f"[{substituted}]"
    return substituted
