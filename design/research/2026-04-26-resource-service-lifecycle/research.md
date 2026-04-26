---
topic: "Python async resource/service lifecycle architecture"
date: 2026-04-26
status: Draft
---

# Prior Art: Python Async Resource/Service Lifecycle Architecture

## The Problem

Any framework that manages multiple long-lived async components needs to answer: how do components start up (in what order, with what dependencies), how do they signal readiness, how do they shut down cleanly, and how does the framework protect its own lifecycle machinery from being broken by user code? The answers to these questions form the "resource lifecycle" layer — the foundation everything else builds on.

Hassette solved these problems early in its development and has built significant functionality on top. This survey compares those foundational decisions against what respected Python async frameworks do, looking for gaps that will cause pain at scale and confirming what's already well-designed.

## How We Do It Today

Hassette uses a three-layer class hierarchy: `LifecycleMixin` (status FSM, ready/shutdown events, transition handlers) → `Resource` (child tracking, dependency ordering via `depends_on` + topological sort, before/on/after hook triplets, FinalMeta override protection) → `Service` (background `serve()` task with deferred readiness). `App` extends Resource as the user-facing automation class. Shutdown is LIFO with continue-on-error and force-terminal timeouts. TaskBucket tracks spawned tasks with strong references.

## Patterns Found

### Pattern 1: Service State Machine with Explicit Transitions

**Used by**: Mode/Faust, hassette, Home Assistant
**How it works**: Services move through defined states (NOT_STARTED → STARTING → RUNNING → STOPPED, with FAILED/CRASHED branches). Each transition is guarded by methods that check current state and emit events. Mode derives state from which asyncio.Events are set; hassette uses an explicit ResourceStatus enum with a setter tracking previous state; HA uses ConfigEntryState.

The key design choice is derived state (Mode: "running means started but not stopped") vs explicit state (hassette: enum set by handle_* methods). Derived state has fewer invalid combinations but is harder to debug. Explicit state is clearer but requires disciplined transition guards.

**Strengths**: Makes lifecycle bugs visible. Enables UI monitoring. Guards against double-init/double-shutdown. Enables telemetry.
**Weaknesses**: State machines add complexity. Edge cases (shutdown during init, re-init after failure) need careful handling.
**Example**: https://faust.readthedocs.io/en/latest/_modules/mode/services.html

**Verdict: ✅ Solid as-is.** Hassette's explicit enum approach is the right call for a framework with a monitoring UI — derived state would make the dashboard harder to build. The status set is appropriate for the domain.

---

### Pattern 2: Beacon / Service Tree for Dependency Visualization

**Used by**: Mode/Faust
**How it works**: Each service holds a `beacon` reference positioning it in a directed graph. Beacons enable tree traversal, crash propagation, and GraphViz visualization of the running system. The beacon is separate from the service — a graph node tracking relationships rather than owning lifecycle logic.

**Strengths**: Debugging tool (render service tree as a graph). Crash propagation follows the tree. Decouples relationship tracking from lifecycle management.
**Weaknesses**: Extra indirection. Most users never visualize the graph. Memory overhead per service.
**Example**: https://mode.readthedocs.io/en/latest/introduction.html

**Verdict: ✅ Not needed.** Hassette already has a web dashboard showing the resource tree with status. The parent/children list on Resource serves the same structural role as Mode's beacons without the extra abstraction layer. If tree visualization becomes needed, it can be derived from the existing children list.

---

### Pattern 3: Cleanup Context / Yield-Based Lifecycle Pairing

**Used by**: aiohttp (cleanup_ctx), FastAPI/Starlette (lifespan), Python contextlib
**How it works**: Resources define lifecycle as an async generator that yields once. Code before `yield` runs during startup; code after `yield` runs during shutdown. The framework guarantees cleanup only runs if startup succeeded. Multiple contexts compose via AsyncExitStack with automatic LIFO teardown.

```python
async def database_lifecycle(app):
    db = await connect_database()
    yield  # app runs here
    await db.close()
```

