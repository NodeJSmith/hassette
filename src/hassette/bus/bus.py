"""
Event bus for subscribing to Home Assistant and Hassette events with powerful filtering.

The Bus provides a clean interface for listening to state changes, service calls, and other events
from Home Assistant. Each app gets its own Bus instance that automatically manages subscriptions
and cleanup. Use predicates and conditions to filter events precisely.

Registration methods (``on_state_change``, ``on_attribute_change``, ``on_call_service``,
``on``, etc.) return a ``Coroutine`` and must be awaited. The ``name=`` parameter is required on
every call — omitting it raises ``ListenerNameRequiredError`` synchronously at call time, before
any handle is constructed. Registration completes inline: ``sub.listener.db_id`` is a valid
integer immediately when the awaited call returns.

Examples:
    Basic state change subscription

    ```python
    # Listen to all changes on an entity — name= is required
    await self.bus.on_state_change("light.kitchen", handler=self.on_light_change, name="kitchen_light")
    ```

    State change with value filters

    ```python
    # Only when light turns on
    await self.bus.on_state_change("light.kitchen", changed_to="on", handler=self.on_light_on, name="kitchen_on")

    # Only when temperature increases above 20
    await self.bus.on_state_change(
        "sensor.temperature",
        changed_to=lambda temp: temp > 20,
        handler=self.on_temp_high,
        name="temp_high",
    )
    ```

    Attribute change monitoring

    ```python
    # Monitor battery level changes
    await self.bus.on_attribute_change(
        "sensor.phone_battery",
        "battery_level",
        handler=self.on_battery_change,
        name="phone_battery",
    )
    ```

    Service call interception

    ```python
    # Listen to light service calls
    await self.bus.on_call_service(
        domain="light",
        service="turn_on",
        handler=self.on_light_service_call,
        name="light_turn_on",
    )
    ```

    Using glob patterns and complex predicates

    ```python
    from hassette import C

    # All lights in kitchen
    await self.bus.on_state_change("light.*kitchen*", handler=self.on_kitchen_light, name="kitchen_lights")

    # Comparison condition - temperature increased
    await self.bus.on_state_change(
        "sensor.temperature",
        changed=C.Increased(),
        handler=self.on_high_temp,
        name="temp_increased",
    )
    ```

    Event options for timing control

    ```python
    # Run only once
    await self.bus.on_state_change("light.kitchen", handler=handler, once=True, name="kitchen_once")

    # Debounce rapid changes (wait 5 seconds after last event)
    await self.bus.on_state_change("sensor.motion", handler=handler, debounce=5.0, name="motion_debounced")

    # Throttle frequent events (max once per 10 seconds)
    await self.bus.on_state_change("sensor.temperature", handler=handler, throttle=10.0, name="temp_throttled")
    ```
"""

import logging
import typing
from collections.abc import Coroutine, Mapping
from functools import partial
from typing import Any, Unpack

from typing_extensions import Sentinel

from hassette.const import NOT_PROVIDED
from hassette.core.await_guard import guard_await
from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.events.base import Event, HassettePayload
from hassette.exceptions import DuplicateListenerError, ListenerNameRequiredError
from hassette.resources.base import Resource
from hassette.types import ComparisonCondition, Topic
from hassette.types.enums import ResourceStatus
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.func_utils import callable_name, callable_short_name
from hassette.utils.glob_utils import is_glob
from hassette.utils.source_capture import capture_registration_source

from .listeners import DurationConfig, HandlerInvoker, Listener, ListenerIdentity, ListenerOptions, Subscription
from .options import Options
from .sync import BusSyncFacade

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from hassette import Hassette
    from hassette.core.bus_service import BusService
    from hassette.types import ChangeType, HandlerType, Predicate
    from hassette.types.types import BusErrorHandlerType


