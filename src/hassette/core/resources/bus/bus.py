import asyncio
import time
import typing
from typing import Any, cast

from hassette import topics
from hassette.core.resources.base import Resource
from hassette.core.services.bus_service import _BusService
from hassette.enums import ResourceStatus
from hassette.events.base import Event
from hassette.utils.async_utils import make_async_adapter

from .listeners import Listener, Subscription
from .predicates import AllOf, AttrChanged, Changed, ChangedFrom, ChangedTo, EntityIs, Guard
from .predicates.base import SENTINEL, normalize_where

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from hassette import Hassette, TaskBucket
    from hassette.events import (
        CallServiceEvent,
        ComponentLoadedEvent,
        HassetteServiceEvent,
        ServiceRegisteredEvent,
        StateChangeEvent,
    )
    from hassette.types import AsyncHandler, E_contra, Handler, Predicate


class Bus(Resource):
    """Individual event bus instance for a specific owner (e.g., App or Service)."""

    def __init__(
        self,
        hassette: "Hassette",
        owner: str,
        unique_name_prefix: str | None = None,
        task_bucket: "TaskBucket | None" = None,
    ) -> None:
        """Initialize the Bus instance."""
        super().__init__(hassette, unique_name_prefix=unique_name_prefix, task_bucket=task_bucket)
        self.set_logger_to_level(self.hassette.config.bus_service_log_level)

        self.owner = owner
        """Owner of the bus, must be a unique identifier for the owner."""

        self.mark_ready(reason="Bus initialized")

    @property
    def bus_service(self) -> _BusService:
        return self.hassette._bus_service

    def add_listener(self, listener: "Listener") -> asyncio.Task:
        """Add a listener to the bus."""
        return self.bus_service.add_listener(listener)

    def remove_listener(self, listener: "Listener") -> asyncio.Task:
        """Remove a listener from the bus."""
        return self.bus_service.remove_listener(listener)

    def remove_all_listeners(self) -> asyncio.Task:
        """Remove all listeners owned by this bus's owner."""
        return self.bus_service.remove_listeners_by_owner(self.owner)

    def on(
        self,
        *,
        topic: str,
        handler: "Handler[Event[Any]]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        once: bool = False,
        debounce: float | None = None,
        throttle: float | None = None,
    ) -> Subscription:
        """Subscribe to an event topic with optional filtering and modifiers.

        Args:
            topic (str): The event topic to listen to.
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Optional predicates to filter events.
            once (bool): If True, the handler will be called only once and then removed.
            debounce (float | None): If set, applies a debounce to the handler.
            throttle (float | None): If set, applies a throttle to the handler.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        pred = normalize_where(where)

        orig = handler

        # ensure-async
        handler = self._make_async_handler(orig)
        # decorate
        if debounce and debounce > 0:
            handler = self._add_debounce(handler, debounce, self.task_bucket)
        if throttle and throttle > 0:
            handler = self._add_throttle(handler, throttle)

        listener = Listener(
            owner=self.owner,
            topic=topic,
            orig_handler=orig,
            handler=handler,
            predicate=pred,
            once=once,
            debounce=debounce,
            throttle=throttle,
        )

        def unsubscribe() -> None:
            self.remove_listener(listener)

        self.add_listener(listener)
        return Subscription(listener, unsubscribe)

    def on_entity(
        self,
        entity: str,
        *,
        handler: "Handler[StateChangeEvent]",
        changed: bool | None = True,
        changed_from: Any | None = SENTINEL,
        changed_to: Any | None = SENTINEL,
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to events for a specific entity.

        Args:
            entity (str): The entity ID to filter events for (e.g., "media_player.living_room_speaker").
            handler (Callable): The function to call when the event matches.
            changed (bool | None): If True, only trigger if `old` and `new` states differ.
            changed_from (Any | None): Filter for state changes from this value.
            changed_to (Any | None): Filter for state changes to this value.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events, such as
                `AttrChanged` or other custom predicates.
            **opts: Additional options like `once`, `debounce` and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """
        self.logger.debug(
            (
                "Subscribing to entity '%s' with changed='%s', changed_from='%s', changed_to='%s', where='%s' -"
                " being handled by '%s'"
            ),
            entity,
            changed,
            changed_from,
            changed_to,
            where,
            handler,
        )

        preds: list[Predicate] = [EntityIs(entity)]
        if changed:
            preds.append(Changed())
        if changed_from != SENTINEL:
            preds.append(ChangedFrom(changed_from))
        if changed_to != SENTINEL:
            preds.append(ChangedTo(changed_to))
        if where is not None:
            preds.append(where if callable(where) else AllOf.ensure_iterable(where))  # allow extra guards
        return self.on(topic=topics.HASS_EVENT_STATE_CHANGED, handler=handler, where=preds, **opts)

    def on_attribute(
        self,
        entity: str,
        attr: str,
        *,
        handler: "Handler[StateChangeEvent]",
        changed_from: Any | None = SENTINEL,
        changed_to: Any | None = SENTINEL,
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to attribute changes for a specific entity.

        Args:
            entity (str): The entity ID to filter events for (e.g., "media_player.living_room_speaker").
            attr (str): The attribute name to filter changes on (e.g., "volume").
            handler (Callable): The function to call when the event matches.
            changed_from (Any | None): Filter for attribute changes from this value.
            changed_to (Any | None): Filter for attribute changes to this value.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            (
                "Subscribing to entity '%s' attribute '%s' with changed_from='%s', changed_to='%s'"
                ", where='%s' - being handled by '%s'"
            ),
            entity,
            attr,
            changed_from,
            changed_to,
            where,
            handler,
        )

        preds: list[Predicate] = [EntityIs(entity)]
        preds.append(AttrChanged(attr, from_=changed_from, to=changed_to))

        if where is not None:
            preds.append(where if callable(where) else AllOf.ensure_iterable(where))

        return self.on(topic=topics.HASS_EVENT_STATE_CHANGED, handler=handler, where=preds, **opts)

    def on_homeassistant_restart(
        self,
        handler: "Handler[CallServiceEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to Home Assistant restart events.

        Args:
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """
        return self.on_call_service(
            domain="homeassistant",
            service="restart",
            handler=handler,
            where=where,
            **opts,
        )

    def on_call_service(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "Handler[CallServiceEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to service call events.

        Args:
            domain (str | None): The domain to filter service calls (e.g., "light").
            service (str | None): The service to filter service calls (e.g., "turn_on").
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to call_service with domain='%s', service='%s', where='%s' - being handled by '%s'"),
            domain,
            service,
            where,
            handler,
        )

        preds: list[Predicate] = []
        if domain is not None:
            preds.append(Guard["CallServiceEvent"](lambda event: event.payload.data.domain == domain))

        if service is not None:
            preds.append(Guard["CallServiceEvent"](lambda event: event.payload.data.service == service))

        if where is not None:
            preds.append(where if callable(where) else AllOf.ensure_iterable(where))

        return self.on(topic=topics.HASS_EVENT_CALL_SERVICE, handler=handler, where=preds, **opts)

    def on_component_loaded(
        self,
        component: str | None = None,
        *,
        handler: "Handler[ComponentLoadedEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to component loaded events.

        Args:
            component (str | None): The component to filter load events (e.g., "light").
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to component_loaded with component='%s', where='%s' - being handled by '%s'"),
            component,
            where,
            handler,
        )

        preds: list[Predicate] = []

        if component is not None:
            preds.append(Guard["ComponentLoadedEvent"](lambda event: event.payload.data.component == component))

        if where is not None:
            preds.append(where if callable(where) else AllOf.ensure_iterable(where))

        return self.on(topic=topics.HASS_EVENT_COMPONENT_LOADED, handler=handler, where=preds, **opts)

    def on_service_registered(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "Handler[ServiceRegisteredEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to service registered events.

        Args:
            domain (str | None): The domain to filter service registrations (e.g., "light").
            service (str | None): The service to filter service registrations (e.g., "turn_on").
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to service_registered with domain='%s', service='%s', where='%s' - being handled by '%s'"),
            domain,
            service,
            where,
            handler,
        )

        preds: list[Predicate] = []

        if domain is not None:
            preds.append(Guard["ServiceRegisteredEvent"](lambda event: event.payload.data.domain == domain))

        if service is not None:
            preds.append(Guard["ServiceRegisteredEvent"](lambda event: event.payload.data.service == service))

        if where is not None:
            preds.append(where if callable(where) else AllOf.ensure_iterable(where))

        return self.on(topic=topics.HASS_EVENT_SERVICE_REGISTERED, handler=handler, where=preds, **opts)

    def on_hassette_service_status(
        self,
        status: ResourceStatus | None = None,
        *,
        handler: "Handler[HassetteServiceEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to hassette service status events.

        Args:
            status (ResourceStatus | None): The status to filter events (e.g., ResourceStatus.STARTED).
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to hassette.service_status with status='%s', where='%s' - being handled by '%s'"),
            status,
            where,
            handler,
        )

        preds: list[Predicate] = []

        if status is not None:
            preds.append(Guard["HassetteServiceEvent"](lambda event: event.payload.data.status == status))

        if where is not None:
            preds.append(where if callable(where) else AllOf.ensure_iterable(where))

        return self.on(topic=topics.HASSETTE_EVENT_SERVICE_STATUS, handler=handler, where=preds, **opts)

    def on_hassette_service_failed(
        self,
        *,
        handler: "Handler[HassetteServiceEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to hassette service failed events.

        Args:
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        return self.on_hassette_service_status(status=ResourceStatus.FAILED, handler=handler, where=where, **opts)

    def on_hassette_service_crashed(
        self,
        *,
        handler: "Handler[HassetteServiceEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to hassette service crashed events.

        Args:
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        return self.on_hassette_service_status(status=ResourceStatus.CRASHED, handler=handler, where=where, **opts)

    def on_hassette_service_started(
        self,
        *,
        handler: "Handler[HassetteServiceEvent]",
        where: "Predicate | Iterable[Predicate] | None" = None,
        **opts,
    ) -> Subscription:
        """Subscribe to hassette service started events.

        Args:
            handler (Callable): The function to call when the event matches.
            where (Predicate | Iterable[Predicate] | None): Additional predicates to filter events.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            Subscription: A subscription object that can be used to manage the listener.
        """

        return self.on_hassette_service_status(status=ResourceStatus.RUNNING, handler=handler, where=where, **opts)

    def _make_async_handler(self, fn: "Handler[E_contra]") -> "AsyncHandler[E_contra]":
        """Wrap a function to ensure it is always called as an async handler.

        If the function is already an async function, it will be called directly.
        If it is a regular function, it will be run in an executor to avoid blocking the event loop.

        Args:
            fn (Callable[..., Any]): The function to adapt.

        Returns:
            AsyncHandler: An async handler that wraps the original function.
        """
        return cast("AsyncHandler[E_contra]", make_async_adapter(fn))

    def _add_debounce(
        self, handler: "AsyncHandler[Event[Any]]", seconds: float, task_bucket: "TaskBucket"
    ) -> "AsyncHandler[Event[Any]]":
        """Add a debounce to an async handler.

        This will ensure that the handler is only called after a specified period of inactivity.
        If a new event comes in before the debounce period has passed, the previous call is cancelled.

        Args:
            handler (AsyncHandler): The async handler to debounce.
            seconds (float): The debounce period in seconds.

        Returns:
            AsyncHandler: A new async handler that applies the debounce logic.
        """
        pending: asyncio.Task | None = None
        last_ev: Event[Any] | None = None

        async def _debounced(event: Event[Any]) -> None:
            nonlocal pending, last_ev
            last_ev = event
            if pending and not pending.done():
                pending.cancel()

            async def _later():
                try:
                    await asyncio.sleep(seconds)
                    if last_ev is not None:
                        await handler(last_ev)
                except asyncio.CancelledError:
                    pass

            pending = task_bucket.spawn(_later(), name="adapters:debounce_handler")

        return _debounced

    def _add_throttle(self, handler: "AsyncHandler[Event[Any]]", seconds: float) -> "AsyncHandler[Event[Any]]":
        """Add a throttle to an async handler.

        This will ensure that the handler is only called at most once every specified period of time.
        If a new event comes in before the throttle period has passed, it will be ignored.

        Args:
            handler (AsyncHandler): The async handler to throttle.
            seconds (float): The throttle period in seconds.

        Returns:
            AsyncHandler: A new async handler that applies the throttle logic.
        """

        last_time = 0.0
        lock = asyncio.Lock()

        async def _throttled(event: Event[Any]) -> None:
            nonlocal last_time
            async with lock:
                now = time.monotonic()
                if now - last_time >= seconds:
                    last_time = now
                    await handler(event)

        return _throttled
