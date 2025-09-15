Scheduler
=========

Run jobs on intervals or cron schedules.

Examples
--------
.. code-block:: python

   self.scheduler.run_cron(self.morning_routine, hour=6)
   self.scheduler.run_every(self.poll, interval=30)