**Strengths**: Setup/teardown co-located (easier to audit for leaks). Guaranteed cleanup-only-if-started. Composes via AsyncExitStack. No separate registration.
**Weaknesses**: Only supports a single yield point (can't express "partially started"). Not suitable for long-running background services. Doesn't support before/on/after granularity.
**Example**: https://docs.aiohttp.org/en/stable/web_advanced.html

**Verdict: ⚠️ Relevant for the App layer.** The yield-based pattern doesn't replace hassette's Resource/Service lifecycle (which needs the full hook machinery for framework internals), but it would be a natural addition for **user-facing App lifecycle**. Today, if `on_initialize` fails after partially setting up resources, `on_shutdown` still runs and may try to clean up things that were never created. A cleanup_ctx-style option for Apps would prevent this class of bugs.

**Potential issue**: Add optional yield-based lifecycle for Apps (cleanup_ctx pattern) — co-locate setup/teardown to prevent cleanup-without-init bugs.

---

### Pattern 4: Ready Signaling via task_status.started()

**Used by**: Trio (nursery.start), AnyIO (TaskGroup.start), Mode (on_started hook)
**How it works**: Parent spawns child and blocks until child explicitly signals readiness. In AnyIO, the child calls `task_status.started(value)` which unblocks the parent. Errors during startup propagate immediately. If the service never signals, the parent gets a RuntimeError (AnyIO) or blocks forever (Trio without timeout).

**Strengths**: Prevents use-before-ready. Immediate error propagation. Parent can receive a value from the child.
**Weaknesses**: Forgetting `started()` blocks the parent. One-shot only — can't toggle readiness.
**Example**: https://anyio.readthedocs.io/en/stable/tasks.html

**Verdict: ✅ Hassette's approach is more flexible and better-suited.** Hassette's `mark_ready()`/`mark_not_ready()` allows toggling readiness over time, which is essential for a Home Assistant framework where WebSocket connections drop and reconnect. The Trio/AnyIO pattern is one-shot — once started, always started. Hassette's event-driven approach with `wait_ready(timeout)` racing against `shutdown_event` is clean and well-implemented.

---

### Pattern 5: LIFO Shutdown with Timeout and Force-Terminal

**Used by**: hassette, Mode/Faust, aiohttp, AsyncExitStack (implicitly)
**How it works**: Resources shut down in reverse initialization order. Each gets a timeout for graceful shutdown. Exceeded timeouts trigger force-termination (task cancellation, terminal state). Children shut down before parents.

Mode reverses child registration order. aiohttp uses a 7-step sequence. AsyncExitStack provides LIFO naturally. Hassette's `_ordered_children_for_shutdown()` returns `reversed(self.children)` with gather-based parallel shutdown of siblings.

**Strengths**: Prevents resource-use-after-close. Timeouts prevent hanging. Force-terminal is a safety valve.
**Weaknesses**: Gather-based parallel shutdown can mask sibling ordering issues. Force-terminal skips hooks.
**Example**: https://faust.readthedocs.io/en/latest/_modules/mode/services.html

**Verdict: ✅ Solid.** LIFO + continue-on-error + force-terminal is the consensus pattern across all surveyed frameworks. The gather-based sibling shutdown is a reasonable tradeoff (speed vs strict ordering) for hassette's scale. aiohttp's more granular 7-step shutdown (stop listening → close idle → signal → wait → cancel → cleanup) is worth noting but is web-server-specific and not directly transferable.

---

### Pattern 6: Hook Triplets (before/on/after)

**Used by**: hassette (unique in surveyed frameworks)
**How it works**: Three hooks per lifecycle phase: before (preparation), on (core logic), after (finalization). `initialize()` is `@final` so users override hooks, not the orchestration method. Mode uses `on_start`/`on_stop` single hooks with `super()` discipline. Most other frameworks use single hooks or context managers.

**Strengths**: No super() call discipline needed. Framework can inject cross-cutting concerns in before/after. Clean separation.
**Weaknesses**: Uncommon — 6 lifecycle hooks is more API surface. In practice, most resources only use `on_initialize` and `on_shutdown`. The before/after hooks are underutilized.
**Example**: [no external source — pattern is specific to hassette]

**Verdict: ⚠️ Works but overbuilt for the common case.** The triplet design is sound for framework-internal resources that need before/after injection points (telemetry, validation). But for user-facing Apps, 6 hooks is a lot of API surface when nearly all apps only use `on_initialize`/`on_shutdown`. This isn't urgent to change — the unused hooks don't hurt — but it's worth auditing whether any framework resource actually uses `before_initialize` or `after_shutdown` for their intended purpose vs. just using `on_initialize` for everything.

**Potential issue**: Audit before/after hook usage — if no resource uses them for their intended purpose, consider deprecating them or moving to a plugin/middleware model for cross-cutting concerns.

---

### Pattern 7: Structured Concurrency via Task Groups

**Used by**: Trio (nurseries), AnyIO (TaskGroup), Python 3.11+ asyncio (TaskGroup)
**How it works**: All tasks spawned within an explicit scope (async context manager). The scope guarantees: the block doesn't exit until all tasks complete, any child failure cancels siblings, exceptions collected as ExceptionGroup, no orphaned tasks can escape.

**Strengths**: Eliminates orphaned tasks by construction. Automatic exception propagation. Guaranteed cleanup.
**Weaknesses**: Doesn't directly model long-lived services (TaskGroup exits when tasks complete). Python 3.11 TaskGroup lacks Trio's `start()`.
**Example**: https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/

**Verdict: ⚠️ TaskBucket is the right concept but could evolve.** Hassette's TaskBucket serves the nursery role — strong references, tracked spawning, cleanup on shutdown. However, `task_bucket.spawn()` is "structured-ish" rather than fully structured: tasks are tracked and cleaned up, but there's no scope boundary preventing orphans by construction. For hassette's current scale (home automation, not distributed systems), this is fine. The direction to watch is whether Python 3.13+ TaskGroup gains enough features to replace TaskBucket entirely.

**Potential issue**: Evaluate TaskGroup migration path — could TaskBucket's spawn/cleanup model be backed by asyncio.TaskGroup instead of manual WeakSet tracking? This would get automatic exception propagation and stronger lifetime guarantees. Not urgent but worth tracking as Python's TaskGroup matures.

---

### Pattern 8: Dependency-Ordered Startup with Auto-Retry

**Used by**: Home Assistant (config entry SETUP_RETRY), python-dependency-injector
**How it works**: When dependencies aren't ready during startup, the framework schedules retry with progressive backoff instead of failing immediately. HA enters SETUP_RETRY state and automatically reschedules. python-dependency-injector uses `asyncio.gather()` to resolve independent dependencies concurrently.

**Strengths**: Handles transient startup failures. Reduces ordering sensitivity. Progressive backoff prevents thundering herd.
**Weaknesses**: Can mask real failures. Harder to debug. More complex state machine.
**Example**: https://developers.home-assistant.io/docs/config_entries_index/

**Verdict: ⚠️ Two actionable gaps here.**

1. **Sequential dependency waiting**: Hassette's `_auto_wait_dependencies()` waits for each dependency sequentially. If a resource depends on A and B, it waits for A, then B — even if B was already ready. Using `asyncio.gather()` for independent deps would reduce startup time. For hassette's current scale this is measured in milliseconds, but it's a correctness improvement (the code should express that A and B are independent).

2. **No retry on transient failure**: If a dependency isn't ready within the timeout, hassette fails the resource permanently. HA's auto-retry with backoff is more resilient for home automation scenarios where the WebSocket connection might not be established yet when apps try to initialize. This is particularly relevant for hassette since it manages a long-lived WebSocket connection to HA that may reconnect.

**Potential issue 1**: Parallelize independent dependency waiting with asyncio.gather()
**Potential issue 2**: Add auto-retry with backoff for dependency unavailability (HA's SETUP_RETRY pattern)

---

## Anti-Patterns

### 1. Fire-and-Forget Task Spawning
**Sources**: [Taming Asyncio](https://timderzhavets.com/blog/taming-asyncio-production-patterns-that-prevent-silent/), [Structured Concurrency](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/)
Creating tasks without storing references lets GC silently cancel them. **Hassette avoids this** — TaskBucket holds strong references and tracks all spawned tasks.

### 2. Synchronous Shutdown Blocking the Event Loop
**Source**: [AppDaemon docs](https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html)
AppDaemon's synchronous `terminate()` can hang the entire system. **Hassette avoids this** — all shutdown hooks are async with timeouts.

### 3. Unpaired Cleanup Handlers
**Source**: [aiohttp docs](https://docs.aiohttp.org/en/stable/web_advanced.html)
Independent on_startup/on_cleanup signal handlers run cleanup even if startup never succeeded. **Hassette is partially exposed** — if `on_initialize` fails after creating some resources, `on_shutdown` still runs. The cleanup_ctx pattern (Pattern 3) addresses this.

### 4. Implicit Ready Assumptions
**Sources**: [AnyIO docs](https://anyio.readthedocs.io/en/stable/tasks.html), [Mode docs](https://mode.readthedocs.io/en/latest/introduction.html)
Assuming readiness based on task creation rather than explicit signal. **Hassette avoids this** — explicit `mark_ready()` / `wait_ready()`.

## Emerging Trends

### Context Manager as Universal Lifecycle Primitive
The ecosystem is converging on `async with` as the standard lifecycle primitive. FastAPI's lifespan, aiohttp's cleanup_ctx, and Python 3.11's TaskGroup all use this pattern. The trend is away from paired callbacks toward co-located setup/teardown.

### Structured Concurrency in stdlib
Python 3.11 added `asyncio.TaskGroup`, Python 3.12+ is extending it. The direction is making structured concurrency the default, not an opt-in library choice.

### AsyncExitStack for Composable Lifecycle
The FastAPI community's adoption of AsyncExitStack for composing independent lifespans is becoming standard. LIFO teardown ordering comes for free.

### Explicit Dependency Graphs Over Convention
Frameworks are moving from priority ordering (AppDaemon's `priority: 10`) to explicit dependency declarations. Python's stdlib `graphlib.TopologicalSorter` makes this accessible. Hassette's `depends_on` is aligned with this trend.

## Relevance to Us

**Well-validated decisions:**
- The Resource/Service/App taxonomy maps cleanly to Mode/Faust's hierarchy — hassette is in good company
- Explicit status enum (vs Mode's derived state) is the right call given the monitoring UI
- Event-driven ready signaling with toggleable readiness is more capable than Trio/AnyIO's one-shot pattern
- LIFO shutdown with timeouts and force-terminal is the consensus pattern
- TaskBucket's strong-reference task tracking avoids the #1 asyncio production bug
- Topological dependency ordering is aligned with the industry trend away from priority-based ordering
- FinalMeta preventing lifecycle override is a stronger guarantee than any surveyed framework offers (most rely on typing.final or documentation)

**Gaps and improvement opportunities:**
1. **Cleanup-without-init risk in Apps** — The before/on/after hook pattern doesn't guarantee that cleanup only runs if setup succeeded. The yield-based cleanup_ctx pattern would fix this for user-facing Apps.
2. **Sequential dependency waiting** — Independent dependencies are waited on sequentially, not in parallel. Small perf impact today but a correctness concern (code should express independence).
3. **No auto-retry for dependency unavailability** — Hard failure on timeout rather than HA-style progressive retry. Relevant for long-lived daemon with reconnecting WebSocket.
4. **Hook triplet overbuilding** — 6 lifecycle hooks when most resources use 2. Worth auditing usage and potentially simplifying the App-facing API.
5. **TaskBucket vs structured concurrency** — TaskBucket is "structured-ish" (tracked, cleaned up) but not fully structured (no scope boundary). Worth tracking asyncio.TaskGroup evolution as a potential backend.
6. **App depends_on unsupported** — Issue #581 already tracks this. The topological infrastructure exists but App subclasses can't use it yet.

## Recommendation

The architecture is fundamentally sound and well-aligned with patterns from Mode/Faust, the closest Python analog. The core decisions (explicit state machine, event-driven readiness, LIFO shutdown, dependency-based ordering, FinalMeta protection) are all validated by prior art. No ❌ "should change" findings.

The two highest-value improvements are:
1. **Cleanup_ctx pattern for Apps** — prevents a real class of bugs (cleanup-without-init) with a pattern the Python ecosystem has converged on
2. **Auto-retry with backoff for dependency unavailability** — directly relevant to hassette's operational reality (HA WebSocket reconnections)

The other findings (parallel dep resolution, hook audit, TaskGroup evolution) are lower priority but worth tracking as issues.

## Sources

### Reference Implementations
- https://faust.readthedocs.io/en/latest/_modules/mode/services.html — Mode/Faust Service class (closest analog)
- https://mode.readthedocs.io/en/latest/introduction.html — Mode dependency and beacon patterns

### Documentation
- https://developers.home-assistant.io/docs/config_entries_index/ — HA config entry lifecycle with auto-retry
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon app lifecycle
- https://anyio.readthedocs.io/en/stable/tasks.html — AnyIO TaskGroup.start() ready signaling
- https://docs.aiohttp.org/en/stable/web_advanced.html — aiohttp cleanup contexts
- https://fastapi.tiangolo.com/advanced/events/ — FastAPI lifespan context manager
- https://docs.python.org/3/library/graphlib.html — stdlib TopologicalSorter
- https://peps.python.org/pep-0591/ — PEP 591 typing.final
- https://python-dependency-injector.ets-labs.org/providers/async.html — Async dependency resolution

### Blog Posts & Experience Reports
- https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/ — Structured concurrency foundation
- https://www.elastic.co/blog/async-patterns-building-python-service — Elastic production async patterns
- https://timderzhavets.com/blog/taming-asyncio-production-patterns-that-prevent-silent/ — Production task management patterns

### Community Discussions
- https://github.com/fastapi/fastapi/discussions/9397 — AsyncExitStack lifecycle composition

Note: URLs were captured during web research and have not been live-verified.
