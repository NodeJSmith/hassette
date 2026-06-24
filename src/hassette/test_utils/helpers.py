import asyncio
import json
import textwrap
from collections.abc import Mapping, Sequence
from logging import Logger, getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import tomli_w

import hassette.utils.date_utils as _date_utils
from hassette.bus.listeners import (
    DurationConfig,
    HandlerInvoker,
    Listener,
    ListenerIdentity,
    ListenerOptions,
)
from hassette.config.classes import AppManifest
from hassette.conversion import STATE_REGISTRY
from hassette.events import (
    CallServiceEvent,
    ComponentLoadedEvent,
    RawStateChangeEvent,
    ServiceRegisteredEvent,
    create_event_from_hass,
)
from hassette.events.hassette import HassetteFileWatcherEvent, HassetteServiceEvent
from hassette.types import StateT
from hassette.types.enums import BackpressurePolicy, ExecutionMode, ResourceStatus
from hassette.utils.func_utils import callable_name, callable_short_name

if TYPE_CHECKING:
    from hassette.bus.bus import Bus
    from hassette.core.core import Hassette
    from hassette.events import HassEventEnvelopeDict, HassStateDict
    from hassette.resources.service import Service
    from hassette.types.types import BusErrorHandlerType, HandlerType, Predicate, SourceTier

STATE_DICT_KEYS = frozenset({"last_changed", "last_updated", "context"})


def noop() -> None:
    pass


def create_hass_event(event_type: str, data: dict[str, Any]) -> Any:
    """Build a HassEventEnvelopeDict envelope and delegate to create_event_from_hass.

    Args:
        event_type: The HA event type string (e.g., "state_changed", "call_service").
        data: The event data dict specific to the event type.

    Returns:
        The typed Event produced by create_event_from_hass.
    """
    envelope: HassEventEnvelopeDict = {
        "id": 1,  # Discarded by create_event_from_hass; present only to satisfy HassEventEnvelopeDict shape
        "type": "event",
        "event": {
            "event_type": event_type,
            "data": data,
            "origin": "LOCAL",
            "time_fired": _date_utils.now().format_iso(),
            "context": {"id": str(uuid4()), "parent_id": None, "user_id": None},
        },
    }
    return create_event_from_hass(envelope)


def create_state_change_event(
    *,
    entity_id: str,
    old_value: Any,
    new_value: Any,
    old_attrs: dict[str, Any] | None = None,
    new_attrs: dict[str, Any] | None = None,
) -> RawStateChangeEvent:
    """Create a state change event for testing.

    Pass ``None`` for ``old_value`` or ``new_value`` to simulate entity creation or removal
    (produces ``None`` for that state dict, not ``{"state": None, ...}``).
    """
    old_state = make_state_dict(entity_id, str(old_value), attributes=old_attrs) if old_value is not None else None
    new_state = make_state_dict(entity_id, str(new_value), attributes=new_attrs) if new_value is not None else None
    event = create_hass_event(
        "state_changed",
        {"entity_id": entity_id, "old_state": old_state, "new_state": new_state},
    )
    assert isinstance(event, RawStateChangeEvent)
    return event


def create_call_service_event(
    *,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
) -> CallServiceEvent:
    """Create a call service event for testing."""
    event = create_hass_event(
        "call_service",
        {"domain": domain, "service": service, "service_data": service_data or {}},
    )
    assert isinstance(event, CallServiceEvent)
    return event


def create_component_loaded_event(
    component: str,
) -> ComponentLoadedEvent:
    """Create a component_loaded event for testing.

    Args:
        component: The component name (e.g., "mqtt", "zwave").

    Returns:
        ComponentLoadedEvent instance.
    """
    event = create_hass_event("component_loaded", {"component": component})
    assert isinstance(event, ComponentLoadedEvent)
    return event


def create_service_registered_event(
    domain: str,
    service: str,
) -> ServiceRegisteredEvent:
    """Create a service_registered event for testing.

    Args:
        domain: The service domain (e.g., "light").
        service: The service name (e.g., "turn_on").

    Returns:
        ServiceRegisteredEvent instance.
    """
    event = create_hass_event("service_registered", {"domain": domain, "service": service})
    assert isinstance(event, ServiceRegisteredEvent)
    return event


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
    now = _date_utils.now().format_iso()
    return {
        "entity_id": entity_id,
        "state": state,
        "attributes": attributes or {},
        "last_changed": last_changed or now,
        "last_updated": last_updated or now,
        "context": context or {"id": str(uuid4()), "parent_id": None, "user_id": None},
    }


