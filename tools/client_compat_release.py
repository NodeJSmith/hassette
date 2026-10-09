"""Which hassette-client release ``tools/generate_client_compat_fixtures.py`` types its fixtures by.

The release is the newest hassette-client PyPI serves whose ``v*`` tag is reachable from HEAD. Rationale:
``design/research/2026-10-08-client-compat-release-baseline/research.md``.
"""

import httpx2
from packaging.version import InvalidVersion, Version

PYPI_CLIENT_URL = "https://pypi.org/pypi/hassette-client/json"
PYPI_TIMEOUT_SECONDS = 30.0
PYPI_CONNECT_RETRIES = 3
"""Retries of a failed connection attempt; a request that reached PyPI isn't retried."""


def published_client_versions(transport: httpx2.BaseTransport | None = None) -> set[Version]:
    """The final, non-yanked hassette-client versions PyPI serves.

    Args:
        transport: Sends the request; defaults to an HTTP transport that retries failed connections.

    Raises:
        httpx2.HTTPError: PyPI didn't answer, or answered with an error status.
    """
    transport = transport or httpx2.HTTPTransport(retries=PYPI_CONNECT_RETRIES)
    with httpx2.Client(transport=transport, timeout=PYPI_TIMEOUT_SECONDS) as client:
        response = client.get(PYPI_CLIENT_URL)
    response.raise_for_status()
    published: set[Version] = set()
    for raw, files in response.json()["releases"].items():
        try:
            release_version = Version(raw)
        except InvalidVersion:
            continue
        if not release_version.is_prerelease and any(not file.get("yanked") for file in files):
            published.add(release_version)
    return published


def choose_release(reachable_tags: list[str], published: set[Version]) -> tuple[str | None, list[str]]:
    """The newest of ``reachable_tags`` (newest first) whose version PyPI serves, plus notices.

    PyPI decides what's released, since the check installs from there; reachability bounds it, since a
    branch can't serve routes added by a release it doesn't contain. A tag PyPI lacks (its publish is
    pending or failed) is skipped with a notice rather than failing the check, and so is a published
    release newer than anything reachable, which means the branch is behind.
    """
    notices: list[str] = []
    chosen = None
    for tag in reachable_tags:
        if Version(tag.removeprefix("v")) in published:
            chosen = tag
            break
        notices.append(f"{tag} is reachable from HEAD but not on PyPI (publish pending or failed); skipped it.")
    newest = max(published, default=None)
    if chosen is not None and newest is not None and newest > Version(chosen.removeprefix("v")):
        notices.append(
            f"PyPI has hassette-client {newest}, newer than any release reachable from HEAD; "
            f"checked against {chosen}. Merge main to check against {newest}."
        )
    return chosen, notices
