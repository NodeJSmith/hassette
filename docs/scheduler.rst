Scheduler
=========

You can schedule any method or function, async or sync, to run at specific times or intervals using the built-in scheduler. The
scheduler will ensure your callable runs asynchronously in Hassette's event loop, even if it's a synchronous function. There is
no required signature for scheduled callables; you can provide parameters using the ``args`` and ``kwargs`` arguments to the scheduling helpers.

The scheduler is created at app instantiation and is available as ``self.scheduler``. There are multiple helper methods to schedule jobs, described below.
These return a ``ScheduledJob`` instance you can keep to inspect or manage the job later. To cancel a job, call its ``cancel()`` method.

.. note::

    The cron helper uses ``croniter`` under the hood, so you can use any cron syntax it supports for the parameters. This will likely be updated in the future
    to expose more ``croniter`` features. The interval helpers use ``whenever`` under the hood. All scheduling is done using ``whenever``s ``SystemDateTime``.
    This will likely need to be updated in the future to something that won't break during DST transitions, but I hadn't thought of that yet when implementing this.


While schedule helpers will have different signatures, all will take the following optional parameters:

 - ``start`` - Provide details for when to first call the job.

    - If an ``int`` or ``float``, this is a delay in seconds from now.
    - If a ``SystemDateTime``, this is the exact time to run.
    - If a ``TimeDelta``, this is added to the current time to get the first run time.
    - If ``tuple[int, int]``, this is treated as ``(hour, minute)`` and added to the current time to get the first run time.
    - If ``Time`` (from ``whenever``) or ``time`` (from stdlib), the hours and minutes are added to the current time to get the first run time.
    - If ``None`` (the default), the job is scheduled to run immediately and then according to its interval or cron schedule.

 - ``name`` - A name for the job, useful for logging and debugging.
 - ``args`` - Positional arguments to pass to your callable, keyword-only.
 - ``kwargs`` - Keyword arguments to pass to your callable, keyword-only.


.. note::

    The ``kwargs`` parameter is a single parameter that expects a dictionary. The helper methods do not accept variable keyword arguments (e.g. ``**kwargs``),
    to avoid ambiguity with other parameters.


.. code-block:: python

   from datetime import datetime, timezone

   async def refresh_sensors(self) -> None:
       await self.api.call_service("sensor", "refresh")

   def log_heartbeat(self) -> None:
       self.logger.info("Still alive at %s", datetime.now(timezone.utc))

   def setup(self) -> None:
       self.scheduler.run_every(self.refresh_sensors, interval=300)
       self.scheduler.run_in(self.log_heartbeat, delay=30)

Scheduling helpers
------------------
Each helper returns a :class:`~hassette.core.resources.scheduler.classes.ScheduledJob` you can keep to inspect
``next_run`` or cancel it later.

Helper methods include the following:
 - ``run_once``: Run once after a delay, does not accept any additional schedule parameters.
 - ``run_at``: Run once at a specific time - alias for ``run_once``.
 - ``run_in``: Run once after a delay, accepts ``delay`` (``TimeDelta`` or seconds).
 - ``run_every``: Run repeatedly at a fixed interval, accepts ``interval`` (``TimeDelta`` or seconds).
 - ``run_minutely``: Run repeatedly every N minutes, accepts ``minutes`` (int).
 - ``run_hourly``: Run repeatedly every N hours, accepts ``hours`` (int), use ``start`` to set minute offset.
 - ``run_daily``: Run repeatedly every N days at a specific time, accepts ``days`` (int), use ``start`` to set hour/minute offset.
 - ``run_cron``: Run repeatedly on a cron schedule.

  - Accepts any of the following cron parameters: ``second``, ``minute``, ``hour``, ``day_of_month``, ``month``, ``day_of_week``.

Detailed documentation for these can be found at :doc:`reference/core/scheduler`.


Worked examples
---------------
The snippet below demonstrates mixed synchronous/async jobs and custom start times.

.. code-block:: python

   from whenever import TimeDelta
   from hassette.utils.date_utils import now

   class MorningRoutine(App):
       async def on_initialize(self) -> None:
           # Run every weekday at 07:15.
           self.scheduler.run_cron(self.prepare_coffee, minute=15, hour=7, day_of_week="mon-fri", name="brew")

           # Poll a sensor every 2 minutes starting 10 seconds from now.
           self.scheduler.run_every(self.refresh_sensors, interval=120, start=10, name="sensor-poll")

           # Fire a one-off reminder in 45 seconds.
           self.scheduler.run_in(self._log_reminder, delay=45, name="reminder")

       async def prepare_coffee(self) -> None:
           await self.api.call_service("switch", "turn_on", {"entity_id": "switch.espresso"})

       async def refresh_sensors(self) -> None:
           await self.api.call_service("sensor", "refresh")

       def _log_reminder(self) -> None:
           self.logger.info("Stretch your legs!", extra={"job": "reminder"})

Managing jobs
-------------
You can keep the ``ScheduledJob`` returned from any helper to manage its lifecycle.

.. code-block:: python

   job = self.scheduler.run_every(self.refresh_sensors, interval=60, name="poll")
   self.logger.debug("Next run at %s", job.next_run)

   # Later during teardown or when conditions change
   job.cancel()

Cancelling sets ``job.cancelled`` and the scheduler will skip future executions. For repeating jobs
``job.next_run`` updates automatically after every run so you can monitor drift or display upcoming
runs in your UI.


Best practices
--------------
* Name your jobs when you have multiples; the scheduler propagates the name into logs and reprs.
* Prefer async callables for I/O heavy work. Reserve synchronous jobs for fast operations.
