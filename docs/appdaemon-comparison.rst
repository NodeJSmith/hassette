AppDaemon vs Hassette
======================

This guide targets AppDaemon users who want to understand where Hassette matches the familiar
workflow, where it differs, and what the migration effort looks like. It focuses on the core moving
parts: the bus, scheduler, Home Assistant API, and app configuration.

Quick reference table
---------------------

.. list-table:: Snapshot of common tasks
   :header-rows: 1
   :widths: 20 60 60

   * - Action
     - AppDaemon
     - Hassette
   * - Listen for an entity state change
     - ``self.listen_state(self.opened, "binary_sensor.door", new="on")``
     - ``self.bus.on_entity("binary_sensor.door", handler=self.on_open, changed_to="on")``
   * - React to an attribute update
     - ``self.listen_state(self.battery, "sensor.phone", attribute="battery", immediate=True)``
     - ``self.bus.on_attribute("sensor.phone", "battery", handler=self.on_battery)``
   * - Monitor service calls
     - ``self.listen_event(self.log_call, "call_service", domain="light")``
     - ``self.bus.on_call_service(domain="light", handler=self.on_service)``
   * - Schedule something in 60 seconds
     - ``self.run_in(self.turn_off, 60)``
     - ``self.scheduler.run_in(self.turn_off, delay=60)``
   * - Run every morning at 07:30
     - ``self.run_daily(self.morning, time(7, 30, 0))``
     - ``self.scheduler.run_cron(self.morning, minute=30, hour=7)``
   * - Call a Home Assistant service
     - ``self.call_service("light/turn_on", entity_id="light.kitchen", brightness=200)``
     - ``await self.api.call_service("light", "turn_on", target={"entity_id": "light.kitchen"}, brightness_pct=80)``
   * - Access app configuration
     - ``self.args["entity"]`` (dict sourced from ``apps.yaml``)
     - ``self.app_config.entity`` (typed Pydantic model validated from ``hassette.toml``)
   * - Stop a listener/timer
     - ``self.cancel_listen_state(handle)`` / ``self.cancel_timer(handle)``
     - ``subscription.unsubscribe()`` / ``job.cancel()``

App model and configuration
---------------------------

*AppDaemon*: Apps subclass ``hass.Hass`` and implement ``initialize`` (synchronous). Configuration is
loaded from ``apps.yaml`` with one section per app instance. Every option arrives as an untyped
``dict`` on ``self.args``; validation is manual. Reusing the same class means copying YAML sections or
relying on ``self.args.get("name")`` conventions. Async code is possible but opt-in via ``async``
callbacks and ``self.get_entity("light.kitchen")`` style wrappers remain untyped.

*Hassette*: Apps subclass :class:`hassette.App` (async) or :class:`hassette.AppSync` (sync bridge).
``initialize`` is ``async`` and should call ``await super().initialize()`` after wiring the bus and
scheduler. Configuration lives in ``hassette.toml`` under ``[apps.*]`` tables. Each app supplies a
:class:`hassette.AppConfig` subclass, so Hassette validates input before instantiating the app and
you access ``self.app_config`` with IDE/autocomplete support. Environment variables (via Pydantic) are
first-class. Multiple instances use TOML list-of-tables, which still maps to a strongly-typed model.

*Migration impact*: Expect to convert ``initialize`` to ``async`` and replace ``self.args`` lookups with
fields on ``self.app_config``. If you depend on runtime-generated keys in ``self.args``, you will need
an explicit ``dict[str, Any]`` field in your config model. Hassette does not yet offer a replacement
for AppDaemon's ``global_modules`` convenience.

Event bus and callbacks
-----------------------

*AppDaemon*: ``listen_state`` (plus variants like ``listen_event`` and ``listen_event("call_service")``)
call your handler with several positional arguments, e.g. ``callback(self, entity, attribute, old, new,
kwargs)``. Convenience keyword arguments include ``attribute``, ``new``, ``old``, ``duration`` (wait for
stable state), ``immediate`` (fire once right away), namespaces, and ``timeout``. You cancel by
passing the handle to ``cancel_listen_state``. Filtering by multiple conditions typically involves
several keyword arguments or manual logic in the callback.

*Hassette*: All subscriptions emit a typed event dataclass as a **single** argument. ``self.bus.on_entity``
and ``self.bus.on_attribute`` wrap Home Assistant's ``state_changed`` topic; ``self.bus.on_call_service``
exposes service traffic; and ``self.bus.on`` lets you subscribe to any topic (including custom events
via ``"hass.event.my_event"``). Predicates provide composable guards (e.g., ``P.ChangedTo("on")`` & ``P.AnyOf``). ``debounce`` and ``throttle`` parameters remove boilerplate that AppDaemon typically handles via extra state variables. Subscription objects expose ``unsubscribe()`` for cleanup.

