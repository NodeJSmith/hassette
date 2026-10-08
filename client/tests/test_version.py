import pytest
from fake_server import HEALTH_BODY
from hassette_client import MIN_API_SCHEMA_VERSION, UnsupportedServerVersionError, check_server_version
from hassette_wire import API_SCHEMA_VERSION, SystemStatusResponse


def health_with_schema(api_schema_version: int | None) -> SystemStatusResponse:
    body = dict(HEALTH_BODY)
    if api_schema_version is not None:
        body["api_schema_version"] = api_schema_version
    return SystemStatusResponse.model_validate(body)


def test_minimum_is_never_above_the_servers_schema() -> None:
    """The client can't require a schema its own checkout's server doesn't serve (the floor tool checks it too)."""
    assert 1 <= MIN_API_SCHEMA_VERSION <= API_SCHEMA_VERSION


@pytest.mark.parametrize("offset", [0, 1, 5])
def test_server_at_or_above_the_minimum_passes(offset: int) -> None:
    assert check_server_version(health_with_schema(MIN_API_SCHEMA_VERSION + offset)) is None


def test_server_below_the_minimum_raises() -> None:
    with pytest.raises(UnsupportedServerVersionError) as exc_info:
        check_server_version(health_with_schema(MIN_API_SCHEMA_VERSION - 1))

    assert exc_info.value.server_version == HEALTH_BODY["version"]
    assert exc_info.value.api_schema_version == MIN_API_SCHEMA_VERSION - 1
    assert exc_info.value.min_api_schema_version == MIN_API_SCHEMA_VERSION
    assert "upgrade the hassette server" in str(exc_info.value)


def test_server_reporting_no_schema_raises() -> None:
    """A server released before the API schema existed predates every route the minimum exists for."""
    with pytest.raises(UnsupportedServerVersionError, match="reports no API schema") as exc_info:
        check_server_version(health_with_schema(None))

    assert exc_info.value.api_schema_version == 0


def test_server_reporting_no_version_still_names_itself_in_the_message() -> None:
    health = SystemStatusResponse.model_validate({**HEALTH_BODY, "version": ""})

    with pytest.raises(UnsupportedServerVersionError, match=r"\(unknown version\)"):
        check_server_version(health)
