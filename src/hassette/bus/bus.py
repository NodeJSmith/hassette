"""Event bus for subscribing to Home Assistant and Hassette events with powerful filtering.

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
from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.events.base import Event, HassettePayload
from hassette.exceptions import DuplicateListenerError, ListenerNameRequiredError
from hassette.resources.base import Resource
from hassette.types import ComparisonCondition, Topic
from hassette.types.enums import BackpressurePolicy, ExecutionMode, ResourceStatus
from hassette.types.types import LOG_LEVEL_TYPE, IfExistsPolicy, WhereClause
from hassette.utils.await_guard import guard_await
from hassette.utils.func_utils import callable_name, callable_short_name
from hassette.utils.glob_utils import is_glob
from hassette.utils.source_capture import capture_registration_source, capture_source_location

from .listeners import DurationConfig, HandlerInvoker, Listener, ListenerIdentity, ListenerOptions, Subscription
from .options import Options
from .sync import BusSyncFacade

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from hassette import Hassette
    from hassette.core.bus_service import BusService
    from hassette.types import ChangeType, HandlerType, Predicate
    from hassette.types.types import BusErrorHandlerType


def _require_name(name: str | None, handler: "HandlerType", topic: str) -> None:
    if not name:
        raise ListenerNameRequiredError(handler_method=callable_name(handler), topic=topic)


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
        self.bus_service = self.hassette.bus_service
        self.priority = priority
        self._registered_listeners: dict[tuple[str, int, str, str], Listener] = {}
        self._error_handler: BusErrorHandlerType | None = None
        self.sync = self.add_child(BusSyncFacade, bus=self)

        # Register removal callback so once-fired listeners release their natural key and
        # record cancelled_at, mirroring Scheduler's register_removal_callback pattern.
        # owner_id derives from self.parent; the callback registry key must stay stable across
        # register/deregister even if a test fixture swaps self.parent after construction
        # (production never does — a hot-reload builds a fresh Bus). Freezing the key here keeps
        # on_shutdown's deregister matched to this register; listener removal still uses the live
        # self.owner_id because listeners register under the live owner too.
        self._removal_callback_owner_id = self.owner_id
        self.bus_service.register_removal_callback(self._removal_callback_owner_id, self._on_listener_removed)

    async def on_initialize(self) -> None:
        # Clear before any on() calls so partial-init failures don't leave stale keys.
        self._registered_listeners.clear()
        self._error_handler = None
        self.mark_ready(reason="Bus initialized")

    async def on_shutdown(self) -> None:
        """Cleanup all listeners owned by this bus's owner on shutdown."""
        self.remove_all_listeners()
        self.bus_service.deregister_removal_callback(self._removal_callback_owner_id)

    def _on_listener_removed(self, listener: "Listener") -> None:
        """Callback invoked by BusService when a listener is removed (including once-fire).

        Closes the once-fire gap: the dispatch finally block calls BusService.remove_listener
        directly without going through Bus.remove_listener, leaving the natural key stale and
        cancelled_at unwritten. This callback pops the key and spawns mark_listener_cancelled.

        The spawn guard (key must still be present) prevents a double write when Bus.remove_listener
        already popped the key and spawned mark_listener_cancelled before calling BusService:
        in that path the key is gone by the time this callback runs, so we skip the spawn.

        Accepted trade-off: during shutdown, remove_all_listeners clears _registered_listeners
        before delegating to remove_listeners_by_owner, so a once-listener that fires concurrently
        with teardown finds was_present=False and skips its cancelled_at write. This loses only a
        telemetry write in a narrow teardown window — no routing impact — and is not worth guarding.
        """
        if listener.identity.name is None:
            # Cancel-listeners (create_cancel_listener) are never tracked in _registered_listeners,
            # so there is nothing to pop. Returning early also avoids building a natural key whose
            # name falls back to "" (_listener_natural_key), which could alias a real listener.
            return
        natural_key = self._listener_natural_key(listener)
        was_present = self._registered_listeners.pop(natural_key, None) is not None
        if was_present and listener.db_id is not None:
            self.bus_service.task_bucket.spawn(
                self.bus_service.mark_listener_cancelled(listener.db_id),
                name="bus:mark_listener_cancelled",
            )

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

    def add_listener(
        self,
        listener: "Listener",
        *,
        if_exists: IfExistsPolicy = "error",
    ) -> "Coroutine[Any, Any, Subscription]":
        """Add a pre-built listener to the bus.

        This is the direct entry point for callers that construct a ``Listener``
        externally. The normal registration flow (``on_state_change``, ``on()``,
        etc.) goes through ``_on_internal`` instead.

        Args:
            listener: The pre-built listener to add.
            if_exists: Behavior when a listener with the same natural key already exists.
                ``"error"`` (default) raises ``DuplicateListenerError``.
                ``"skip"`` returns a subscription to the existing listener when configs match.
                ``"replace"`` cancels the existing listener and registers the new one.

        Returns:
            A subscription to the added listener (or the existing listener on skip).

        Raises:
            ListenerNameRequiredError: If the listener has no ``name`` (required for all DB-registered
                listeners, including once-listeners; cancel-listeners bypass this path entirely).
            DuplicateListenerError: If the listener's natural key is already registered and
                ``if_exists="error"``.
        """
        # Synchronous validation runs before the handle is constructed (design Edge Cases).
        if not listener.identity.name:
            raise ListenerNameRequiredError(handler_method=listener.identity.handler_name, topic=listener.topic)
        # Cheap path: the pre-built Listener already carries identity.source_location /
        # registration_source; only warning attribution needs the location here.
        source_location = capture_source_location()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._resolve_and_register(listener, if_exists=if_exists),
            owner=self.parent,
            source_location=source_location,
            method_name="add_listener",
        )

    def _resolve_collision(
        self,
        listener: "Listener",
        *,
        if_exists: IfExistsPolicy = "error",
    ) -> "Listener | None":
        """Resolve a potential registration collision using the if_exists policy.

        Mutates the per-bus key registry as a side effect — this is the single point where
        in-session duplicate detection and resolution happens.

        On skip short-circuit (matching existing listener), returns the existing ``Listener``
        so the caller can wrap it in a ``Subscription``. Returns ``None`` on the proceed path
        (no existing, or replace after cancelling the old), meaning the caller should register
        the new listener normally.

        Collision semantics:
        - No existing listener → register the key, return ``None`` (proceed).
        - Existing + ``if_exists="error"`` → raise ``DuplicateListenerError``.
        - Existing + ``if_exists="replace"`` → cancel/remove the existing listener, register
          the new key, return ``None`` (proceed).
        - Existing + ``if_exists="skip"`` and configs match → return the existing listener
          (short-circuit; the caller does NOT register the new one).
        - Existing + ``if_exists="skip"`` and configs differ → raise ``ValueError`` listing
          the changed fields (from ``diff_fields``).

        All listeners — including once-listeners — participate in collision tracking.
        """
        natural_key = self._listener_natural_key(listener)
        existing = self._registered_listeners.get(natural_key)
        if existing is not None:
            if if_exists == "replace":
                self.logger.debug(
                    "Replacing existing listener '%s' on topic '%s' (cancelling old, registering new)",
                    listener.identity.name,
                    listener.topic,
                )
                self.remove_listener(existing)
            elif if_exists == "skip" and existing.config_matches(listener):
                return existing
            elif if_exists == "skip":
                changed_fields = existing.diff_fields(listener)
                msg = (
                    f"A listener named '{listener.identity.name}' on topic '{listener.topic}' already exists "
                    f"but its configuration has changed (changed fields: {', '.join(changed_fields)})"
                )
                if "predicate" in changed_fields:
                    msg += (
                        ". Note: lambda/closure predicates compare by identity — two fresh lambdas with "
                        "identical bodies are not equal; use a named predicate function or if_exists='replace'"
                    )
                raise ValueError(msg)
            else:
                raise DuplicateListenerError(
                    name=listener.identity.name or "",
                    topic=listener.topic,
                    existing_handler=existing.identity.handler_name,
                    duplicate_handler=listener.identity.handler_name,
                )
        self._registered_listeners[natural_key] = listener
        return None

    async def _resolve_and_register(
        self,
        listener: "Listener",
        *,
        if_exists: IfExistsPolicy,
    ) -> Subscription:
        """Resolve a collision then register the listener, returning its Subscription.

        The async body for both add_listener and _on_internal. _resolve_collision mutates the
        per-bus key registry, so it must not run for a never-awaited call — keeping it here, in
        the awaited coroutine, is what prevents that.

        On the skip short-circuit, returns a subscription wrapping the existing listener.
        On the replace path, _resolve_collision has already cancelled the existing listener;
        if the new registration then fails, an ERROR is logged so the now-open gap (no handler
        routed under this key) is observable before the exception propagates.
        """
        # `is_replacing` must be captured BEFORE _resolve_collision runs: on the replace path it
        # pops the existing key, so reading _registered_listeners afterward would always be False.
        natural_key = self._listener_natural_key(listener)
        is_replacing = if_exists == "replace" and natural_key in self._registered_listeners

        existing = self._resolve_collision(listener, if_exists=if_exists)
        if existing is not None:
            # skip short-circuit: return a subscription wrapping the existing listener.
            return Subscription(existing, lambda: self.remove_listener(existing))

        try:
            await self.bus_service.add_listener(listener)
        except Exception:
            # _resolve_collision reserved natural_key before the await; drop it so a failed add
            # doesn't leave a phantom registration that blocks retries with a false collision.
            # Guard on identity: a concurrent replace may have re-pointed the key to a new listener
            # while this task was awaiting, and that newer mapping must not be evicted.
            if self._registered_listeners.get(natural_key) is listener:
                self._registered_listeners.pop(natural_key, None)
            if is_replacing:
                self.logger.error(
                    "Listener '%s' on topic '%s' failed to register after replacing (cancelling) the "
                    "existing listener — no handler is active for this key",
                    listener.identity.name,
                    listener.topic,
                )
            raise
        return Subscription(listener, lambda: self.remove_listener(listener))

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
        """Remove a listener from the bus and persist cancellation to the database.

        Pops the natural key from the in-memory registry, removes the listener from routing
        (via BusService), and — when ``db_id`` is set — spawns ``mark_listener_cancelled``
        on ``bus_service.task_bucket`` so the write survives resource shutdown, mirroring
        ``Scheduler.cancel_job``.

        BusService.remove_listener also fires _on_listener_removed, but that callback only
        spawns mark_listener_cancelled when the key is still present (once-fire path). Because
        this method pops the key first, the callback's spawn is skipped — avoiding a double write.
        """
        natural_key = self._listener_natural_key(listener)
        self._registered_listeners.pop(natural_key, None)
        self.bus_service.remove_listener(listener)
        if listener.db_id is not None:
            self.bus_service.task_bucket.spawn(
                self.bus_service.mark_listener_cancelled(listener.db_id),
                name="bus:mark_listener_cancelled",
            )

    def remove_all_listeners(self) -> None:
        """Remove all listeners owned by this bus's owner."""
        # Pre-clear is load-bearing: it must run before remove_listeners_by_owner so that
        # _on_listener_removed finds was_present=False and skips the cancelled_at spawn for every
        # listener on clean shutdown (shutdown maps to retired_at via reconciliation, not cancelled_at).
        self._registered_listeners.clear()
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
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        mode: "ExecutionMode | str | None" = None,
        backpressure: "BackpressurePolicy | str | None" = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        if_exists: IfExistsPolicy = "error",
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
            mode: Overlap behavior when a trigger fires while a prior invocation still runs —
                ``"single"``, ``"restart"``, ``"queued"``, or ``"parallel"``. When omitted, the
                effective default is tier-aware: ``parallel`` for framework listeners, ``single``
                for app listeners. Suppressed/dropped counts are live-only diagnostics, reset on
                restart.
            backpressure: Saturation policy when the global dispatch concurrency semaphore is full.
                ``"block"`` (default) waits for a slot; ``"drop_newest"`` skips the event immediately
                and records one drop on the listener. When omitted, the effective default is ``block``.
            name: Required. Stable string identifier for this listener. Forms part of the natural
                key ``(app_key, instance_index, name, topic)`` used for upsert deduplication across
                restarts. Omitting it entirely raises ``TypeError`` (no default value); passing an
                empty string raises ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            if_exists: Behavior when a listener with the same natural key already exists.
                ``"error"`` (default) raises ``DuplicateListenerError``. ``"skip"`` returns the
                existing listener's subscription when the configurations match, and raises
                ``ValueError`` if the configuration has drifted. ``"replace"`` cancels the
                existing listener and registers the new one in its place.

        Returns:
            A subscription object. ``sub.cancel()`` removes the listener.
            ``sub.listener.db_id`` is a valid integer immediately on return.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already
                registered and ``if_exists="error"`` (the default).
            ValueError: If ``if_exists="skip"`` and a listener with the same ``(name, topic)``
                exists but with a different configuration (the message lists the changed fields).
        """
        _require_name(name, handler, topic)
        # Eager capture in the public def — user frame is live here (not inside the async body).
        # Returns a 2-tuple — unpack it. Two destinations: guard_await (warning attribution) AND
        # _on_internal (populates ListenerIdentity.source_location / registration_source on the DB record).
        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
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
                mode=mode,
                backpressure=backpressure,
                name=name,
                on_error=on_error,
                if_exists=if_exists,
                duration_config=None,
                source_location=source_location,
                registration_source=registration_source,
            ),
            owner=self.parent,
            source_location=source_location,
            method_name="on",
        )

    async def _on_internal(
        self,
        *,
        topic: str,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
        timeout: float | None = None,
        timeout_disabled: bool = False,
        mode: "ExecutionMode | str | None" = None,
        backpressure: "BackpressurePolicy | str | None" = None,
        name: str | None = None,
        on_error: "BusErrorHandlerType | None" = None,
        if_exists: IfExistsPolicy = "error",
        duration_config: "DurationConfig | None" = None,
        source_location: str = "",
        registration_source: str | None = None,
    ) -> Subscription:
        """Private registration method carrying the full parameter set.

        ``mode=None`` means "not supplied" — it resolves to the tier-aware default
        (``parallel`` for framework listeners, ``single`` for app listeners). An explicit
        mode always wins.

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

        # Tier-aware default: an omitted mode (None) resolves to ``parallel`` for framework
        # listeners — preserving the supervisor/state-cache concurrency — and ``single`` for app
        # listeners. An explicit mode always wins. A raw string is coerced here so an invalid value
        # raises a clear ValueError at registration time.
        if mode is None:
            resolved_mode = ExecutionMode.PARALLEL if source_tier == "framework" else ExecutionMode.SINGLE
        elif isinstance(mode, ExecutionMode):
            resolved_mode = mode
        else:
            try:
                resolved_mode = ExecutionMode(mode)
            except ValueError as exc:
                valid = ", ".join(repr(m.value) for m in ExecutionMode)
                raise ValueError(f"Invalid execution mode {mode!r}; must be one of {valid}") from exc

        handler_name = callable_name(handler)
        short_name = callable_short_name(handler)

        _require_name(name, handler, topic)

        # Resolve instance_name once at registration so the executor hot path reads it off the
        # command instead of traversing app_handler per execution.
        instance_name = parent.instance_name

        identity = ListenerIdentity(
            owner_id=self.owner_id,
            app_key=app_key,
            instance_index=instance_index,
            instance_name=instance_name,
            name=name,
            source_tier=source_tier,
            handler_name=handler_name,
            handler_short_name=short_name,
            source_location=source_location,
            registration_source=registration_source or "",
        )

        # An omitted policy resolves to the flat BLOCK default (no tier-awareness, unlike mode). A raw
        # string is coerced here so an invalid value raises a clear ValueError at registration time —
        # mirroring the mode coercion above and ListenerOptions.__post_init__.
        if backpressure is None:
            resolved_backpressure = BackpressurePolicy.BLOCK
        elif isinstance(backpressure, BackpressurePolicy):
            resolved_backpressure = backpressure
        else:
            try:
                resolved_backpressure = BackpressurePolicy(backpressure)
            except ValueError as exc:
                valid = ", ".join(repr(p.value) for p in BackpressurePolicy)
                raise ValueError(f"Invalid backpressure policy {backpressure!r}; must be one of {valid}") from exc

        options = ListenerOptions(
            once=once,
            debounce=debounce,
            throttle=throttle,
            timeout=timeout,
            timeout_disabled=timeout_disabled,
            priority=self.priority,
            mode=resolved_mode,
            backpressure=resolved_backpressure,
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

        return await self._resolve_and_register(listener, if_exists=if_exists)

    async def _subscribe(
        self,
        *,
        log_label: str,
        topic: str,
        handler: "HandlerType",
        preds: list["Predicate"],
        where: WhereClause = None,
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
                log_label,
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
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        immediate: bool = False,
        duration: float | None = None,
        name: str,
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
                restarts. Omitting it entirely raises ``TypeError`` (no default value); passing an
                empty string raises ``ListenerNameRequiredError`` at call time.
            **opts: Additional options. Accepts ``once``, ``debounce``, ``throttle``, ``timeout``,
                ``timeout_disabled``, ``if_exists``, ``mode``, and ``backpressure``.

                ``mode`` controls overlap behavior when a trigger fires while a prior invocation
                is still running: ``"single"`` drops the re-fire (the default for app handlers),
                ``"restart"`` cancels and replaces, ``"queued"`` serializes in arrival order
                (bounded at 10 pending), ``"parallel"`` runs concurrently. When omitted, the
                tier-aware default applies: ``"single"`` for app handlers, ``"parallel"`` for
                framework-internal listeners. An explicit ``mode=`` always wins. Suppressed
                (``single``) and dropped (``queued`` cap) events log at DEBUG only.
                Suppressed/dropped counts are live-only diagnostics, reset on restart.
                See `Execution Modes <https://hassette.dev/core-concepts/bus/execution-modes/>`_.

                ``backpressure`` controls what this listener does when the dispatch concurrency
                semaphore is saturated: ``"block"`` (default) waits for a slot, unchanged from
                today; ``"drop_newest"`` skips the event immediately rather than waiting. It gates
                at the dispatch acquire point (global bus saturation), orthogonal to
                ``mode``/``debounce``/``throttle``.

        Returns:
            A subscription object. ``sub.listener.db_id`` is set immediately. ``sub.cancel()``
            removes the listener from routing.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already
                registered on this bus in the current session and ``if_exists="error"``
                (the default).
        """
        # Synchronous validation runs before the handle is constructed (design Edge Cases).
        _require_name(name, handler, f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}")
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
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                log_label=f"entity '{entity_id}'",
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
            method_name="on_state_change",
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
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        immediate: bool = False,
        duration: float | None = None,
        name: str,
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
            name: Required. Stable string identifier. Omitting it entirely raises ``TypeError``
                (no default value); passing an empty string raises ``ListenerNameRequiredError``
                at call time.
            **opts: Additional options. Accepts ``once``, ``debounce``, ``throttle``, ``timeout``,
                ``timeout_disabled``, ``if_exists``, ``mode``, and ``backpressure``.

                ``mode`` controls overlap behavior when a trigger fires while a prior invocation
                is still running: ``"single"`` drops the re-fire (the default for app handlers),
                ``"restart"`` cancels and replaces, ``"queued"`` serializes in arrival order
                (bounded at 10 pending), ``"parallel"`` runs concurrently. Suppressed/dropped
                counts are live-only diagnostics, reset on restart.

                ``backpressure`` controls what this listener does when the dispatch concurrency
                semaphore is saturated: ``"block"`` (default) waits for a slot, unchanged from
                today; ``"drop_newest"`` skips the event immediately rather than waiting. It gates
                at the dispatch acquire point (global bus saturation), orthogonal to
                ``mode``/``debounce``/``throttle``.

        Returns:
            A subscription object. ``sub.listener.db_id`` is set immediately.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already
                registered and ``if_exists="error"`` (the default).
        """
        # Synchronous validation runs before the handle is constructed (design Edge Cases).
        _require_name(name, handler, f"{Topic.HASS_EVENT_STATE_CHANGED!s}.{entity_id}[{attr}]")
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
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                log_label=f"entity '{entity_id}' attribute '{attr}'",
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
            method_name="on_attribute_change",
        )

    def on_call_service(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | Mapping[str, ChangeType] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
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
            name: Required. Stable string identifier for this listener. Omitting it entirely
                raises ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            **opts: Additional options. Accepts ``once``, ``debounce``, ``throttle``, ``timeout``,
                ``timeout_disabled``, ``if_exists``, ``mode``, and ``backpressure``.

                ``mode`` controls overlap behavior when a trigger fires while a prior invocation
                is still running: ``"single"`` drops the re-fire (the default for app handlers),
                ``"restart"`` cancels and replaces, ``"queued"`` serializes in arrival order
                (bounded at 10 pending), ``"parallel"`` runs concurrently. Suppressed/dropped
                counts are live-only diagnostics, reset on restart.

                ``backpressure`` controls what this listener does when the dispatch concurrency
                semaphore is saturated: ``"block"`` (default) waits for a slot, unchanged from
                today; ``"drop_newest"`` skips the event immediately rather than waiting. It gates
                at the dispatch acquire point (global bus saturation), orthogonal to
                ``mode``/``debounce``/``throttle``.

        Returns:
            A subscription object. ``sub.listener.db_id`` is set immediately.

        Raises:
            ListenerNameRequiredError: If ``name`` is not provided.
            DuplicateListenerError: If a listener with the same ``(name, topic)`` is already
                registered and ``if_exists="error"`` (the default).
        """
        _require_name(name, handler, str(Topic.HASS_EVENT_CALL_SERVICE))
        preds: list[Predicate] = []
        if domain is not None:
            preds.append(P.DomainMatches(domain))

        if service is not None:
            preds.append(P.ServiceMatches(service))

        self._normalize_service_where(preds, where)

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                log_label="call_service",
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
            method_name="on_call_service",
        )

    def on_component_loaded(
        self,
        component: str | None = None,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
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
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        _require_name(name, handler, str(Topic.HASS_EVENT_COMPONENT_LOADED))
        preds: list[Predicate] = []

        if component is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.component"), condition=component))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                log_label="component_loaded",
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
            method_name="on_component_loaded",
        )

    def on_service_registered(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
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
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        _require_name(name, handler, str(Topic.HASS_EVENT_SERVICE_REGISTERED))
        preds: list[Predicate] = []

        if domain is not None:
            preds.append(P.DomainMatches(domain))

        if service is not None:
            preds.append(P.ServiceMatches(service))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                log_label="service_registered",
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
            method_name="on_service_registered",
        )

    def on_homeassistant_restart(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to Home Assistant restart events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_call_service (the true primary). See design/071.
        return self.on_call_service(
            domain="homeassistant",
            service="restart",
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            on_error=on_error,
            **opts,
        )

    def on_homeassistant_start(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to Home Assistant start events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_call_service (the true primary). See design/071.
        return self.on_call_service(
            domain="homeassistant",
            service="start",
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            on_error=on_error,
            **opts,
        )

    def on_homeassistant_stop(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to Home Assistant stop events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_call_service (the true primary). See design/071.
        return self.on_call_service(
            domain="homeassistant",
            service="stop",
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            on_error=on_error,
            **opts,
        )

    def on_hassette_service_status(
        self,
        status: ResourceStatus | None = None,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
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
                deduplication across restarts. Omitting it entirely raises ``TypeError`` (no
                default value); passing an empty string raises ``ListenerNameRequiredError``
                at call time.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        _require_name(name, handler, str(Topic.HASSETTE_EVENT_SERVICE_STATUS))
        preds: list[Predicate] = []

        if status is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.status"), condition=status))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                log_label="hassette.service_status",
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
            method_name="on_hassette_service_status",
        )

    def on_hassette_service_failed(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to hassette service failed events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. A stable string identifier for this listener. Forms part of the
                natural key ``(app_key, instance_index, name, topic)`` used for upsert
                deduplication across restarts. Omitting it entirely raises ``TypeError`` (no
                default value); passing an empty string raises ``ListenerNameRequiredError``
                at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_hassette_service_status (the true primary). See design/071.
        return self.on_hassette_service_status(
            status=ResourceStatus.FAILED,
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            on_error=on_error,
            **opts,
        )

    def on_hassette_service_crashed(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to hassette service crashed events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_hassette_service_status (the true primary). See design/071.
        return self.on_hassette_service_status(
            status=ResourceStatus.CRASHED,
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            on_error=on_error,
            **opts,
        )

    def on_hassette_service_started(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to hassette service started events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at on_hassette_service_status (the true primary). See design/071.
        return self.on_hassette_service_status(
            status=ResourceStatus.RUNNING,
            handler=handler,
            where=where,
            kwargs=kwargs,
            name=name,
            on_error=on_error,
            **opts,
        )

    def on_websocket_connected(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to websocket connected events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

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
            on_error=on_error,
            **opts,
        )

    def on_websocket_disconnected(
        self,
        *,
        handler: "HandlerType",
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to websocket disconnected events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

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
            on_error=on_error,
            **opts,
        )

    def on_app_state_changed(
        self,
        *,
        handler: "HandlerType",
        app_key: str | None = None,
        status: ResourceStatus | None = None,
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
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
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        _require_name(name, handler, str(Topic.HASSETTE_EVENT_APP_STATE_CHANGED))
        preds: list[Predicate] = []

        if app_key is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.app_key"), condition=app_key))

        if status is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.status"), condition=status))

        source_location, registration_source = capture_registration_source()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._subscribe(
                log_label="app_state_changed",
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
            method_name="on_app_state_changed",
        )

    def on_app_running(
        self,
        *,
        handler: "HandlerType",
        app_key: str | None = None,
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to app instances reaching RUNNING status.

        Args:
            handler: The function to call when the event matches.
            app_key: Filter events for a specific app key.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

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
            on_error=on_error,
            **opts,
        )

    def on_app_stopping(
        self,
        *,
        handler: "HandlerType",
        app_key: str | None = None,
        where: WhereClause = None,
        kwargs: Mapping[str, Any] | None = None,
        name: str,
        on_error: "BusErrorHandlerType | None" = None,
        **opts: Unpack[Options],
    ) -> "Coroutine[Any, Any, Subscription]":
        """Subscribe to app instances entering STOPPING status.

        Args:
            handler: The function to call when the event matches.
            app_key: Filter events for a specific app key.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            name: Required. Stable name for this listener. Omitting it entirely raises
                ``TypeError`` (no default value); passing an empty string raises
                ``ListenerNameRequiredError`` at call time.
            on_error: Optional per-listener error handler.
            **opts: Additional options like `once`, `debounce`, `throttle`, `mode`, and `backpressure`.

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
            on_error=on_error,
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