*Where Hassette shines*

- Typed payloads with exact models (``StateChangeEvent[LightState]``) instead of raw dicts.
- Predicate composition beats nested ``if`` trees and can guard on attributes without extra callbacks.
- Async-first handlers avoid thread-launch overhead.

*Where Hassette lags today*

- No built-in equivalent to ``duration``/``timeout``; replicate via ``debounce`` + scheduler or custom predicates.
- No convenience helper yet for generic HA events (``listen_event``); use ``bus.on(topic="hass.event.<type>")``.
- Callbacks currently receive only the event object—there is no automatic ``**kwargs`` passthrough.

Scheduler differences
---------------------

*AppDaemon*: Offers a large toolbox—``run_in``, ``run_once``, ``run_every``, ``run_daily``, ``run_hourly``,
``run_minutely``, ``run_at``, ``run_at_sunrise``/``sunset`` (with offsets), and cron support. Timers
return handles you pass to ``cancel_timer``. Scheduler helpers can pass ``kwargs`` back into the
callback so the same function can serve multiple timers.

*Hassette*: Consolidates on a smaller set: ``run_in``, ``run_every``, ``run_once``, and ``run_cron``. All
helpers accept async or sync callables and return a ``ScheduledJob`` object with ``next_run`` metadata
and ``cancel()``. Triggers use the ``whenever`` library, so you can express start times and intervals
with precise objects (``TimeDelta``, ``SystemDateTime``). Cron covers most repeating needs, but there
is not yet a dedicated sunrise/sunset helper or wrappers like ``run_daily``. You supply context via
closures or ``functools.partial`` if needed.

*Where Hassette shines*

- Async jobs run on the main loop—no background threads required.
- Cron has second-level precision and shares a consistent API for async/sync functions.
- ``ScheduledJob`` exposes ``next_run`` without extra API calls.

*Where Hassette lags today*

- Missing sunrise/sunset and ``run_daily`` convenience wrappers (you can emulate with ``run_cron``).
- Timer callbacks do not automatically receive identifiers/kwargs—carry that state yourself.

Home Assistant API surface
--------------------------

*AppDaemon*: ``get_state``/``set_state``/``call_service``/``fire_event``/``listen_event`` return raw
strings or dicts. The API is synchronous; under the hood AppDaemon manages background threads to talk
to Home Assistant and blocks your coroutine until the request finishes. There are optional async APIs
but most community examples rely on synchronous helpers. There is no typing or schema validation, so
runtime errors emerge only when Home Assistant rejects a payload.

*Hassette*: ``self.api`` is async from top to bottom. ``get_state`` and ``get_states`` coerce responses
into Pydantic models (``states.LightState`` etc.), while ``get_state_raw`` mirrors AppDaemon's dict
return. ``get_entity`` begins a push toward entity classes, though today only ``BaseEntity`` and
``LightEntity`` ship. ``call_service`` and ``turn_on``/``turn_off`` return the ``HassContext`` when
available, which helps with debugging. Low-level ``rest_request`` and ``ws_send_and_wait`` expose the
underlying ``aiohttp`` session if you need endpoints Hassette has not wrapped yet. For synchronous
apps, ``self.api.sync`` mirrors the async API.

*Where Hassette shines*

- Strong typing on read operations: IDEs surface attributes, and Pydantic validates conversions.
- Explicit separation between raw state values and state models reduces stringly-typed bugs.
- Shared aiohttp session with retry/backoff baked in.

*Where Hassette lags today*

- Service calls are not fully typed yet; you still pass ``**data`` manually.
- Entity helper classes are nascent (only lights today), so you may need to keep using plain service calls.
- Some AppDaemon conveniences like ``get_app``/``list_entities`` do not have direct equivalents.

Migration checklist
-------------------

- Update class definitions to inherit from ``App[MyConfig]`` (or ``AppSync``) and adjust ``initialize``
  to be ``async``. Call the ``super()`` lifecycle methods.
- Replace ``self.args`` access with a real ``AppConfig`` model. Validate secrets via environment
  variables or ``SettingsConfigDict``.
- Convert listeners to accept a single event argument. Leverage predicates (``ChangedTo``/``AttrChanged``)
  instead of keyword filters, and plan to manage duration/timeouts manually for now.
- Swap scheduler helpers to ``self.scheduler.*`` and decide how to pass context to callbacks (closures
  or ``partial``).
- Replace synchronous API calls with ``await self.api...`` variants; use ``self.api.sync`` only inside
  ``AppSync`` code paths.

If you rely on AppDaemon features that Hassette lacks (duration listeners, sunrise/sunset triggers,
rich entity classes), consider whether you can rebuild them with predicates/scheduler hooks today or
whether they need to stay on your migration backlog.


:sub:`Generated by ChatGPT, will review prior to PR.`