class Bus(Resource):
    """Individual event bus instance for a specific owner (e.g., App or Service)."""

    bus_service: "BusService"

    sync: BusSyncFacade
    """Synchronous facade for registering listeners from sync code (e.g. ``AppSync`` hooks)."""

    priority: int = 0
    """Priority level for event handlers created by this bus."""

    def __init__(self, hassette: "Hassette", *, priority: int = 0, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        assert self.parent is not None, "Bus requires a parent Resource for telemetry identity (app_key/source_tier)"
        assert self.hassette._bus_service is not None, "Bus service not initialized"
        self.bus_service = self.hassette._bus_service
        self.priority = priority
        self._registered_handler_names: dict[tuple[str, int, str, str], str] = {}
        self._error_handler: BusErrorHandlerType | None = None
        self.sync = self.add_child(BusSyncFacade, bus=self)

    async def on_initialize(self) -> None:
        # Clear before any on() calls so partial-init failures don't leave stale keys.
        self._registered_handler_names.clear()
        self._error_handler = None
        self.mark_ready(reason="Bus initialized")

    async def on_shutdown(self) -> None:
        """Cleanup all listeners owned by this bus's owner on shutdown."""
        self.remove_all_listeners()

    def on_error(self, handler: "BusErrorHandlerType") -> None:
        """Register an app-level error handler for this bus.

        The handler is called when any listener on this bus raises an exception
        (including ``TimeoutError``) and the listener does not have its own
        per-registration error handler.

        This is an app-level fallback — it is resolved at dispatch time, not at listener
        registration time. A later call to ``on_error()`` replaces any previously registered
        handler.

        Note: error handlers are spawned as fire-and-forget tasks. Handlers spawned near
        app shutdown may be cancelled before they complete. Do not rely on error handlers
        for delivery-critical alerting during system teardown.

        Args:
            handler: A sync or async callable that accepts a :class:`~hassette.bus.error_context.BusErrorContext`.
        """
        self._error_handler = handler

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.logging.bus_service

    def add_listener(self, listener: "Listener") -> "Coroutine[Any, Any, None]":
        """Add a pre-built listener to the bus.

        This is the direct entry point for callers that construct a ``Listener``
        externally. The normal registration flow (``on_state_change``, ``on()``,
        etc.) goes through ``_on_internal`` instead.

        Raises:
            ListenerNameRequiredError: If the listener has no ``name`` (required for all DB-registered
                listeners, including once-listeners; cancel-listeners bypass this path entirely).
            DuplicateListenerError: If the listener's natural key is already registered on this bus instance.
        """
        # Synchronous validation runs before the handle is constructed (design Edge Cases).
        if listener.identity.name is None:
            raise ListenerNameRequiredError(handler_method=listener.identity.handler_name, topic=listener.topic)
        # _registration_source discarded: the pre-built Listener already carries identity.source_location /
        # registration_source; only warning attribution needs the location here.
        source_location, _registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._add_listener(listener),
            owner=self.parent,
            source_location=source_location,
        )

    async def _add_listener(self, listener: "Listener") -> None:
        """Async body for add_listener: collision check + DB registration.

        register_and_check_collision is a registry mutation — it must not run for a
        never-awaited call (would pollute the duplicate-name registry). Matches the
        on() path where collision check lives in _on_internal.
        """
        self.register_and_check_collision(listener)
        await self.bus_service.add_listener(listener)

    def register_and_check_collision(self, listener: "Listener") -> None:
        """Register a non-once listener's natural key, raising DuplicateListenerError on a same-session clash.

        Mutates the per-bus key registry as a side effect — this is the single point where in-session
        duplicate detection happens. Once-listeners are exempt and are not registered.
        """
        if listener.options.once:
            return
        natural_key = self._listener_natural_key(listener)
        if natural_key in self._registered_handler_names:
            existing_handler = self._registered_handler_names[natural_key]
            raise DuplicateListenerError(
                name=listener.identity.name or "",
                topic=listener.topic,
                existing_handler=existing_handler,
                duplicate_handler=listener.identity.handler_name,
            )
        self._registered_handler_names[natural_key] = listener.identity.handler_name

    def _listener_natural_key(self, listener: "Listener") -> tuple[str, int, str, str]:
        """Compute the natural key tuple for a listener (for collision tracking).

        CANONICAL form: ``(app_key, instance_index, name, topic)``.
        Matches the SQL unique index defined in 001.sql and the repository upsert ON CONFLICT target.
        """
        return (
            listener.identity.app_key,
            listener.identity.instance_index,
            listener.identity.name or "",
            listener.topic,
        )

    def remove_listener(self, listener: "Listener") -> None:
        """Remove a listener from the bus."""
        natural_key = self._listener_natural_key(listener)
        self._registered_handler_names.pop(natural_key, None)
        self.bus_service.remove_listener(listener)

    def remove_all_listeners(self) -> None:
        """Remove all listeners owned by this bus's owner."""
        self._registered_handler_names.clear()
        self.bus_service.remove_listeners_by_owner(self.owner_id)

    def get_listeners(self) -> list["Listener"]:
        """Get all listeners owned by this bus's owner."""
        return self.bus_service.get_listeners_by_owner(self.owner_id)

    async def emit(self, topic: str, data: object) -> None:
        """Broadcast data to all subscribers of the given topic.

        Subscribers annotated with ``D.EventData[T]`` receive ``data`` pre-extracted.
        If the internal event stream is closed (during shutdown), the event is silently dropped.
        """
        payload = HassettePayload(data=data)
        event = Event(topic=topic, payload=payload)
        await self.hassette.send_event(event)

    def on(
        self,
        *,
        topic: str,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to an event topic with optional filtering and modifiers.

        This is the public registration method for raw topic subscriptions. Must be awaited.
        Registration completes before the call returns — ``sub.listener.db_id`` is a valid
        integer immediately on return.

        Args:
            topic: The event topic to listen to.
            handler: The function to call when the event matches.
            where: Optional predicates to filter events. These can be custom callables or predefined predicates from
                `hassette.event_handling.predicates`. They will receive the full event for evaluation.
            kwargs: Keyword arguments to pass to the handler.
            once: If True, the handler will be called only once and then removed.
            debounce: If set, applies a debounce to the handler.
            throttle: If set, applies a throttle to the handler.
            timeout: Per-listener timeout in seconds. Overrides the global event_handler_timeout_seconds config.
                None means fall through to the config default.
            timeout_disabled: When True, disables timeout enforcement for this listener regardless of config.
            name: Required. Stable string identifier for this listener. Forms part of the natural
                key ``(app_key, instance_index, name, topic)`` used for upsert deduplication across
                restarts. Omitting it raises ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.

        Returns:
            A subscription object. ``sub.cancel()`` removes the listener.
            ``sub.listener.db_id`` is a valid integer immediately on return.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already registered.
        """
        if name is None:
            raise ListenerNameRequiredError(handler_method=callable_name(handler), topic=topic)
        # Eager capture in the public def — user frame is live here (not inside the async body).
        # Returns a 2-tuple — unpack it. Two destinations: guard_await (warning attribution) AND
        # _on_internal (populates ListenerIdentity.source_location / registration_source on the DB record).
        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._on_internal(
                topic=topic,
                handler=handler,
                where=where,
                kwargs=kwargs,
                once=once,
                debounce=debounce,
                throttle=throttle,
                timeout=timeout,
                timeout_disabled=timeout_disabled,
                name=name,
                on_error=on_error,
                duration_config=None,
                source_location=source_location,
                registration_source=registration_source,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    async def _on_internal(
        self,
        *,
        topic: str,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        duration_config: "DurationConfig | None" = None,
        source_location: str = "",
        registration_source: str | None = None,
    ) -> Subscription:
        """Private registration method carrying the full parameter set.

        Called by on() (with duration_config=None) and by _subscribe() (which
        builds DurationConfig from duration/entity_id when provided).

        source_location and registration_source are captured in the public def (user
        frame live there) and threaded down here to populate ListenerIdentity — the
        capture must NOT be duplicated here or the user frame will be gone by then.

        Builds all sub-structs (ListenerIdentity, ListenerOptions, HandlerInvoker)
        here and calls Listener.create() via the sub-struct path.

        DB registration is awaited inline — the listener's db_id is set and the
        listener is routable before this method returns.
        """
        parent = self.parent
        assert parent is not None
        app_key = parent.app_key
        instance_index = parent.index
        source_tier = parent.source_tier
        assert source_tier in ("app", "framework"), f"Invalid source_tier={source_tier!r} on {parent.class_name}"

        handler_name = callable_name(handler)
        short_name = callable_short_name(handler)

        if name is None:
            raise ListenerNameRequiredError(handler_method=handler_name, topic=topic)

        identity = ListenerIdentity(
            owner_id=self.owner_id,
            app_key=app_key,
            instance_index=instance_index,
            name=name,
            source_tier=source_tier,
            handler_name=handler_name,
            handler_short_name=short_name,
            source_location=source_location,
            registration_source=registration_source or "",
        )

        options = ListenerOptions(
            once=once,
            debounce=debounce,
            throttle=throttle,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            priority=self.priority,
        )

        invoker = HandlerInvoker.create(
            task_bucket=self.task_bucket,
            handler=handler,
            kwargs=kwargs,
            options=options,
            error_handler=on_error,
            app_error_handler_resolver=lambda: self._error_handler,
        )

        listener = Listener.create(
            topic=topic,
            identity=identity,
            options=options,
            invoker=invoker,
            where=where,
            duration_config=duration_config,
            logger=self.logger,
        )

        self.register_and_check_collision(listener)

        def unsubscribe() -> None:
            self.remove_listener(listener)

        await self.bus_service.add_listener(listener)
        return Subscription(listener, unsubscribe)

    async def _subscribe(
        self,
        *,
        method_name: str,
        topic: str,
        handler: "HandlerType",
        preds: list["Predicate"],
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        log_params: Mapping[str, Any] | None = None,
        immediate: bool = False,
        duration: float | None = None,
        entity_id: str | None = None,
        is_attribute_listener: bool = False,
        hold_preds: list["Predicate"] | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        source_location: str = "",
        registration_source: str | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Common subscription tail: log, normalize where, delegate to _on_internal()."""
        if self.logger.isEnabledFor(logging.DEBUG):
            filtered = (
                {k: v for k, v in log_params.items() if v is not None and not isinstance(v, Sentinel)}
                if log_params
                else {}
            )
            params_str = ", ".join(f"{k}='{v}'" for k, v in filtered.items())

            self.logger.debug(
                "Subscribing to %s with %s - being handled by '%s'",
                method_name,
                params_str,
                callable_short_name(handler),
            )

        if where is not None:
            normalized_where = where if callable(where) else P.AllOf.ensure_iterable(where)
            preds.append(normalized_where)
            if hold_preds is not None:
                hold_preds = [*hold_preds, normalized_where]

        # Build DurationConfig when entity_id is provided (for duration or immediate listeners)
        duration_config: DurationConfig | None = None
        if entity_id:
            duration_config = DurationConfig(
                entity_id=entity_id,
                duration=duration,
                immediate=immediate,
                is_attribute_listener=is_attribute_listener,
                hold_predicate=P.AllOf.ensure_iterable(hold_preds) if hold_preds else None,
            )

        return await self._on_internal(
            topic=topic,
            handler=handler,
            where=preds,
            kwargs=kwargs,
            duration_config=duration_config,
            name=name,
            on_error=on_error,
            source_location=source_location,
            registration_source=registration_source,
            **opts,
        )

    @staticmethod
    def _normalize_service_where(
        preds: list["Predicate"],
        where: "Predicate | Sequence[Predicate] | Mapping[str, ChangeType] | None",
    ) -> None:
        """Normalize on_call_service's Mapping-aware where clause into predicates."""
        if where is None:
            return

        if isinstance(where, Mapping):
            preds.append(P.ServiceDataWhere(where))
        elif callable(where):
            preds.append(where)
        else:
            mappings = [w for w in where if isinstance(w, Mapping)]
            other = [w for w in where if not isinstance(w, Mapping)]

            preds.extend(P.ServiceDataWhere(w) for w in mappings)

            if other:
                preds.append(P.AllOf.ensure_iterable(other))

    def on_state_change(
        self,
        entity_id: str,
        *,
        handler: "HandlerType",
        changed: bool | ComparisonCondition = True,
        changed_from: "ChangeType" = NOT_PROVIDED,
        changed_to: "ChangeType" = NOT_PROVIDED,
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        immediate: bool = False,
        duration: float | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to state changes for a specific entity.

        Must be awaited. Registration completes before the call returns.
        ``sub.listener.db_id`` is a valid integer immediately on return.

        Args:
            entity_id: The entity ID to filter events for (e.g., "media_player.living_room_speaker").
            handler: The function to call when the event matches.
            changed: Whether to filter only events where the state changed. If a ComparisonCondition is provided, it
                will be used to compare the old and new state values.
            changed_from: A value or callable that will be used to filter state changes *from* this value.
            changed_to: A value or callable that will be used to filter state changes *to* this value.
            where: Additional predicates to filter events (e.g. ValueIs) or custom callables. These will receive the
                full event for evaluation.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. A stable string identifier for this listener. Forms part of the natural
                key ``(app_key, instance_index, name, topic)`` used for upsert deduplication across
                restarts. Omitting it raises ``ListenerNameRequiredError`` at call time.
            **opts: Additional options like `once`, `debounce` and `throttle`.

        Returns:
            A subscription object. ``sub.listener.db_id`` is set immediately. ``sub.cancel()``
            removes the listener from routing.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already
                registered on this bus in the current session.
        """
        # Synchronous validation runs before the handle is constructed (design Edge Cases).
        if name is None:
            raise ListenerNameRequiredError(
                handler_method=callable_name(handler),
                topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}",
            )
        if immediate and is_glob(entity_id):
            raise ValueError(
                f"'immediate=True' is not supported with glob patterns. "
                f"entity_id={entity_id!r} contains glob characters."
            )
        if duration is not None and is_glob(entity_id):
            raise ValueError(
                f"'duration' is not supported with glob patterns. entity_id={entity_id!r} contains glob characters."
            )

        preds, hold_preds = build_state_preds(
            entity_id, changed=changed, changed_from=changed_from, changed_to=changed_to
        )

        # Eager capture in the public def — user frame is live here.
        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                method_name=f"entity '{entity_id}'",
                topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}",
                handler=handler,
                preds=preds,
                where=where,
                kwargs=kwargs,
                log_params={"changed": changed, "changed_from": changed_from, "changed_to": changed_to, "where": where},
                immediate=immediate,
                duration=duration,
                entity_id=entity_id,
                hold_preds=hold_preds if duration is not None else None,
                name=name,
                on_error=on_error,
                source_location=source_location,
                registration_source=registration_source,
                **opts,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    def on_attribute_change(
        self,
        entity_id: str,
        attr: str,
        *,
        handler: "HandlerType",
        changed: bool | ComparisonCondition = True,
        changed_from: "ChangeType" = NOT_PROVIDED,
        changed_to: "ChangeType" = NOT_PROVIDED,
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        immediate: bool = False,
        duration: float | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to state change events for a specific entity's attribute.

        Must be awaited. Registration completes before the call returns.
        ``sub.listener.db_id`` is a valid integer immediately on return.

        Args:
            entity_id: The entity ID to filter events for (e.g., "media_player.living_room_speaker").
            attr: The attribute name to filter changes on (e.g., "volume").
            handler: The function to call when the event matches.
            changed: Whether to filter only events where the attribute changed. If a ComparisonCondition is provided,
                it will be used to compare the old and new attribute values.
            changed_from: A value or callable that will be used to filter attribute changes *from* this value.
            changed_to: A value or callable that will be used to filter attribute changes *to* this value.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable string identifier. Omitting it raises ``ListenerNameRequiredError``.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object. ``sub.listener.db_id`` is set immediately.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already registered.
        """
        # Synchronous validation runs before the handle is constructed (design Edge Cases).
        if name is None:
            # [{attr}] suffix distinguishes this error from on_state_change's (same wire topic).
            raise ListenerNameRequiredError(
                handler_method=callable_name(handler),
                topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}[{attr}]",
            )
        if immediate and is_glob(entity_id):
            raise ValueError(
                f"'immediate=True' is not supported with glob patterns. "
                f"entity_id={entity_id!r} contains glob characters."
            )
        if duration is not None and is_glob(entity_id):
            raise ValueError(
                f"'duration' is not supported with glob patterns. entity_id={entity_id!r} contains glob characters."
            )

        if not changed:
            self.logger.warning(
                (
                    "Handler '%s' - attribute change subscription "
                    "will fire on every change event for '%s' due to 'changed=False'. "
                    "Consider using `on_state_change` with 'changed=False' instead for clarity."
                ),
                callable_short_name(handler),
                entity_id,
            )

        preds, hold_preds = build_attr_preds(
            entity_id, attr, changed=changed, changed_from=changed_from, changed_to=changed_to
        )

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                method_name=f"entity '{entity_id}' attribute '{attr}'",
                topic=f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}",
                handler=handler,
                preds=preds,
                where=where,
                kwargs=kwargs,
                log_params={"changed_from": changed_from, "changed_to": changed_to, "where": where},
                immediate=immediate,
                duration=duration,
                entity_id=entity_id,
                hold_preds=hold_preds if duration is not None else None,
                is_attribute_listener=True,
                name=name,
                on_error=on_error,
                source_location=source_location,
                registration_source=registration_source,
                **opts,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    def on_call_service(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | Mapping[str, ChangeType] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to service call events.

        Must be awaited. Registration completes before the call returns.
        ``sub.listener.db_id`` is a valid integer immediately on return.

        Args:
            domain: The domain to filter service calls (e.g., "light").
            service: The service to filter service calls (e.g., "turn_on").
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable string identifier for this listener. Omitting it raises
                ``ListenerNameRequiredError`` at call time.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object. ``sub.listener.db_id`` is set immediately.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already registered.
        """
        if name is None:
            raise ListenerNameRequiredError(
                handler_method=callable_name(handler),
                topic=str(Topic.HASS_EVENT_CALL_SERVICE),
            )
        preds: list[Predicate] = []
        if domain is not None:
            preds.append(P.DomainMatches(domain))

        if service is not None:
            preds.append(P.ServiceMatches(service))

        self._normalize_service_where(preds, where)

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                method_name="call_service",
                topic=Topic.HASS_EVENT_CALL_SERVICE,
                handler=handler,
                preds=preds,
                where=None,
                kwargs=kwargs,
                log_params={"domain": domain, "service": service, "where": where},
                name=name,
                on_error=on_error,
                source_location=source_location,
                registration_source=registration_source,
                **opts,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    def on_component_loaded(
        self,
        component: str | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to component loaded events.

        Must be awaited. Registration completes before the call returns.
        ``sub.listener.db_id`` is a valid integer immediately on return.

        Args:
            component: The component to filter load events (e.g., "light").
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        if name is None:
            raise ListenerNameRequiredError(
                handler_method=callable_name(handler),
                topic=str(Topic.HASS_EVENT_COMPONENT_LOADED),
            )
        preds: list[Predicate] = []

        if component is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.component"), condition=component))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                method_name="component_loaded",
                topic=Topic.HASS_EVENT_COMPONENT_LOADED,
                handler=handler,
                preds=preds,
                where=where,
                kwargs=kwargs,
                log_params={"component": component, "where": where},
                name=name,
                on_error=on_error,
                source_location=source_location,
                registration_source=registration_source,
                **opts,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    def on_service_registered(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to service registered events.

        Must be awaited. Registration completes before the call returns.
        ``sub.listener.db_id`` is a valid integer immediately on return.

        Args:
            domain: The domain to filter service registrations (e.g., "light").
            service: The service to filter service registrations (e.g., "turn_on").
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        if name is None:
            raise ListenerNameRequiredError(
                handler_method=callable_name(handler),
                topic=str(Topic.HASS_EVENT_SERVICE_REGISTERED),
            )
        preds: list[Predicate] = []

        if domain is not None:
            preds.append(P.DomainMatches(domain))

        if service is not None:
            preds.append(P.ServiceMatches(service))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                method_name="service_registered",
                topic=Topic.HASS_EVENT_SERVICE_REGISTERED,
                handler=handler,
                preds=preds,
                where=where,
                kwargs=kwargs,
                log_params={"domain": domain, "service": service, "where": where},
                name=name,
                on_error=on_error,
                source_location=source_location,
                registration_source=registration_source,
                **opts,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    def on_homeassistant_restart(
        self,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to Home Assistant restart events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_call_service (the true primary). See design/071.
        return self.on_call_service(
            domain="homeassistant", service="restart", handler=handler, where=where, kwargs=kwargs, name=name, **opts
        )

    def on_homeassistant_start(
        self,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to Home Assistant start events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_call_service (the true primary). See design/071.
        return self.on_call_service(
            domain="homeassistant", service="start", handler=handler, where=where, kwargs=kwargs, name=name, **opts
        )

    def on_homeassistant_stop(
        self,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to Home Assistant stop events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_call_service (the true primary). See design/071.
        return self.on_call_service(
            domain="homeassistant", service="stop", handler=handler, where=where, kwargs=kwargs, name=name, **opts
        )

    def on_hassette_service_status(
        self,
        status: ResourceStatus | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to hassette service status events.

        Must be awaited. Registration completes before the call returns.
        ``sub.listener.db_id`` is a valid integer immediately on return.

        Args:
            status: The status to filter events (e.g., ResourceStatus.STARTED).
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. A stable string identifier for this listener. Forms part of the
                natural key ``(app_key, instance_index, name, topic)`` used for upsert
                deduplication across restarts. Omitting it raises ``ListenerNameRequiredError``
                at call time.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        if name is None:
            raise ListenerNameRequiredError(
                handler_method=callable_name(handler),
                topic=str(Topic.HASSETTE_EVENT_SERVICE_STATUS),
            )
        preds: list[Predicate] = []

        if status is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.status"), condition=status))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                method_name="hassette.service_status",
                topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
                handler=handler,
                preds=preds,
                where=where,
                kwargs=kwargs,
                log_params={"status": status, "where": where},
                name=name,
                on_error=on_error,
                source_location=source_location,
                registration_source=registration_source,
                **opts,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    def on_hassette_service_failed(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to hassette service failed events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. A stable string identifier for this listener. Forms part of the
                natural key ``(app_key, instance_index, name, topic)`` used for upsert
                deduplication across restarts. Omitting it raises ``ListenerNameRequiredError``
                at call time.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_hassette_service_status (the true primary). See design/071.
        return self.on_hassette_service_status(
            status=ResourceStatus.FAILED, handler=handler, where=where, kwargs=kwargs, name=name, **opts
        )

    def on_hassette_service_crashed(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to hassette service crashed events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_hassette_service_status (the true primary). See design/071.
        return self.on_hassette_service_status(
            status=ResourceStatus.CRASHED, handler=handler, where=where, kwargs=kwargs, name=name, **opts
        )

    def on_hassette_service_started(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to hassette service started events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_hassette_service_status (the true primary). See design/071.
        return self.on_hassette_service_status(
            status=ResourceStatus.RUNNING, handler=handler, where=where, kwargs=kwargs, name=name, **opts
        )

    def on_websocket_connected(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to websocket connected events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on() (the true primary). See design/071.
        return self.on(
            topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED,
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            **opts,
        )

    def on_websocket_disconnected(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to websocket disconnected events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on() (the true primary). See design/071.
        return self.on(
            topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED,
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            **opts,
        )

    def on_app_state_changed(
        self,
        *,
        handler: "HandlerType",
        app_key: str | None = None,
        status: ResourceStatus | None = None,
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to app instance state change events.

        Must be awaited. Registration completes before the call returns.
        ``sub.listener.db_id`` is a valid integer immediately on return.

        Args:
            handler: The function to call when the event matches.
            app_key: Filter events for a specific app key.
            status: Filter events for a specific status.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        if name is None:
            raise ListenerNameRequiredError(
                handler_method=callable_name(handler),
                topic=str(Topic.HASSETTE_EVENT_APP_STATE_CHANGED),
            )
        preds: list[Predicate] = []

        if app_key is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.app_key"), condition=app_key))

        if status is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.status"), condition=status))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/core/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                method_name="app_state_changed",
                topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED,
                handler=handler,
                preds=preds,
                where=where,
                kwargs=kwargs,
                log_params={"app_key": app_key, "status": status, "where": where},
                name=name,
                on_error=on_error,
                source_location=source_location,
                registration_source=registration_source,
                **opts,
            ),
            owner=self.parent,
            source_location=source_location,
        )

    def on_app_running(
        self,
        *,
        handler: "HandlerType",
        app_key: str | None = None,
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to app instances reaching RUNNING status.

        Args:
            handler: The function to call when the event matches.
            app_key: Filter events for a specific app key.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_app_state_changed (the true primary). See design/071.
        return self.on_app_state_changed(
            handler=handler,
            app_key=app_key,
            status=ResourceStatus.RUNNING,
            where=where,
            kwargs=kwargs,
            name=name,
            **opts,
        )

    def on_app_stopping(
        self,
        *,
        handler: "HandlerType",
        app_key: str | None = None,
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str | None = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to app instances entering STOPPING status.

        Args:
            handler: The function to call when the event matches.
            app_key: Filter events for a specific app key.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Stable name for this listener. Required on all DB-registered listeners.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_app_state_changed (the true primary). See design/071.
        return self.on_app_state_changed(
            handler=handler,
            app_key=app_key,
            status=ResourceStatus.STOPPING,
            where=where,
            kwargs=kwargs,
            name=name,
            **opts,
        )


def _build_preds(
    entity_id: str,
    *,
    changed: "bool | ComparisonCondition",
    changed_from: Any,
    changed_to: Any,
    make_did_change: "Callable[[], Predicate]",
    make_comparison: "Callable[..., Predicate]",
    make_from: "Callable[..., Predicate]",
    make_to: "Callable[..., Predicate]",
) -> "tuple[list[Predicate], list[Predicate]]":
    """Build predicate lists for state/attribute change subscriptions."""
    preds: list[Predicate] = [P.EntityMatches(entity_id)]
    hold_preds: list[Predicate] = [P.EntityMatches(entity_id)]

    if changed:
        if changed is True:
            preds.append(make_did_change())
        else:
            preds.append(make_comparison(condition=changed))

    if changed_from is not NOT_PROVIDED:
        preds.append(make_from(condition=changed_from))

    if changed_to is not NOT_PROVIDED:
        changed_to_pred = make_to(condition=changed_to)
        preds.append(changed_to_pred)
        hold_preds.append(changed_to_pred)

    return preds, hold_preds


def build_state_preds(
    entity_id: str,
    *,
    changed: "bool | ComparisonCondition",
    changed_from: Any,
    changed_to: Any,
) -> "tuple[list[Predicate], list[Predicate]]":
    return _build_preds(
        entity_id,
        changed=changed,
        changed_from=changed_from,
        changed_to=changed_to,
        make_did_change=P.StateDidChange,
        make_comparison=P.StateComparison,
        make_from=P.StateFrom,
        make_to=P.StateTo,
    )


def build_attr_preds(
    entity_id: str,
    attr: str,
    *,
    changed: "bool | ComparisonCondition",
    changed_from: Any,
    changed_to: Any,
) -> "tuple[list[Predicate], list[Predicate]]":
    return _build_preds(
        entity_id,
        changed=changed,
        changed_from=changed_from,
        changed_to=changed_to,
        make_did_change=partial(P.AttrDidChange, attr),
        make_comparison=partial(P.AttrComparison, attr),
        make_from=partial(P.AttrFrom, attr),
        make_to=partial(P.AttrTo, attr),
    )
