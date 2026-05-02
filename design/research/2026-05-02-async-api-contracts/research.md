---
topic: "async API contract design — when to return Task vs await vs fire-and-forget"
date: 2026-05-02
status: Draft
---

# Prior Art: Async API Contract Design

## The Problem

A Python async framework's public methods must communicate their lifecycle semantics through their signatures. Three choices exist: `async def` (caller awaits, work completes on return), sync def returning `asyncio.Task` (caller gets a handle, may or may not use it), and sync def returning `None` (fire-and-forget, no handle). Each creates a different contract about error propagation, completion guarantees, and caller responsibility.

When these patterns are mixed inconsistently — similar operations using different contracts without clear rationale — callers must learn multiple mental models, and the framework's error handling becomes unpredictable. The Python async ecosystem has strong opinions about this, converging on structured concurrency principles that reject "detached tasks" as fundamentally unsafe.

## How We Do It Today

Hassette uses all three patterns across its core APIs:

**Pattern A — Sync returning Task (Bus):** `Bus.add_listener()`, `remove_listener()`, `remove_all_listeners()`, `get_listeners()` are all sync defs that return `asyncio.Task`. The rationale: these perform synchronous validation/collision checks immediately, then spawn async I/O (route insertion, DB registration) in the background. Callers *can* await for completion guarantees but typically don't.

**Pattern B — Async def (TelemetryRepository):** `register_listener()`, `register_job()`, `persist_batch()`, etc. are all async methods awaited via `DatabaseService.submit()`. Pure I/O with no synchronous preconditions; callers always await.

**Pattern C — Fire-and-forget void (Scheduler):** `cancel_job()`, `cancel_group()` are sync defs returning `None`. Synchronous state mutation (heap removal) is the real contract; the async DB write is spawned separately via `task_bucket.spawn()` and never observed by the caller.

The inconsistency: `Bus.add_listener()` and `Scheduler.cancel_job()` serve similar roles ("do this, I don't need to wait") but use different patterns (Task return vs. void). Both spawn background I/O that the caller doesn't observe.

## Patterns Found

### Pattern 1: Pure Coroutine (async def, caller awaits)

**Used by**: HTTPX, aiohttp, asyncpg, most well-designed async Python libraries

**How it works**: Every public method is `async def` and returns the operation's result. The caller `await`s it; when the await completes, the work is done. The library never spawns background tasks on behalf of the caller. Concurrency is the caller's responsibility (via TaskGroup/gather).

This is the default for operations where: the caller needs the result, the operation has a natural completion point, and errors should propagate to the caller.

**Strengths**: Maximum composability. Errors propagate naturally. No lifecycle surprises. Type signatures clearly communicate behavior. Easy to test. Works with any concurrency primitive.

**Weaknesses**: Cannot express "start this and let it run" without the caller managing concurrency. Sequential by default.

**Example**: https://www.python-httpx.org/async/

### Pattern 2: Scoped Spawn (sync def returning None, within a scope owner)

**Used by**: Trio nurseries (`start_soon`), AnyIO task groups (`start_soon`), asyncio.TaskGroup (`create_task`)

**How it works**: A sync method on a scope object spawns a task that the scope guarantees to await at scope exit. The method is deliberately sync and returns nothing (AnyIO/Trio) or a Task handle for inspection only (asyncio). The contract: "I'll start this, the scope will wait for it, and if it fails the scope handles it."

The caller gives up direct control in exchange for a no-orphan guarantee. The scope cancels children on failure, propagates exceptions via ExceptionGroup, and blocks at exit until all children complete.

This is the pattern for: "I need things running concurrently within a bounded lifetime, but I don't need individual results."

**Strengths**: Structured concurrency guarantee. No orphaned tasks, no lost exceptions. Clear ownership model. Sync signature signals "non-blocking but not fire-and-forget."

**Weaknesses**: Requires a scope object (adds nesting). asyncio's returning of Task confuses people. Cannot express "run forever" without the scope also running forever.

**Example**: https://anyio.readthedocs.io/en/stable/tasks.html

### Pattern 3: Scoped Spawn with Readiness Signal (async def, blocks until "started")

**Used by**: Trio (`nursery.start()`), AnyIO (`task_group.start()`)

**How it works**: An async method spawns a task and blocks until the task signals initialization complete (via `task_status.started(value)`). The task continues running in the background within the scope. The awaited return value communicates "what did the task set up."

Solves the "server startup" problem: spawn a long-running service, know when it's ready, let it run. Without this, you need separate Events or polling.

**Strengths**: Solves initialization races cleanly. The awaited value communicates setup state. Still structured. The `async def` signature honestly communicates "this blocks."

