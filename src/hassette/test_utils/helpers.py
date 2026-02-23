import asyncio
import json
import textwrap
from logging import getLogger
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import tomli_w
from whenever import ZonedDateTime

from hassette.config.classes import AppManifest
from hassette.events import CallServiceEvent, RawStateChangeEvent, create_event_from_hass
from hassette.types.enums import ResourceStatus

if TYPE_CHECKING:
    from hassette.bus.bus import Bus
    from hassette.core.core import Hassette
    from hassette.events import HassEventEnvelopeDict
    from hassette.events.hassette import HassetteServiceEvent
    from hassette.resources.base import Service


def create_state_change_event(
    *,
    entity_id: str,
    old_value: Any,
    new_value: Any,
    old_attrs: dict[str, Any] | None = None,
    new_attrs: dict[str, Any] | None = None,
) -> Any:
    data: HassEventEnvelopeDict = {
        "id": 1,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "data": {
                "entity_id": entity_id,
                "old_state": {"state": old_value, "attributes": old_attrs or {}},
                "new_state": {"state": new_value, "attributes": new_attrs or {}},
            },
            "origin": "LOCAL",
            "time_fired": ZonedDateTime.now_in_system_tz().format_iso(),
            "context": {"id": "test_context_id", "parent_id": None, "user_id": None},
        },
    }
    return create_event_from_hass(data)


def create_call_service_event(
    *,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
) -> CallServiceEvent:
    """Create a mock call service event for testing."""
    data = SimpleNamespace(domain=domain, service=service, service_data=service_data or {})
    payload = SimpleNamespace(data=data)
    return cast("CallServiceEvent", SimpleNamespace(topic="hass.event.call_service", payload=payload))


