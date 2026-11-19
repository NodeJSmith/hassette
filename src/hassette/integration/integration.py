"""``self.integration``: the buttons, switches and sensors one app instance declares to Home Assistant."""

import asyncio
import copy
import typing
from collections.abc import Coroutine, Mapping
from dataclasses import replace
from enum import Enum, auto
from typing import Any, TypeVar

from hassette_wire import BackpressurePolicy, ExecutionMode, LogLevel

from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready
from hassette.types import Topic
from hassette.utils.await_guard import guard_await
from hassette.utils.source_capture import capture_registration_source

from .declarations import (
    Declaration,
    EntityState,
    IntegrationPlatform,
    check_attributes,
    check_value,
    default_state,
    resolve_state,
    validate_default_entity_id,
    validate_key,
    validate_sensor_fields,
)
from .errors import IntegrationDeclarationClosedError, IntegrationHandleClosedError
from .handles import IntegrationButton, IntegrationSensor, IntegrationSwitch
from .sync import IntegrationSyncFacade

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.app.app import App
    from hassette.bus import Subscription
    from hassette.core.integration_service import CommitCounts, IntegrationService
    from hassette.types import HandlerType

HandleT = TypeVar("HandleT", IntegrationButton, IntegrationSwitch)


class Phase(Enum):
    """Where an ``Integration`` is in its instance's run; decides what its handles' reads and writes do."""

    DECLARING = auto()
    """``add_*`` is allowed; ``set()`` values are held until the commit."""

    COMMITTING = auto()
    """The declared set is being written. ``set()`` goes to the service, queued behind the commit."""

    COMMITTED = auto()
    """This resource holds the instance's committed set; reads and ``set()`` use it."""

    CLOSED = auto()
    """The commit failed or this resource shut down; reads and ``set()`` raise."""


