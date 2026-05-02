---
topic: "Async Task Management and Structured Concurrency"
date: 2026-05-01
status: Draft
---

# Prior Art: Async Task Management and Structured Concurrency

## The Problem

Long-running async services need to spawn many concurrent tasks — event handlers, scheduled jobs, background workers — while maintaining three invariants: no task silently disappears (orphan prevention), one task's failure doesn't crash unrelated tasks (error isolation), and the system can shut down cleanly with bounded time (graceful shutdown). These invariants are in tension: strict structured concurrency (TaskGroup) enforces no-orphans but cancels everything on first error; fire-and-forget gives isolation but loses tasks to garbage collection. The design space between "cancel all siblings" and "let it crash, restart one" is where most production services live, and there's no standard library solution for it yet.

Additional dimensions — backpressure (don't spawn unbounded tasks under load), cancellation semantics (cooperative vs. forced), and error reporting (who sees the exception) — multiply the design choices. Get these wrong and you get silent failures, OOM under load, or services that hang during shutdown.

## How We Do It Today

Hassette uses **TaskBucket** — a lightweight Resource wrapper around asyncio's task system. All tasks spawned on the event loop are automatically registered via a globally-installed task factory that routes new tasks to the current context's bucket (read from a `CURRENT_BUCKET` context variable). Tasks are tracked in a `WeakSet` with strong references maintained through done callbacks. Error isolation is per-task: exception recorders (callbacks) fire for non-CancelledError exceptions in FIFO order without re-raising, so one task's failure never crashes another. Cancellation has two modes: `cancel_all_sync()` (fire-and-forget) and `cancel_all()` (async with configurable timeout — tasks that survive the timeout are logged as "refused to die"). Backpressure is managed at the subsystem level, not in TaskBucket itself: BusService tracks in-flight dispatch counts and idle state, SchedulerService uses fair locking, and the event stream (anyio MemoryObjectReceiveStream) provides natural backpressure. Shutdown is wave-based through the Resource hierarchy — leaf services first, dependencies last, with per-wave and total timeout budgets, and a force-terminal fallback.

## Patterns Found

### Pattern 1: Structured Concurrency (Nurseries / Task Groups)

**Used by**: Trio (nurseries), AnyIO (task groups), asyncio.TaskGroup (Python 3.11+), Kotlin (coroutineScope), Java (StructuredTaskScope via Project Loom)

**How it works**: Tasks are spawned into a scope that owns their lifetime. The scope blocks until all children finish. If any child raises an unhandled exception, all siblings are cancelled, and the exception (or ExceptionGroup) propagates to the parent. This creates a tree-shaped hierarchy where task lifetimes strictly nest within their parent scope — no orphan tasks are possible.

Cancel scopes (Trio/AnyIO) layer on top to provide timeouts and deadlines orthogonal to the task group. Python 3.12+ added eager task creation for TaskGroup. The key invariant: when execution leaves a task group block, all tasks spawned in that block have finished.

**Strengths**: Eliminates orphan tasks, guarantees cleanup, makes error propagation predictable, composes well (nested scopes). ExceptionGroup (PEP 654) allows callers to selectively handle different failure types via `except*`.

**Weaknesses**: The all-or-nothing cancellation is too aggressive for long-running services where one task failure should not kill siblings. No built-in restart logic. Requires Python 3.11+. Cannot express "run forever, restarting failures" without a supervision layer on top.

**Example**: https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup / https://trio.readthedocs.io/en/stable/reference-core.html

### Pattern 2: Supervision Trees (Erlang/OTP Model)

**Used by**: Erlang/OTP (supervisor behaviour), Elixir (Supervisor, DynamicSupervisor, Task.Supervisor), Akka (classic actors), Pykka

**How it works**: A supervisor monitors child processes and restarts them on failure according to a strategy: `one_for_one` (restart only the crashed child — independent children), `one_for_all` (restart all — shared critical state), or `rest_for_one` (restart crashed child and everything started after it — ordered dependencies). Supervisors form a tree. If a supervisor exhausts its restart budget (N restarts in T seconds), it crashes itself, escalating to its parent.

The "let it crash" philosophy keeps workers simple — they don't handle every error. Supervisors restart them in a known-good initial state, resolving most transient errors. Elixir's `Task.Supervisor` adds dynamic task spawning with `max_children` for backpressure and `async_nolink` for decoupled error handling.

**Strengths**: Battle-tested in telecom (99.999% uptime). Natural error isolation under `one_for_one`. Restart budgets prevent storms. Hierarchical escalation handles cascading failures. Three restart strategies encode common dependency patterns declaratively.

**Weaknesses**: Designed for process-level isolation (separate memory spaces). Mapping to async tasks in a single process is imperfect — a corrupted shared data structure can't be fixed by restarting a coroutine. Assumes stateless or easily-reconstructable workers. Restart budget tuning is a judgment call.

**Example**: https://www.erlang.org/doc/system/sup_princ.html / https://hexdocs.pm/elixir/Task.Supervisor.html

### Pattern 3: Persistent Task Group (Error-Isolating Scope)

**Used by**: Backend.AI (PersistentTaskGroup), custom implementations in production async services

**How it works**: A variation of the task group that does NOT cancel siblings when one task fails. Instead, it logs or collects the error and keeps remaining tasks running. Optionally, the failed task is restarted with backoff. The group still blocks on exit until all tasks complete, maintaining the "no orphans" invariant.

This sits between pure structured concurrency (cancel everything) and full supervision trees (restart with strategies). The key design decision is what to do with errors: log and continue, collect for later inspection, or restart with backoff. Different services choose different policies.

**Strengths**: Error isolation without process overhead. Maintains no-orphan invariant. Simpler than full supervision trees. Good fit for async services with mostly-independent tasks sharing a lifecycle.

**Weaknesses**: No standardized implementation — everyone builds their own. Easy to accidentally swallow exceptions. Restart logic tends to grow into ad-hoc supervision. Not in any standard library.

**Example**: https://www.backend.ai/blog/2022-03-PersistentTaskGroup

### Pattern 4: Bounded Concurrency with Backpressure

**Used by**: Go errgroup (SetLimit), Tokio (Semaphore + JoinSet), asyncio (Semaphore + Queue), Elixir (Task.Supervisor max_children), Celery/Dramatiq (worker pool limits)

**How it works**: Limits concurrent tasks via semaphores (acquire before spawn, release on completion), bounded queues (producer blocks when full), or fixed worker pools. The critical concept is backpressure: when at capacity, the system signals upstream rather than silently accepting more work. `asyncio.create_task()` never blocks, so bounds must be explicit.

Go's `errgroup.SetLimit(n)` and Elixir's `max_children` show how this integrates into the task group API. Semaphores are simplest for fan-out limiting, bounded queues decouple producers from consumers, and process pools give the strongest isolation.

**Strengths**: Prevents OOM from unbounded spawning. Provides natural flow control. Semaphore limits compose with TaskGroup. Queue depth is measurable.

**Weaknesses**: Requires upfront capacity planning. Wrong limits cause underutilization or head-of-line blocking. Backpressure propagation is complex in multi-stage pipelines.

**Example**: https://pkg.go.dev/golang.org/x/sync/errgroup / https://tech-champion.com/programming/python-programming/manage-async-i-o-backpressure-using-bounded-queues-and-timeouts/

### Pattern 5: Three-Phase Graceful Shutdown

**Used by**: Tokio (documented pattern), Go services (errgroup + context), Kubernetes (SIGTERM + grace period), Celery, systemd

**How it works**: Shutdown in three ordered phases: (1) **Stop accepting** — signal entry points to reject new work. (2) **Drain existing** — wait for in-flight tasks with a timeout; tasks check cancellation token cooperatively. (3) **Force cleanup** — cancel remaining tasks, close connections, flush buffers. Each phase has its own timeout.

In asyncio, this maps to: stop calling `create_task()`, await the task group to drain, cancel stragglers via `task.cancel()`. The drain phase requires tasks to support cooperative cancellation (handling CancelledError, checking shutdown flags). Tasks that catch-and-suppress CancelledError break the sequence.

**Strengths**: Clean resource cleanup. No data loss within drain timeout. Compatible with Kubernetes terminationGracePeriodSeconds. Each phase testable independently.

**Weaknesses**: All tasks must support cooperative cancellation. Drain timeout is a judgment call. Nested task groups complicate ordering. CancelledError handling in Python is subtle — `try/finally` blocks run during cancellation and bugs there hang shutdown.

**Example**: https://tokio.rs/tokio/topics/shutdown

### Pattern 6: Process-Level Isolation (Worker Pools)

**Used by**: Celery (pre-fork pool), Dramatiq (process + thread workers), Gunicorn, uWSGI

**How it works**: Each task runs in a separate OS process. A master manages the pool: spawning, distributing tasks, monitoring health, replacing crashed workers. Process crashes (OOM, segfault) are detected via exit codes or heartbeat timeouts. Dramatiq adds thread pools within each process for I/O-bound concurrency.

**Strengths**: Strongest isolation — OOM, segfaults, memory leaks contained. Simple master process. Works with C extensions and blocking I/O.

**Weaknesses**: High overhead (process creation, IPC serialization). Not suitable for sub-millisecond async tasks. Requires broker infrastructure (Redis, RabbitMQ). Cold start latency.

**Example**: https://docs.celeryq.dev/en/stable/userguide/tasks.html

### Pattern 7: Middleware Pipeline (Cross-Cutting Task Concerns)

**Used by**: Dramatiq (middleware), Celery (signals + task base classes), ASP.NET, Express.js

**How it works**: Cross-cutting concerns (retry, timeout, rate limiting, logging) are implemented as middleware wrapping task execution. Tasks contain only business logic. Dramatiq's built-in middleware includes Retries (exponential backoff), TimeLimit, AgeLimit (discard stale tasks), and ShutdownNotifications. Custom middleware adds circuit breakers, rate limiters, or telemetry. Tasks declare requirements declaratively (`max_retries=3, time_limit=30000`).

**Strengths**: Clean separation of concerns. Task code stays simple. Policies are declarative and composable. New concerns added without modifying tasks.

**Weaknesses**: Pipeline ordering is subtle. Too many layers add latency. More suited to queue-based architectures than in-process task groups.

**Example**: https://dramatiq.io/guide.html

## Anti-Patterns

- **Fire-and-forget without strong references**: Since Python 3.12, `create_task()` without saving a reference can result in GC collecting the task before completion — the event loop only holds weak references. The task vanishes silently, its exception is never retrieved. ([source](https://mkennedy.codes/posts/fire-and-forget-or-never-with-python-s-asyncio/), [source](https://github.com/python/cpython/issues/104091))

- **Swallowing CancelledError**: A bare `except Exception` or `except BaseException` that suppresses `asyncio.CancelledError` prevents cooperative cancellation and breaks graceful shutdown. Since Python 3.9, CancelledError inherits from BaseException (not Exception), which helps — but bare `except:` still catches it. ([source](https://timderzhavets.com/blog/taming-asyncio-production-patterns-that-prevent-silent/))

- **Unbounded concurrency without backpressure**: `create_task()` never blocks, so spawning without limits under load causes thundering herds, OOM, and connection pool exhaustion. Backpressure must be explicit from day one — retrofitting it requires changing every producer. ([source](https://timderzhavets.com/blog/taming-asyncio-production-patterns-that-prevent-silent/))

- **Restart storms from missing backoff**: Immediately restarting failed tasks without backoff or restart budgets causes tight failure loops consuming all CPU. OTP solves this with supervisor intensity limits; Celery/Dramatiq use exponential backoff with jitter. Any supervision system needs both backoff and a circuit breaker. ([source](https://www.erlang.org/doc/system/sup_princ.html), [source](https://blog.gitguardian.com/celery-tasks-retries-errors/))

## Emerging Trends

**Structured concurrency entering language standards**: Python's TaskGroup (3.11), Java's StructuredTaskScope (JEP 453), Swift's task groups, and Kotlin's coroutineScope all represent mainstream adoption. The Python community is actively discussing bringing cancel scopes and channels from AnyIO/Trio into stdlib asyncio. ([source](https://discuss.python.org/t/adopt-proven-anyio-trio-patterns-natively-into-asyncio-multi-release-roadmap/106067))

**Hybrid patterns: structured concurrency + supervision**: The gap between TaskGroup's "cancel all" and OTP's "restart one" is recognized as unsolved in Python. Backend.AI's PersistentTaskGroup and similar custom implementations show demand for a middle ground. No standard library solution exists yet, but combining ExceptionGroup handling (`except*`) with custom task groups that selectively restart failures is becoming common. ([source](https://www.backend.ai/blog/2022-03-PersistentTaskGroup))

**Async generator cancellation safety (PEP 789)**: Async generators yielding inside cancel scopes can leak cancellation across boundaries — relevant for services using async generators for streaming (WebSocket streams, event feeds). ([source](https://peps.python.org/pep-0789/))

## Relevance to Us

Hassette's TaskBucket is essentially **Pattern 3 (Persistent Task Group)** — error-isolating task scope with no sibling cancellation. Combined with ServiceWatcher's RestartSpec (restart types, sliding-window budgets, backoff, error routing), hassette has independently converged on the **hybrid Pattern 2 + Pattern 3** approach that multiple production services have arrived at. This is validating — it's the pragmatic sweet spot for long-running async services that need error isolation without process overhead.

**What we're doing well:**
- **Task tracking via context-variable task factory** — every spawned task is automatically registered, preventing the orphan/GC anti-pattern. This is more robust than manual "save a reference" patterns.
- **Per-task exception recorders** — error isolation without sibling cancellation, matching the PersistentTaskGroup pattern.
- **Wave-based hierarchical shutdown** — matches the three-phase pattern (stop accepting → drain with timeout → force cleanup), with per-wave and total timeout budgets.
- **ServiceWatcher's RestartSpec** — restart types (PERMANENT, TRANSIENT, TEMPORARY), sliding-window budgets, backoff parameters, and error routing. This is recognizably OTP-inspired supervision, adapted for async Python.

**Gaps worth examining:**

1. **No concurrency limits in TaskBucket itself**: Backpressure is managed at the subsystem level (BusService in-flight tracking, SchedulerService fair locking), but TaskBucket has no built-in bound. Under pathological conditions (event storm from HA), tasks can be spawned without limit. A semaphore-based `max_concurrent` on TaskBucket (like Elixir's `max_children`) would add a safety floor. Whether this is worth adding depends on whether the subsystem-level backpressure is sufficient in practice.

2. **WeakSet for task tracking**: TaskBucket uses a `WeakSet` with strong references maintained through done callbacks. This works but is exactly the pattern that the Python core team calls "fragile and error-prone" (cpython [#104091](https://github.com/python/cpython/issues/104091)). A regular set with explicit cleanup on task completion would be more robust and eliminate the GC race window.

3. **No cancel scope composability**: Trio/AnyIO's cancel scopes provide timeout and deadline management orthogonal to task groups. Hassette handles timeouts at the shutdown level (per-wave, total) but doesn't expose scoped timeouts for arbitrary task groups. This may not be needed for the home automation domain, but is worth noting as the ecosystem moves toward this pattern.

4. **CancelledError handling audit**: The "refused to die" logging in `cancel_all()` correctly identifies tasks that survive cancellation. Worth auditing whether any handler code accidentally catches CancelledError (the swallowing anti-pattern), which would cause those tasks to appear to hang during shutdown.

## Recommendation

Hassette's TaskBucket + ServiceWatcher combination is well-positioned in the design space — it's independently arrived at the hybrid structured-concurrency + supervision pattern that the ecosystem is converging on. The architecture doesn't need a fundamental redesign.

Two targeted improvements are worth considering:

1. **Upgrade task set from WeakSet to regular Set** — eliminate the GC race window that the CPython core team has flagged as problematic. The done-callback cleanup pattern already maintains effective strong references; making them explicit reduces fragility. Low-risk change.

2. **Optional concurrency bound on TaskBucket** — a `max_tasks` parameter backed by an asyncio.Semaphore, similar to Elixir's `max_children`. Default to unbounded (current behavior) but allow subsystems to opt into a safety floor. This would complement the existing subsystem-level backpressure rather than replace it.

A CancelledError audit across handler code would also be a quick win — the shutdown timeout infrastructure is solid, but tasks that accidentally swallow CancelledError undermine it silently.

## Sources

### Reference implementations
- https://docs.python.org/3/library/asyncio-task.html — Python asyncio.TaskGroup documentation
- https://trio.readthedocs.io/en/stable/reference-core.html — Trio nurseries
- https://deepwiki.com/agronholm/anyio/2.2-task-groups-and-structured-concurrency — AnyIO task groups
- https://www.erlang.org/doc/system/sup_princ.html — Erlang/OTP supervisor behaviour
- https://hexdocs.pm/elixir/Task.Supervisor.html — Elixir Task.Supervisor
- https://docs.celeryq.dev/en/stable/userguide/tasks.html — Celery task documentation
- https://dramatiq.io/guide.html — Dramatiq user guide
- https://pkg.go.dev/golang.org/x/sync/errgroup — Go errgroup
- https://appdaemon.readthedocs.io/en/stable/INTERNALS.html — AppDaemon internals

### Blog posts & writeups
- https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/ — Nathaniel Smith's foundational structured concurrency post
- https://www.backend.ai/blog/2022-03-PersistentTaskGroup — Backend.AI PersistentTaskGroup
- https://timderzhavets.com/blog/taming-asyncio-production-patterns-that-prevent-silent/ — Production asyncio patterns
- https://sailor.li/asyncio — asyncio sharp corners critique
- https://mkennedy.codes/posts/fire-and-forget-or-never-with-python-s-asyncio/ — Fire-and-forget GC problem
- https://mattwestcott.org/blog/structured-concurrency-in-python-with-anyio — AnyIO migration guide
- https://ksysoev.github.io/posts/errgroup/ — Go errgroup service management
- https://blog.gitguardian.com/celery-tasks-retries-errors/ — Celery retry resilience patterns

### Documentation & standards
- https://peps.python.org/pep-0654/ — PEP 654: Exception Groups
- https://peps.python.org/pep-0789/ — PEP 789: Async generator cancellation safety
- https://tokio.rs/tokio/topics/shutdown — Tokio graceful shutdown
- https://tech-champion.com/programming/python-programming/manage-async-i-o-backpressure-using-bounded-queues-and-timeouts/ — asyncio backpressure patterns

### Issues & discussions
- https://github.com/python/cpython/issues/104091 — create_task() strong reference discussion
- https://discuss.python.org/t/adopt-proven-anyio-trio-patterns-natively-into-asyncio-multi-release-roadmap/106067 — Structured concurrency in stdlib asyncio proposal
