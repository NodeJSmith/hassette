import json
from pathlib import Path
from unittest.mock import patch

from whenever import PlainDateTime

from hassette.api import Api
from hassette.test_utils.test_server import SimpleTestServer

TEST_DATA_PATH = Path.cwd().joinpath("tests", "data", "api_responses")

history_raw = json.loads((TEST_DATA_PATH / "full_history.json").read_text())
history_minimal_raw = json.loads((TEST_DATA_PATH / "minimal_history.json").read_text())

light_entryway_raw_history = history_raw[0]
light_entryway_minimal_history = history_minimal_raw[0]


START = PlainDateTime(2025, 6, 30, 0, 0, 0)
END = PlainDateTime(2025, 6, 30, 23, 59, 59)


async def test_get_histories(hassette_with_mock_api: tuple[Api, SimpleTestServer]) -> None:
    """get_histories fetches each entity and returns a mapping."""
    api_client, mock_server = hassette_with_mock_api

    # Expect one GET to the combined history endpoint for two entities
    path, qs = SimpleTestServer.make_history_path(["light.entryway", "light.office"], START, END, minimal=False)
    mock_server.expect("GET", path, qs, json=history_raw, status=200)

    history_by_entity = await api_client.get_histories(
        entity_ids=["light.entryway", "light.office"],
        start_time=START,
        end_time=END,
        minimal_response=False,
    )

    assert isinstance(history_by_entity, dict), "Expected history to be a dict"
    assert "light.entryway" in history_by_entity, "Expected light.entryway in history"
    assert "light.office" in history_by_entity, "Expected light.office in history"


async def test_history_is_normalized(hassette_with_mock_api: tuple[Api, SimpleTestServer]):
    """Minimal and full history variants normalise to the same result."""
    api_client, mock_server = hassette_with_mock_api

    path, qs = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=False)
    mock_server.expect("GET", path, qs, json=history_raw[0])
    path_minimal, qs_minimal = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=True)
    mock_server.expect("GET", path_minimal, qs_minimal, json=history_minimal_raw[0])

    full_history = await api_client.get_history("light.entryway", START, END, minimal_response=False)
    minimal_history = await api_client.get_history("light.entryway", START, END, minimal_response=True)

    assert minimal_history, "Minimal history should not be empty"
    assert full_history, "Normal history should not be empty"
    assert minimal_history == full_history, "Minimal and normal history should be equal after normalization"


async def test_minimal_history_differs_if_not_normalized(hassette_with_mock_api: tuple[Api, SimpleTestServer]) -> None:
    """Without normalization, minimal and full history responses differ."""
    api_client, mock_server = hassette_with_mock_api

    # Expect the non-minimal and minimal variants for a single entity
    path1, qs1 = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=False)
    mock_server.expect("GET", path1, qs1, json=light_entryway_raw_history, status=200)

    path2, qs2 = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=True)
    mock_server.expect("GET", path2, qs2, json=light_entryway_minimal_history, status=200)

    history_without_minimal_flag = await api_client._api_service._get_history_raw(
        entity_id="light.entryway", start_time=START, end_time=END, minimal_response=False
    )

    # normalize_history is called automatically, so we mock it make sure
    # it doesn't get called and that the un-normalized history differs
    with patch("hassette.core.api_resource.normalize_history") as mock_normalize:
        mock_normalize.return_value = lambda x: x
        history_with_minimal_flag = await api_client._api_service._get_history_raw(
            entity_id="light.entryway",
            start_time=START,
            end_time=END,
            minimal_response=True,
        )

    assert history_with_minimal_flag, "Minimal history should not be empty"
    assert history_without_minimal_flag, "Normal history should not be empty"
    assert history_with_minimal_flag != history_without_minimal_flag, (
        "Minimal and normal history responses should differ"
    )
