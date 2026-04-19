---
topic: "Execution overlap / concurrency control for event handlers and scheduled jobs"
date: 2026-04-19
status: Draft
---

# Prior Art: Execution Overlap & Concurrency Modes

## The Problem

When an event handler or scheduled job is still running and its trigger fires again, the framework must decide what to do with the new invocation. Without explicit concurrency control, the default behavior is usually "run both concurrently" — which causes subtle state corruption, duplicate side effects, and race conditions that only manifest under load. Every mature automation framework eventually adds this feature; the question is naming, defaults, and interface design.

## How We Do It Today

Hassette has **no execution overlap control**. Both event handlers and scheduled jobs fire-and-forget via `TaskBucket.spawn()` with no concurrency gating. If a handler or job is still running when a new trigger arrives, both run concurrently. Rate limiters (debounce/throttle) modify *timing* but don't prevent overlapping *execution*. There is no `mode`, `concurrency`, or similar parameter on bus registrations or scheduler jobs.

## Patterns Found

### Pattern 1: Declarative Concurrency Modes (Enum-Based)

**Used by**: Home Assistant, Power Automate (partially)

**How it works**: The framework defines a fixed set of named modes that control what happens when a handler is already running and a new trigger arrives. The user selects a mode at registration time via a simple string/enum parameter.

Home Assistant defines four modes:
- **`single`** (default) — ignore new triggers while running; log a warning (configurable via `max_exceeded`)
- **`restart`** — cancel the running instance and start fresh with the new trigger
- **`queued`** — line up new triggers and process them in order (accepts `max` parameter, default 10)
- **`parallel`** — allow multiple instances to run concurrently (accepts `max` parameter, default 10)

The `max_exceeded` option controls what happens when `max` is hit: `warning` (default), `silent`, `error`. This was added in response to user complaints about log spam from suppressed triggers on high-frequency sensors.

**Strengths**: Easy to understand, hard to misuse, self-documenting. Four modes cover the vast majority of real-world use cases. Configuration is declarative, not imperative.

**Weaknesses**: Less composable than operator-based approaches. Edge cases within a mode (e.g., "queue but drop if queue is full") require additional parameters. The `single` default, while safe, confuses users who expect every trigger to produce an action.

**Example**: https://www.home-assistant.io/docs/automation/modes/

### Pattern 2: Reactive Operators (Composable Flattening)

**Used by**: RxJS, RxJava, RxSwift, Project Reactor

**How it works**: The developer composes observable streams using higher-order mapping operators that each encode a specific concurrency strategy:
- **`mergeMap`** — parallel, all run (= HA `parallel`)
- **`switchMap`** — cancel previous, run latest (= HA `restart`)
- **`concatMap`** — queue in order (= HA `queued`)
- **`exhaustMap`** — ignore new while busy (= HA `single`)

The operator determines how overlapping inner observables interact. This is the most theoretically elegant approach — concurrency behavior is just another stream transformation, composable with debounce, throttle, buffer, etc.

**Strengths**: Highly composable. Precise semantics with well-defined marble diagrams. Battle-tested across multiple language implementations. Standard terminology in the reactive world.

**Weaknesses**: Steep learning curve. Requires understanding reactive programming concepts. Overkill for simple automation scenarios. Error handling in operator chains is notoriously tricky.

**Example**: https://blog.angular-university.io/rxjs-higher-order-mapping/

### Pattern 3: Numeric Concurrency Limits with Misfire Policy

**Used by**: APScheduler, Quartz, Power Automate

**How it works**: Instead of named modes, the framework exposes numeric parameters. APScheduler combines three:
- **`max_instances`** (default 1) — how many concurrent runs are allowed
- **`misfire_grace_time`** — how late a job can still start (seconds after designated time)
- **`coalesce`** — collapse multiple missed runs into one

Setting `max_instances=1` with coalescing gives "single" behavior. Higher values give "parallel" behavior. There's no built-in "restart" (cancel-previous) mode. APScheduler 4.x renamed `max_instances` to `max_running_jobs`, suggesting the original name was confusing.

**Strengths**: More granular control than enum modes. The separation of "how many" from "what to do with extras" is clean. `coalesce` is a useful concept that named-mode systems often lack.

**Weaknesses**: Harder to reason about than named modes. The interaction between parameters creates a combinatorial space. No "cancel previous" option. Users frequently misconfigure.

**Example**: https://apscheduler.readthedocs.io/en/3.x/userguide.html

### Pattern 4: Annotation/Decorator-Based Opt-In

**Used by**: Quartz (`@DisallowConcurrentExecution`), Spring (ShedLock), Celery (via third-party libs)

