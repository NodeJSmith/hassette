"""
Event bus for subscribing to Home Assistant and Hassette events with powerful filtering.

The Bus provides a clean interface for listening to state changes, service calls, and other events
from Home Assistant. Each app gets its own Bus instance that automatically manages subscriptions
and cleanup. Use predicates and conditions to filter events precisely.

Examples:
    Basic state change subscription

    ```python
    # Listen to all changes on an entity
    self.bus.on_state_change("light.kitchen", handler=self.on_light_change)
    ```

    State change with value filters

    ```python
    # Only when light turns on
    self.bus.on_state_change("light.kitchen", changed_to="on", handler=self.on_light_on)

    # Only when temperature increases above 20
    self.bus.on_state_change(
        "sensor.temperature",
        changed_to=lambda temp: temp > 20,
        handler=self.on_temp_high
    )
    ```

    Attribute change monitoring

    ```python
    # Monitor battery level changes
    self.bus.on_attribute_change(
        "sensor.phone_battery",
        "battery_level",
        handler=self.on_battery_change
    )
    ```

    Service call interception

    ```python
    # Listen to light service calls
    self.bus.on_call_service(
        domain="light",
        service="turn_on",
        handler=self.on_light_service_call
    )
    ```

    Using glob patterns and complex predicates

    ```python
    from hassette import conditions as C

    # All lights in kitchen
    self.bus.on_state_change("light.*kitchen*", handler=self.on_kitchen_light)

    # Comparison condition - temperature increased
    self.bus.on_state_change(
        "sensor.temperature",
        changed=C.Increased(),
        handler=self.on_high_temp
    )
    ```

    Event options for timing control

    ```python
    # Run only once
    self.bus.on_state_change("light.kitchen", handler=handler, once=True)

    # Debounce rapid changes (wait 5 seconds after last event)
    self.bus.on_state_change("sensor.motion", handler=handler, debounce=5.0)

    # Throttle frequent events (max once per 10 seconds)
    self.bus.on_state_change("sensor.temperature", handler=handler, throttle=10.0)
    ```
"""

import asyncio
import typing
from collections.abc import Mapping
from typing import Any, TypeVar, Unpack

from typing_extensions import TypedDict

from hassette.const import NOT_PROVIDED
from hassette.event_handling import predicates as P
from hassette.event_handling.accessors import get_path
from hassette.resources.base import Resource
from hassette.types import ComparisonCondition, Topic
from hassette.types.enums import ResourceStatus
from hassette.utils.func_utils import callable_short_name

from .listeners import Listener, Subscription

if typing.TYPE_CHECKING:
    from collections.abc import Sequence

    from hassette import Hassette
    from hassette.core.bus_service import BusService
    from hassette.types import ChangeType, HandlerType, Predicate

T = TypeVar("T", covariant=True)


class Options(TypedDict, total=False):
    once: bool
    """Whether the listener should be removed after one invocation."""

    debounce: float | None
    """Length of time in seconds to wait before invoking the handler, resetting if another event is received."""

    throttle: float | None
    """Length of time in seconds to wait before allowing the handler to be invoked again."""


