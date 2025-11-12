# Scheduler

Schedule any callable—async or sync—to run at specific times or intervals using the built-in scheduler. Jobs always execute on Hassette’s event loop (sync callables are offloaded automatically). There’s no required signature; pass parameters through the `args` and `kwargs` arguments on each helper.

`self.scheduler` is created when your app instantiates. Helpers return a `ScheduledJob` you can inspect or cancel later.

!!! note
    Cron support uses `croniter` under the hood; interval helpers rely on `whenever`. Everything schedules via `whenever`’s `ZonedDateTime`, which will eventually be replaced with something more DST-friendly.

While helper signatures differ, they all share these optional parameters:

- **start** – first-run timing:
  - `int | float` → delay in seconds.
  - `ZonedDateTime` → exact timestamp.
  - `TimeDelta` → added to current time.
  - `tuple[int, int]` → `(hour, minute)` offset from now.
  - `Time`/`time` → time-of-day offset.
  - `None` → run immediately, then follow the interval/cron.
- **name** – label that shows up in logs/reprs.
- **args** – positional arguments passed to your callable.
- **kwargs** – dictionary of keyword arguments for your callable.

!!! note
    `kwargs` is passed as a single dictionary argument; helper methods don’t accept real `**kwargs` to avoid ambiguity with their own keyword parameters.

```python
--8<-- "pages/core-concepts/scheduler/basic_example.py"
```

## Scheduling helpers

Each helper returns a `hassette.scheduler.classes.ScheduledJob` (aliased `ScheduledJob` in the examples). Keep the handle if you need to inspect or cancel the job later.

- `run_once` – run one time after an optional delay.
- `run_in` – run one time after `delay` seconds/`TimeDelta`.
- `run_every` – run repeatedly at a fixed interval.
- `run_minutely` – run every _n_ minutes.
- `run_hourly` – run every _n_ hours (use `start` for minute offsets).
- `run_daily` – run every _n_ days at a specific time.
- `run_cron` – run on a cron schedule (`second`, `minute`, `hour`, `day_of_month`, `month`, `day_of_week`).

## Worked examples

Mixed async/sync jobs and custom start times:

```python
--8<-- "pages/core-concepts/scheduler/worked_examples.py"
```

## Managing jobs

Hold onto the returned `ScheduledJob` to manage lifecycle:

```python
--8<-- "pages/core-concepts/scheduler/managing_jobs_example.py"
```

Calling `job.cancel()` marks it cancelled and removes it from the scheduler. For repeating jobs, `job.next_run` updates after every run so you can monitor drift or show upcoming runs in a UI.

## Best practices

- Name your jobs when multiple instances exist; names flow into logs and reprs.
- Prefer async callables for I/O heavy work and reserve sync callables for quick tasks.

## See also

- [Core concepts](../index.md)
- [Apps](../apps/index.md)
- [Bus](../bus/index.md)
- [API](../api/index.md)
- [Configuration](../configuration/index.md)
