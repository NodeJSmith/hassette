---
topic: "Process shutdown while a per-app setup, reload or stop is in flight"
date: 2026-11-14
status: Draft
---

# Prior Art: Exit vs In-Flight App Lifecycle Work

## The Problem

A framework that hosts many apps or integrations serializes runtime start, reload and stop per app, usually with a lock. Process exit then has to stop everything. If exit takes the same locks, a hung setup can hold up exit. If it doesn't, exit races the in-flight operations, and their state writes can land in the wrong order: a late "running" after "stopping", a stale "stopped" that removes a replacement's entry, or an entry re-created after the registry was cleared.

This brief came from Finding 1 of the ship-time challenge on `design/specs/154-registry-owns-app-status`. Four findings traced to `shutdown_all` stopping instances without taking the app-key lock. The question for the brief: do comparable projects lock, cancel, or race at exit, and do they guard against late status writes?

## How We Do It Today

`AppLifecycleInstancesMixin.shutdown_all` (`src/hassette/core/app_lifecycle_instances.py`) lists live instances from the registry once, stops them concurrently without taking any app-key lock, then calls `AppRegistry.clear_all()`. That is a raw reset that sends no events (D7). Runtime start, reload and stop run under the per-app lock. `AppRegistry.set_status` is the single writer, and its only arbitration is the missing-entry, flagged-entry and no-App rules. `_record_created` already re-checks the needs-restart flag because exit can flag a name mid-start.

## Patterns Found

### Pattern 1: Lock-free global stop; the per-entry lock is for runtime operations only

