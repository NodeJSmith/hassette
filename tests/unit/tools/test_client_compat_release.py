"""Tests for tools/client_compat_release.py: which release the client-compat fixtures are typed by."""

import httpx2
from client_compat_release import PYPI_CLIENT_URL, choose_release, published_client_versions
from packaging.version import Version

PYPI_RELEASES = {
    "1.0.0": [{"yanked": True}],
    "1.1.0": [],
    "1.2.0rc1": [{}],
    "junk": [{}],
    "1.0.1": [{"yanked": False}],
}
"""One release per reason to drop it (yanked, no files, pre-release, not PEP 440), plus one to keep."""


def test_published_client_versions_keeps_only_final_releases_with_a_live_file() -> None:
    def pypi(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == PYPI_CLIENT_URL
        return httpx2.Response(200, json={"releases": PYPI_RELEASES})

    assert published_client_versions(httpx2.MockTransport(pypi)) == {Version("1.0.1")}


def test_choose_release_takes_the_newest_reachable_published_tag() -> None:
    tag, notices = choose_release(["v1.2.0", "v1.1.0"], {Version("1.1.0"), Version("1.2.0")})

    assert (tag, notices) == ("v1.2.0", [])


def test_choose_release_skips_a_tag_pypi_lacks_with_a_notice() -> None:
    tag, notices = choose_release(["v1.2.0", "v1.1.0"], {Version("1.1.0")})

    assert tag == "v1.1.0"
    assert notices == ["v1.2.0 is reachable from HEAD but not on PyPI (publish pending or failed); skipped it."]


def test_choose_release_notes_a_newer_release_the_branch_cant_reach() -> None:
    tag, notices = choose_release(["v1.1.0"], {Version("1.1.0"), Version("1.2.0")})

    assert tag == "v1.1.0"
    assert len(notices) == 1
    assert "PyPI has hassette-client 1.2.0" in notices[0]


def test_choose_release_finds_nothing_when_no_reachable_tag_is_published() -> None:
    tag, _ = choose_release(["v1.1.0"], {Version("1.0.0")})

    assert tag is None
