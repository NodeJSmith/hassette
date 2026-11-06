---
topic: "Lifecycle of runtime per-component debug-logging overrides (stop, reload, reconfigure, failed teardown)"
date: 2026-11-06
status: Draft
---

# Prior Art: Debug-Override Lifecycle Across Component Exits

## The Problem

Hassette's per-app debug capture (spec 148, PR #3853) lets a user turn DEBUG on for one app instance at runtime. The override has to coexist with the app lifecycle: an instance can be stopped, reloaded, have its config block removed, be removed as an app entirely, or fail to tear down and keep running unregistered. Across three review rounds, five findings each found an exit path where the override's state and the instance's state fell out of step, and each got its own patch. The question is whether comparable projects couple an override to component lifecycle at all, and how much machinery they use.

## How We Do It Today

- **Two copies of "is it on".** The intent is a set of `(app_key, instance_name)` pairs on `AppRegistry`. The pairs are name-keyed and survive unregister and re-register. `App.debug_capture` mirrors the intent, and `Resource.reapply_log_levels` turns that mirror into stdlib logger levels.
- **Logger levels are name-keyed too.** Loggers are `hassette.apps.<unique_name>` and its children, which live in Python's process-global `loggerDict` and are never deleted.
- **Per-exit-path upkeep.** The pairs are pruned at app start, in public `stop_app`/`stop_instance`, and cleared in the orphan-removal `finally`. The per-instance config-change stop prunes nothing. Logger levels are reset only for survivors in the orphan `finally`.
- **The gap.** `shutdown_instance` (`core/app_lifecycle_instances.py`) unregisters every departing instance, at `:252` or `:300`. A failed or INCOMPLETE stop leaves the App alive but unreachable. Its loggers stay at DEBUG, and `off` can't reach them because `AppHandler.set_debug_capture` acts only on registry hits.

## Patterns Found