def split_state_kwargs(kwargs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    state_kwargs = {k: v for k, v in kwargs.items() if k in STATE_DICT_KEYS}
    extra_attrs = {k: v for k, v in kwargs.items() if k not in STATE_DICT_KEYS}
    return state_kwargs, extra_attrs


def make_light_state_dict(
    entity_id: str = "light.kitchen",
    state: str = "on",
    brightness: int | None = None,
    color_temp: int | None = None,
    **kwargs: Any,
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

    state_kwargs, extra_attrs = split_state_kwargs(kwargs)
    attributes.update(extra_attrs)

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_sensor_state_dict(
    entity_id: str = "sensor.temperature",
    state: str = "25.5",
    unit_of_measurement: str | None = None,
    device_class: str | None = None,
    **kwargs: Any,
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

    state_kwargs, extra_attrs = split_state_kwargs(kwargs)
    attributes.update(extra_attrs)

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_switch_state_dict(entity_id: str = "switch.outlet", state: str = "on", **kwargs: Any) -> dict[str, Any]:
    """Factory for creating switch state dictionary.

    Args:
        entity_id: The switch entity ID
        state: "on" or "off"
        **kwargs: Additional attributes or state dict fields

    Returns:
        Dictionary matching Home Assistant switch state format
    """
    attributes = {"friendly_name": entity_id.split(".")[-1].replace("_", " ").title()}

    state_kwargs, extra_attrs = split_state_kwargs(kwargs)
    attributes.update(extra_attrs)

    return make_state_dict(entity_id, state, attributes=attributes, **state_kwargs)


def make_typed_state(state_class: type[StateT], state_dict: "dict[str, Any]") -> StateT:
    """Convert a raw state dict to a typed state via the conversion pipeline.

    Replaces direct ``XState.model_validate(dict)`` calls in tests; routes through
    the conversion entry point so tests exercise the same path as production.

    Args:
        state_class: The target state model class (e.g., LightState, SensorState).
        state_dict: A raw state dict as produced by make_state_dict / make_*_state_dict.

    Returns:
        The typed state instance.
    """
    entity_id: str = state_dict.get("entity_id", "<unknown>")
    result = STATE_REGISTRY.coerce_and_construct(state_class, cast("HassStateDict", state_dict), entity_id)
    assert isinstance(result, state_class)
    return result


def make_full_state_change_event(
    entity_id: str, old_state: dict[str, Any] | None, new_state: dict[str, Any] | None
) -> RawStateChangeEvent:
    """Factory for creating state change events from pre-built state dicts.

    Args:
        entity_id: The entity ID
        old_state: Old state dictionary (None for new entity)
        new_state: New state dictionary (None for removed entity)

    Returns:
        RawStateChangeEvent instance
    """
    event = create_hass_event(
        "state_changed",
        {"entity_id": entity_id, "old_state": old_state, "new_state": new_state},
    )
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


def get_app_manifest_for_toml(app: AppManifest) -> dict[str, Any]:
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

    apps_section: dict[str, Any] = {
        "directory": app_dir.as_posix(),
        "autodetect": False,
    }

    if apps:
        for app in apps:
            apps_section[app.app_key] = get_app_manifest_for_toml(app)

    hassette_dict: dict[str, Any] = {
        "dev_mode": dev_mode,
        "apps": apps_section,
    }

    toml_dict = {"hassette": hassette_dict}

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
    await hassette.send_event(event)


async def emit_file_change_event(hassette: "Hassette", changed_paths: set[Path]) -> None:
    """Emit a synthetic file-watcher event for the given paths."""
    event = HassetteFileWatcherEvent.create_event(changed_file_paths=changed_paths)
    await hassette.send_event(event)


def make_service_failed_event(
    service: "Service",
    exception: Exception | None = None,
) -> HassetteServiceEvent:
    """Create a HassetteServiceEvent with FAILED status for testing."""
    return HassetteServiceEvent.from_data(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.FAILED,
        exception=exception or Exception("test"),
    )


def make_service_running_event(service: "Service") -> HassetteServiceEvent:
    """Create a HassetteServiceEvent with RUNNING status for testing."""
    return HassetteServiceEvent.from_data(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.RUNNING,
    )


async def wire_up_app_state_listener(
    bus: "Bus",
    event: asyncio.Event,
    app_key: str,
    status: ResourceStatus,
) -> None:
    """Wire up a listener that fires when a specific app reaches the given status."""

    async def handler() -> None:
        bus.task_bucket.post_to_loop(event.set)

    await bus.on_app_state_changed(
        handler=handler,
        app_key=app_key,
        status=status,
        once=True,
        name=f"hassette.test_utils.wire_up_{app_key}_{status}",
        # Once-listeners participate in collision tracking, so re-wiring the same
        # (app_key, status) — e.g. across a hot-reload — would raise without replace.
        if_exists="replace",
    )


async def wire_up_app_running_listener(bus: "Bus", event: asyncio.Event, app_key: str) -> None:
    """Wire up a listener that fires when a specific app reaches RUNNING status."""
    await wire_up_app_state_listener(bus, event, app_key, ResourceStatus.RUNNING)


def make_task_bucket() -> MagicMock:
    """Create a MagicMock TaskBucket suitable for Listener construction in tests.

    ``spawn`` creates a real ``asyncio.Task`` when a loop is running so the execution-mode
    guard (which spawns and awaits the cancellable child handler task) behaves like production.
    Outside a running loop it returns a MagicMock so sync-context construction still works.
    """
    tb = MagicMock()
    tb.make_async_adapter = MagicMock(side_effect=lambda fn: fn)

    def spawn_side_effect(coro: Any, *, name: str | None = None) -> Any:  # noqa: ARG001
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop (sync-context test): close the coroutine so it isn't reported as
            # "never awaited", then hand back a MagicMock standing in for the Task.
            if asyncio.iscoroutine(coro):
                coro.close()
            return MagicMock()
        return asyncio.create_task(coro)

    tb.spawn = MagicMock(side_effect=spawn_side_effect)
    return tb


def create_listener(
    handler: "HandlerType | None" = None,
    *,
    topic: str = "state_changed.light.test",
    owner_id: str = "test_owner",
    task_bucket: Any = None,
    where: "Predicate | Sequence[Predicate] | None" = None,
    kwargs: Mapping[str, Any] | None = None,
    once: bool = False,
    debounce: float | None = None,
    throttle: float | None = None,
    timeout: float | None = None,
    timeout_disabled: bool = False,
    priority: int = 0,
    mode: "ExecutionMode | str" = ExecutionMode.PARALLEL,
    backpressure: "BackpressurePolicy | str" = BackpressurePolicy.BLOCK,
    app_key: str = "",
    instance_index: int = 0,
    name: str | None = None,
    source_tier: "SourceTier" = "app",
    immediate: bool = False,
    duration: float | None = None,
    entity_id: str | None = None,
    is_attribute_listener: bool = False,
    hold_predicate: "Predicate | None" = None,
    error_handler: "BusErrorHandlerType | None" = None,
    source_location: str = "",
    registration_source: str = "",
    logger: Logger | None = None,
) -> Listener:
    """Test factory: build a Listener from simple kwargs.

    Constructs sub-structs internally and delegates to Listener.create().
    Default handler is a sync lambda; default task_bucket is a MagicMock.
    """
    # duration + debounce/throttle incompatibility is validated by Listener.create() below.
    if duration is not None and not entity_id:
        raise ValueError("'duration' requires an entity_id — use on_state_change() or on_attribute_change()")
    if immediate and not entity_id:
        raise ValueError("'immediate' requires an entity_id — use on_state_change() or on_attribute_change()")

    if handler is None:
        handler = noop
    if task_bucket is None:
        task_bucket = make_task_bucket()

    handler_name = callable_name(handler)
    short_name = callable_short_name(handler)

    identity = ListenerIdentity(
        owner_id=owner_id,
        app_key=app_key,
        instance_index=instance_index,
        name=name,
        source_tier=source_tier,
        handler_name=handler_name,
        handler_short_name=short_name,
        source_location=source_location,
        registration_source=registration_source,
    )

    options = ListenerOptions(
        once=once,
        debounce=debounce,
        throttle=throttle,
        timeout=timeout,
        timeout_disabled=timeout_disabled,
        priority=priority,
        mode=ExecutionMode(mode),
        backpressure=BackpressurePolicy(backpressure),
    )

    invoker = HandlerInvoker.create(
        task_bucket=task_bucket,
        handler=handler,
        kwargs=kwargs,
        options=options,
        error_handler=error_handler,
    )

    duration_config: DurationConfig | None = None
    if entity_id:
        # DurationConfig carries entity_id even when duration/immediate are None —
        # BusService uses entity_id for cancel-listener topic construction and state reads.
        duration_config = DurationConfig(
            entity_id=entity_id,
            duration=duration,
            immediate=immediate,
            is_attribute_listener=is_attribute_listener,
            hold_predicate=hold_predicate,
        )

    return Listener.create(
        topic=topic,
        identity=identity,
        options=options,
        invoker=invoker,
        where=where,
        duration_config=duration_config,
        logger=logger or getLogger("test"),
    )
