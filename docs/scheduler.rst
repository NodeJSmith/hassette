Scheduler
=========

Run jobs on intervals or cron schedules.

Main methods
------------
- ``run_once(func, run_at, name="")``: Run once at a specific time.
- ``run_in(func, delay, name="", start=None)``: Run once after a delay.
- ``run_every(func, interval, name="", start=None)``: Run repeatedly at a fixed interval.
- ``run_cron(func, second=0, minute=0, hour=0, day_of_month="*", month="*", day_of_week="*", name="", start=None)``: Cron-like schedule (6 fields with seconds).

Examples
--------
.. code-block:: python

   # Every 30s starting now
   self.job_poll = self.scheduler.run_every(self.poll, interval=30)

   # Run once in 5 minutes
   self.scheduler.run_in(self.send_reminder, delay=300)

   # Daily at 06:00
   self.scheduler.run_cron(self.morning_routine, hour=6)

Canceling jobs
--------------
Keep the returned ``ScheduledJob`` and call ``cancel()``.

.. code-block:: python

   job = self.scheduler.run_every(self.poll, interval=60)
   # later
   job.cancel()
