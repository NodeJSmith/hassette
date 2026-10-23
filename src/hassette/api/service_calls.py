"""Service-call and event-firing methods of :class:`~hassette.api.api.Api`."""

import typing
from collections.abc import Coroutine, Mapping  # Coroutine is needed at runtime for annotation inspection
from enum import StrEnum
from logging import Logger
from typing import Any, Literal, overload

from hassette.models.services import ServiceResponse
from hassette.utils.await_guard import guard_await
from hassette.utils.source_capture import capture_source_location

if typing.TYPE_CHECKING:
    from hassette.resources.base import Resource

NOTIFY_DOMAIN = "notify"
"""Home Assistant service domain that hosts every notifier (``notify.<notifier>``)."""


def normalize_notifier(notifier: str) -> str:
    """Return the bare notify service name for *notifier*.

    Accepts either a bare name (``"mobile_app_phone"``) or a fully-qualified one
    (``"notify.mobile_app_phone"``), so users can paste whichever form they see in
    Home Assistant's developer tools.

    Args:
        notifier: The notify service name, with or without the ``notify.`` prefix.

    Returns:
        The service name without the ``notify.`` prefix.

    Raises:
        ValueError: If *notifier* is blank, or qualified with a domain other than ``notify``.
    """
    name = notifier.strip()
    if not name:
        raise ValueError("notifier must be a non-empty notify service name, e.g. 'mobile_app_phone'.")

    if "." not in name:
        return name

    domain, _, service = name.partition(".")
    if domain != NOTIFY_DOMAIN or not service or "." in service:
        raise ValueError(
            f"Invalid notifier {notifier!r}: expected a bare service name (e.g. 'mobile_app_phone') "
            "or a 'notify.'-qualified one (e.g. 'notify.mobile_app_phone')."
        )
    return service


