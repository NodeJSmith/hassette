Pyscript vs Hassette
====================

This guide targets Pyscript users who want to understand where Hassette matches the familiar
workflow, where it differs, and what the migration effort looks like. It focuses on the core moving
parts: triggers and the event bus, the scheduler, Home Assistant API access, and app configuration.

Quick reference table
---------------------

.. list-table:: Snapshot of common tasks
   :header-rows: 1
   :widths: 20 40 40

   * - Action
     - Pyscript
     - Hassette
   * - Listen for an entity turning on
     - ``@state_trigger("binary_sensor.door == 'on'")``
     - ``self.bus.on_entity("binary_sensor.door", handler=self.on_open, changed_to="on")``
   * - React to an attribute threshold
     - ``@state_trigger("sensor.phone.battery < 20")``
     - ``self.bus.on_attribute("sensor.phone", "battery", handler=self.on_battery, where=lambda e: (e.payload.data.new_value or 100) < 20)``
   * - Monitor service calls
     - ``@event_trigger("call_service", "domain == 'light'")``
     - ``self.bus.on_call_service(domain="light", handler=self.on_service)``
   * - Schedule something in 60 seconds
     - ``@time_trigger("once(now + 60s)")``
     - ``self.scheduler.run_in(self.turn_off, delay=60)``
   * - Run every morning at 07:30
     - ``@time_trigger("cron(30 7 * * *)")``
     - ``self.scheduler.run_cron(self.morning, minute=30, hour=7)``
   * - Debounce noisy updates
     - ``@state_trigger("sensor.motion == 'on'", state_hold=2)``
     - ``self.bus.on_entity("sensor.motion", handler=self.on_motion, debounce=2.0)``
   * - Call a Home Assistant service
     - ``light.turn_on(entity_id="light.kitchen", brightness=200)``
     - ``await self.api.call_service("light", "turn_on", target={"entity_id": "light.kitchen"}, brightness_pct=80)``
   * - Access automation configuration
     - ``pyscript.app_config["entity"]``
     - ``self.app_config.entity``
   * - Stop a listener or timer
     - ``task.cancel(task_id)``
     - ``subscription.unsubscribe()`` / ``job.cancel()``

App model and configuration
---------------------------

Pyscript
    Scripts live under ``<config>/pyscript`` and load automatically. Reusable packages live in
    ``pyscript/apps`` and are activated with YAML entries under ``pyscript.apps.<name>`` (see
    ``docs/reference.rst``). Configuration stays untyped: ``pyscript.app_config`` and
    ``pyscript.config`` expose plain ``dict`` objects, so validation and secrets are manual. Triggers
    register at import time via decorators, there is no lifecycle method, and both async coroutines and
    sync helpers can run as long as they yield to the event loop. File or config changes reload the
    module; long-running tasks continue unless you cancel them with ``task.unique`` or ``task.cancel``.

Hassette
    Apps inherit from :class:`hassette.App[MyConfig]` (async) or :class:`hassette.AppSync` (sync
    bridge). ``initialize`` is ``async`` and should call ``await super().initialize()`` after custom
    setup. Configuration lives in ``hassette.toml`` under ``[apps.*]`` tables. Each app ships with an
    :class:`hassette.AppConfig` subclass so Hassette validates input before instantiating the app, and
    you access ``self.app_config`` with IDE/autocomplete support. Environment variables wire in via
    Pydantic. Multiple instances use TOML list-of-tables while keeping strong typing, and lifecycle
    hooks (``initialize``, ``shutdown``) emit bus events for health monitoring.

.. rubric:: Where Hassette shines

- Strongly typed configuration models improve IDE support and reduce runtime surprises.
- Multiple app instances stay clear in ``hassette.toml`` because they share table names and validation.
- Lifecycle hooks make it easy to observe startup and shutdown status from tooling.

.. rubric:: Where Hassette lags today

- No module auto-reload -- redeploying requires restarting the Hassette process.
- Secrets must be surfaced through Pydantic models instead of implicit YAML access.
- Cross-app configuration access is deliberate; you must declare dependencies explicitly.

Event bus and callbacks
-----------------------

Pyscript
    Decorators bind triggers directly to functions. ``@state_trigger`` watches expressions against Home
    Assistant state, and options like ``state_hold``/``state_hold_false`` implement debouncing and edge
    semantics. ``@event_trigger`` targets Home Assistant events (including ``call_service``) with
    optional boolean expressions. ``@time_active`` and ``@state_active`` act as guards, while
    ``@mqtt_trigger`` handles MQTT topics. Each trigger run spawns a task and passes keyword arguments
    such as ``trigger_type`` and ``value``. There is no central bus API or subscription object; the
    decorator is the binding.

Hassette
    ``self.bus`` centralises subscriptions and returns ``Subscription`` handles. Handlers receive a
    single typed event dataclass (e.g., ``StateChangeEvent[states.LightState]``) and can compose
    predicates (``ChangedTo``, ``AttrChanged``, ``AnyOf``) alongside ``debounce`` and ``throttle``
    modifiers. Custom topics (``"hassette.event.my_event"``) use ``bus.on(...)``, and
    ``unsubscribe()`` removes the listener. Because handlers run inside the app instance they can share
    state, reuse the scheduler, and call the API without extra globals.

