import asyncio
import itertools
import typing
from typing import Any

from anyio.streams.memory import MemoryObjectReceiveStream

from hassette.core import topics
from hassette.core.classes.resource import Resource, Service
from hassette.core.enums import ResourceStatus

from .adapters import add_debounce, add_throttle, make_async_handler
from .listeners import Listener, Subscription
from .predicates import AllOf, AttrChanged, Changed, ChangedFrom, ChangedTo, EntityIs, Guard
from .predicates.base import SENTINEL, normalize_where
from .routing import Router

if typing.TYPE_CHECKING:
    from collections.abc import Iterable

    from hassette.core.core import Hassette
    from hassette.core.events import (
        CallServiceEvent,
        ComponentLoadedEvent,
        Event,
        HassetteServiceEvent,
        ServiceRegisteredEvent,
        StateChangeEvent,
    )
    from hassette.core.types import Handler, Predicate


class _BusService(Service):
    """EventBus service that handles event dispatching and listener management."""

    def __init__(self, hassette: "Hassette", stream: MemoryObjectReceiveStream["tuple[str, Event[Any]]"]):
        super().__init__(hassette)
        self.logger.setLevel(self.hassette.config.bus_service_log_level)

        self.stream = stream

        self.listener_seq = itertools.count(1)
        self.router = Router()
        self._tasks: set[asyncio.Task[Any]] = set()

    def _log_task_result(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return

        exc = task.exception()
        if exc:
            self.logger.error("Bus background task failed", exc_info=exc)

    def add_listener(self, listener: Listener) -> None:
        """Add a listener to the bus."""
        self.task_bucket.spawn(self.router.add_route(listener.topic, listener), name="bus:add_listener")

    def remove_listener(self, listener: Listener) -> None:
        """Remove a listener from the bus."""
        self.remove_listener_by_id(listener.topic, listener.listener_id)

    def remove_listener_by_id(self, topic: str, listener_id: int) -> None:
        """Remove a listener by its ID."""
        self.task_bucket.spawn(self.router.remove_listener_by_id(topic, listener_id), name="bus:remove_listener")

    def remove_listeners_by_owner(self, owner: str) -> None:
        """Remove all listeners owned by a specific owner."""
        self.task_bucket.spawn(self.router.clear_owner(owner), name="bus:remove_listeners_by_owner")

    async def dispatch(self, topic: str, event: "Event[Any]") -> None:
        """Dispatch an event to all matching listeners for the given topic."""
        try:
            if (
                event.payload.event_type == "call_service"
                and event.payload.data.domain == "system_log"
                and event.payload.data.service_data.get("level") == "debug"
            ):
                return
        except Exception:
            pass

        targets = await self.router.get_matching_listeners(topic)

        self.logger.debug("Event: %r", event)

        if not targets:
            return

        self.logger.debug("Dispatching %s to %d listeners", topic, len(targets))
        self.logger.debug("Listeners for %s: %r", topic, targets)

        for listener in targets:
            self.task_bucket.spawn(self._dispatch(topic, event, listener), name="bus:dispatch_listener")

    async def _dispatch(self, topic: str, event: "Event[Any]", listener: Listener) -> None:
        try:
            if await listener.matches(event):
                self.logger.debug("Dispatching %s -> %r", topic, listener)
                await listener.handler(event)
        except asyncio.CancelledError:
            self.logger.debug("Listener dispatch cancelled (topic=%s, handler=%r)", topic, listener.handler_name)
            raise
        except Exception:
            self.logger.exception("Listener error (topic=%s, handler=%r)", topic, listener.handler_name)
        finally:
            # if once, remove after running
            if listener.once:
                self.remove_listener(listener)

    async def run_forever(self) -> None:
        """Worker loop that processes events from the stream."""

        async with self.starting():
            self.logger.debug("Waiting for Hassette ready event")
            await self.hassette.ready_event.wait()
            self.mark_ready(reason="Hassette is ready")

        try:
            async with self.stream:
                async for event_name, event_data in self.stream:
                    try:
                        await self.dispatch(event_name, event_data)
                    except Exception as e:
                        self.logger.exception("Error processing event: %s", e)
        except asyncio.CancelledError:
            self.logger.debug("EventBus service cancelled")
            self.mark_not_ready(reason="EventBus cancelled")
            await self.handle_stop()
        except Exception as e:
            await self.handle_crash(e)
            raise
        finally:
            await self._cleanup()


class Bus(Resource):
    """Individual event bus instance for a specific owner (e.g., App or Service)."""

    def __init__(self, hassette: "Hassette", owner: str):
        """Initialize the Bus instance."""
        super().__init__(hassette)
        self.logger.setLevel(self.hassette.config.bus_service_log_level)

        self.owner = owner
        """Owner of the bus, must be a unique identifier for the owner."""

        self.mark_ready(reason="Bus initialized")

    @property
    def bus_service(self) -> _BusService:
        return self.hassette._bus_service

    def add_listener(self, listener: Listener) -> None:
        """Add a listener to the bus."""
        self.bus_service.add_listener(listener)

    def remove_listener(self, listener: Listener) -> None:
        """Remove a listener from the bus."""
        self.bus_service.remove_listener(listener)

    def remove_all_listeners(self) -> None:
        """Remove all listeners owned by this bus's owner."""
        self.bus_service.remove_listeners_by_owner(self.owner)

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
        handler = make_async_handler(orig)
        # decorate
        if debounce and debounce > 0:
            handler = add_debounce(handler, debounce, self.task_bucket)
        if throttle and throttle > 0:
            handler = add_throttle(handler, throttle)

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
