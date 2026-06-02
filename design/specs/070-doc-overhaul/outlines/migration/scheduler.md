# Migration — Scheduler

**Page type:** Migration (feature comparison)
**Reader's job:** Convert their AppDaemon scheduler calls (`run_in`, `run_daily`, `run_every`) to Hassette equivalents with correct syntax and parameters.
**Voice mode:** Comparison — "you" allowed

## What was cut (and where it goes)

- **Overview section** replaced by a one-sentence intro. The method table is the overview.
- **Side-by-Side Comparison** section removed. It duplicated the Migration Example with no additional value.
- **Callback Signatures** moved after the method table. The reader's first question is "what's the equivalent method?" not "how do callback signatures differ?" Signatures matter once they've found the right method.

## Outline

### H2: Method Equivalents
Lead with the lookup table. The reader has a specific AppDaemon call and wants the Hassette version. Table: AppDaemon method | Hassette method | Notes. Include `run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `cancel_timer`. Note Hassette-only additions: `run_cron`, `schedule()` with trigger objects.

Admonition: `run_daily` is now wall-clock-aligned (cron-backed, DST-safe). This is the most common behavioral surprise.

### H2: Callback Signatures
AppDaemon's `def my_callback(self, **kwargs)` with `kwargs` dict vs Hassette's flexible signatures. Scheduler automatically runs sync callables in a thread pool. Snippet showing a Hassette scheduled handler.

### H2: Migration Example
Complete before/after: an app with `run_in`, `run_daily`, `run_every` in AppDaemon converted to Hassette. Side-by-side tabs. Key changes bullet list after the example.

### H2: Blocking Work
AppDaemon runs callbacks in threads, so blocking is safe. Hassette: sync callables run in a thread pool automatically. Async callbacks run in the event loop — use `asyncio.to_thread()` or `self.task_bucket.run_in_thread()` for blocking IO inside async handlers. `AppSync` is for apps with heavy sync lifecycle logic, not for individual scheduler callbacks.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `scheduler_appdaemon.py` | Keep | AppDaemon scheduler example |
| `scheduler_hassette.py` | Keep | Hassette scheduler example |
| `scheduler_migration.py` | Keep | Full migration before/after |

## Cross-Links

- **Links to:** Scheduler overview, Scheduler/Methods, Job Management
- **Linked from:** Migration overview, Migration checklist