class Integration(Resource):
    """Declares an app instance's buttons, switches and sensors, which the hass-hassette integration shows in HA.

    Declare every entity in ``on_initialize``. hassette commits the declared set just before the instance is
    marked running, replacing the set from its last run: an entity no longer declared is removed with its state.
    A switch or sensor keeps its state across restarts for as long as it stays declared.
    """

    sync: IntegrationSyncFacade
    """Synchronous versions of ``add_*`` and ``set()``, for ``AppSync`` apps."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._declarations: dict[str, Declaration] = {}
        self._pending: dict[str, EntityState] = {}
        self._phase = Phase.DECLARING
        self.sync = self.add_child(IntegrationSyncFacade, integration=self)

    async def on_initialize(self) -> None:
        """Mark ready; declarations happen during the app's own initialization, before this runs."""
        mark_ready(self, reason="integration declarations ready")

    @property
    def config_log_level(self) -> LogLevel:
        """Return the app handler's configured log level (``logging.app_handler``)."""
        return self.hassette.config.logging.app_handler

    @property
    def app(self) -> "App[Any]":
        """The app instance that owns this integration."""
        return typing.cast("App[Any]", self.parent)

    @property
    def app_key(self) -> str:
        """The owning app's key."""
        return self.app.app_key

    @property
    def instance_name(self) -> str:
        """The owning instance's name."""
        return self.app.instance_name

    @property
    def instance_key(self) -> tuple[str, str]:
        """``(app_key, instance_name)``: the instance this resource declares for."""
        return (self.app_key, self.instance_name)

    @property
    def service(self) -> "IntegrationService":
        """The core service holding every instance's committed declarations and state."""
        return self.hassette.integration_service

    def add_button(
        self,
        key: str,
        *,
        name: str,
        on_press: "HandlerType",
        mode: ExecutionMode | str | None = None,
        default_entity_id: str | None = None,
    ) -> Coroutine[Any, Any, IntegrationButton]:
        """Declare a button. Pressing it in Home Assistant runs ``on_press``.

        Must be awaited, during initialization. ``on_press`` is registered as a bus listener named
        ``integration.button.<key>``, so it gets the bus's execution modes, error handling and telemetry.

        Args:
            key: Identifies the button within this instance: lowercase letters, digits and ``_``, starting with a
                letter. Changing it makes a new entity.
            name: The button's display name in Home Assistant.
            on_press: The handler to run on a press.
            mode: What a press does while the previous one is still running; the bus's ``ExecutionMode``,
                ``single`` by default.
            default_entity_id: A full entity id (``"button.feed_cat"``) Home Assistant uses when it first creates
                the entity; ignored after that.

        Returns:
            The button's handle.

        Raises:
            ValueError: An invalid or duplicate key, or an invalid ``default_entity_id``.
            IntegrationDeclarationClosedError: The instance's declarations were already committed.
        """
        platform = IntegrationPlatform.BUTTON
        declaration = Declaration(
            key=self.check_declarable(key, platform),
            platform=platform,
            name=name,
            default_entity_id=validate_default_entity_id(default_entity_id, platform),
        )
        source_location, registration_source = capture_registration_source()
        return guard_await(
            self.declare_with_handler(
                declaration, on_press, mode, IntegrationButton, source_location, registration_source
            ),
            owner=self.parent,
            source_location=source_location,
            method_name="add_button",
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
    ) -> Coroutine[Any, Any, IntegrationSwitch]:
        """Declare a switch. Toggling it in Home Assistant runs ``on_toggle``.

        Must be awaited, during initialization. ``on_toggle`` is registered as a bus listener named
        ``integration.switch.<key>``; it reads the commanded value with ``D.SwitchCommand``. The switch's state
        changes only when the app calls ``set()``, so call it first thing in the handler.

        Args:
            key: Identifies the switch within this instance: lowercase letters, digits and ``_``, starting with a
                letter. Changing it makes a new entity.
            name: The switch's display name in Home Assistant.
            on_toggle: The handler to run on a toggle.
            initial: The state of a switch that has never been stored. Changing it later has no effect on a switch
                that already has a stored state.
            mode: What a toggle does while the previous one is still running; the bus's ``ExecutionMode``,
                ``single`` by default.
            default_entity_id: A full entity id (``"switch.show"``) Home Assistant uses when it first creates the
                entity; ignored after that.

        Returns:
            The switch's handle.

        Raises:
            ValueError: An invalid or duplicate key, a non-bool ``initial``, or an invalid ``default_entity_id``.
            IntegrationDeclarationClosedError: The instance's declarations were already committed.
        """
        platform = IntegrationPlatform.SWITCH
        if not isinstance(initial, bool):
            raise ValueError(f"switch {key!r} initial must be a bool, got {initial!r}")
        declaration = Declaration(
            key=self.check_declarable(key, platform),
            platform=platform,
            name=name,
            default_entity_id=validate_default_entity_id(default_entity_id, platform),
            initial=initial,
        )
        source_location, registration_source = capture_registration_source()
        return guard_await(
            self.declare_with_handler(
                declaration, on_toggle, mode, IntegrationSwitch, source_location, registration_source
            ),
            owner=self.parent,
            source_location=source_location,
            method_name="add_switch",
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
    ) -> Coroutine[Any, Any, IntegrationSensor]:
        """Declare a sensor, whose value the app sets.

        Must be awaited, during initialization. The device class, unit and state class decide which values
        ``set()`` accepts, following Home Assistant's own rules.

        Args:
            key: Identifies the sensor within this instance: lowercase letters, digits and ``_``, starting with a
                letter. Changing it makes a new entity.
            name: The sensor's display name in Home Assistant.
            unit: The unit of measurement; a sensor with a unit is numeric.
            device_class: One of Home Assistant's sensor device classes (``"temperature"``, ``"enum"``,
                ``"timestamp"``, ...).
            state_class: ``"measurement"``, ``"measurement_angle"``, ``"total"`` or ``"total_increasing"``; a
                sensor with a state class is numeric.
            options: The allowed values of an enum sensor (``device_class="enum"``), which requires them.
            default_entity_id: A full entity id (``"sensor.next_feed"``) Home Assistant uses when it first creates
                the entity; ignored after that.

        Returns:
            The sensor's handle.

        Raises:
            ValueError: An invalid or duplicate key, an unknown device or state class, an enum sensor without
                options, options on another sensor, or an invalid ``default_entity_id``.
            IntegrationDeclarationClosedError: The instance's declarations were already committed.
        """
        platform = IntegrationPlatform.SENSOR
        key = self.check_declarable(key, platform)
        declaration = Declaration(
            key=key,
            platform=platform,
            name=name,
            default_entity_id=validate_default_entity_id(default_entity_id, platform),
            unit=unit,
            device_class=device_class,
            state_class=state_class,
            options=validate_sensor_fields(key, device_class=device_class, state_class=state_class, options=options),
        )
        source_location, _ = capture_registration_source()
        return guard_await(
            self.declare_sensor(declaration),
            owner=self.parent,
            source_location=source_location,
            method_name="add_sensor",
        )

    def check_declarable(self, key: object, platform: IntegrationPlatform) -> str:
        """Return ``key`` if it is valid and not yet declared, and the declaration window is open.

        Raises:
            IntegrationDeclarationClosedError: The window is closed.
            ValueError: The key is invalid or already declared on this instance.
        """
        valid = validate_key(key, platform)
        if self._phase is not Phase.DECLARING:
            raise IntegrationDeclarationClosedError(valid, platform)
        if (existing := self._declarations.get(valid)) is not None:
            raise ValueError(f"key {valid!r} is already declared on this instance, as a {existing.platform}")
        return valid

    async def declare_sensor(self, declaration: Declaration) -> IntegrationSensor:
        """Record a sensor declaration.

        Re-checks the key, which ``add_sensor`` already checked: the window may have closed, or the key been
        declared, between that call and this coroutine running.
        """
        self.check_declarable(declaration.key, declaration.platform)
        self._declarations[declaration.key] = declaration
        return IntegrationSensor(self, declaration)

    async def declare_with_handler(
        self,
        declaration: Declaration,
        handler: "HandlerType",
        mode: ExecutionMode | str | None,
        handle_cls: type[HandleT],
        source_location: str,
        registration_source: str | None,
    ) -> HandleT:
        """Record a button or switch declaration and register its handler's listener on the app's bus.

        The key is reserved before the listener registers and released if registration fails, so a declaration
        never exists without its listener. It is re-checked first, since the window may have closed, or the key
        been declared, between the ``add_*`` call and this coroutine running.
        """
        self.check_declarable(declaration.key, declaration.platform)
        self._declarations[declaration.key] = declaration
        try:
            subscription = await self.register_listener(
                declaration, handler, mode, source_location, registration_source
            )
        except BaseException:
            del self._declarations[declaration.key]
            raise
        return handle_cls(self, declaration, subscription)

    async def register_listener(
        self,
        declaration: Declaration,
        handler: "HandlerType",
        mode: ExecutionMode | str | None,
        source_location: str,
        registration_source: str | None,
    ) -> "Subscription":
        """Register ``handler`` on this instance's command events for ``declaration``'s key and platform."""
        scope = [
            P.ValueIs(source=get_path("payload.data.app_key"), condition=self.app_key),
            P.ValueIs(source=get_path("payload.data.instance_name"), condition=self.instance_name),
            P.ValueIs(source=get_path("payload.data.key"), condition=declaration.key),
            P.ValueIs(source=get_path("payload.data.platform"), condition=str(declaration.platform)),
        ]
        return await self.app.bus._on_internal(
            topic=Topic.HASSETTE_EVENT_INTEGRATION_COMMAND,
            handler=handler,
            scope=scope,
            name=f"integration.{declaration.platform}.{declaration.key}",
            mode=mode,
            backpressure=BackpressurePolicy.BLOCK,
            source_location=source_location,
            registration_source=registration_source,
        )

    def read_state(self, declaration: Declaration) -> EntityState:
        """A switch's or sensor's current state, as its handle exposes it, as a copy the caller may change.

        During initialization: the state the commit will start it with (``resolve_state``). While the commit is
        being written: its restored state or default, since the values set during initialization are in the commit
        and show once it lands. After: the committed state.

        Raises:
            IntegrationHandleClosedError: The instance's commit failed, or this resource has shut down.
        """
        if self._phase is Phase.CLOSED:
            raise IntegrationHandleClosedError(self.instance_name, declaration.key)
        committed = self.service.committed(self.instance_key, declaration)
        if self._phase is Phase.COMMITTED:
            state = committed.state if committed is not None else default_state(declaration)
        else:
            pending = self._pending.get(declaration.key)
            state, _ = resolve_state(declaration, pending, None if committed is None else committed.state)
        return replace(state, attributes=copy.deepcopy(dict(state.attributes)))

    async def set_state(self, declaration: Declaration, value: object, attributes: Mapping[str, Any] | None) -> None:
        """Validate and set a switch's or sensor's state: held until the commit during init, written after it.

        Once the declarations are submitted, the service decides: it accepts the write only from the
        ``Integration`` that holds the instance's committed set (``IntegrationService.is_owner``). A closed
        resource refuses first, since a shutdown during the commit closes it before the commit makes it the owner.
        """
        if self._phase is Phase.CLOSED:
            raise IntegrationHandleClosedError(self.instance_name, declaration.key)
        state = EntityState(
            value=check_value(declaration, value), attributes=check_attributes(declaration.key, attributes)
        )
        if self._phase is Phase.DECLARING:
            self._pending[declaration.key] = state
            return
        await self.service.set_state(self, declaration, state)

    async def commit_declarations(self) -> "CommitCounts | None":
        """Close the declaration window and commit the declared set with its pending values. Framework-internal.

        The window closes and the pending set is taken in one synchronous step before the write is submitted, so
        no declaration can miss the commit. The write is shielded from cancellation: once submitted, its outcome
        lands in the service, and this resource's phase follows it, whether or not the caller is still waiting.
        Pending values are discarded either way.

        An instance that declared nothing and has nothing committed has nothing to replace, so it writes nothing.

        Returns:
            How the commit changed the instance's set, or ``None`` when there was nothing to commit.

        Raises:
            Exception: The commit failed; the instance's last committed set is unchanged.
        """
        declarations = list(self._declarations.values())
        pending = dict(self._pending)
        self._pending.clear()
        if not declarations and not self.service.entities(*self.instance_key):
            self._phase = Phase.COMMITTED
            return None
        self._phase = Phase.COMMITTING
        return await asyncio.shield(self.commit_and_settle(declarations, pending))

    async def commit_and_settle(
        self, declarations: list[Declaration], pending: Mapping[str, EntityState]
    ) -> "CommitCounts":
        """Run the commit and move to its resulting phase; shielded by ``commit_declarations``.

        A shutdown that lands while the commit is in flight has already closed this resource, so a commit that
        then succeeds is released straight away rather than left owned by a closed resource.
        """
        try:
            counts = await self.service.commit_instance(self, declarations, pending)
        except BaseException:
            self._phase = Phase.CLOSED
            raise
        if self._phase is Phase.CLOSED:
            self.service.release(self)
        else:
            self._phase = Phase.COMMITTED
        return counts

    async def on_shutdown(self) -> None:
        """Close this resource's handles: later reads and writes raise ``IntegrationHandleClosedError``."""
        self._phase = Phase.CLOSED
        self._pending.clear()
        self.service.release(self)
