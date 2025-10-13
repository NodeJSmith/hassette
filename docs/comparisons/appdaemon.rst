AppDaemon vs Hassette
=====================

AppDaemon
==========

AppDaemon is a long-running Python process that connects to Home Assistant via WebSocket and REST API.
You develop apps by writing Python classes that subclass ``hass.Hass`` and saving them in a configured directory.
Configuration lives in ``apps.yaml`` and ``appdaemon.yaml``. AppDaemon apps are generally written in an IDE (e.g., VSCode)
which enables linting and autocompletion as well as debugging and stepping through code.

Key Points
-----------

- AppDaemon runs apps in separate threads, so you can write synchronous code without worrying about blocking the main event loop.
- The scheduler offers a variety of helpers for delayed and recurring tasks.
- The event bus exposes entity state changes, service calls, and custom events.
- The Home Assistant API is synchronous and returns raw strings or dicts.
- All access to these features is via methods on ``self`` (the app instance).

Hassette
==========

Hassette offers similar features but with a different design philosophy. It is async-first, strongly typed, and
built around composition instead of inheritance. Hassette also connects to Home Assistant via WebSocket and REST API,
you write apps as Python classes that inherit from :py:class:`~hassette.core.resources.app.app.App`, and configuration lives in ``hassette.toml``.
Hassette apps are also written in an IDE, offering the same debugging benefits, but is also strongly typed, which enables better autocompletion
and earlier error detection.

Hassette Key Points
--------------------

- Hassette apps run in the main event loop, so you write async code. A synchronous bridge class is available for simpler use cases.
- The scheduler offers similar helpers but uses a consistent API and returns rich job objects.
- The event bus uses typed events and composable predicates for filtering.
- The Home Assistant API is async and uses Pydantic models for responses.
- Features are accessed via composition: ``self.bus``, ``self.scheduler``, and ``self.api``.

Quick reference table
---------------------

.. list-table:: Snapshot of common tasks
   :header-rows: 1
   :widths: 20 40 40

   * - Action
     - AppDaemon
     - Hassette
   * - Listen for an entity state change
     - ``self.listen_state(self.on_open, "binary_sensor.door", new="on")``
     - ``self.bus.on_entity("binary_sensor.door", handler=self.on_open, changed_to="on")``
   * - React to an attribute threshold
     - ``self.listen_state(self.on_battery, "sensor.phone", attribute="battery", below=20)``
     - ``self.bus.on_attribute("sensor.phone", "battery", handler=self.on_battery, where=lambda e: (e.payload.data.new_value or 100) < 20)``
   * - Monitor service calls
     - ``self.listen_event(self.on_service, "call_service", domain="light")``
     - ``self.bus.on_call_service(domain="light", handler=self.on_service)``
   * - Schedule something in 60 seconds
     - ``self.run_in(self.turn_off, 60)``
     - ``self.scheduler.run_in(self.turn_off, delay=60)``
   * - Run every morning at 07:30
     - ``self.run_daily(self.morning, time(7, 30, 0))``
     - ``self.scheduler.run_daily(self.morning, start=time(7, 30))``
   * - Call a Home Assistant service
     - ``self.call_service("light/turn_on", entity_id="light.kitchen", brightness=200)``
     - ``await self.api.call_service("light", "turn_on", target={"entity_id": "light.kitchen"}, brightness_pct=80)``
   * - Access app configuration
     - ``self.args["entity"]``
     - ``self.app_config.entity``
   * - Stop a listener
     - ``self.cancel_listen_state(handle)``
     - ``subscription.cancel()``
   * - Stop a scheduled job
     - ``self.cancel_timer(handle)``
     - ``job.cancel()``

App model and configuration
---------------------------

AppDaemon
    - Apps subclass ``hass.Hass`` and implement ``initialize`` (synchronous).
    - Configuration is loaded from ``apps.yaml`` with one section per app instance.
    - App configuration arrives as an untyped ``dict`` on ``self.args``; validation is manual.
    - Reusing an app means adding another section in ``apps.yaml`` that points to the same module/class but tweaks arguments.

Hassette
    - Apps subclass :class:`hassette.core.resources.app.app.App` (async) or :class:`hassette.core.resources.app.app.AppSync` (sync bridge).
    - ``initialize`` is ``async`` and should call ``await super().initialize()`` after custom initialization. Configuration lives in ``hassette.toml`` under ``[apps.*]`` tables.
    - Each app ships with a :class:`hassette.core.resources.app.app_config.AppConfig` subclass, so Hassette validates input before instantiating the app and you access ``self.app_config`` with IDE/autocomplete support.
    - Environment variables (via Pydantic) are first-class. Multiple instances use TOML list-of-tables, which still map to strongly typed models.

.. rubric:: Where Hassette shines

- Strongly typed configuration models improve IDE support and reduce runtime errors.
- Multiple app instances are clearer in ``hassette.toml`` since they share the same table name.
- Async-first lifecycle keeps all automation logic in the main coroutine context.

Event bus and callbacks
-----------------------

AppDaemon
    - ``listen_state`` (plus variants like ``listen_event`` and ``listen_event("call_service")``) call your handler with several positional arguments (``callback(self, entity, attribute, old, new, kwargs)``).
    - Convenience keyword arguments include ``attribute``, ``new``, ``old``, ``duration`` (wait for stable state), ``immediate`` (fire once right away), namespaces, and ``timeout``.
    - You cancel by passing the handle to ``cancel_listen_state``.
    - Filtering by multiple conditions typically involves several keyword arguments or manual logic in the callback.