**Weaknesses**: Requires task cooperation (`started()` call). Not available in stdlib asyncio.TaskGroup. Can deadlock if task never calls `started()`.

**Example**: https://trio.readthedocs.io/en/stable/reference-core.html

### Pattern 4: Fire-and-Forget with Infrastructure Error Handling

**Used by**: Celery (`task.delay()`), Dramatiq (`actor.send()`), FastAPI BackgroundTasks, cloud task queues

**How it works**: A sync method submits work to an external execution system and returns immediately. Errors are handled out-of-band: retries, dead-letter queues, monitoring alerts, error callbacks. The caller never sees exceptions — they are the infrastructure's problem.

Returned handles (AsyncResult, Message) exist for monitoring/debugging, not correctness. Ignoring them is the expected pattern. The work may execute later, possibly on a different machine.

Legitimate when: work is cross-process/cross-machine, should survive caller's death, or caller genuinely cannot use the result (e.g., post-response email sending).

**Strengths**: True decoupling. Survives process restarts. Scales horizontally. Natural for eventual consistency.

**Weaknesses**: Errors invisible to caller. No structured concurrency guarantee. Requires monitoring infrastructure (retries, DLQ, alerting) or errors are simply lost. Testing requires mocking the queue.

**Example**: https://www.fullstackpython.com/celery.html

### Pattern 5: Hybrid Handle (sync def returning Task, caller optionally awaits)

**Used by**: asyncio.create_task() (bare, outside TaskGroup), some older asyncio libraries, internal framework plumbing

**How it works**: A sync method creates a Task and returns it. The caller may await it, add callbacks, or forget about it. The Task runs regardless. This is the "detached task" pattern.

**This is widely considered an anti-pattern.** CPython issue #104091 documents community consensus against it. If nobody awaits the Task, exceptions produce only a warning log. The garbage collector may destroy the Task before completion (requiring the `background_tasks = set()` hack). This violates structured concurrency: tasks have no owner.

**Strengths**: Maximum flexibility. Simple for prototypes. No nesting required.

**Weaknesses**: No ownership guarantee — orphan risk. Silent exception loss. GC destruction risk. Violates structured concurrency. Community consensus is moving away from this.

**Example**: https://github.com/python/cpython/issues/104091 (documented as anti-pattern)

## Anti-Patterns

- **Returning Task objects that callers ignore**: The `background_tasks = set()` pattern is the canonical anti-pattern. If callers don't need the handle, don't return one. Use scoped spawning instead. Source: https://github.com/python/cpython/issues/104091

- **Mixing async-def and sync-def-returning-Task for similar operations**: When `async def get_state()` coexists with `def schedule_task() -> Task`, callers must learn two mental models. Trio/AnyIO avoid this: all completing operations are `async def`; all spawning uses explicit scope methods. Source: https://anyio.readthedocs.io/en/stable/why.html

- **Fire-and-forget without error handling strategy**: Spawning work with no owner and no error handler means lost errors. Legitimate fire-and-forget (Pattern 4) always pairs with infrastructure-level error handling. In-process fire-and-forget without such infrastructure is simply silent failure. Source: https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/