.. rubric:: Where Hassette shines

- Typed payloads and single-argument signatures simplify refactors versus unpacking ``**data``.
- Predicate composition mirrors Pyscript decorators while keeping logic in regular Python.
- Subscriptions can be stored and removed dynamically without reloading modules.

.. rubric:: Where Hassette lags today

- No built-in ``state_hold`` equivalent -- pair ``debounce`` with scheduler logic for edge cases.
- No decorator sugar -- subscriptions are manual calls inside ``initialize``.
- MQTT helpers require custom event parsing today.

Scheduler differences
---------------------

Pyscript
    ``@time_trigger`` covers cron, once-off, startup/shutdown, and periodic schedules directly on
    functions, including sunrise/sunset offsets via ``sunrise``/``sunset`` keywords. ``@time_active``
    limits execution windows and doubles as a rate limiter through ``hold_off``. For ad-hoc waits you
    ``await task.sleep`` or ``task.wait_until`` inside the running coroutine. There is no persistent job
    handle; control comes from ``task.unique`` (kill previous runs) or ``task.cancel`` (with a task id).

Hassette
    The scheduler exposes ``run_in``, ``run_every``, ``run_once``, and ``run_cron``. Each returns a
    ``ScheduledJob`` with ``next_run`` metadata and ``cancel()``. Helpers accept async/sync callables and
    rely on ``whenever`` time primitives, so you can pass ``TimeDelta`` or ``SystemDateTime`` objects.
    There are no first-class sunrise/sunset helpers yet, but cron covers many needs. Rate limiting lives
    on the bus via ``debounce``/``throttle`` or in code via scheduler jobs.

.. rubric:: Where Hassette shines

- Job handles make cancellation and inspection straightforward compared to tracking task ids.
- Consistent async execution -- no risk of blocking the event loop with a forgotten synchronous decorator.
- Cron helpers expose seconds and integrate with naming/logging for easier debugging.

.. rubric:: Where Hassette lags today

- Missing sunrise/sunset convenience built-ins you get from ``@time_trigger``.
- No decorator syntax; scheduling happens inside ``initialize``.
- Callbacks do not receive automatic keyword arguments -- use closures or partials for context.

Home Assistant API surface
--------------------------

Pyscript
    Services behave like Python functions (``light.turn_on(...)``) and state reads assign to variables
    (``binary_sensor.door``). Helper namespaces (``state.get``, ``service.call``, ``event.fire``) support
    dynamic usage. Everything is stringly typed; conversions are manual, and invalid payloads fail at
    runtime. You can expose new services with ``@service`` (including YAML docstrings) and bridge to
    blocking code using ``@pyscript_executor`` or ``task.executor``. Returning data from services is
    possible when ``supports_response`` is set.

Hassette
    ``self.api`` wraps REST/WebSocket calls with Pydantic models. ``get_state``/``get_states`` convert to
    ``states.*`` classes, ``get_entity`` begins a roadmap toward entity helpers, and ``call_service``
    optionally returns ``HassContext``. Typed vs raw methods coexist (``get_state_raw``). Custom
    endpoints remain reachable via ``rest_request``/``ws_send_and_wait``. There is no decorator-based
    service registration yet; exposing functions requires listening for custom events or building a
    dedicated app.

.. rubric:: Where Hassette shines

- Strong typing on reads reduces the "value vs attributes" ambiguity common in Pyscript scripts.
- Unified async session includes retries/backoff; no need to manage blocking calls.
- Error handling uses Hassette exceptions (``EntityNotFoundError`` etc.) instead of plain ``NameError``.

.. rubric:: Where Hassette lags today

- Service helpers remain untyped, whereas Pyscript's direct binding feels concise.
- No first-class story for user-defined services yet.
- States are not auto-exported as attributes; fetch them explicitly.

Migration checklist
-------------------

- Move module-level scripts into ``App`` subclasses; convert trigger decorators into bus subscriptions
  and scheduler calls during ``initialize``.
- Replace ``pyscript.app_config`` dict usage with a Pydantic ``AppConfig``. Use environment variables
  or TOML defaults instead of reading arbitrary YAML from other apps.
- Turn ``@service`` functions into dedicated apps that listen for custom events or leverage forthcoming
  Hassette service registration APIs; in the interim, consider exposing functions via Home Assistant
  scripts/services that Hassette can call.
- Rewrite direct state references (``binary_sensor.door``) to ``await self.api.get_state_value(...)``
  or subscribe via the bus to maintain live updates.
- For decorator conveniences like ``state_hold`` or ``@time_active``, combine Hassette predicates,
  scheduler jobs, and app-level logic (for example, maintain a timestamp to enforce hold-off windows).

If you rely on Pyscript features that Hassette lacks (Jupyter kernel integration, decorator sugar,
inline YAML service docs), please open an issue to discuss your use case and help prioritise the
roadmap.

---------------

:sub:`Disclaimer: The above is accurate to the best of my knowledge, please open an issue if you spot anything wrong or missing!`