class ApiServiceCallsMixin:
    """Service calls, event firing, and notifications on :class:`~hassette.api.api.Api`."""

    # Provided by Resource via Api; declared here for type narrowing within the mixin.
    parent: "Resource | None"
    logger: Logger

    if typing.TYPE_CHECKING:

        async def ws_send_and_wait(self, *, retry_on_timeout: bool = True, **data: Any) -> Any:
            """Type-checking stub for :meth:`Api.ws_send_and_wait`, which sends a command and returns its result."""
            ...

        async def ws_send_json(self, **data: Any) -> None:
            """Type-checking stub for :meth:`Api.ws_send_json`, which sends a message without awaiting a reply."""
            ...

        async def get_services(self) -> dict[str, Any]:
            """Type-checking stub for :meth:`Api.get_services`, which returns every registered service by domain."""
            ...

    def fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, dict[str, Any]]":
        """Fire a custom event in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            event_type: The type of the event to fire (e.g., "custom_event").
            event_data: Additional data to include with the event.

        Returns:
            The response from Home Assistant.
        """
        # Cheap path: no DB-record telemetry on api fire-and-forget methods
        # (unlike bus/scheduler listeners) — only warning attribution needs the location here.
        source_location = capture_source_location()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._fire_event(event_type, event_data),
            owner=self.parent,
            source_location=source_location,
            method_name="fire_event",
        )

    async def _fire_event(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Async body for fire_event."""
        event_data = event_data or {}

        data = {"type": "fire_event", "event_type": event_type, "event_data": event_data}
        if not event_data:
            data.pop("event_data")

        return await self.ws_send_and_wait(retry_on_timeout=False, **data)  # sent once; re-send would refire it

    # Overload order is load-bearing — Pyright matches top-to-bottom, first hit wins.
    # The None-returning (return_response not True) overload MUST come first so a call
    # that omits return_response resolves to it. The True overload needs a default
    # (target already has one, and a non-default arg can't follow a default arg), but
    # that default never makes it the chosen overload for an omitted return_response,
    # because the None overload above matches first. Reordering or dropping the default
    # silently flips the inferred return type — covered by tests/pyright_probes.
    # dup-ignore-start: @overload signatures necessarily mirror the implementation param list
    @overload
    def call_service(
        self,
        domain: str,
        service: str,
        target: Mapping[str, str | list[str]] | None = None,
        return_response: typing.Literal[False] | None = None,
        *,
        wait_for_ack: bool = False,
        **data: Any,
    ) -> "Coroutine[Any, Any, None]": ...

    # dup-ignore-end

    # dup-ignore-start: @overload signatures necessarily mirror the implementation param list
    @overload
    def call_service(
        self,
        domain: str,
        service: str,
        target: Mapping[str, str | list[str]] | None = None,
        return_response: Literal[True] = True,
        *,
        wait_for_ack: bool = False,
        **data: Any,
    ) -> "Coroutine[Any, Any, ServiceResponse]": ...

    # dup-ignore-end

    # dup-ignore-start: @overload signatures necessarily mirror the implementation param list
    def call_service(
        self,
        domain: str,
        service: str,
        target: Mapping[str, str | list[str]] | None = None,
        return_response: bool | None = False,
        *,
        wait_for_ack: bool = False,
        **data: Any,
    ) -> "Coroutine[Any, Any, ServiceResponse | None]":
        # dup-ignore-end
        """Call a Home Assistant service.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            domain: The domain of the service (e.g., "light").
            service: The name of the service to call (e.g., "turn_on").
            target: What the call acts on, keyed by ``entity_id``, ``device_id``, ``area_id``, ``floor_id`` or
                ``label_id``. Preferred form; the same keys in ``**data`` reach the service identically, because
                Home Assistant merges ``target`` into the service data before validating it (``target`` wins).
            return_response: Whether to return the response from Home Assistant. Defaults to False. Only valid for
                services Home Assistant declares as returning a response — requesting it for any other service is
                rejected by Home Assistant. Services declared as returning *only* a response require it, so those
                need it alongside ``wait_for_ack`` rather than ``wait_for_ack`` on its own.
            wait_for_ack: Whether to wait for Home Assistant to acknowledge the call. Defaults to False. Waits on
                Home Assistant's result envelope instead of sending fire-and-forget, surfacing HA-side failures as
                ``FailedMessageError`` without asking for response data — so it works for services that return no
                response, which ``return_response`` cannot.
            **data: Additional data to send with the service call.

        Returns:
            ServiceResponse | None: The response from Home Assistant if return_response is True. Otherwise None.

        Raises:
            ResponseTimeoutError: If ``return_response`` or ``wait_for_ack`` is set and times out.
                Never re-sent, since Home Assistant may already have applied it.
        """
        # Cheap path — see fire_event (same rationale for all api methods)
        source_location = capture_source_location()
        # Coroutine[...] supertype annotation is load-bearing — see hassette/utils/await_guard.py / design/071.
        return guard_await(
            self._call_service(domain, service, target, return_response, wait_for_ack=wait_for_ack, **data),
            owner=self.parent,
            source_location=source_location,
            method_name="call_service",
        )

    # dup-ignore-start: async body mirrors the sync overloads' param list — see call_service above
    async def _call_service(
        self,
        domain: str,
        service: str,
        target: Mapping[str, str | list[str]] | None = None,
        return_response: bool | None = False,
        *,
        wait_for_ack: bool = False,
        **data: Any,
    ) -> ServiceResponse | None:
        # dup-ignore-end
        """Async body for call_service."""
        payload = {
            "type": "call_service",
            "domain": domain,
            "service": service,
            "target": dict(target) if target is not None else None,
            "return_response": return_response,
        }

        payload = {k: v for k, v in payload.items() if v is not None}
        data = {k: v for k, v in data.items() if v is not None}

        if data:
            self.logger.debug("Adding extra data to service call: %s", data)
            payload["service_data"] = data

        # Neither waiting path re-sends on timeout — a lost response doesn't mean HA skipped
        # the call, so a retry could apply it twice (counter.increment would count twice), and
        # a response-returning service can still act (conversation.process, scripts).
        if return_response:
            resp = await self.ws_send_and_wait(retry_on_timeout=False, **payload)
            return ServiceResponse(**resp)

        if wait_for_ack:
            # Waits on the same result envelope as the return_response path, without asking HA
            # for response data. Services declared as returning no response (e.g.
            # counter.increment) reject return_response=True outright, so this is the only way
            # to surface their HA-side errors. ws_send_and_wait raises FailedMessageError on a
            # failed envelope, so no envelope parsing is needed here.
            await self.ws_send_and_wait(retry_on_timeout=False, **payload)
            return None

        await self.ws_send_json(**payload)
        return None

    def turn_on(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> "Coroutine[Any, Any, None]":
        """Turn on a specific entity in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            entity_id: The ID of the entity to turn on (e.g., "light.office").
            domain: The domain to use for the service call. Defaults to the entity's domain,
                derived from ``entity_id`` (e.g., ``"light.office"`` derives ``"light"``). Pass
                explicitly to override — for example, ``domain="homeassistant"`` to use the
                generic (deprecated) service.
            **data: Additional service data forwarded to the service call.

        """
        entity_id = str(entity_id)
        if domain is None:
            domain = entity_id.split(".", 1)[0]
        return self.call_service(domain=domain, service="turn_on", target={"entity_id": entity_id}, **data)

    def turn_off(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> "Coroutine[Any, Any, None]":
        """Turn off a specific entity in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            entity_id: The ID of the entity to turn off (e.g., "light.office").
            domain: The domain to use for the service call. Defaults to the entity's domain,
                derived from ``entity_id`` (e.g., ``"light.office"`` derives ``"light"``). Pass
                explicitly to override — for example, ``domain="homeassistant"`` to use the
                generic (deprecated) service.
            **data: Additional service data forwarded to the service call.

        """
        entity_id = str(entity_id)
        if domain is None:
            domain = entity_id.split(".", 1)[0]
        return self.call_service(domain=domain, service="turn_off", target={"entity_id": entity_id}, **data)

    def toggle(self, entity_id: str | StrEnum, domain: str | None = None, **data: Any) -> "Coroutine[Any, Any, None]":
        """Toggle a specific entity in Home Assistant.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            entity_id: The ID of the entity to toggle (e.g., "light.office").
            domain: The domain to use for the service call. Defaults to the entity's domain,
                derived from ``entity_id`` (e.g., ``"light.office"`` derives ``"light"``). Pass
                explicitly to override — for example, ``domain="homeassistant"`` to use the
                generic (deprecated) service.
            **data: Additional service data forwarded to the service call.

        """
        entity_id = str(entity_id)
        if domain is None:
            domain = entity_id.split(".", 1)[0]
        return self.call_service(domain=domain, service="toggle", target={"entity_id": entity_id}, **data)

    def notify(
        self,
        message: str,
        notifier: str,
        title: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> "Coroutine[Any, Any, None]":
        """Send a notification through a Home Assistant notify service.

        Shorthand for ``call_service("notify", notifier, message=..., title=..., data=...)``.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).

        Args:
            message: The notification body.
            notifier: The notify service to send through. Accepts a bare name
                (``"mobile_app_phone"``) or a fully-qualified one
                (``"notify.mobile_app_phone"``). Call :meth:`get_notify_services`
                to discover which notifiers exist on your instance.
            title: Optional notification title. Omitted from the service call when None.
            data: Optional platform-specific payload (e.g. Android/iOS push options),
                forwarded as the service's ``data`` field. Omitted when None.

        Raises:
            ValueError: If ``notifier`` is blank, or qualified with a domain other than ``notify``.
        """
        service = normalize_notifier(notifier)
        return self.call_service(NOTIFY_DOMAIN, service, message=message, title=title, data=data)

    async def get_notify_services(self) -> list[str]:
        """Get the notify services available on this Home Assistant instance.

        Returns:
            Sorted bare service names (without the ``notify.`` prefix), ready to pass
            straight to :meth:`notify` — e.g. ``["mobile_app_phone", "persistent_notification"]``.
        """
        services = await self.get_services()
        return sorted(services.get(NOTIFY_DOMAIN, {}).keys())
