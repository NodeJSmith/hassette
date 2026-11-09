"""Unit tests for Api.set_state's read-then-merge of current attributes.

set_state reads the entity once with a suppressed GET. A 404 (the entity doesn't exist, or was
removed mid-call) means there are no current attributes, and the POST creates the entity.
"""

from unittest.mock import AsyncMock

from hassette.exceptions import EntityNotFoundError
from tests.unit.conftest import as_async_mock, awaited_kwargs, make_api


async def test_set_state_missing_entity_posts_only_caller_attributes() -> None:
    """A 404 on the state GET doesn't escape; the POST carries only the caller's attributes."""
    api = make_api()
    api.rest_request = AsyncMock(side_effect=EntityNotFoundError("gone"))

    await api.set_state("sensor.test", "on", {"a": 1})

    rest = as_async_mock(api.rest_request)
    rest.assert_awaited_once_with("GET", "states/sensor.test", suppress_error_message=True)
    assert awaited_kwargs(api.post_rest_request)["data"] == {"state": "on", "attributes": {"a": 1}}


async def test_set_state_existing_entity_merges_with_one_get() -> None:
    """An existing entity is read once, and its attributes merge under the caller's."""
    api = make_api()
    get_resp = AsyncMock()
    get_resp.json = AsyncMock(return_value={"state": "off", "attributes": {"a": 1, "b": 2}})
    api.rest_request = AsyncMock(return_value=get_resp)

    await api.set_state("sensor.test", "on", {"a": 9})

    as_async_mock(api.rest_request).assert_awaited_once()
    assert awaited_kwargs(api.post_rest_request)["data"] == {"state": "on", "attributes": {"a": 9, "b": 2}}
