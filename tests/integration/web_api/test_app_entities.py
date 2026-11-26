"""Declared entities on ``GET /api/apps`` and their command routes (spec 158)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx2 import AsyncClient
from whenever import Date, Instant

from hassette.integration.declarations import (
    CommandDispatchResult,
    CommittedEntity,
    Declaration,
    EntityState,
    IntegrationPlatform,
)
from hassette.testing._harness_resources import HarnessIntegrationService
from tests.integration.conftest import make_manifest_mock
from tests.support.web_manifest_helpers import STUB_BOOT_ID
from tests.support.web_mocks import wire_integration_service

from .conftest import APP_GRID_PATH, APP_PATH, APPS_PATH, get_json, seed_grid_apps

APP_KEY = "my_app"
INSTANCE = "my_app"
"""``seed_grid_apps`` names each app's one instance after its key."""

INSTANCE_PATH = f"{APPS_PATH}/{APP_KEY}/instances/{INSTANCE}"

BUTTON = CommittedEntity(
    Declaration("doorbell", IntegrationPlatform.BUTTON, "Doorbell", entity_category="config"), EntityState()
)
SWITCH = CommittedEntity(
    Declaration("guest_mode", IntegrationPlatform.SWITCH, "Guest mode", default_entity_id="switch.guest", initial=True),
    EntityState(value=False),
)
BATTERY = CommittedEntity(
    Declaration(
        "battery", IntegrationPlatform.SENSOR, "Battery", unit="%", device_class="battery", state_class="measurement"
    ),
    EntityState(value=87.5, attributes={"charging": False, "cells": [1, 2]}),
)
LAST_SEEN = CommittedEntity(
    Declaration("last_seen", IntegrationPlatform.SENSOR, "Last seen", device_class="timestamp"),
    EntityState(value=Instant.from_utc(2024, 1, 1, 12, 30)),
)
BIRTHDAY = CommittedEntity(
    Declaration("birthday", IntegrationPlatform.SENSOR, "Birthday", device_class="date"),
    EntityState(value=Date(2024, 2, 29)),
)
MODE = CommittedEntity(
    Declaration("mode", IntegrationPlatform.SENSOR, "Mode", device_class="enum", options=("home", "away")),
    EntityState(value="home"),
)
ENTITIES = [BATTERY, BIRTHDAY, BUTTON, SWITCH, LAST_SEEN, MODE]


@pytest.fixture
def running(mock_hassette: MagicMock) -> MagicMock:
    """``my_app`` configured on a real registry, its instance running and declaring :data:`ENTITIES`."""
    seed_grid_apps(mock_hassette, APP_KEY)
    wire_integration_service(mock_hassette, declared_entities={(APP_KEY, INSTANCE): ENTITIES})
    mock_hassette.integration_service.entity_revision = 42
    return mock_hassette


