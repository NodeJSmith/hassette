---
topic: "Perfect public API for Hassette's Scheduler resource and trigger system (full rewrite)"
date: 2026-04-14
ranked_by: user impact
status: Draft
---

# Brainstorm: Scheduler API Redesign

## Context

Full rewrite is on the table. No hard constraints. The prior art brief (`design/research/2026-04-14-scheduler-api-ergonomics/research.md`) identified several issues with the current API:

- `run_daily` uses a 24h `IntervalTrigger` — silently drifts from wall-clock time on restart
- `ScheduleStartType` accepts 7 types parsed by a 7-branch function — confusing
- No jitter, no configurable misfire policy, no public `TriggerProtocol`
- Method proliferation (`run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `run_cron`) will only grow

---

## Ideas — Ranked by User Impact

### 1. Declarative trigger object API — Score: 5.0 ⭐ (selected for design)

**The idea**: Replace the proliferating `run_*` methods with a single `schedule(func, trigger)` entry point where trigger types are composable nouns — `Every(hours=1)`, `Daily(at="07:00")`, `Cron("*/5 * * * *")` — with convenience methods as thin sugar.

**Why it could work**: The entire API surface collapses to one method and an open trigger protocol. Solar, calendar, and condition-gated triggers become just more trigger objects — no new methods ever needed. The vocabulary is learnable once and generative forever. AppDaemon's 10+ proliferating methods show exactly where the current path leads.

**The catch**: Requires designing the trigger object API well upfront — naming, constructor ergonomics, and whether triggers are stateless or stateful. Wrong choice here is harder to fix later.

**Origin**: All 4 lenses — strongest convergence signal in the session.

---

### 2. Wall-clock anchoring for all time-of-day schedules — Score: 4.5 ⭐ (selected for design)

**The idea**: `Daily(at="07:00")` fires at 07:00 every day regardless of when the app restarted — implemented via `CronTrigger` internals, not a 24h `IntervalTrigger`.

**Why it could work**: Fixes a real silent bug users will discover months after deploying. "Fire at this time of day" and "fire every N seconds" are fundamentally different semantics and should use different trigger implementations.

**The catch**: Only lands cleanly if idea #1 lands too — otherwise you're patching one method while leaving the rest of the API as-is.

**Origin**: Pragmatist + User Advocate.

---

### 3. `@schedule` decorator API — Score: 4.0

**The idea**: Declare scheduling intent directly on the method — `@schedule.daily(at="07:00")` — and the `App` base class introspects and registers annotated methods automatically at `on_initialize` time.

**Why it could work**: Collocates the temporal contract with the code it governs. The schedule is visible right where you read the method.

**The catch**: Dynamic schedule changes don't fit the decorator model well — you'd still need the imperative API alongside it. This is sugar, not a replacement.

**Origin**: Moonshot.

---

### 4. Condition-gated triggers (`when=` guard) — Score: 4.0 ⭐ (selected for design)

**The idea**: Every scheduling call accepts an optional `when` predicate — a DI-injected callable returning `bool` — evaluated at fire time; skipped executions are logged as `status="skipped"` in telemetry.

**Why it could work**: Eliminates the ubiquitous "check precondition, early-return" pattern at the top of every callback. Symmetric with the Bus's predicate/condition filter system.

**The catch**: DI resolution inside the predicate must be fast and fail-safe. Skipped fires are invisible unless telemetry surfaces them.

**Origin**: User Advocate + Moonshot.

---

### 5. Named job groups + bulk cancel — Score: 3.5 ⭐ (selected for design)

**The idea**: Jobs take an optional `group=` parameter; `scheduler.cancel_group("morning_routine")` atomically cancels all jobs in that group.

**Why it could work**: Automations that dynamically reconfigure their schedule currently require manually tracking every handle. Groups map to how users think about their automations — not as individual timers but as features.

**The catch**: Adds a parallel lookup structure alongside `_jobs_by_name`. Group membership after partial cancel needs to be well-defined.

**Origin**: User Advocate + Moonshot.

---

### 6. First-class jitter — Score: 3.5

**The idea**: All trigger types accept `jitter: timedelta | float = 0` — a random offset applied at actual fire time.

**Why it could work**: When 20 apps all fire at midnight, they pile up. A 60-second jitter window staggers them with zero user effort.

**The catch**: Non-deterministic firing complicates testing. Users need a way to disable jitter in test mode.

**Origin**: Pragmatist + User Advocate.

---

### 7. Make `TriggerProtocol` a public export — Score: 3.5 ⭐ (selected for design)

**The idea**: Re-export `TriggerProtocol` from `scheduler/__init__.py` — users can already pass custom triggers to `schedule()`, they just don't know it.

**Why it could work**: Unlocks solar, calendar, and condition-gated triggers for power users. Effectively free — two-line re-export and a doc example.

**The catch**: Commits to the current `TriggerProtocol` shape as a public API. If idea #1 redesigns trigger objects, sequence this after.

**Origin**: Pragmatist.

---

### 8. `if_exists="replace"` atomic swap — Score: 3.0

**The idea**: Third option alongside `"error"` and `"skip"` that cancels the existing job and registers the new one atomically.

**Origin**: Pragmatist.

---

### 9. Narrow `ScheduleStartType` union — Score: 3.0 ⭐ (selected for design)

**The idea**: Explicit types per method instead of a 7-branch polymorphic union parser — `run_once` takes `ZonedDateTime`, `run_every` takes `timedelta`, etc.

**Why it could work**: Reduces API confusion, improves Pyright diagnostics, eliminates surprising type coercions.

**The catch**: Breaking change for users relying on the polymorphic `(hour, minute)` tuple shorthand.

**Origin**: Pragmatist.

---

### 10. Reactive job signals — Score: 3.0

**The idea**: `ScheduledJob.on_fire`, `.on_error`, `.on_cancel` subscriptions for chaining and monitoring.

**Origin**: Moonshot.

---

### 11. Check-in / pull model — Score: 3.0

**The idea**: Callback returns an action or `timedelta`; avoids cancellation logic for self-rescheduling tasks.

**Origin**: Wildcard.

---

### 12. Fallback chains — Score: 2.5

**The idea**: Priority-ordered handler list per trigger; if the primary can't run, the next promotes automatically.

**Origin**: Wildcard.

---

## Selected for Design

Ideas 1, 2, 4, 5, 7, and 9 will be written up as a combined API design doc, then challenged.

---

## Appendix: Individual Thinker Reports

These files contain each thinker's unfiltered output:

- Pragmatist: /tmp/claude-mine-brainstorm-tX54bs/pragmatist.md
- User Advocate: /tmp/claude-mine-brainstorm-tX54bs/advocate.md
- Moonshot Thinker: /tmp/claude-mine-brainstorm-tX54bs/moonshot.md
- Wildly Imaginative: /tmp/claude-mine-brainstorm-tX54bs/wildcard.md
