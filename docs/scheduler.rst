Scheduler
=========

The scheduler lets your app run work in the future without spinning up your own background tasks.

Async jobs are executed on Hassette's asyncio loop and receive the same ``self`` context as any other
method on your app, which makes it easy to share state or call the Home Assistant API. Sync jobs are
wrapped with ``make_async_adapter`` so they run without blocking the loop.

Under the hood the scheduler uses the `whenever <https://github.com/ariebovenberg/whenever>`_ time primitives, so
you should prefer :class:`whenever.SystemDateTime` and :class:`whenever.TimeDelta` whenever you need
absolute or relative times. Plain floats are still accepted for convenience; they are treated as
seconds and converted into ``TimeDelta`` instances internally. Cron schedules use `croniter
<https://github.com/pallets-eco/croniter>`_.


.. code-block:: python

   from datetime import datetime, timezone

   async def refresh_sensors(self) -> None:
       await self.api.call_service("sensor", "refresh")

   def log_heartbeat(self) -> None:
       self.log.info("Still alive at %s", datetime.now(timezone.utc))

   def setup(self) -> None:
       self.scheduler.run_every(self.refresh_sensors, interval=300)
       self.scheduler.run_in(self.log_heartbeat, delay=30)

Scheduling helpers
------------------
Each helper returns a :class:`hassette.core.scheduler.scheduler.ScheduledJob` you can keep to inspect
``next_run`` or cancel it later.

``run_once(func, run_at, name="")``
    Execute exactly once at a specific :class:`whenever.SystemDateTime`.

``run_in(func, delay, name="", start=None)``
    Fire once after ``delay`` seconds. ``delay`` can be a ``float``/``int`` (interpreted as seconds)
    or a :class:`whenever.TimeDelta`. Optionally provide ``start`` (a ``SystemDateTime``) if you want
    to delay commencement until a particular instant.

``run_every(func, interval, name="", start=None)``
    Repeat forever with a fixed interval. ``interval`` may be a ``float``/``int`` representing
    seconds, but using ``TimeDelta`` keeps your intent explicit. ``start`` (``SystemDateTime``)
    lets you align the first run sometime in the future.

``run_cron(func, ..., name="", start=None)``
    6-field cron syntax (seconds, minutes, hours, day-of-month, month, day-of-week). You can mix
    integers and expressions like ``"*/15"``. Provide ``start`` (``SystemDateTime``) to delay
    commencement until a particular instant.

Worked examples
---------------
The snippet below demonstrates mixed synchronous/async jobs and custom start times.

.. code-block:: python

   from whenever import TimeDelta
   from hassette.core.scheduler.triggers import now

   class MorningRoutine(App):
       async def on_start(self) -> None:
           # Run every weekday at 07:15.
           self.scheduler.run_cron(
               self.prepare_coffee,
               minute=15,
               hour=7,
               day_of_week="mon-fri",
               name="brew",
           )

           # Poll a sensor every 2 minutes starting 10 seconds from now.
           self.scheduler.run_every(
               self.refresh_sensors,
               interval=TimeDelta(minutes=2),
               start=now().add(seconds=10),
               name="sensor-poll",
           )

           # Fire a one-off reminder in 45 seconds.
           self.scheduler.run_in(self._log_reminder, delay=45, name="reminder")

       async def prepare_coffee(self) -> None:
           await self.api.call_service("switch", "turn_on", {"entity_id": "switch.espresso"})

       async def refresh_sensors(self) -> None:
           await self.api.call_service("sensor", "refresh")

       def _log_reminder(self) -> None:
           self.log.info("Stretch your legs!", extra={"job": "reminder"})

Managing jobs
-------------
You can keep the ``ScheduledJob`` returned from any helper to manage its lifecycle.

.. code-block:: python

   job = self.scheduler.run_every(self.refresh_sensors, interval=60, name="poll")
   self.log.debug("Next run at %s", job.next_run)

   # Later during teardown or when conditions change
   job.cancel()

Cancelling sets ``job.cancelled`` and the scheduler will skip future executions. For repeating jobs
``job.next_run`` updates automatically after every run so you can monitor drift or display upcoming
runs in your UI.

Cron tips
---------
Cron schedules use the Whenever parser with second-level precision. Some quick reminders:

* Use strings for expressions such as ``"*/10"`` or ``"mon-fri"``.
* ``day_of_week`` accepts both numbers (0=Monday) and aliases (``"sun"``).
* Provide ``start`` if you need to delay activation - for example to avoid running until Home
  Assistant has finished booting.

Best practices
--------------
* Name your jobs when you have multiples; the scheduler propagates the name into logs and reprs.
* Prefer async callables for I/O heavy work. Reserve synchronous jobs for fast operations.