Hassette
    - All subscriptions emit a typed event dataclass as a single argument.
    - ``self.bus.on_entity`` and ``self.bus.on_attribute`` wrap Home Assistant's ``state_changed`` topic.
    - ``self.bus.on_call_service`` exposes service traffic.
    - ``self.bus.on`` lets you subscribe to any topic (including custom events via ``"hassette.event.my_event"``).
    - Predicates provide composable guards (e.g., ``P.ChangedTo("on")`` & ``P.AnyOf``).
    - ``debounce`` and ``throttle`` parameters remove boilerplate that AppDaemon typically handles via extra state variables.
    - Subscription objects expose ``unsubscribe()`` for cleanup.

.. rubric:: Where Hassette shines

- Typed payloads with exact models (``StateChangeEvent[LightState]``) instead of raw dicts.
- Predicate composition beats nested ``if`` trees and can guard on attributes without extra callbacks.

.. rubric:: Where Hassette lags today

- No built-in equivalent for ``duration``, ``timeout``, or ``immediate`` (on the roadmap).


Scheduler differences
---------------------

AppDaemon
    - Offers a large toolbox — ``run_in``, ``run_once``, ``run_every``, ``run_daily``, ``run_hourly``, ``run_minutely``, ``run_at``, ``run_at_sunrise/sunset``, and cron support.
    - Timers return handles you pass to ``cancel_timer``.
    - Scheduler helpers can pass ``kwargs`` back into the callback so the same function can serve multiple timers.
    - ``info_timer`` exists to inspect the next run time, but it requires an extra API call.

Hassette
    - Similar level of coverage: ``run_in``, ``run_every``, ``run_once``, ``run_minutely``, ``run_hourly``, ``run_daily``, ``run_at``, and ``run_cron``.
    - Can pass ``args`` and ``kwargs`` to the job.
    - All helpers accept async or sync callables and return a ``ScheduledJob`` object with ``next_run`` metadata and ``cancel()``.
    - Triggers use the ``whenever`` library, so start times are always unambiguous ``SystemDateTime`` instances, although helper methods take multiple input types for convenience.

.. rubric:: Where Hassette shines

- Async jobs run on the main loop—no background threads required.
- Cron has second-level precision and shares a consistent API for async/sync functions.
- ``ScheduledJob`` exposes ``next_run`` without extra API calls.

.. note::

    At this time there is no plan to surface a sunrise/sunset helper. You can use Home Assistant's
    ``sun.sun`` entity with an attribute trigger or cron schedule instead.

Home Assistant API surface
--------------------------

AppDaemon
    - ``get_state``/``set_state``/``call_service``/``fire_event``/``listen_event`` return raw strings or dicts.
    - There is no typing or schema validation, so runtime errors emerge only when Home Assistant rejects a payload.
    - Calls to ``get_state`` access state stored in AppDaemon's internal state tracker and run synchronously.
    - Domain and entity are often provided as a single string separated by a ``/`` (e.g., ``light/turn_on``).
    - Helper functions like ``anyone_home`` or ``notify`` are included.

Hassette
    - ``self.api`` is async from top to bottom.
    - ``get_state`` and ``get_states`` coerce responses into Pydantic models (``states.LightState`` etc.)
        -  ``get_state_raw`` mirrors AppDaemon's dict return.
    - ``get_entity`` begins a push toward entity classes, though today only ``BaseEntity`` and ``LightEntity`` ship.
    - ``turn_on`` and ``turn_off`` now return ``None``. ``call_service`` returns a ``ServiceResponse`` when ``return_response=True``.
    - Low-level ``rest_request`` and ``ws_send_and_wait`` expose the underlying ``aiohttp`` session if you need endpoints Hassette has not wrapped yet.
    - For synchronous apps, ``self.api.sync`` mirrors the async API.

.. note::

    See :ref:`the note on the API page <entity-state-note>` for terminology differences regarding
    states and entities.

.. rubric:: Where Hassette shines

- Strong typing on read operations: IDEs surface attributes, and Pydantic validates conversions.
- Explicit separation between entities, states, state values, and attributes.
- Simple API surface: no deep class hierarchies or plugin layers to trace through.

.. rubric:: Where Hassette lags today

- Service calls are not fully typed yet; you still pass ``**data`` manually.
- Entity helper classes are nascent (only lights today), so you may need to keep using plain service calls.
- Currently no built-in helpers like ``notify`` or ``area_devices`` (on the roadmap).


Migration checklist
-------------------

- Update class definitions to inherit from ``App[MyConfig]`` (or ``AppSync``) and adjust ``initialize``
  to be ``async``. Call the ``super()`` lifecycle methods.
- Replace ``self.args`` access with the typed ``self.app_config`` attribute. Validate secrets via environment
  variables or ``SettingsConfigDict``.
- Convert listeners to accept a single event argument.
- Leverage predicates (``ChangedTo``/``AttrChanged``) instead of keyword filters.
- Swap scheduler helpers to ``self.scheduler.*``, use ``run_cron`` instead of ``run_daily``/``run_hourly``, and
  consider ``TimeDelta``/``SystemDateTime`` for intervals and start times.
- Use ``subscription.unsubscribe()`` and ``job.cancel()`` instead of ``self.cancel_listen_state`` and ``self.cancel_timer``.
- Change ``self.call_service("domain/service", ...)`` to ``await self.api.call_service("domain", "service", ...)``.
- Replace synchronous API calls with ``await self.api...`` variants; use ``self.api.sync`` only inside
  ``AppSync`` code paths.

If you rely on AppDaemon features that Hassette lacks (timeout/duration/immediate, specific helpers), please open an issue
to discuss your use case and help prioritize the roadmap.

---------------

:sub:`Disclaimer: The above is accurate to the best of my knowledge, please open an issue if you spot anything wrong or missing!`