**Used by**: Home Assistant config entries, NetDaemon, pyscript
**How it works**: Runtime setup, unload, reload and remove are serialized per entry (HA's `ConfigEntry.setup_lock`, which `async_setup`/`async_unload` assert is held). Process stop does not take it. HA's `ConfigEntries._async_shutdown`, the EVENT_HOMEASSISTANT_STOP listener, only calls `entry.async_shutdown()`, which cancels a pending setup retry. NetDaemon's `DisposeAsync` disposes a snapshot of `_applications` with no lock. App loading runs with `CancellationToken.None`, so an app can finish initializing after dispose. pyscript's `hass_stop` stops and deletes each registered global context.
**Strengths**: Exit cannot deadlock on a stuck setup. Almost no code.
**Weaknesses**: Late state writes land. HA's `_async_set_state` and NetDaemon's state save are unconditional. Nothing reconciles state afterwards.
**Example**: HA `config_entries.py` `_async_shutdown` (L2453 on `dev`, 2026-11-14).
**Read**: HA `homeassistant/config_entries.py` L1062-1100, L1245, L2453; NetDaemon `NetDaemonRuntime.cs` L106-183, `AppModelContext.cs`; pyscript `custom_components/pyscript/__init__.py` L442-505.

### Pattern 2: A stopping flag checked before starting new work

**Used by**: Home Assistant (`hass.is_stopping`), Node-RED (`started`/`state` flags), AppDaemon (`self.stopping`, used only to dedupe `stop()`)
**How it works**: Shutdown sets a flag first. Code that is about to start new work checks the flag and bails. HA checks it before scheduling a setup retry ("so we do not block shutdown"). Work that is already running is not affected.
**Strengths**: One check per entry point. No lock, no deadlock.
**Weaknesses**: Check-then-act. It only covers the gap before work begins.
**Example**: `if not hass.is_stopping: hass.async_create_background_task(self.async_setup_locked(hass), ...)`
**Read**: HA `config_entries.py` L1062-1077, `setup.py` L769; Node-RED `@node-red/runtime/lib/flows/index.js` L434-460.

### Pattern 3: Take the shared lock at shutdown, with a hard timeout

**Used by**: AppDaemon
**How it works**: `AppDaemon.stop()` runs `app_management.stop()`, which goes through the single global `check_updates_lock` that runtime reloads also use. The call is wrapped in `asyncio.wait_for(..., timeout=3)`. On timeout it logs "AppManagement stop timed out, continuing shutdown" and goes on.
**Strengths**: Ordered in the common case, and exit is bounded.
**Weaknesses**: After a timeout the race is back. `terminate_app` still writes "terminated" unconditionally in a `finally`. A start is not refused once `stopping` is set.
**Read**: AppDaemon `appdaemon/appdaemon.py` ~L385-400; `appdaemon/app_management.py` L187-196, L365, L951.

### Pattern 4: Cancel background tasks, then a bounded drain

**Used by**: Home Assistant (`HomeAssistant.async_stop`; per-entry unload)
**How it works**: Stop cancels background tasks, sets `CoreState.stopping`, fires the stop event, then runs `async_block_till_done` under stage timeouts. On timeout it logs the still-running tasks and continues. Entry unload does the same per entry under the lock: cancel, wait 10s, warn. A stop during startup only logs that it "may fail".
**Strengths**: Stragglers are named in the logs, and exit is guaranteed.
**Weaknesses**: Foreground setup is waited on, not cancelled. Status isn't reconciled.
**Read**: HA `homeassistant/core.py` L117-120, L1191-1260; `config_entries.py` L1374-1395.

## Anti-Patterns

- None of the peers treats inaccurate status at exit as a bug. HA, AppDaemon (`terminate_app`'s `finally`) and NetDaemon all write state unconditionally during teardown. No project had a compare-and-set or a tombstone against re-creating an entry after a clear.

## Gaps

- Node-RED: how a stop during an in-flight `start()` is serialized was not traced. Only the flag handling was read.
- AppDaemon: only `app_management.py` was checked for a `stopping` guard on start. A check elsewhere is possible.
- Issue trackers were not searched. "They accept it" rests on code, not on a maintainer statement or a documented limitation.

## Relevance to Us

hassette's lock-free `shutdown_all` is Pattern 1, which is what HA config entries, NetDaemon and pyscript do. The guards Findings 3, 4 and 5 propose (STOPPING precedence in `set_status`, writer identity, a teardown-vs-create FAILED split) are more machinery than any peer has: none of them guard late status writes at all. Taking the lock at exit (option 1) is AppDaemon's Pattern 3, and AppDaemon has to cap it with a timeout that brings the race back. Cancelling in-flight work (option 2) is closest to HA's Pattern 4, which relies on HA's background-task registry. hassette has no equivalent for lifecycle operations.

The one guard peers do use is Pattern 2: don't start new work once stopping has begun. Finding 2's fix (skip `initialize()` when the STARTING write was refused) is a per-instance form of that check, keyed on the registry's own answer instead of a global flag.

## Recommendation

Keep the lock-free exit. Document every exit-time status inaccuracy once, at `shutdown_all`. Add the Pattern 2-style guard Finding 2 proposes, so a sibling torn down before its turn isn't initialized. A global "stopping" flag on `AppHandler` checked before init would be the more literal port of HA's check. It would also cover an instance whose entry exit hasn't reached yet, but `shutdown_all` already stops every listed instance. The registry-refusal check covers the harmful case (initializing a torn-down App) without new state.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py — `setup_lock`, `_async_shutdown`, `_async_set_state`, `is_stopping` retry guard
- https://github.com/home-assistant/core/blob/dev/homeassistant/core.py — `async_stop` stages, cancel and bounded drain
- https://github.com/AppDaemon/appdaemon/blob/master/appdaemon/appdaemon.py — `stop()` with a 3s `wait_for`
- https://github.com/AppDaemon/appdaemon/blob/master/appdaemon/app_management.py — `check_updates_lock`, `terminate_app`
- https://github.com/net-daemon/netdaemon/blob/main/src/Runtime/NetDaemon.Runtime/Internal/NetDaemonRuntime.cs — lock-free dispose, `CancellationToken.None` load
- https://github.com/custom-components/pyscript/blob/master/custom_components/pyscript/__init__.py — `hass_stop`, `unload_scripts`
- https://github.com/node-red/node-red/blob/master/packages/node_modules/@node-red/runtime/lib/flows/index.js — `started`/`state` flags on stop
