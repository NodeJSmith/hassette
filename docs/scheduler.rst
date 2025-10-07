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
Each helper returns a :class:`~hassette.core.resources.scheduler.classes.ScheduledJob` you can keep to inspect
``next_run`` or cancel it later.

All helpers accept keyword-only parameters ``args`` and ``kwargs`` that are forwarded to your callable when it runs.

.. currentmodule:: hassette.core.resources.scheduler

.. automethod:: Scheduler.run_once

.. automethod:: Scheduler.run_in

.. automethod:: Scheduler.run_every

.. automethod:: Scheduler.run_cron

Worked examples
---------------
The snippet below demonstrates mixed synchronous/async jobs and custom start times.

.. code-block:: python

   from whenever import TimeDelta
   from hassette.utils.date_utils import now

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


Best practices
--------------
* Name your jobs when you have multiples; the scheduler propagates the name into logs and reprs.
* Prefer async callables for I/O heavy work. Reserve synchronous jobs for fast operations.