**How it works**: The default behavior is to allow concurrent execution. To prevent overlap, the developer adds an annotation to the job class or method. This is a binary opt-in — you either allow concurrency or you don't. Quartz's annotation queues new triggers (not skip); Spring has no built-in mechanism at all; Celery spawned three competing third-party libraries.

Notable: Quartz scopes by JobDetail key (not class), so two different triggers for the same job are serialized, but two different jobs using the same class can run in parallel.

**Strengths**: Zero-config for the common case. Familiar pattern for Python/Java developers.

**Weaknesses**: Binary choice without nuance. No "cancel previous" or "skip if running." Third-party lock solutions add external dependencies. Celery's lack of built-in support is widely cited as a design gap.

**Example**: https://jayvilalta.com/blog/2014/06/04/understanding-the-disallowconcurrentexecution-job-attribute/

### Pattern 5: Lock-Based Deduplication (External State)

**Used by**: Celery ecosystem, ShedLock, custom distributed systems

**How it works**: Before executing, acquire a lock (Redis/DB) keyed on task identity. Two philosophies: `celery-singleton` returns the `AsyncResult` of the already-running task; `celery-once` raises `AlreadyQueued`. Both require TTL to handle worker crashes.

**Strengths**: Works across distributed systems and multiple processes.

**Weaknesses**: Adds external dependency. Only covers "skip if running" — no queue or cancel semantics. Lock management is error-prone (TTL too short = false parallel; TTL too long = stuck tasks).

**Example**: https://github.com/steinitzu/celery-singleton

## Anti-Patterns

- **Accidental serialization masquerading as overlap protection**: Spring's default single-thread pool prevents overlap as a side effect, not by design. Increasing pool size for performance suddenly exposes overlap bugs. ([Source](https://medium.com/@wldbs9644/managing-scheduled-tasks-and-preventing-overlaps-in-spring-boot-thread-pools-virtual-threads-d5ee49295264))

