---
topic: "scheduler API design and ergonomics in Python async frameworks and home automation / IoT systems"
date: 2026-04-14
status: Draft
---

# Prior Art: Scheduler API Design and Ergonomics

## The Problem

Scheduler APIs in automation frameworks must balance two competing concerns: ergonomics for the common case (fire this callback every hour) and expressiveness for the complex case (fire at civil twilight, unless the house is already lit, with a 90-second random offset). Get the ergonomics wrong and the API becomes verbose boilerplate; get the expressiveness wrong and users hit walls and work around the scheduler entirely.

In async Python specifically, scheduling adds a second axis of complexity: cancellation semantics, drift prevention, error isolation for job failures, and misfire handling across restarts. These are often underdesigned because they only matter at failure boundaries — which is exactly when users need them most.

## How We Do It Today

Hassette exposes a fluent method API on the `Scheduler` resource: `run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `run_cron`. Each returns a `ScheduledJob` object with a `.cancel()` method. Internally, jobs use `IntervalTrigger` and `CronTrigger` implementing `TriggerProtocol` (`first_run_time`, `next_run_time`). The `IntervalTrigger._advance_past()` correctly prevents drift by snapping to an anchored interval rather than adding to last-run time. Jobs are persisted to SQLite and reconciled after restart. There is no misfire grace time, no coalescing policy configuration, no jitter support, and no solar trigger support.

## Patterns Found

### Pattern 1: Fluent Convenience Method API

**Used by**: AppDaemon, Hassette (current), Home Assistant Python scripts

**How it works**: The scheduler surface encodes trigger type in the method name — `run_in()`, `run_daily()`, `run_cron()` — rather than requiring users to construct trigger objects. Each method handles trigger construction internally and presents a focused parameter surface for that specific use case. AppDaemon extends this to 10+ methods including `run_at_sunrise`, `run_at_sunset`, `run_weekly`, `run_monthly`, and `run_seasonal`. Hassette currently offers 7 methods.

The key ergonomic win is IDE discoverability: users type `self.scheduler.run_` and autocomplete surfaces the available scheduling strategies. No knowledge of the underlying trigger object model is needed for the common cases.

**Strengths**: Lowest friction for the common case. Self-documenting method names. No imports beyond the scheduler itself. IDE-friendly.

**Weaknesses**: Proliferates into many methods as edge cases accumulate. Combining triggers (fire when A OR B is true) is not expressible without a separate API layer. Solar and calendar triggers are awkward to fit in this style.

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html

---

### Pattern 2: Trigger Object Protocol

**Used by**: APScheduler v3 and v4, Hassette (internally, not exposed)

**How it works**: Triggers are first-class objects implementing a protocol — typically `next_run_time(previous_run, current_time) -> datetime | None`. The scheduler calls this to determine when to fire next. Users construct trigger objects explicitly (`IntervalTrigger(seconds=5)`) and pass them to a single `add_job(func, trigger)` entry point.

APScheduler v4 made triggers **stateful** to support combining triggers with `AndTrigger`/`OrTrigger`. Stateful triggers can track which sub-trigger last fired and coordinate between multiple schedules. At the same time, v4 moved jitter out of triggers and into the `Schedule` object — an acknowledgment that jitter is a scheduling concern, not a timing concern.

Hassette already implements this pattern internally via `TriggerProtocol` and the `IntervalTrigger`/`CronTrigger` classes — it is just not exposed publicly. Exposing the trigger protocol would let users write custom triggers without modifying the scheduler.

**Strengths**: Composable. Arbitrary trigger logic without modifying the scheduler. Clean separation between "when to fire" and "what to do." Enables `AndTrigger`/`OrTrigger` composition.

**Weaknesses**: Higher barrier to entry. Users must know the object model. Stateful triggers are subtle — the same trigger instance cannot be safely reused across multiple schedules.

**Example**: https://apscheduler.readthedocs.io/en/master/api.html, https://apscheduler.readthedocs.io/en/master/extending.html

---

### Pattern 3: Rich Job Object vs Opaque Handle for Cancellation

**Used by**: APScheduler v3 (rich `Job` object), AppDaemon (opaque string handle), APScheduler v4 (string ID with separate lookup), Hassette (rich `ScheduledJob` with `.cancel()`)

**How it works**: Two philosophies exist for what a scheduling call returns:

*Opaque handle*: `handle = self.run_in(cb, 60)` returns a string token. Cancellation is `cancel_timer(handle)`. The handle encodes nothing — you cannot inspect the job's next_run or trigger from it. AppDaemon uses this model.

*Rich object*: `job = scheduler.run_in(cb, 60)` returns a `ScheduledJob` with `.cancel()`, `.next_run`, `.matches()`, and `.db_id`. The object is inspectable. This is Hassette's model.

APScheduler v4 moved back toward opaque string IDs for schedules, but provides `scheduler.get_schedule(id)` for inspection when needed — a hybrid approach that avoids the staleness issue of rich objects held by the user.

The staleness problem: if `ScheduledJob.next_run` is updated in-place by the scheduler service, a user holding a reference to the job object will see the mutation — which is actually desirable for monitoring but surprising for those expecting immutability.

**Strengths of rich objects**: Inspectable, cancellable directly, natural Python ergonomics. Users can `assert job.next_run > now` in tests.

**Weaknesses of rich objects**: In-place mutation of `next_run` is a hidden side-effect. The object may become invalid after cancellation, but nothing prevents calling `.cancel()` twice.

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html (handle), current Hassette codebase (rich object)

---

### Pattern 4: Misfire Handling — Coalescing and Grace Time

**Used by**: APScheduler (all versions), Celery Beat, production schedulers broadly

**How it works**: When a scheduler restarts after downtime, scheduled fires may have been missed. Three standard strategies exist:

*Coalescing*: If N fires were missed, execute only once (the latest). APScheduler's `CoalescePolicy.latest` does this. `CoalescePolicy.all` fires all missed events in sequence. For most home automation cases, coalescing to latest is correct — firing "check if lights are on" 47 times after a restart is not useful.

*Misfire grace time*: A window within which a late fire still executes. If the scheduler was down 30 seconds and grace time is 60 seconds, the missed fire runs. If it was down 90 seconds, the fire is skipped as too stale.

*Skip and advance*: Hassette's current implicit strategy via `IntervalTrigger._advance_past()` — compute the next valid interval from the anchor and fire from there, discarding all missed fires. This is effectively "coalesce all, skip to next."

None of these three strategies are currently configurable by users in Hassette — the behavior is fixed in the trigger implementation.

**Strengths**: Prevents runaway catch-up execution. Grace time enables resilience to brief outages. Explicit policy is clearer than implicit trigger behavior.

**Weaknesses**: Adds configuration surface. Users who don't understand the policies may choose incorrectly. Coalescing means some fires are genuinely lost — not acceptable for all use cases.

**Example**: https://apscheduler.readthedocs.io/en/master/api.html, https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html

---

### Pattern 5: Built-In Jitter / Randomization

**Used by**: AppDaemon (per-call `random_start`/`random_end`), APScheduler v4 (`max_jitter` on Schedule), some IoT frameworks

**How it works**: Rather than always firing at the exact scheduled time, the scheduler adds a random offset within a specified window. AppDaemon integrates this into every scheduling call: `self.run_daily(cb, "02:00:00", random_start=-300, random_end=300)` fires any time between 1:55 AM and 2:05 AM.

APScheduler v4 expresses this as `max_jitter` on the `Schedule` object — a uniform random delay between 0 and `max_jitter` seconds is added. The key design decision v4 made: jitter belongs at the **schedule level**, not the trigger level. A trigger computes "when logically to fire"; jitter is a deployment concern about not firing all schedules simultaneously.

For home automation: if 20 Hassette apps all run a daily status check at midnight, they pile up. Even a `max_jitter=60` seconds staggers them significantly.

**Strengths**: Prevents thundering herd. Particularly valuable when many apps share heuristic times. Simple to express at registration.

**Weaknesses**: Makes firing non-deterministic, which complicates testing. AppDaemon's `random_start`/`random_end` API requires reasoning about relative offsets, which is confusing. APScheduler's `max_jitter` is cleaner but less flexible.

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html, https://apscheduler.readthedocs.io/en/master/api.html

---

### Pattern 6: Solar / Astronomical Triggers

**Used by**: AppDaemon (`run_at_sunrise`, `run_at_sunset`), Home Assistant (Sun Elevation Trigger), Node-RED Big Timer

**How it works**: Home automation frameworks provide scheduling methods that fire relative to solar events. AppDaemon offers `run_at_sunrise(callback, offset=0)` and `run_at_sunset(callback, offset=0)` where offset is in seconds.

Home Assistant has two distinct trigger types for solar events:

- **Sunset/Sunrise Trigger** (`trigger: sun` with `event: sunset/sunrise` and optional `offset`): fires at a computed fixed time relative to the solar event.
- **Sun Elevation Trigger** (`trigger: numeric_state` on `sun.sun` attribute `elevation`): fires when the sun crosses a specified elevation angle.

HA's documentation explicitly recommends the elevation approach for dusk/dawn automations (quoted from the "Sun elevation trigger" section of the automation trigger docs):

> "Since the duration of twilight is different throughout the year, it is recommended to use sun elevation triggers instead of `sunset` or `sunrise` with a time offset to trigger automations during dusk or dawn."

The rationale is physical: twilight duration varies seasonally, so a fixed time offset fires at inconsistent light levels. An elevation threshold (e.g., `-4.0°` for civil twilight) is consistent regardless of season.

Note: HA's recommendation is to use the dedicated **Sun Elevation Trigger type**, not to watch the `sun.sun` entity's state attribute via a generic state-change trigger. These are different mechanisms.

Hassette has no solar trigger support. The HA recommendation suggests that for dusk/dawn use cases, the right design is an elevation-based trigger — which would be a new trigger type rather than a convenience method wrapping a fixed-offset calculation.

**Strengths**: Semantically natural for home automation. Eliminates hardcoded time tables. Elevation-based is more physically accurate than time-offset.

**Weaknesses**: Requires lat/lng configuration. Solar computation needs a dependency (e.g., `ephem` or `astral`). Elevation-based triggers require understanding solar geometry.

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html, https://www.home-assistant.io/docs/automation/trigger/#sun-elevation-trigger

---

### Pattern 7: Callback Signature — Uniform kwargs vs Typed DI

**Used by**: AppDaemon (uniform `**kwargs`), Hassette (FastAPI-style DI)

**How it works**: AppDaemon requires all scheduler callbacks to use `def callback(self, **kwargs)`. All job metadata and custom kwargs passed at registration arrive via the kwargs dict. Users must know key names — `kwargs["trigger"]`, `kwargs["kwargs"]` — to access them.

Hassette uses dependency injection: `async def my_job(api: Api, state: StateManager)` — the job callable declares parameters by name and the framework resolves them. No boilerplate kwargs dict.

The AppDaemon model's critical flaw: misspelled kwargs keys (`kwargs.get('entyty_id')`) fail silently with `None`. The DI model converts this into a registration-time error.

**Strengths of uniform kwargs**: Simple, predictable, no framework magic. Easy for newcomers.
**Weaknesses of uniform kwargs**: No IDE completion for callback parameters. Silent key typos.
**Strengths of DI**: Typed, autocompleted, self-documenting signature. Registration-time error on unknown parameters.
**Weaknesses of DI**: Surprising magic for newcomers. DI resolution failures require understanding the injection system.

**Example**: https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html (kwargs model)

---

### Pattern 8: Structured Concurrency for Job Execution

**Used by**: Trio (nurseries), AnyIO (task groups), emerging best practice in async Python

**How it works**: Rather than spawning free-floating `asyncio.create_task()` calls for each job, a structured approach uses task groups where the scheduler is the parent and all in-flight job tasks are children. The parent context cannot exit until all children complete. This eliminates orphan tasks that outlive the scheduler.

In AnyIO: `async with anyio.create_task_group() as tg: tg.start_soon(run_job, job)` ensures all in-flight jobs are awaited before the scheduler shuts down.

Hassette's current model (inferred from the codebase) likely uses `asyncio.create_task()` for job execution — worth verifying whether in-flight job tasks are properly awaited during `on_shutdown`.

**Strengths**: No orphan tasks. Clean shutdown — `on_shutdown` naturally waits for in-flight jobs. Error propagation follows the task hierarchy.

**Weaknesses**: Can block shutdown if a job is stuck. Requires timeout/cancellation scope to bound job runtime. AnyIO task groups do not return values from child tasks.

**Example**: https://anyio.readthedocs.io/en/stable/cancellation.html, https://applifting.io/blog/python-structured-concurrency

---

## Anti-Patterns

- **Interval drift via naive sleep-then-run loops**: `asyncio.sleep(interval)` in a loop accumulates drift because sleep measures elapsed time from when the job resumes, not from the scheduled fire time. A 2-second job at a 60-second interval drifts 2 seconds per cycle. Over months, daily tasks visibly slip. The correct approach — used correctly in Hassette's `IntervalTrigger._advance_past()` — computes the next fire relative to a fixed anchor. Source: https://medium.com/@ThinkingLoop/7-scheduler-strategies-for-python-jobs-celery-rq-arq-48b1eb5f8f79

- **Swallowing `CancelledError` in retry logic**: Retry decorators that catch broad exceptions (including `BaseException` or `CancelledError`) cause tasks to continue running after cancellation is requested. The task appears cancelled to the scheduler but keeps executing, producing resource leaks and jobs that run after shutdown. Fix: always re-raise `CancelledError` explicitly. Source: https://medium.com/@fikralaksanaputra_24915/the-hidden-danger-of-asyncio-task-cancellation-with-retry-decorators-2945044df6fa

- **Silent kwargs key typos**: Uniform `**kwargs` callback signatures (AppDaemon style) silently return `None` for misspelled keys. This is the most common class of AppDaemon bug in community forum posts. Hassette's typed DI approach eliminates this.

- **Overlapping execution without protection**: Celery Beat explicitly documents that tasks may overlap when the job runtime exceeds the scheduling interval — and provides no built-in prevention. Users must implement external locking. In a single-process async scheduler like Hassette, this is not an issue for async jobs (the event loop is cooperative), but sync callables executed via `run_in_executor` can still overlap.

---

## Emerging Trends

**Structured concurrency adoption**: `asyncio.TaskGroup` (Python 3.11+) and Trio nurseries are becoming the standard for managing groups of async tasks. Free-floating `create_task()` is increasingly flagged as an anti-pattern in async Python codebases.

**Schedule-level jitter as standard**: APScheduler v4's decision to move jitter from triggers to the schedule layer signals that randomization is now a first-class scheduling concern, driven by cloud-scale deployments where synchronized job firing causes measurable load spikes.

**Elevation-based solar triggers over time-offset**: The HA community is moving away from `trigger: sun` with time offsets toward the dedicated Sun Elevation Trigger for dusk/dawn automations. Physical-state-based triggers are more accurate across seasons than computed time offsets.

**`typing.Protocol` over ABC inheritance for trigger extensibility**: APScheduler v4 and the broader Python ecosystem have shifted from requiring inheritance from `BaseTrigger` to implementing a `Protocol`. Hassette's `TriggerProtocol` already follows this trend.

---

## Relevance to Us

Hassette's current scheduler is already ahead of AppDaemon in key areas: drift-resistant interval advancement, typed returns, `.cancel()` on a rich object, and DI-style callback injection. The areas where Hassette lags or has gaps:

1. **No jitter support**: Both AppDaemon and APScheduler v4 provide this. Home automation use cases need it. Adding `jitter: float = 0` to each `run_*` method would be a low-friction addition.

2. **No configurable misfire policy**: Hassette's restart behavior (skip all missed fires, advance to next) is implicit and undocumented. Exposing `if_missed: Literal["skip", "run_once"]` on the `run_every` / `run_cron` methods would make the contract explicit.

3. **`TriggerProtocol` is internal-only**: Exposing it publicly would let users write custom triggers (solar, calendar, condition-gated) without modifying the framework. APScheduler has provided this extensibility point since v3.

4. **No solar triggers**: AppDaemon has `run_at_sunrise`/`run_at_sunset`. HA's own recommendation is to use the Sun Elevation Trigger for dusk/dawn automations — which fires on a physical threshold rather than a fixed time offset. The right answer for Hassette is not a time-offset `run_at_sunset()` but either a solar elevation trigger type (exposing `TriggerProtocol` publicly would enable users to build this) or documentation pointing to the bus-based `on_attribute_change` on `sun.sun` elevation as an interim approach.

5. **`run_daily` is implemented as a 24-hour interval**: This means it drifts relative to wall-clock time if the app restarts at a different time of day. A true "fire at HH:MM every day" would use `run_cron` internally, not `IntervalTrigger`. This is a silent correctness issue.

6. **No `run_weekly`/`run_monthly`**: AppDaemon has these. The ergonomic question is whether these are worth adding vs. pointing users to `run_cron`.

---

## Recommendation

The two highest-value additions supported by prior art are:

**1. Jitter parameter on all `run_*` methods** (`jitter: float = 0` in seconds): Low implementation cost, well-precedented by both AppDaemon and APScheduler v4, materially useful for production deployments where multiple apps share heuristic times.

**2. Explicit misfire policy on recurring methods** (`if_missed: Literal["skip", "run_once"] = "skip"`): Currently this behavior is implicit in trigger logic. Making it explicit and documented closes a real user confusion gap. "Skip" is the correct default for home automation.

Lower priority but worth tracking:
- Fix `run_daily` to use cron-based scheduling (fire at a consistent wall-clock time) rather than a 24-hour interval.
- Expose `TriggerProtocol` publicly for custom trigger extensibility.
- Document the solar trigger gap: recommend `on_attribute_change` on `sun.sun` elevation as the interim approach, and expose `TriggerProtocol` as the path for users who want a proper solar trigger type.

The DI callback model, rich `ScheduledJob` return, and drift-resistant trigger arithmetic are already best-in-class relative to the prior art — these should be preserved and highlighted in user-facing documentation.

---

## Sources

### Reference implementations
- https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html — AppDaemon full scheduler API reference
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon app writing guide (scheduling patterns in context)
- https://apscheduler.readthedocs.io/en/master/api.html — APScheduler v4 async API reference
- https://apscheduler.readthedocs.io/en/stable/userguide.html — APScheduler v4 user guide (trigger design, misfire, coalesce)
- https://apscheduler.readthedocs.io/en/3.x/userguide.html — APScheduler v3 user guide (for comparison)

### Blog posts & writeups
- https://medium.com/@ThinkingLoop/7-scheduler-strategies-for-python-jobs-celery-rq-arq-48b1eb5f8f79 — Scheduler anti-patterns (drift, overlap, monitoring)
- https://medium.com/@fikralaksanaputra_24915/the-hidden-danger-of-asyncio-task-cancellation-with-retry-decorators-2945044df6fa — CancelledError swallowing in retry decorators
- https://betterstack.com/community/guides/scaling-python/apscheduler-scheduled-tasks/ — APScheduler tutorial with concrete API examples
- https://applifting.io/blog/python-structured-concurrency — Structured concurrency patterns in Python
- https://randomnerdtutorials.com/node-red-big-timer-automation/ — Node-RED Big Timer (solar scheduling reference)

### Documentation & standards
- https://www.home-assistant.io/docs/automation/trigger/ — HA time, time_pattern, sun, and sun elevation trigger documentation
- https://www.home-assistant.io/integrations/sun/ — HA sun integration (elevation-based trigger guidance)
- https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html — Celery Beat periodic task design
- https://anyio.readthedocs.io/en/stable/cancellation.html — AnyIO cancel scopes
- https://peps.python.org/pep-0789/ — PEP 789 (CancelledError in async generators)
- https://apscheduler.readthedocs.io/en/master/migration.html — APScheduler v3→v4 migration (stateful triggers, jitter move)
