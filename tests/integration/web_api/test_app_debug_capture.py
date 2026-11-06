"""``PUT /api/apps/{app_key}/debug`` and its instance-scoped twin (spec 148 D3, D5, D6)."""

from unittest.mock import MagicMock

import pytest
from httpx2 import AsyncClient

from tests.integration.conftest import make_manifest_mock

from .conftest import APPS_PATH

CONFIGURED = [{"instance_name": "alpha"}, {"instance_name": "beta"}]


@pytest.fixture
def toggle(mock_hassette: MagicMock) -> MagicMock:
    """``my_app`` configured with two instances, and the AppHandler toggle answering both captured."""
    handler = mock_hassette.app_handler
    handler.registry.get_manifest.side_effect = lambda key: (
        make_manifest_mock(app_config=CONFIGURED) if key == "my_app" else None
    )
    handler.registry.get_instances.return_value = {}
    handler.set_debug_capture = MagicMock(return_value={"alpha": True, "beta": True})
    return handler.set_debug_capture


async def test_app_wide_on_reports_each_instance(client: AsyncClient, toggle: MagicMock) -> None:
    response = await client.put(f"{APPS_PATH}/my_app/debug", json={"enabled": True})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "app_key": "my_app",
        "instance_name": None,
        "instances": [
            {"instance_name": "alpha", "debug_capture": True},
            {"instance_name": "beta", "debug_capture": True},
        ],
    }
    toggle.assert_called_once_with("my_app", None, True)


async def test_instance_off_targets_that_instance(client: AsyncClient, toggle: MagicMock) -> None:
    toggle.return_value = {"alpha": False}

    response = await client.put(f"{APPS_PATH}/my_app/instances/alpha/debug", json={"enabled": False})

    assert response.status_code == 200, response.text
    assert response.json()["instance_name"] == "alpha"
    assert response.json()["instances"] == [{"instance_name": "alpha", "debug_capture": False}]
    toggle.assert_called_once_with("my_app", "alpha", False)


async def test_unknown_app_is_404(client: AsyncClient, toggle: MagicMock) -> None:
    response = await client.put(f"{APPS_PATH}/nope/debug", json={"enabled": True})

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "app_not_found"
    toggle.assert_not_called()


async def test_unconfigured_instance_is_404(client: AsyncClient, toggle: MagicMock) -> None:
    response = await client.put(f"{APPS_PATH}/my_app/instances/gamma/debug", json={"enabled": True})

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "instance_not_found"
    toggle.assert_not_called()


async def test_bad_body_is_422(client: AsyncClient, toggle: MagicMock) -> None:
    response = await client.put(f"{APPS_PATH}/my_app/debug", json={"enabled": "sometimes"})

    assert response.status_code == 422, response.text
    toggle.assert_not_called()


@pytest.mark.parametrize("suffix", ["debug", "instances/alpha/debug"])
async def test_answers_while_another_action_holds_the_lock(
    client: AsyncClient, mock_hassette: MagicMock, toggle: MagicMock, suffix: str
) -> None:
    """The toggle takes no lifecycle lock, so it works during a hung startup or reload (spec 148 D6)."""
    mock_hassette.app_handler.is_action_in_progress = MagicMock(return_value=True)

    response = await client.put(f"{APPS_PATH}/my_app/{suffix}", json={"enabled": True})

    assert response.status_code == 200, response.text
    toggle.assert_called_once()