- **Missing TTL on concurrency locks**: Lock-based deduplication without TTL leads to permanent deadlocks when workers crash. Production data corruption documented by Glinteco. Every lock must have a TTL longer than max expected execution time. ([Source](https://glinteco.com/en/post/glintecos-case-study-mitigating-duplicate-task-execution-with-a-custom-celery-solution/))

- **WARNING-level logs for expected behavior**: HA's `single` mode logs WARNING every time a trigger is suppressed. For high-frequency triggers (motion sensors), this floods logs. Suppressed executions in "single" mode are *expected*, not exceptional — should default to DEBUG or INFO. HA later added `max_exceeded: silent` as a fix, but it's poorly discoverable. ([Source](https://community.home-assistant.io/t/automation-in-single-mode-is-spamming-my-logs/590165))

- **Irreversible concurrency settings**: Power Automate's concurrency control cannot be disabled once enabled — you must recreate the flow from scratch. ([Source](https://www.crmsoftwareblog.com/2024/05/cs-pros-and-cons-of-concurrency-control-in-power-automate-flows/))

- **No built-in support spawning ecosystem fragmentation**: Celery's omission of task deduplication spawned three competing libraries with different semantics, confusing users and making behavior inconsistent across projects. ([Source](https://github.com/steinitzu/celery-singleton))

## Emerging Trends

**Convergence on four canonical modes**: Despite different naming, the industry has converged on four strategies:

| Behavior | HA | RxJS | APScheduler equiv | Description |
|---|---|---|---|---|
| Ignore new while busy | `single` | `exhaustMap` | `max_instances=1`, skip | Default safe choice |
| Cancel running, start new | `restart` | `switchMap` | (none) | "Latest value wins" |
| Queue in order | `queued` | `concatMap` | `max_instances=1`, queue | Guarantees all triggers run |
| Allow concurrent | `parallel` | `mergeMap` | `max_instances=N` | Max throughput |

**Per-registration over per-class**: Trend is moving from class-level annotations (Quartz) toward per-registration configuration (HA per-automation, APScheduler per-job). More flexible — same handler can have different modes for different triggers.

**Async-first redesigns retain overlap concepts**: APScheduler 4.x redesigned for async-first but kept the same concurrency abstractions. Validates that these modes are durable across sync/async boundaries.

## Relevance to Us

**Direct alignment with HA's model**: As a Home Assistant automation framework, adopting HA's mode terminology (`single`, `restart`, `queued`, `parallel`) would be the natural choice. Users already know these names from HA YAML automations. Using different names would create confusion.

**Architecture is ready**: Hassette's async-first design and `TaskBucket` execution layer provide the building blocks. The guard would go in the dispatch path (before `task_bucket.spawn()`), checking per-listener/per-job execution state. `asyncio.Lock` and `asyncio.Semaphore` are the right primitives for queue and parallel-with-limit modes.

**Interaction with existing features**: Debounce and throttle are *timing* controls and compose naturally with concurrency modes. `once=True` is orthogonal (fires at most once total, regardless of mode). These interactions should be documented but don't create conflicts.

**Single interface for both bus and scheduler**: The user explicitly wants one `mode` parameter for both event handlers and scheduled jobs, not separate concurrency models. This aligns with HA's approach (same modes for automations and scripts) and simplifies the mental model.

**Key design decisions**:
1. **Default**: `single` (matches HA, prevents accidental overlap, safest default) — but *must* avoid HA's WARNING log spam anti-pattern
2. **Log level for suppressed executions**: DEBUG by default, with an option to escalate. Do not repeat HA's mistake of WARNING by default.
3. **`max` parameter**: Useful for `queued` and `parallel` modes but can wait for v2 — start with the four modes only
4. **`restart` implementation**: Requires `asyncio.Task.cancel()` on the running execution. Need to handle `CancelledError` gracefully in handlers.

## Recommendation

**Adopt HA's four-mode enum** (`single`, `restart`, `queued`, `parallel`) as a `mode` parameter on both bus registrations and scheduler jobs. This is the strongest pattern: battle-tested by HA's massive user base, intuitive naming, and directly aligned with hassette's target audience. Default to `single`.

**Learn from HA's mistakes**: default log level for suppressed executions should be DEBUG, not WARNING. Consider a `max_exceeded` parameter from the start, but default it to `silent` rather than `warning`.

**Skip numeric concurrency limits initially**: APScheduler's `max_instances` approach is more powerful but harder to reason about. The four named modes cover >95% of use cases. `max` can be added to `queued`/`parallel` later if needed.

**Per-registration, not per-class**: Mode should be a parameter on `bus.on_state_change(..., mode="single")` and `scheduler.schedule(..., mode="single")`, not a class-level attribute. Matches the per-registration trend and hassette's existing registration API.

## Sources

### Reference implementations
- https://www.home-assistant.io/docs/automation/modes/ — HA automation modes (single/restart/queued/parallel)
- https://apscheduler.readthedocs.io/en/3.x/userguide.html — APScheduler max_instances, misfire, coalesce
- https://apscheduler.readthedocs.io/en/master/api.html — APScheduler 4.x async-first redesign
- https://github.com/steinitzu/celery-singleton — Celery task deduplication via Redis locks
- https://github.com/cameronmaske/celery-once — Alternative Celery deduplication (raises AlreadyQueued)

### Blog posts & writeups
- https://www.thecandidstartup.org/2025/10/20/home-assistant-concurrency-model.html — HA concurrency model deep dive
- https://www.xda-developers.com/home-assistant-mistakes-that-can-break-your-automations/ — Common HA mistakes including mode confusion
- https://blog.angular-university.io/rxjs-higher-order-mapping/ — RxJS higher-order mapping operators explained
- https://thinkrx.io/rxjs/mergeMap-vs-exhaustMap-vs-switchMap-vs-concatMap/ — Visual comparison of RxJS operators
- https://glinteco.com/en/post/glintecos-case-study-mitigating-duplicate-task-execution-with-a-custom-celery-solution/ — Production duplicate task case study
- https://medium.com/@wldbs9644/managing-scheduled-tasks-and-preventing-overlaps-in-spring-boot-thread-pools-virtual-threads-d5ee49295264 — Spring @Scheduled overlap management
- https://dev.to/dixitgurv/spring-boot-scheduling-best-practices-503h — Spring scheduling best practices
- https://jayvilalta.com/blog/2014/06/04/understanding-the-disallowconcurrentexecution-job-attribute/ — Quartz DisallowConcurrentExecution
- https://ryanc118.medium.com/python-asyncio-and-footguns-8ebdb4409122 — asyncio footguns
- https://www.inngest.com/blog/no-lost-updates-python-asyncio — asyncio shared state race conditions
- https://www.crmsoftwareblog.com/2024/05/cs-pros-and-cons-of-concurrency-control-in-power-automate-flows/ — Power Automate concurrency pitfalls

### Documentation & standards
- https://learn.microsoft.com/en-us/power-automate/guidance/coding-guidelines/implement-parallel-execution — Power Automate concurrency docs
- https://nodered.org/blog/2019/08/16/going-async — Node-RED async handling

### Community discussions
- https://community.home-assistant.io/t/automation-modes-and-their-use-cases/401468 — HA mode confusion (per-trigger vs per-automation)
- https://community.home-assistant.io/t/automation-in-single-mode-is-spamming-my-logs/590165 — HA single-mode log spam complaints