class TestListing:
    async def test_carries_each_instances_entities_and_the_revision(self, client: AsyncClient, running) -> None:
        data = await get_json(client, APPS_PATH)

        assert data["boot_id"] == STUB_BOOT_ID
        assert data["entity_revision"] == 42
        [app] = data["apps"]
        [instance] = app["instances"]
        assert [entity["key"] for entity in instance["entities"]] == [entity.declaration.key for entity in ENTITIES]

    async def test_maps_every_declared_entity_field(self, client: AsyncClient, running) -> None:
        data = await get_json(client, APPS_PATH)

        by_key = {entity["key"]: entity for entity in data["apps"][0]["instances"][0]["entities"]}
        assert by_key["battery"] == {
            "key": "battery",
            "platform": "sensor",
            "name": "Battery",
            "default_entity_id": None,
            "entity_category": None,
            "unit": "%",
            "device_class": "battery",
            "state_class": "measurement",
            "options": None,
            "value": 87.5,
            "attributes": {"charging": False, "cells": [1, 2]},
        }
        assert by_key["doorbell"]["platform"] == "button"
        assert by_key["doorbell"]["entity_category"] == "config"
        assert by_key["doorbell"]["value"] is None
        assert by_key["guest_mode"]["value"] is False
        assert by_key["guest_mode"]["default_entity_id"] == "switch.guest"
        assert "initial" not in by_key["guest_mode"]
        assert by_key["mode"]["options"] == ["home", "away"]

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            pytest.param("last_seen", "2024-01-01T12:30:00Z", id="timestamp_iso_with_offset"),
            pytest.param("birthday", "2024-02-29", id="date_iso"),
        ],
    )
    async def test_converts_temporal_values_to_iso_strings(
        self,
        client: AsyncClient,
        running,
        key: str,
        expected: str,
    ) -> None:
        data = await get_json(client, APPS_PATH)

        by_key = {entity["key"]: entity for entity in data["apps"][0]["instances"][0]["entities"]}
        assert by_key[key]["value"] == expected

    async def test_instance_declaring_nothing_lists_an_empty_list(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        seed_grid_apps(mock_hassette, APP_KEY)

        data = await get_json(client, APPS_PATH)

        assert data["apps"][0]["instances"][0]["entities"] == []

    async def test_single_app_response_leaves_entities_out(
        self,
        client: AsyncClient,
        running: MagicMock,
        known_app,
    ) -> None:
        running.telemetry_query_service.get_app_manifest.return_value = (
            running.telemetry_query_service.get_all_app_manifests.return_value[0]
        )

        data = await get_json(client, APP_PATH)

        assert [instance["entities"] for instance in data["instances"]] == [None]

    async def test_app_grid_leaves_entities_out(self, client: AsyncClient, running) -> None:
        data = await get_json(client, APP_GRID_PATH)

        assert [instance["entities"] for entry in data["apps"] for instance in entry["app"]["instances"]] == [None]


class TestCommands:
    @pytest.mark.parametrize(
        ("path", "key", "platform", "value"),
        [
            pytest.param("buttons/doorbell/press", "doorbell", IntegrationPlatform.BUTTON, None, id="press"),
            pytest.param("switches/guest_mode/turn_on", "guest_mode", IntegrationPlatform.SWITCH, True, id="turn_on"),
            pytest.param(
                "switches/guest_mode/turn_off", "guest_mode", IntegrationPlatform.SWITCH, False, id="turn_off"
            ),
        ],
    )
    async def test_dispatched_command_answers_202(
        self,
        client: AsyncClient,
        running: MagicMock,
        path: str,
        key: str,
        platform: IntegrationPlatform,
        value: bool | None,
    ) -> None:
        response = await client.post(f"{INSTANCE_PATH}/{path}")

        assert response.status_code == 202, response.text
        assert response.json() == {
            "status": "accepted",
            "app_key": APP_KEY,
            "instance_name": INSTANCE,
            "key": key,
            "platform": platform.value,
        }
        running.integration_service.dispatch_command.assert_awaited_once_with(APP_KEY, INSTANCE, key, platform, value)

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("buttons/no_such_key/press", id="unknown_key"),
            pytest.param("buttons/guest_mode/press", id="key_on_another_platform"),
        ],
    )
    async def test_undeclared_key_answers_entity_not_declared(
        self,
        client: AsyncClient,
        running,
        path: str,
    ) -> None:
        response = await client.post(f"{INSTANCE_PATH}/{path}")

        assert response.status_code == 409
        assert response.json()["code"] == "entity_not_declared"

    async def test_configured_instance_not_running_answers_instance_not_running(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        seed_grid_apps(mock_hassette, APP_KEY)

        response = await client.post(f"{INSTANCE_PATH}/buttons/doorbell/press")

        assert response.status_code == 409
        assert response.json()["code"] == "instance_not_running"

    async def test_tracked_instance_removed_from_config_answers_instance_not_running(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        """A stopped orphan the registry still tracks exists, so it isn't a 404."""
        registry = mock_hassette.app_handler.registry
        registry.get_manifest.return_value = make_manifest_mock(app_config=[])
        registry.configured_names.return_value = []
        registry.get_instances.return_value = {INSTANCE: MagicMock()}

        response = await client.post(f"{INSTANCE_PATH}/buttons/doorbell/press")

        assert response.status_code == 409
        assert response.json()["code"] == "instance_not_running"

    async def test_unknown_app_answers_app_not_found(self, client: AsyncClient, mock_hassette: MagicMock) -> None:
        registry = mock_hassette.app_handler.registry
        registry.get_manifest.return_value = None
        registry.get_instances.return_value = {}

        response = await client.post(f"{APPS_PATH}/nope/instances/{INSTANCE}/buttons/doorbell/press")

        assert response.status_code == 404
        assert response.json()["code"] == "app_not_found"

    async def test_unknown_instance_answers_instance_not_found(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        seed_grid_apps(mock_hassette, APP_KEY)

        response = await client.post(f"{APPS_PATH}/{APP_KEY}/instances/other/switches/guest_mode/turn_on")

        assert response.status_code == 404
        assert response.json()["code"] == "instance_not_found"

    async def test_running_orphan_is_admitted_without_reading_config(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        """Admission is the owner map's alone (D2): a running instance whose config block is gone still answers."""
        wire_integration_service(mock_hassette, declared_entities={(APP_KEY, "orphan"): [BUTTON]})
        registry = mock_hassette.app_handler.registry

        response = await client.post(f"{APPS_PATH}/{APP_KEY}/instances/orphan/buttons/doorbell/press")

        assert response.status_code == 202, response.text
        registry.get_manifest.assert_not_called()
        registry.configured_names.assert_not_called()

    async def test_invalid_app_key_answers_400_before_dispatch(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        response = await client.post(f"{APPS_PATH}/bad%20key/instances/{INSTANCE}/buttons/doorbell/press")

        assert response.status_code == 400
        assert response.json()["code"] == "invalid_app_key"
        mock_hassette.integration_service.dispatch_command.assert_not_awaited()

    async def test_not_declared_never_consults_the_registry(
        self, client: AsyncClient, mock_hassette: MagicMock
    ) -> None:
        mock_hassette.integration_service.dispatch_command.side_effect = None
        mock_hassette.integration_service.dispatch_command.return_value = CommandDispatchResult.NOT_DECLARED

        response = await client.post(f"{INSTANCE_PATH}/buttons/doorbell/press")

        assert response.status_code == 409
        mock_hassette.app_handler.registry.get_manifest.assert_not_called()


async def test_real_integration_service_drives_listing_and_commands(
    client: AsyncClient, mock_hassette: MagicMock
) -> None:
    """The route and listing against a real ``IntegrationService``, not the stub: commit, list, press, stop, press."""
    seed_grid_apps(mock_hassette, APP_KEY)
    mock_hassette.send_event = AsyncMock()
    service = HarnessIntegrationService(mock_hassette)
    mock_hassette.integration_service = service
    owner = SimpleNamespace(instance_key=(APP_KEY, INSTANCE), _closed=False)
    await service.commit_job(owner, [BUTTON.declaration, SWITCH.declaration], {})  # pyright: ignore[reportArgumentType]

    listing = await get_json(client, APPS_PATH)
    pressed = await client.post(f"{INSTANCE_PATH}/buttons/doorbell/press")
    service.release(owner)  # pyright: ignore[reportArgumentType]
    refused = await client.post(f"{INSTANCE_PATH}/buttons/doorbell/press")
    after_stop = await get_json(client, APPS_PATH)

    assert (listing["boot_id"], listing["entity_revision"]) == (service.boot_id, service.entity_revision)
    assert [e["key"] for e in listing["apps"][0]["instances"][0]["entities"]] == ["doorbell", "guest_mode"]
    assert pressed.status_code == 202, pressed.text
    mock_hassette.send_event.assert_awaited_once()
    assert refused.status_code == 409
    assert refused.json()["code"] == "instance_not_running"
    assert [e["key"] for e in after_stop["apps"][0]["instances"][0]["entities"]] == ["doorbell", "guest_mode"]