class Bus(Resource):
    """Individual event bus instance for a specific owner (e.g., App or Service)."""

    bus_service: "BusService"

    priority: int = 0
    """Priority level for event handlers created by this bus."""

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource", priority: int = 0):
        inst = cls(hassette=hassette, parent=parent)
        inst.bus_service = inst.hassette._bus_service
        inst.priority = priority

        assert inst.bus_service is not None, "Bus service not initialized"
        inst.mark_ready(reason="Bus initialized")
        return inst

    async def on_shutdown(self) -> None:
        """Cleanup all listeners owned by this bus's owner on shutdown."""
        await self.remove_all_listeners()

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.bus_service_log_level

    def add_listener(self, listener: "Listener") -> asyncio.Task[None]:
        """Add a listener to the bus."""
        return self.bus_service.add_listener(listener)

    def remove_listener(self, listener: "Listener") -> asyncio.Task[None]:
        """Remove a listener from the bus."""
        return self.bus_service.remove_listener(listener)

    def remove_all_listeners(self) -> asyncio.Task[None]:
        """Remove all listeners owned by this bus's owner."""
        return self.bus_service.remove_listeners_by_owner(self.owner_id)

    def get_listeners(self) -> asyncio.Task[list["Listener"]]:
        """Get all listeners owned by this bus's owner."""
        return self.bus_service.get_listeners_by_owner(self.owner_id)

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
    ) -> Subscription:
        """Subscribe to an event topic with optional filtering and modifiers.

        Args:
            topic: The event topic to listen to.
            handler: The function to call when the event matches.
            where: Optional predicates to filter events. These can be custom callables or predefined predicates from
                `hassette.event_handling.predicates`. They will receive the full event for evaluation.
            kwargs: Keyword arguments to pass to the handler.
            once: If True, the handler will be called only once and then removed.
            debounce: If set, applies a debounce to the handler.
            throttle: If set, applies a throttle to the handler.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        listener = Listener.create(
            task_bucket=self.task_bucket,
            owner=self.owner_id,
            topic=topic,
            handler=handler,
            where=where,
            kwargs=kwargs,
            once=once,
            debounce=debounce,
            throttle=throttle,
            priority=self.priority,
        )

        def unsubscribe() -> None:
            self.remove_listener(listener)

        self.add_listener(listener)
        return Subscription(listener, unsubscribe)

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
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to state changes for a specific entity.

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
            **opts: Additional options like `once`, `debounce` and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        self.logger.debug(
            (
                "Subscribing to entity '%s' with changed='%s', changed_from='%s', changed_to='%s', where='%s' -"
                " being handled by '%s'"
            ),
            entity_id,
            changed,
            changed_from,
            changed_to,
            where,
            callable_short_name(handler),
        )

        preds: list[Predicate] = [P.EntityMatches(entity_id)]
        if changed:
            if changed is True:
                preds.append(P.StateDidChange())
            else:
                preds.append(P.StateComparison(condition=changed))

        if changed_from is not NOT_PROVIDED:
            preds.append(P.StateFrom(condition=changed_from))

        if changed_to is not NOT_PROVIDED:
            preds.append(P.StateTo(condition=changed_to))

        if where is not None:
            preds.append(where if callable(where) else P.AllOf.ensure_iterable(where))  # allow extra guards

        return self.on(topic=Topic.HASS_EVENT_STATE_CHANGED, handler=handler, where=preds, kwargs=kwargs, **opts)

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
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to state change events for a specific entity's attribute.

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
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            (
                "Subscribing to entity '%s' attribute '%s' with changed_from='%s', changed_to='%s'"
                ", where='%s' - being handled by '%s'"
            ),
            entity_id,
            attr,
            changed_from,
            changed_to,
            where,
            callable_short_name(handler),
        )

        preds: list[Predicate] = [P.EntityMatches(entity_id)]

        # if not changed then we are going to fire every time the entity has a StateChanged event
        # regardless of what changed - not sure if that is desired behavior or not, but it is consistent with the main
        # on_state_change method
        if changed:
            if changed is True:
                preds.append(P.AttrDidChange(attr))
            else:
                preds.append(P.AttrComparison(attr, condition=changed))
        else:
            self.logger.warning(
                "Attribute change subscription for entity '%s' on attribute '%s' with changed=False will fire on"
                " every state change event for the entity",
                entity_id,
                attr,
            )

        if changed_from is not NOT_PROVIDED:
            preds.append(P.AttrFrom(attr, condition=changed_from))

        if changed_to is not NOT_PROVIDED:
            preds.append(P.AttrTo(attr, condition=changed_to))

        if where is not None:
            preds.append(where if callable(where) else P.AllOf.ensure_iterable(where))

        return self.on(topic=Topic.HASS_EVENT_STATE_CHANGED, handler=handler, where=preds, kwargs=kwargs, **opts)

    def on_call_service(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | Mapping[str, ChangeType] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to service call events.

        Args:
            domain: The domain to filter service calls (e.g., "light").
            service: The service to filter service calls (e.g., "turn_on").
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to call_service with domain='%s', service='%s', where='%s' - being handled by '%s'"),
            domain,
            service,
            where,
            callable_short_name(handler),
        )

        preds: list[Predicate] = []
        if domain is not None:
            preds.append(P.DomainMatches(domain))

        if service is not None:
            preds.append(P.ServiceMatches(service))

        if where is not None:
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

        return self.on(topic=Topic.HASS_EVENT_CALL_SERVICE, handler=handler, where=preds, kwargs=kwargs, **opts)

    def on_component_loaded(
        self,
        component: str | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to component loaded events.

        Args:
            component: The component to filter load events (e.g., "light").
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to component_loaded with component='%s', where='%s' - being handled by '%s'"),
            component,
            where,
            callable_short_name(handler),
        )

        preds: list[Predicate] = []

        if component is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.component"), condition=component))

        if where is not None:
            preds.append(where if callable(where) else P.AllOf.ensure_iterable(where))

        return self.on(topic=Topic.HASS_EVENT_COMPONENT_LOADED, handler=handler, where=preds, kwargs=kwargs, **opts)

    def on_service_registered(
        self,
        domain: str | None = None,
        service: str | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to service registered events.

        Args:
            domain: The domain to filter service registrations (e.g., "light").
            service: The service to filter service registrations (e.g., "turn_on").
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to service_registered with domain='%s', service='%s', where='%s' - being handled by '%s'"),
            domain,
            service,
            where,
            callable_short_name(handler),
        )

        preds: list[Predicate] = []

        if domain is not None:
            preds.append(P.DomainMatches(domain))

        if service is not None:
            preds.append(P.ServiceMatches(service))

        if where is not None:
            preds.append(where if callable(where) else P.AllOf.ensure_iterable(where))

        return self.on(topic=Topic.HASS_EVENT_SERVICE_REGISTERED, handler=handler, where=preds, kwargs=kwargs, **opts)

    def on_homeassistant_restart(
        self,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to Home Assistant restart events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        return self.on_call_service(
            domain="homeassistant", service="restart", handler=handler, where=where, kwargs=kwargs, **opts
        )

    def on_homeassistant_start(
        self,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to Home Assistant start events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        return self.on_call_service(
            domain="homeassistant", service="start", handler=handler, where=where, kwargs=kwargs, **opts
        )

    def on_homeassistant_stop(
        self,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to Home Assistant stop events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """
        return self.on_call_service(
            domain="homeassistant", service="stop", handler=handler, where=where, kwargs=kwargs, **opts
        )

    def on_hassette_service_status(
        self,
        status: ResourceStatus | None = None,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to hassette service status events.

        Args:
            status: The status to filter events (e.g., ResourceStatus.STARTED).
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        self.logger.debug(
            ("Subscribing to hassette.service_status with status='%s', where='%s' - being handled by '%s'"),
            status,
            where,
            callable_short_name(handler),
        )

        preds: list[Predicate] = []

        if status is not None:
            preds.append(P.ValueIs(source=get_path("payload.data.status"), condition=status))

        if where is not None:
            preds.append(where if callable(where) else P.AllOf.ensure_iterable(where))

        return self.on(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, handler=handler, where=preds, kwargs=kwargs, **opts)

    def on_hassette_service_failed(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to hassette service failed events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        return self.on_hassette_service_status(
            status=ResourceStatus.FAILED, handler=handler, where=where, kwargs=kwargs, **opts
        )

    def on_hassette_service_crashed(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to hassette service crashed events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        return self.on_hassette_service_status(
            status=ResourceStatus.CRASHED, handler=handler, where=where, kwargs=kwargs, **opts
        )

    def on_hassette_service_started(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to hassette service started events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        return self.on_hassette_service_status(
            status=ResourceStatus.RUNNING, handler=handler, where=where, kwargs=kwargs, **opts
        )

    def on_websocket_connected(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to websocket connected events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        return self.on(
            topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED, handler=handler, where=where, kwargs=kwargs, **opts
        )

    def on_websocket_disconnected(
        self,
        *,
        handler: "HandlerType",
        where: "Predicate | Sequence[Predicate] | None" = None,
        kwargs: Mapping[str, Any] | None = None,
        **opts: Unpack[Options],
    ) -> Subscription:
        """Subscribe to websocket disconnected events.

        Args:
            handler: The function to call when the event matches.
            where: Additional predicates to filter events.
            kwargs: Keyword arguments to pass to the handler.
            **opts: Additional options like `once`, `debounce`, and `throttle`.

        Returns:
            A subscription object that can be used to manage the listener.
        """

        return self.on(
            topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED, handler=handler, where=where, kwargs=kwargs, **opts
        )