def make_state_dict(
    entity_id: str,
    state: str,
    attributes: dict[str, Any] | None = None,
    last_changed: str | None = None,
    last_updated: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Factory for creating state dictionary in Home Assistant format.

    Args:
        entity_id: The entity ID (e.g., "light.kitchen")
        state: The state value (e.g., "on", "off", "25.5")
        attributes: Entity attributes dict
        last_changed: ISO timestamp string
        last_updated: ISO timestamp string
        context: Event context dict

    Returns:
        Dictionary matching Home Assistant state format
    """
    now = ZonedDateTime.now("UTC").format_iso()
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {},
        "last_changed": last_changed or now,
        "last_updated": last_updated or now,
        "context": context or {"id": str(uuid4()), "parent_id": None, "user_id": None},
    }


def make_light_state_dict(
    entity_id: str = "light.kitchen",
    state: str = "on",
    brightness: int | None = None,
    color_temp: int | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Factory for creating light state dictionary.

    Args:
        entity_id: The light entity ID
        state: "on" or "off"
        brightness: Brightness value 0-255
        color_temp: Color temperature in mireds
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant light state format
    """
    attributes: dict[str, Any] = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}
    if brightness is not None:
        attributes["brightness"] = brightness
    if color_temp is not None:
        attributes["color_temp"] = color_temp

    # Extract base state dict kwargs
    state_kwargs = {k: v for k, v in kwargs.items() if k in ("last_changed", "last_updated", "context")}
    # Add extra attributes
    attributes.update({k: v for k, v in kwargs.items() if k not in state_kwargs})

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_sensor_state_dict(
    entity_id: str = "sensor.temperature",
    state: str = "25.5",
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Factory for creating sensor state dictionary.

    Args:
        entity_id: The sensor entity ID
        state: The sensor value as string
        unit_of_measurement: Unit string (e.g., "°C", "%")
        device_class: Device class (e.g., "temperature", "humidity")
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant sensor state format
    """
    attributes = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}
    if unit_of_measurement is not None:
        attributes["unit_of_measurement"] = unit_of_measurement
    if device_class is not None:
        attributes["device_class"] = device_class

    state_kwargs = {k: v for k, v in kwargs.items() if k in ("last_changed", "last_updated", "context")}
    attributes.update({k: v for k, v in kwargs.items() if k not in state_kwargs})

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_switch_state_dict(entity_id: str = "switch.outlet", state: str = "on", **kwargs) -> dict[str, Any]:
    """Factory for creating switch state dictionary.

    Args:
        entity_id: The switch entity ID
        state: "on" or "off"
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant switch state format
    """
    attributes = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}

    state_kwargs = {k: v for k, v in kwargs.items() if k in ("last_changed", "last_updated", "context")}
    attributes.update({k: v for k, v in kwargs.items() if k not in state_kwargs})

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_full_state_change_event(
    entity_id: str, old_state: dict[str, Any] | None, new_state: dict[str, Any] | None
) -> RawStateChangeEvent:
    """Factory for creating state change events.

    Args:
        entity_id: The entity ID
        old_state: Old state dictionary (None for new entity)
        new_state: New state dictionary (None for removed entity)

    Returns:
        RawStateChangeEvent instance
    """
    envelope: HassEventEnvelopeDict = {
        "id": 1,
        "type": "event",
        "event": {
            "event_type": "state_changed",
            "data": {
                "entity_id": entity_id,
                "old_state": old_state,
                "new_state": new_state,
            },
            "origin": "LOCAL",
            "time_fired": ZonedDateTime.now_in_system_tz().format_iso(),
            "context": {"id": "test_context_id", "parent_id": None, "user_id": None},
        },
    }
    event = create_event_from_hass(envelope)
    assert isinstance(event, RawStateChangeEvent)
    return event


def create_app_manifest(
    suffix: str,
    app_dir: Path,
    enabled: bool = True,
    app_config: dict | None = None,
) -> AppManifest:
    """Helper to create an AppManifest instance."""
    app_config = app_config or {}

    key = f"my_app_{suffix}"
    filename = f"my_app_{suffix}.py"
    class_name = f"MyApp{suffix.capitalize()}"
    full_path = app_dir / filename

    return AppManifest(
        app_key=key,
        filename=filename,
        class_name=class_name,
        enabled=enabled,
        app_config=app_config,
        app_dir=app_dir,
        full_path=full_path,
    )


def get_app_manifest_for_toml(app: AppManifest) -> dict:
    """Convert AppManifest to TOML string."""
    data = app.model_dump(exclude_unset=True)
    config_key = "app_config" if "app_config" in data else "config"

    config = data.pop(config_key, {})

    return {**data, "config": config}


def write_app_toml(
    toml_file: Path,
    *,
    app_dir: Path,
    dev_mode: bool = True,
    apps: list[AppManifest] | None = None,
) -> None:
    """Write a hassette.toml with specified apps."""
    apps = apps or []

    hassette_dict = {
        "app_dir": app_dir.as_posix(),
        "autodetect_apps": False,
        "dev_mode": dev_mode,
    }

    app_dicts = {"apps": {app.app_key: get_app_manifest_for_toml(app) for app in apps}}

    toml_dict = {"hassette": hassette_dict, **app_dicts}

    # Convert any non-serializable types to strings for TOML compatibility
    toml_dict = json.loads(json.dumps(toml_dict, indent=2, default=str))

    with toml_file.open("wb") as f:
        tomli_w.dump(toml_dict, f)


def write_test_app_with_decorator(
    app_file: Path,
    class_name: str,
    has_only_app: bool = False,
    config_fields: dict | None = None,
) -> None:
    """Write a test app Python file with optional @only_app decorator."""
    getLogger(__name__).debug("Writing test app to %s", app_file)
    decorator = "@only_app\n" if has_only_app else ""
    config_fields_str = ""

    if config_fields:
        for field_name, field_type in config_fields.items():
            config_fields_str += f"\n    {field_name}: {field_type} = None"

    content = f'''
from hassette import App, AppConfig, only_app

class {class_name}Config(AppConfig):
    """Config for {class_name}."""{config_fields_str}

{decorator}class {class_name}(App[{class_name}Config]):
    """Test app."""

    async def on_initialize(self) -> None:
        self.logger.info("{class_name} initialized")
'''

    app_file.write_text(textwrap.dedent(content).lstrip())


async def emit_service_event(hassette: "Hassette", event: "HassetteServiceEvent") -> None:
    """Inject a HassetteServiceEvent into the bus."""
    await hassette.send_event(event.topic, event)


async def emit_file_change_event(hassette: "Hassette", changed_paths: set[Path]) -> None:
    """Emit a synthetic file-watcher event for the given paths."""
    from hassette.events.hassette import HassetteFileWatcherEvent

    event = HassetteFileWatcherEvent.create_event(changed_file_paths=changed_paths)
    await hassette.send_event(event.topic, event)


def make_service_failed_event(
    service: "Service",
    exception: Exception | None = None,
) -> "HassetteServiceEvent":
    """Create a HassetteServiceEvent with FAILED status for testing."""
    from hassette.events.hassette import HassetteServiceEvent

    return HassetteServiceEvent.from_data(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.FAILED,
        exception=exception or Exception("test"),
    )


def make_service_running_event(service: "Service") -> "HassetteServiceEvent":
    """Create a HassetteServiceEvent with RUNNING status for testing."""
    from hassette.events.hassette import HassetteServiceEvent

    return HassetteServiceEvent.from_data(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.RUNNING,
    )


def wire_up_app_state_listener(
    bus: "Bus",
    event: asyncio.Event,
    app_key: str,
    status: ResourceStatus,
) -> None:
    """Wire up a listener that fires when a specific app reaches the given status."""

    async def handler() -> None:
        bus.task_bucket.post_to_loop(event.set)

    bus.on_app_state_changed(handler=handler, app_key=app_key, status=status, once=True)


def wire_up_app_running_listener(bus: "Bus", event: asyncio.Event, app_key: str) -> None:
    """Wire up a listener that fires when a specific app reaches RUNNING status."""
    wire_up_app_state_listener(bus, event, app_key, ResourceStatus.RUNNING)
