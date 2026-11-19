"""Synchronous facade for ``self.integration``, for ``AppSync`` apps."""

import typing
from collections.abc import Mapping
from typing import Any

from hassette_wire import ExecutionMode, LogLevel

from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.types import HandlerType

    from .handles import IntegrationButton, IntegrationSensor, IntegrationSwitch
    from .integration import Integration


class IntegrationSyncFacade(Resource):
    """Synchronous versions of ``self.integration``'s ``add_*`` methods and of each handle's ``set()``.

    For code running outside the event loop, such as an ``AppSync`` hook in a worker thread. Calling these from
    the event loop raises ``RuntimeError``; use the async methods there.
    """

    def __init__(self, hassette: "Hassette", *, integration: "Integration", parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._integration = integration

    async def on_initialize(self) -> None:
        """Mark the facade ready; it wraps ``Integration`` and needs no setup of its own."""
        mark_ready(self, reason="Synchronous integration facade initialized")

    @property
    def config_log_level(self) -> LogLevel:
        """Return the app handler's configured log level, shared with ``Integration``."""
        return self.hassette.config.logging.app_handler

    def add_button(
        self,
        key: str,
        *,
        name: str,
        on_press: "HandlerType",
        mode: ExecutionMode | str | None = None,
        default_entity_id: str | None = None,
    ) -> "IntegrationButton":
        """Declare a button; see ``Integration.add_button``."""
        return self.task_bucket.run_sync(
            self._integration.add_button(
                key, name=name, on_press=on_press, mode=mode, default_entity_id=default_entity_id
            )
        )

    def add_switch(
        self,
        key: str,
        *,
        name: str,
        on_toggle: "HandlerType",
        initial: bool = False,
        mode: ExecutionMode | str | None = None,
        default_entity_id: str | None = None,
    ) -> "IntegrationSwitch":
        """Declare a switch; see ``Integration.add_switch``."""
        return self.task_bucket.run_sync(
            self._integration.add_switch(
                key, name=name, on_toggle=on_toggle, initial=initial, mode=mode, default_entity_id=default_entity_id
            )
        )

    def add_sensor(
        self,
        key: str,
        *,
        name: str,
        unit: str | None = None,
        device_class: str | None = None,
        state_class: str | None = None,
        options: list[str] | None = None,
        default_entity_id: str | None = None,
    ) -> "IntegrationSensor":
        """Declare a sensor; see ``Integration.add_sensor``."""
        return self.task_bucket.run_sync(
            self._integration.add_sensor(
                key,
                name=name,
                unit=unit,
                device_class=device_class,
                state_class=state_class,
                options=options,
                default_entity_id=default_entity_id,
            )
        )

    def set(
        self,
        handle: "IntegrationSwitch | IntegrationSensor",
        value: Any,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        """Set a switch's or sensor's state; see ``IntegrationSwitch.set`` and ``IntegrationSensor.set``."""
        self.task_bucket.run_sync(handle.set(value, attributes))
