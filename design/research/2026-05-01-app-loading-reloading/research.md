---
topic: "App Loading and Reloading"
date: 2026-05-01
status: Draft
---

# Prior Art: App Loading and Reloading

## The Problem

Automation frameworks that load user-written code face a core tension: how do you pick up code changes without restarting the entire framework? The answer determines developer experience (how fast is the edit-test cycle), reliability (does a broken user app take down the framework), and operational complexity (what happens to in-flight automations, timers, and subscriptions during a reload).

The problem has several hard sub-problems: module invalidation (Python's import system wasn't designed for it), state preservation (do counters, learned patterns, and connection pools survive a reload), resource cleanup (who guarantees that event subscriptions, scheduled jobs, and WebSocket connections from the old version are torn down), dependency tracking (does changing a shared utility module trigger reload of all apps that use it), and error isolation (a syntax error in one app shouldn't brick the framework).

## How We Do It Today

Hassette uses a **terminate-and-reinitialize** approach. Apps are discovered from `hassette.toml`, loaded by `AppFactory` via dynamic import (cached per file_path+class_name), and each gets its own Bus, Scheduler, and StateManager resources. Reload is all-or-nothing per app: `stop_app()` tears down all resources, evicts the class cache if the file changed, reimports the module, and `start_app()` creates fresh instances. State is not preserved — apps rebuild from scratch. Errors during import, config validation, or initialization are caught and recorded per-app without blocking others. Post-ready reconciliation cleans up stale DB rows from failed sessions. There is no declared dependency graph between user apps; they start concurrently after framework services are ready.

## Patterns Found

### Pattern 1: Terminate-and-Reinitialize

**Used by**: AppDaemon, Hassette (current), many plugin systems

**How it works**: When a code change is detected, the framework calls a teardown hook (`terminate()` in AppDaemon) on the running app instance, clears all registered callbacks and timers, destroys the instance, reloads the module via `importlib.reload()`, creates a new instance, and calls the initialization hook. The framework owns the callback registry and timer schedule, so it can guarantee cleanup even if the user's teardown code is incomplete or crashes. AppDaemon uses AST-based dependency tracking — parsing import statements to determine which apps need reloading when a shared module changes.

**Strengths**: Simple mental model for users — every reload is equivalent to a fresh start. No stale state bugs. Framework-owned cleanup prevents resource leaks even if user code is buggy. Well-tested in production (AppDaemon since ~2016).

**Weaknesses**: State loss on every reload (in-progress automations, accumulated counters, learned patterns). AST-based dependency tracking can miss dynamic imports and `importlib.import_module()` calls (AppDaemon issue [#1135](https://github.com/AppDaemon/appdaemon/issues/1135)). `importlib.reload()` is not thread-safe (CPython [#126548](https://github.com/python/cpython/issues/126548)). Synchronous lifecycle hooks can hang the entire framework if user code blocks in `terminate()`. Module-level side effects (class registrations, singleton patterns) may not be properly undone by reload.

**Example**: https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html

### Pattern 2: Config Entry State Machine (Home Assistant)

**Used by**: Home Assistant (integration config entries)

**How it works**: Each integration instance progresses through a state machine: `NOT_LOADED` → `SETUP_IN_PROGRESS` → `LOADED` (or `SETUP_ERROR` / `SETUP_RETRY`). Unloading transitions through `UNLOAD_IN_PROGRESS`. Reload is unload + setup.

The key innovation is `runtime_data` — a typed storage slot where the integration stores cleanup handles (unsubscribe functions, connection close callbacks). The `async_on_unload()` method registers callbacks that fire automatically on both intentional unload AND setup failure, preventing resource leaks from partial initialization. Platform forwarding (`async_unload_platforms()`) propagates teardown to sub-components.

**Strengths**: Explicit state machine makes lifecycle visible and debuggable. `async_on_unload()` handles the "setup crashed halfway" case — cleanup is registered at resource-acquisition time rather than in a separate teardown method, so partial initialization doesn't leak. `runtime_data` provides structured cleanup-handle storage. Retry with backoff for transient setup failures.

**Weaknesses**: No state preservation (reload = unload + fresh setup). The state machine adds complexity. `FAILED_UNLOAD` state can leave integrations in limbo. No dependency ordering between integrations during reload.

**Example**: https://developers.home-assistant.io/docs/config_entries_index/

### Pattern 3: Graduated Deployment (Node-RED)

**Used by**: Node-RED

**How it works**: Node-RED offers four deployment granularities: `full` (stop all, restart all), `nodes` (stop only modified nodes), `flows` (stop flows containing modified nodes), `reload` (reload from storage, restart all). Each node has `close()` and `init()` lifecycle hooks. During partial deployment, unmodified nodes continue running. The runtime calculates a diff between current and new configuration to determine which nodes are affected.

**Strengths**: Partial deployment minimizes disruption to unrelated flows. Users choose the granularity appropriate to their change. Unmodified nodes keep their state and connections. The diff-based approach is more precise than "reload everything that might be affected."

**Weaknesses**: Node state is lost for any node that gets restarted — no migration path. Partial deploys can leave the system in an inconsistent state if nodes have implicit dependencies. The diff calculation adds complexity. Version conflicts (409 responses) require manual resolution.

**Example**: https://nodered.org/docs/api/admin/methods/post/flows/

### Pattern 4: Suspend-Transform-Resume (Erlang/OTP)

**Used by**: Erlang/OTP (gen_server, gen_statem), Elixir

**How it works**: The BEAM VM maintains two versions of each module simultaneously ("current" and "old"). Local function calls route to the running version; fully-qualified calls route to "current." During supervised upgrade, each process is suspended, new code is loaded, `code_change(OldVsn, State, Extra)` transforms process state from old schema to new, and the process is resumed. State migration is explicit and testable — pattern-matching on old version converts state structures.

**Strengths**: State is preserved across reloads with explicit migration. Connections are not dropped. Two-version coexistence allows graceful migration. Decades of production use in telecom systems.

**Weaknesses**: Extremely complex — described as "one of the most complex parts of OTP" by its own documentation. State migration code must be written and tested for every version pair. Most Elixir teams in practice use rolling deploys instead. Two-version limit means rapid successive changes can cause purge-related crashes. Not applicable to Python (no VM-level code versioning).

**Example**: https://www.erlang.org/doc/system/gen_server_concepts.html

### Pattern 5: Kill-and-Restart (Django/Celery/Gunicorn)

**Used by**: Django (runserver), Celery, Gunicorn (SIGHUP), most Python web frameworks

**How it works**: A parent process monitors files for changes. When detected, the child process is killed and a new one spawned. Django uses `subprocess.call(sys.argv)` in a loop. Celery uses `watchmedo` to kill and restart workers. Gunicorn's SIGHUP reloads config and gracefully restarts workers (in-flight requests complete, but new requests block until new workers are ready). File watching can use polling (Django's StatReloader, ~1.6% CPU) or OS notifications (WatchmanReloader, ~0% CPU idle).

**Strengths**: Maximally simple and reliable. No stale module state, no reference leaks, no thread-safety concerns. Works with C extensions, dynamic imports, metaclasses, and every Python feature. Easy to reason about — every restart is identical to a fresh start.

**Weaknesses**: Slow for large applications (startup can take seconds). All in-flight work is lost or must complete before shutdown. All connections are dropped and must be re-established. Not suitable when startup cost is high or state is expensive to reconstruct.

**Example**: https://github.com/django/django/blob/main/django/utils/autoreload.py

### Pattern 6: Fork-Based Module Isolation (Firehot)

**Used by**: Firehot (Pierce Freeman), similar concepts in Jupyter's autoreload

**How it works**: A base Python process imports all third-party dependencies but no user code. This base process is long-lived. When user code changes, the base is forked via `os.fork()`, and the child loads only the user's project modules fresh. Third-party dependencies are already in memory (shared via copy-on-write). The old child is terminated.

**Strengths**: Combines speed of selective invalidation with reliability of process restart. Third-party imports are amortized across all reloads. No `importlib.reload` thread-safety issues. Startup cost proportional to user code size, not total dependency size.

**Weaknesses**: Unix-only. Fork-unsafe libraries (some C extensions, CUDA) can break. Doesn't preserve state. More complex process management. Copy-on-write memory sharing can be defeated by garbage collection.

**Example**: https://pierce.dev/notes/misadventures-in-python-hot-reloading

### Pattern 7: In-Place Code Patching (Jurigged)

**Used by**: Jurigged, IPython autoreload (partial), Reloadium

**How it works**: Patches live code objects in place. Uses `gc.get_referrers()` to find all references to a function's code object, then replaces `__code__` pointers. For classes, updates method code objects on all existing instances. Module-level statements are selectively re-executed via AST diffing — only changed lines run.

**Strengths**: Extremely fast (sub-millisecond for small changes). Existing object references remain valid. No module re-import overhead. Zero setup.

**Weaknesses**: Not thread-safe. Running async functions not affected until next invocation. Class instances get new methods but keep old `__init__` data — "you can easily end up with broken objects." Cannot handle structural class changes (adding/removing attributes). Not suitable for production.

**Example**: https://github.com/breuleux/jurigged

## Anti-Patterns

- **`importlib.reload()` without dependency tracking**: Reloading a module doesn't update references held by importers. If module A does `from module_b import func`, reloading module_b leaves A with the old `func`. AppDaemon addresses this with AST analysis but has known failure modes ([#1135](https://github.com/AppDaemon/appdaemon/issues/1135)). ([source](https://pierce.dev/notes/misadventures-in-python-hot-reloading))

- **Blocking in teardown hooks**: AppDaemon explicitly warns that "any significant delays in the `terminate()` code could have the effect of hanging AppDaemon for the duration." Since teardown is synchronous to the management loop, one blocking app freezes the entire framework's reload. ([source](https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html))

- **Designing for state preservation during reload**: Almost every mechanism except Erlang's `code_change` discards state. AppDaemon: "the App is responsible for recreating any state as if it were the first time." Node-RED: "most nodes states are lost." Code that assumes in-memory state survives reload produces subtle bugs. ([source](https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html))

- **In-place code patching in production**: Not thread-safe, can leave instances in broken states, cannot update running async functions. Even Elixir teams with BEAM's superior hot-reload prefer rolling deploys in production. ([source](https://github.com/breuleux/jurigged), [source](https://medium.com/ovice/hot-code-reloading-of-elixir-otp-application-58ef4170b5aa))

## Emerging Trends

**Cleanup registration at setup time**: HA's `async_on_unload()` pattern — register cleanup callbacks during setup so they fire automatically on both intentional unload and setup failure — is gaining traction. This inverts the "override a teardown method" model: cleanup is registered at resource acquisition, preventing leaks from partial initialization. The same pattern appears in React (useEffect cleanup), Rust (Drop), and Go (defer). ([source](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/config-entry-unloading/))

**Fork-based isolation**: Firehot (2025) represents a new category that uses `os.fork()` to get clean module state without full restart cost — particularly relevant for apps with heavy third-party dependencies. ([source](https://pierce.dev/notes/misadventures-in-python-hot-reloading))

**Middleware lifecycle hooks**: Dramatiq's approach of granular middleware hooks (process boot, worker boot, consumer thread boot) rather than monolithic startup/shutdown is being adopted more broadly. ([source](https://dramatiq.io/reference.html))

## Relevance to Us

Hassette's current approach is squarely in Pattern 1 (terminate-and-reinitialize), which is the same approach as AppDaemon — the most directly comparable framework. This is a well-validated choice for the home automation domain.

**What we're already doing well:**
- Framework-owned cleanup of Bus subscriptions, Scheduler jobs, and StateManager — this is the critical reliability property and we have it
- Per-app error isolation — import failures, config errors, and initialization crashes don't cascade
- Post-ready reconciliation catches stale DB rows from failed sessions
- Async lifecycle hooks (vs. AppDaemon's synchronous ones) — avoids the "blocking terminate hangs the framework" anti-pattern

**Where HA's patterns could improve our approach:**

1. **`async_on_unload()` cleanup registration** (Pattern 2): Currently, hassette's resource cleanup is centralized in the framework's teardown path. If an app's `on_initialize` creates external connections or spawns background tasks before crashing partway through, those resources could leak. HA's pattern of registering cleanup callbacks at acquisition time handles partial initialization gracefully. This would be particularly valuable as users write more complex apps with external API connections.

2. **Explicit lifecycle state machine** (Pattern 2): Hassette tracks app state via events and status fields, but doesn't have a formal state machine with explicit transitions and invalid-state guards. A lightweight state machine would make lifecycle bugs more visible and prevent invalid transitions (e.g., starting an app that's already running).

**What we should NOT adopt:**
- Graduated deployment (Pattern 3) — adds significant complexity for minimal benefit when app startup is fast and apps are independent
- State preservation (Pattern 4) — even Erlang/OTP documentation calls this "one of the most complex parts of OTP." For home automations, rebuilding state from HA's current entity states is the right approach
- Fork-based isolation (Pattern 6) — hassette's startup is fast and third-party dependencies are light; the complexity isn't justified
- In-place patching (Pattern 7) — not production-suitable

**Thread safety gap**: Hassette's reload uses module reimport, not `importlib.reload()` directly, but the CPython thread-safety limitation (issue #126548) applies to any import during reload. The current approach of reloading apps one-at-a-time (not concurrently) mitigates this, but it's worth verifying that concurrent app starts don't race on shared module imports.

## Recommendation

Hassette's terminate-and-reinitialize approach is the right foundation — it matches the dominant pattern for automation frameworks and avoids the complexity traps of state preservation or in-place patching. Two specific improvements from HA's pattern are worth evaluating:

1. **Setup-time cleanup registration** — an `on_unload()` or `on_teardown()` mechanism that apps call during `on_initialize` to register cleanup callbacks. This would handle partial-initialization leaks without changing the overall reload model. Low complexity, high reliability benefit.

2. **Lifecycle state machine formalization** — making the existing implicit states (not loaded, loading, ready, stopping, stopped, failed) into an explicit state machine with guarded transitions. This would help with debugging and prevent invalid lifecycle operations.

Neither change alters the fundamental architecture. Both are incremental improvements to a pattern that's well-validated in the automation domain.

## Sources

### Reference implementations
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon app lifecycle and reload
- https://developers.home-assistant.io/docs/config_entries_index/ — HA config entry lifecycle
- https://nodered.org/docs/api/admin/methods/post/flows/ — Node-RED deployment API
- https://www.erlang.org/doc/system/gen_server_concepts.html — Erlang/OTP gen_server code_change
- https://github.com/django/django/blob/main/django/utils/autoreload.py — Django autoreload
- https://github.com/breuleux/jurigged — Jurigged hot reload
- https://dramatiq.io/reference.html — Dramatiq middleware lifecycle

### Blog posts & writeups
- https://pierce.dev/notes/misadventures-in-python-hot-reloading — Python hot reload tradeoffs (Firehot)
- http://malloc.dog/blog/2026/01/31/hot-reloading-code-in-erlang-how-does-it-work/ — Erlang hot reload internals
- https://medium.com/ovice/hot-code-reloading-of-elixir-otp-application-58ef4170b5aa — Elixir teams prefer rolling deploys
- https://adamj.eu/tech/2021/01/20/efficient-reloading-in-djangos-runserver-with-watchman/ — Django WatchmanReloader
- https://medium.com/@prabhavjain/adventures-with-gunicorn-supervisor-graceful-reload-on-code-changes-a13b221d946b — Gunicorn/Supervisor reload pitfalls
- https://hbenjamin.com/post/hot-reloads-with-gunicorn-supervisor/ — Gunicorn hot reload wrapper

### Documentation & standards
- https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/config-entry-unloading/ — HA config entry unloading quality rules
- https://docs.gunicorn.org/en/stable/signals.html — Gunicorn signal handling
- https://learnyousomeerlang.com/relups — Erlang release upgrades complexity
- https://celery.school/watchfiles-reload-celery-worker-code-changes — Celery reload with watchfiles

### Bug reports & issues
- https://github.com/python/cpython/issues/126548 — importlib.reload thread-safety
- https://github.com/AppDaemon/appdaemon/issues/1135 — AppDaemon global module reload failure
