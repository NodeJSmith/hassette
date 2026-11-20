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
    validate_name,
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
    """The declared set is being written. Reads show the values set during initialization; ``set()`` waits for
    the commit to settle, then writes (COMMITTED) or raises (CLOSED).

    This phase is the ``Integration``'s own early refusal and ordering: a ``set()`` never reaches the service ahead
    of the commit. ``IntegrationService.is_owner`` is the authority for writes already queued when ownership
    changes, such as an old instance's write queued before a restart's new commit landed.
    """

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
        self._reserved: set[str] = set()
        self._commit_task: asyncio.Task[CommitCounts] | None = None
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
    def _closed(self) -> bool:
        """Whether this resource has shut down or its commit failed, so it must not own the instance's set."""
        return self._phase is Phase.CLOSED

    @property
    def _service(self) -> "IntegrationService":
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
            ValueError: An invalid or duplicate key, an invalid name, or an invalid ``default_entity_id``.
            IntegrationDeclarationClosedError: The instance's declarations were already committed.
        """
        platform = IntegrationPlatform.BUTTON
        declaration = Declaration(
            key=self._check_declarable(key, platform),
            platform=platform,
            name=validate_name(name, platform),
            default_entity_id=validate_default_entity_id(default_entity_id, platform),
        )
        source_location, registration_source = capture_registration_source()
        return guard_await(
            self._declare_with_handler(
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
            ValueError: An invalid or duplicate key, an invalid name, a non-bool ``initial``, or an invalid
                ``default_entity_id``.
            IntegrationDeclarationClosedError: The instance's declarations were already committed.
        """
        platform = IntegrationPlatform.SWITCH
        if not isinstance(initial, bool):
            raise ValueError(f"switch {key!r} initial must be a bool, got {initial!r}")
        declaration = Declaration(
            key=self._check_declarable(key, platform),
            platform=platform,
            name=validate_name(name, platform),
            default_entity_id=validate_default_entity_id(default_entity_id, platform),
            initial=initial,
        )
        source_location, registration_source = capture_registration_source()
        return guard_await(
            self._declare_with_handler(
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
            ValueError: An invalid or duplicate key, an invalid name, an unknown device or state class, an enum
                sensor without options or with a unit or state class, options on another sensor, or an invalid
                ``default_entity_id``.
            IntegrationDeclarationClosedError: The instance's declarations were already committed.
        """
        platform = IntegrationPlatform.SENSOR
        key = self._check_declarable(key, platform)
        declaration = Declaration(
            key=key,
            platform=platform,
            name=validate_name(name, platform),
            default_entity_id=validate_default_entity_id(default_entity_id, platform),
            unit=unit,
            device_class=device_class,
            state_class=state_class,
            options=validate_sensor_fields(
                key, device_class=device_class, state_class=state_class, unit=unit, options=options
            ),
        )
        source_location, _ = capture_registration_source()
        return guard_await(
            self._declare_sensor(declaration),
            owner=self.parent,
            source_location=source_location,
            method_name="add_sensor",
        )

    def _check_declarable(self, key: object, platform: IntegrationPlatform) -> str:
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
        if valid in self._reserved:
            raise ValueError(f"key {valid!r} is already being declared on this instance")
        return valid

    async def _declare_sensor(self, declaration: Declaration) -> IntegrationSensor:
        """Record a sensor declaration.

        Re-checks the key, which ``add_sensor`` already checked: the window may have closed, or the key been
        declared, between that call and this coroutine running.
        """
        self._check_declarable(declaration.key, declaration.platform)
        self._declarations[declaration.key] = declaration
        return IntegrationSensor(self, declaration)

    async def _declare_with_handler(
        self,
        declaration: Declaration,
        handler: "HandlerType",
        mode: ExecutionMode | str | None,
        handle_cls: type[HandleT],
        source_location: str,
        registration_source: str | None,
    ) -> HandleT:
        """Register a button or switch's listener, then record its declaration.

        The listener registers first, so a commit never includes a declaration whose listener isn't registered.
        The key is reserved while it registers, so a second declaration of it is rejected meanwhile. The
        window is re-checked first, since it may have closed, or the key been declared, between the ``add_*``
        call and this coroutine running, and again after registering, since a commit may have closed it while
        the listener registered; that listener is then cancelled.
        """
        key = self._check_declarable(declaration.key, declaration.platform)
        self._reserved.add(key)
        try:
            subscription = await self._register_listener(
                declaration, handler, mode, source_location, registration_source
            )
            if self._phase is not Phase.DECLARING:
                subscription.cancel()
                raise IntegrationDeclarationClosedError(key, declaration.platform)
            self._declarations[key] = declaration
        finally:
            self._reserved.discard(key)
        return handle_cls(self, declaration, subscription)

    async def _register_listener(
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

    def _read_state(self, declaration: Declaration) -> EntityState:
        """A switch's or sensor's current state, as its handle exposes it, as a copy the caller may change.

        During initialization and while the commit is being written: the state the commit starts it with
        (``resolve_state``), so a value set during initialization reads back throughout. After: the committed state.

        Raises:
            IntegrationHandleClosedError: The instance's commit failed, or this resource has shut down.
        """
        if self._phase is Phase.CLOSED:
            raise IntegrationHandleClosedError(self.instance_name, declaration.key)
        committed = self._service.committed(self.instance_key, declaration)
        if self._phase is Phase.COMMITTED:
            state = committed.state if committed is not None else default_state(declaration)
        else:
            pending = self._pending.get(declaration.key)
            state, _ = resolve_state(declaration, pending, None if committed is None else committed.state)
        return replace(state, attributes=copy.deepcopy(dict(state.attributes)))

    async def _set_state(self, declaration: Declaration, value: object, attributes: Mapping[str, Any] | None) -> None:
        """Validate and set a switch's or sensor's state: held until the commit during init, written after it.

        While the commit is in flight the write waits for it to settle, so it never reaches the service ahead of
        the commit, then follows the resulting phase. After that the service decides: it accepts the write only
        from the ``Integration`` that holds the instance's committed set (``IntegrationService.is_owner``), which
        also covers a write queued before a restart's new commit landed.

        Raises:
            ValueError: ``value`` or ``attributes`` is invalid.
            IntegrationHandleClosedError: The instance has stopped or its commit failed.
        """
        if self._phase is Phase.CLOSED:
            raise IntegrationHandleClosedError(self.instance_name, declaration.key)
        state = EntityState(
            value=check_value(declaration, value), attributes=check_attributes(declaration.key, attributes)
        )
        if self._phase is Phase.DECLARING:
            self._pending[declaration.key] = state
            return
        if self._phase is Phase.COMMITTING and self._commit_task is not None:
            # Waiting, not awaiting the task: its failure belongs to the caller of ``_commit_declarations``, and
            # cancelling this caller must not cancel the commit.
            await asyncio.wait({self._commit_task})
            if self._closed:
                raise IntegrationHandleClosedError(self.instance_name, declaration.key)
        await self._service.set_state(self, declaration, state)

    async def _commit_declarations(self) -> "CommitCounts | None":
        """Close the declaration window and commit the declared set with its pending values. Framework-internal.

        The window closes and the declared set and pending values are taken in one synchronous step before the
        write is submitted, so no declaration can miss the commit. The write runs as its own task, shielded from
        cancellation: once started, its outcome lands in the service, and this resource's phase follows it,
        whether or not the caller is still waiting. The pending values stay readable until the commit settles,
        then are discarded whatever its outcome.

        An instance that declared nothing and has nothing committed has nothing to replace, so it writes nothing.

        Returns:
            How the commit changed the instance's set, or ``None`` when there was nothing to commit or this
            resource is already closed.

        Raises:
            Exception: The commit failed; the instance's last committed set is unchanged.
        """
        declarations = list(self._declarations.values())
        if self._closed:
            return None
        if not declarations and not self._service.entities(*self.instance_key):
            self._phase = Phase.COMMITTED
            self._pending.clear()
            self._service.claim(self)
            return None
        self._phase = Phase.COMMITTING
        self._commit_task = asyncio.create_task(self._commit_and_settle(declarations, dict(self._pending)))
        self._commit_task.add_done_callback(self._log_unawaited_commit_failure)
        return await asyncio.shield(self._commit_task)

    def _log_unawaited_commit_failure(self, task: "asyncio.Task[CommitCounts]") -> None:
        """Consume the commit's failure so it is logged even when the caller stopped waiting (it was cancelled).

        The caller that is still waiting gets the exception from the shield and reports it; this only logs at
        DEBUG so a commit failing after its caller was cancelled isn't left as "never retrieved".
        """
        if task.cancelled() or (exc := task.exception()) is None:
            return
        self.logger.debug("Integration commit of app instance '%s/%s' failed", *self.instance_key, exc_info=exc)

    async def _commit_and_settle(
        self, declarations: list[Declaration], pending: Mapping[str, EntityState]
    ) -> "CommitCounts":
        """Run the commit and move to its resulting phase; run as a task by ``_commit_declarations``.

        A shutdown that lands while the commit is in flight has already closed this resource, so the service
        doesn't make a closed resource the owner of what the commit writes.
        """
        try:
            counts = await self._service.commit_instance(self, declarations, pending)
        except BaseException:
            self._phase = Phase.CLOSED
            raise
        finally:
            self._pending.clear()
        if self._phase is not Phase.CLOSED:
            self._phase = Phase.COMMITTED
        return counts

    async def on_shutdown(self) -> None:
        """Close this resource's handles: later reads and writes raise ``IntegrationHandleClosedError``."""
        self._close()

    def _close(self) -> None:
        """Close this resource and end its ownership of the instance. Idempotent.

        Runs from its own shutdown, and from the lifecycle when the instance's stop finishes, which covers a
        walk-away whose teardown never reached this resource. A commit still in flight then lands unowned.
        """
        self._phase = Phase.CLOSED
        self._pending.clear()
        self._service.release(self)
