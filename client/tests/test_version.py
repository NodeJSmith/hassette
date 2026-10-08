import pytest
from fake_server import HEALTH_BODY
from hassette_client import MIN_SERVER_VERSION, UnsupportedServerVersionError, check_server_version
from hassette_wire import SystemStatusResponse
from packaging.version import Version

MINIMUM = Version(MIN_SERVER_VERSION)


def health_with_version(server_version: str) -> SystemStatusResponse:
    return SystemStatusResponse.model_validate({**HEALTH_BODY, "version": server_version})


@pytest.mark.parametrize(
    "server_version",
    [
        MIN_SERVER_VERSION,
        f"{MINIMUM.major}.{MINIMUM.minor}.{MINIMUM.micro + 1}",
        f"{MINIMUM.major}.{MINIMUM.minor + 1}.0.dev3",
        f"{MINIMUM.major + 1}.0.0",
    ],
)
def test_server_at_or_above_the_minimum_passes(server_version: str) -> None:
    check_server_version(health_with_version(server_version))


@pytest.mark.parametrize(
    "server_version",
    [
        "0.0.1",
        # A dev build of the minimum may predate the routes the minimum exists for.
        f"{MIN_SERVER_VERSION}.dev3",
        f"{MIN_SERVER_VERSION}rc1",
    ],
)
def test_server_below_the_minimum_raises(server_version: str) -> None:
    with pytest.raises(UnsupportedServerVersionError) as exc_info:
        check_server_version(health_with_version(server_version))

    assert exc_info.value.server_version == server_version
    assert exc_info.value.min_version == MIN_SERVER_VERSION
    assert "upgrade the hassette server" in str(exc_info.value)


@pytest.mark.parametrize("server_version", ["", "unknown", "not a version"])
def test_unreadable_server_version_passes(server_version: str) -> None:
    """A source checkout reports ``"unknown"``, and the client must still talk to it."""
    check_server_version(health_with_version(server_version))
