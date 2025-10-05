import json
from pathlib import Path
from unittest.mock import patch

from whenever import PlainDateTime

from hassette.core.api import Api
from hassette.test_utils.test_server import SimpleTestServer

TEST_DATA_PATH = Path.cwd().joinpath("tests", "data")

history_raw = json.loads((TEST_DATA_PATH / "full_history.json").read_text())
history_minimal_raw = json.loads((TEST_DATA_PATH / "minimal_history.json").read_text())

light_entryway_raw_history = history_raw[0]
light_entryway_minimal_history = history_minimal_raw[0]


START = PlainDateTime(2025, 6, 30, 0, 0, 0)
END = PlainDateTime(2025, 6, 30, 23, 59, 59)


async def test_get_histories(hassette_with_mock_api: tuple[Api, SimpleTestServer]) -> None:
    api, mock = hassette_with_mock_api

    # Expect one GET to the combined history endpoint for two entities
    path, qs = SimpleTestServer.make_history_path(["light.entryway", "light.office"], START, END, minimal=False)
    mock.expect("GET", path, qs, json=history_raw, status=200)

    history = await api.get_histories(
        entity_ids=["light.entryway", "light.office"],
        start_time=START,
        end_time=END,
        minimal_response=False,
    )

    assert isinstance(history, dict), "Expected history to be a dict"
    assert "light.entryway" in history, "Expected light.entryway in history"
    assert "light.office" in history, "Expected light.office in history"


async def test_history_is_normalized(hassette_with_mock_api: tuple[Api, SimpleTestServer]):
    api, mock = hassette_with_mock_api

    path, qs = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=False)
    mock.expect("GET", path, qs, json=history_raw[0])
    path_m, qs_m = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=True)
    mock.expect("GET", path_m, qs_m, json=history_minimal_raw[0])

    norm = await api.get_history("light.entryway", START, END, minimal_response=False)
    mini = await api.get_history("light.entryway", START, END, minimal_response=True)

    assert mini, "Minimal history should not be empty"
    assert norm, "Normal history should not be empty"
    assert mini == norm, "Minimal and normal history should be equal after normalization"


async def test_minimal_history_differs_if_not_normalized(hassette_with_mock_api: tuple[Api, SimpleTestServer]) -> None:
    api, mock = hassette_with_mock_api

    # Expect the non-minimal and minimal variants for a single entity
    path1, qs1 = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=False)
    mock.expect("GET", path1, qs1, json=light_entryway_raw_history, status=200)

    path2, qs2 = SimpleTestServer.make_history_path(["light.entryway"], START, END, minimal=True)
    mock.expect("GET", path2, qs2, json=light_entryway_minimal_history, status=200)

    history_norm = await api._api._get_history_raw(
        entity_id="light.entryway", start_time=START, end_time=END, minimal_response=False
    )

    # normalize_history is called automatically, so we mock it make sure
    # it doesn't get called and that the un-normalized history differs
    with patch("hassette.core.api.normalize_history") as mock_normalize:
        mock_normalize.return_value = lambda x: x
        history_minimal = await api._api._get_history_raw(
            entity_id="light.entryway",
            start_time=START,
            end_time=END,
            minimal_response=True,
        )

    assert history_minimal, "Minimal history should not be empty"
    assert history_norm, "Normal history should not be empty"
    assert history_minimal != history_norm, "Minimal and normal history responses should differ"
