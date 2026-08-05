"""Shared network classification helpers.

Home to :func:`is_loopback_host`, used by both the web API service (to decide whether an
unauthenticated bind is acceptable) and the CLI (to decide whether a credential may be sent to a
resolved target). Both feed the same trust decision, so this lives below both callers in the
layer DAG rather than being duplicated.
"""

import ipaddress

_LOOPBACK_HOSTNAMES = frozenset({"localhost"})
"""Hostname spellings treated as loopback without DNS resolution — see is_loopback_host."""


def is_loopback_host(host: str) -> bool:
    """Return whether ``host`` is a loopback address or the ``"localhost"`` hostname.

    ``WebApiConfig.host`` is a plain ``str`` with no format restriction: it can be an IP
    literal (``"127.0.0.1"``, ``"::1"``, ``"0.0.0.0"``) or the hostname ``"localhost"``.
    ``ipaddress.ip_address()`` raises ``ValueError`` on a hostname, so that case is handled
    separately rather than resolved via DNS — this check only needs to recognize the handful
    of conventional loopback spellings operators actually use, not arbitrary hostnames
    (mirrors the bind-all substitution in ``cli/client.py``'s ``_BIND_ALL_SUBSTITUTIONS``).

    Bracketed IPv6 literals (``"[::1]"``) are stripped to their unbracketed form before
    parsing, so a caller that passes ``yarl.URL.host`` (always unbracketed) and a caller that
    passes a raw bracketed literal both classify identically.
    """
    host = host.strip("[]")
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() in _LOOPBACK_HOSTNAMES