- **Using return type as sole indicator of lifecycle semantics**: `None` could mean "fire-and-forget" or "scoped spawn." `Task` could mean "you must await" or "you may ignore." The type alone is ambiguous. Good APIs encode semantics in method names (Trio's `start_soon` vs `start`). Source: https://trio.readthedocs.io/en/stable/reference-core.html

## Emerging Trends

- **Structured concurrency becoming the Python default**: Python 3.11 added TaskGroup, 3.12 added eager task factories, and there's active discussion about making eager factories the default. The ecosystem converges on "tasks should be scoped, not detached." Libraries returning bare Tasks are increasingly seen as legacy.

- **Coroutine-vs-Task distinction becoming an optimization detail**: With eager task factories, `create_task()` may complete synchronously for fast paths. This suggests APIs should expose semantic contracts (`async def` = done when await returns) rather than scheduling mechanisms (Task = scheduled). Source: https://discuss.python.org/t/make-asyncio-eager-task-factory-default/75164

- **Two-tier spawn API as cross-library consensus**: Trio, AnyIO, and asyncio.TaskGroup all converge on two spawning methods: `start_soon` (fire within scope, don't wait) and `start` (fire within scope, wait until ready). This is becoming the expected API shape.

## Relevance to Us

Hassette's situation maps directly to the patterns above:

**Bus.add_listener() → Pattern 5 (Hybrid Handle)**: Returns a Task that callers typically ignore. Per community consensus, this is the anti-pattern. *However*, hassette's implementation has a nuance: the Bus has its own scope (TaskBucket) that owns these Tasks. The Tasks aren't truly "detached" — TaskBucket tracks them and handles errors via exception recorders. So hassette has Pattern 5's *signature* but Pattern 2's *lifecycle semantics*. The returned Task is not needed for correctness.

**Scheduler.cancel_job() → Pattern 2 (Scoped Spawn)**: Void return, background I/O owned by TaskBucket. This is actually the correct pattern per structured concurrency principles. The scope (TaskBucket) owns the spawned work.

**TelemetryRepository → Pattern 1 (Pure Coroutine)**: All async def, all awaited. Textbook correct.

**The inconsistency**: Bus and Scheduler serve the same role (user-facing resource API) but Bus returns Tasks (Pattern 5 signature) while Scheduler returns None (Pattern 2 signature). Both spawn background work into TaskBucket. The Bus *could* return None like the Scheduler without losing any functionality — callers don't use the returned Task for correctness.

**Key insight**: Hassette's underlying lifecycle management (TaskBucket + exception recorders) already provides the error handling guarantees that structured concurrency demands. The problem is purely at the API signature level — the Bus exposes Pattern 5's confusing interface while internally implementing Pattern 2's semantics.

## Recommendation

The ecosystem guidance is clear and directly applicable:

**Convention to adopt:**

1. **Operations that complete → `async def`** (Pattern 1): Methods where the caller needs the result or where completion is the contract. `TelemetryRepository` already does this correctly.

2. **Operations that spawn background work → sync def returning `None`** (Pattern 2): Methods where the real contract is "I've accepted your request" and the async work is owned by an internal scope. `Scheduler.cancel_job()` already does this correctly. `Bus.add_listener()` should switch to this.

3. **Operations that spawn AND the caller needs to know when ready → `async def`** (Pattern 3): Methods where there's a meaningful "initialized" signal. Consider for `Bus.add_listener()` if callers need to know when the listener is actually registered in the DB (vs. just accepted for registration).

4. **Never Pattern 5**: Don't return Task objects that callers are expected to ignore. If the scope owns the task, the caller doesn't need a handle.

**Specific recommendations for the audit (#646):**

- `Bus.add_listener()` / `remove_listener()` / `remove_all_listeners()`: Change to return `None`. TaskBucket already owns the spawned work. If any caller actually awaits these (check during audit), consider whether they need an `async def` version instead.
- `Bus.get_listeners()`: This is different — callers need the result. Should be `async def get_listeners() -> list[Listener]` (Pattern 1).
- `Scheduler._remove_all_jobs()`: Private, returns Task, awaited in `on_shutdown`. Should be `async def` since it's always awaited.
- Document the convention: "sync returning None = accepted, work in progress; async def = work complete on return."

**The naming question**: Consider whether method names should signal the dispatch pattern (Trio's `start_soon` vs `start` convention). For hassette, the distinction might be: methods that complete synchronous validation and spawn async side-effects could use a naming convention (e.g., no prefix = sync with background I/O, `await` in examples = async). But this might be over-engineering for the current API surface.

## Sources

### Design manifestos & thought leadership
- https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/ — Nathaniel Smith on why fire-and-forget is "goto for concurrency"
- https://hynek.me/articles/waiting-in-asyncio/ — Hynek Schlawack's asyncio waiting cheatsheet

### Library design documentation
- https://trio.readthedocs.io/en/stable/reference-core.html — Trio nursery API (start_soon / start)
- https://anyio.readthedocs.io/en/stable/tasks.html — AnyIO task spawning design
- https://anyio.readthedocs.io/en/stable/why.html — AnyIO design rationale vs asyncio
- https://www.python-httpx.org/async/ — HTTPX pure-coroutine library design

### Standard library & community discussion
- https://docs.python.org/3/library/asyncio-task.html — asyncio.TaskGroup documentation
- https://github.com/python/cpython/issues/104091 — CPython issue on create_task anti-pattern
- https://discuss.python.org/t/make-asyncio-eager-task-factory-default/75164 — Eager task factory discussion
- https://en.wikipedia.org/wiki/Structured_concurrency — Structured concurrency overview

### Framework patterns
- https://fastapi.tiangolo.com/tutorial/background-tasks/ — FastAPI background tasks (legitimate fire-and-forget)
- https://www.fullstackpython.com/celery.html — Celery AsyncResult pattern
- https://oneuptime.com/blog/post/2026-01-24-python-task-queues-dramatiq/view — Dramatiq fire-and-forget design