### Pattern 1: The level lives on the global logger, with no lifecycle coupling and no cleanup
**Used by**: AppDaemon, Spring Boot Actuator, NetDaemon (config only), pyscript (through HA's logger)
**How it works**:
- The override is a plain `logger.setLevel()` on a named, process-global logger. No registry tracks overrides, and no lifecycle hook clears them.
- When a component restarts, its init re-applies the configured level if there is one.
- An override made at runtime lasts until the process restarts.
- AppDaemon reads the effective level back from the live logger.

**Strengths**: There is no cleanup code to maintain, and a failed teardown leaves nothing behind beyond what the logger already held.
**Weaknesses**:
- A runtime override silently carries across reloads, including into a re-added app with the same name.
- The only way to see which overrides are active is to scan the loggers.

**Example**: AppDaemon `adapi.py` `set_log_level`; Spring `LoggingSystem.setLogLevel`
**Read**: AppDaemon `adapi.py`, `app_management.py`; Spring `LoggingApplicationListener.java`, `LogbackLoggingSystem.java` (opened). Spring behavior on a context refresh: secondary.

### Pattern 2: A central name-keyed registry, independent of component lifecycle by design
**Used by**: Home Assistant core `logger` integration (pyscript inherits it); Erlang `set_module_level` (secondary)
**How it works**:
- One `overrides` dict plus a persisted store, keyed by logger name, set through a service or the websocket.
- A `HassLogger` subclass ignores `setLevel()` on overridden names, so a component restarting can't undo an override.
- Reloading or unloading an integration never touches the overrides.
- Whether an override survives an HA restart is the user's choice: `none`, `once` or `permanent`. A `once` setting is demoted on the next load.
- An override is cleared only by explicitly setting the level again.

**Strengths**:
- The state has one owner, and no exit path needs its own pruning.
- An override survives a reload on purpose, which is what you want when debugging the reload itself.

**Weaknesses**:
- Stale entries stay until someone clears them.
- An entry applies to any future component that uses the same name.

**Example**: `homeassistant/components/logger/helpers.py` (`set_log_levels`, `LoggerSettings`)
**Read**: `helpers.py`, `__init__.py`, `websocket_api.py` (opened).

### Pattern 3: One teardown choke point in a `finally`
**Used by**: AppDaemon (`terminate_app`)
**How it works**:
- Every stop, restart, reload and config-change path calls `terminate_app`.
- Its `finally` runs even when the app's `terminate()` raised. It cleans up callbacks, futures, services, the scheduler, the http routes and state.
- Logger levels are not on that list, but this is where they would go.

**Strengths**:
- Cleanup has exactly one home.
- A failed teardown is covered by construction, because the cleanup is in a `finally`.

**Weaknesses**:
- It only works while every path funnels through it.
- Each unguarded `await` inside the `finally` can skip the cleanup steps after it.

**Example**: `appdaemon/app_management.py` `terminate_app`
**Read**: opened.

### Pattern 4: Snapshot and restore, with a reference count
**Used by**: HA ZHA debug mode
**How it works**:
- Enabling it snapshots the levels of a fixed set of loggers, sets them to DEBUG, and increments a counter.
- Disabling it restores the snapshot once the counter reaches zero.
- The restore is tied to an explicit disable call, not to unload.

**Strengths**: It restores the true previous level, and overlapping enables are handled.
**Weaknesses**: An unload without a disable call leaves the levels stranded. This rests on a grep only.
**Read**: `zha/helpers.py` (opened).

### Pattern 5: The override is part of the saved config
**Used by**: Node-RED debug node
**How it works**:
- The node's `active` flag in the saved flow is the durable truth.
- A redeploy reconciles the runtime back to that flag. Maintainers closed the "reverts on refresh" report (#1195) as by design.

**Strengths**: There is one source of truth, and an override is deleted along with its node.
**Weaknesses**: Toggles made at runtime are lost on redeploy, and the UI and the runtime can disagree (#5751).
**Read**: issue opened; the HTML source is secondary.

## Anti-Patterns

- **Setting a level on a never-deleted Python logger from per-instance state, with nothing responsible for resetting it.** The level outlives the object that set it (CPython #56159; the weakness in Pattern 1). Hassette's stuck-DEBUG zombie is this case.
- **Two copies of "is it on" that can drift apart.** Node-RED #5751 is the UI and the runtime disagreeing. Hassette has the same shape in the registry pair and the per-App mirror.

## Gaps

- I found no AppDaemon issue that treats a runtime `log_level` carrying across a restart as either a bug or a won't-fix.
- I didn't read HA's `config_entries` unload path. That HA never resets levels on unload rests on reading the logger integration and grepping for debug-logging helpers.
- I didn't test Spring's behavior on a context refresh.
- The Erlang claims rest on the shape of its API, not its source. NetDaemon, pyscript and Node-RED come from docs and issues only.

## Relevance to Us

No peer ties a debug override to the component lifecycle and prunes it once per exit path. That per-path pruning is the mechanism hassette has patched five times. The two approaches that hold up are to let the override outlive the component on purpose, keyed by name (HA), or to keep no state beyond the logger (AppDaemon, Spring).

Hassette already keys both copies by name. The registry pair is keyed by `(app_key, instance_name)`, and the stdlib logger is keyed by `unique_name`. That makes the pair registry structurally the same as HA's `overrides` dict. HA does nothing on unload, and accepts that stale entries stay until cleared, with the active overrides visible to the user. Under D8, hassette already accepts that a name returning to config comes back captured. That suggests the pairs need fewer pruning points, not more. CodeRabbit's config-change-stop prune is a sixth.

The logger level is a different matter. The Codex finding is the anti-pattern above: a level on a never-deleted logger, with nothing left that can reset it. No peer handles a failed teardown, but AppDaemon's `finally` choke point is the place it would go, and hassette has the equivalent in `shutdown_instance`. Every departing instance passes through it, and it still holds the instance when it unregisters it.

## Recommendation

Treat the two copies differently:

1. **Logger levels: reset once, where every instance leaves.** Do it in `shutdown_instance`, at or before `unregister_app`, for every outcome, the failed and INCOMPLETE stops included. This is Pattern 3, plus the logger reset AppDaemon itself doesn't do. It makes "a name with no registered instance logs at its config level" hold on every exit, which fixes the Codex finding without one more per-path patch.
   - It doesn't break reload. Loggers are shared by name, so the next instance re-applies DEBUG from the pair when it is set up.
   - The orphan-removal `finally` still resets survivors, because those are still registered.
2. **Capture pairs: follow HA and stop adding exit-path prunes.** The pairs are name-keyed intent, and D8 already accepts that a stale pair re-arms capture for a returning name. Decline CodeRabbit's config-change-stop prune and cite D8.
   - Keep the start-time prune and the orphan clear, since those are the two points that reconcile against config.
   - Re-examine the public-stop prune (ship F7). It exists because routes return 404 for a stopped orphan, so it is about the pair being unreachable rather than lifecycle sync. It is reasonable to keep.

Accepting the stale-pair limitation is exactly what HA does. Adding the logger reset at the choke point goes one step beyond the peers, and it is justified here because hassette's `off` reports that levels are back to config, which a stranded zombie makes untrue.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/logger/helpers.py — HA override registry, persistence modes
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/logger/__init__.py — `HassLogger` ignores `setLevel` for overrides
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/logger/websocket_api.py — runtime set path
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/zha/helpers.py — ZHA snapshot/restore debug mode
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/app_management.py — `terminate_app` finally choke point
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/adapi.py — per-app `set_log_level`
- https://github.com/spring-projects/spring-boot/blob/main/core/spring-boot/src/main/java/org/springframework/boot/context/logging/LoggingApplicationListener.java — Spring logging lifecycle

### Issues & discussions
- https://github.com/node-red/node-red/issues/1195 — debug toggle reverts on redeploy, closed as by design
- https://community.home-assistant.io/t/what-is-self-set-log-level-supposed-to-do/177411 — AppDaemon set_log_level semantics (not opened)
- https://github.com/python/cpython/issues/56159 — loggers are never deleted
- https://github.com/custom-components/pyscript/discussions/562 — pyscript logging (not opened)

### Documentation
- https://www.home-assistant.io/actions/logger.set_level/ — HA set_level action
- https://www.erlang.org/doc/apps/kernel/logger.html — Erlang logger API (text not extracted)
- https://netdaemon.xyz/docs/user/app_model/app_model_custom_logging/ — NetDaemon logging config (not opened)
- https://docs.python.org/3/library/logging.html — stdlib logging
