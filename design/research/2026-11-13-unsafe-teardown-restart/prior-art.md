---
topic: "Handling an app instance whose teardown may have left work running"
date: 2026-11-13
status: Draft
---

# Prior Art: Unsafe teardown and "needs restart"

## The Problem

An app's teardown can fail, time out, or return while tasks, threads, or listeners it started are still running. Reloading the app in-process then risks the leftover work colliding with the new instance. The question is whether peers track a "needs a process restart" condition, where they keep it, whether they refuse reload until then, and whether the condition outlives the instance. Hassette is redesigning its app registry to be the single owner of app status (#4092), and its needs-restart mechanism sits beside that status as a separate overlay.

## How We Do It Today

`AppRegistry` keeps a separate `_needs_restart` map of `NeedsRestartRecord` per `(app_key, instance_name)`. The first flag wins, and only `clear_all` (process exit or test reset) clears it. `_combine_instance_info` lays the record over the instance entry, so the status resolves to FAILED with `needs_restart` set. The record survives `unregister_app`, `record_failure`, and config changes.

It is flagged in three places: `settle_failed_init`, `settle_failed_stop`, and `settle_raised_shutdown`. Each flags only when `ShutdownOutcome.is_restart_safe` is false (a walk-away, tasks still running, or a raised shutdown), and each writes FAILED first.

A flagged name has its start and reload refused (HTTP 409 `NEEDS_RESTART`), and a stop of it is reported as `refused`. It surfaces in the wire models, the CLI, and a UI badge.

The mechanism dates from specs 138 (#3109), 139 and 140. The concrete failure it guards against is leftover work that shares a Bus/Scheduler owner id with a replacement instance. A late teardown can then remove the replacement's registrations.

It is about 108 source lines, with dedicated tests: `test_app_registry_needs_restart.py` and `test_apps_reload_gate.py`.

## Patterns Found

### Pattern 1: A non-recoverable state on the instance itself

**Used by**: Home Assistant core.
**How it works**: `ConfigEntryState.FAILED_UNLOAD = ("failed_unload", False)`, where the second field is `recoverable`. An entry enters it when `async_unload_entry` raises, or when the integration can't unload. `ConfigEntries.async_unload` raises `OperationNotAllowed` for a non-recoverable state, and `async_setup` refuses any state but NOT_LOADED, so the entry can't be unloaded, set up, or reloaded. Removal is still allowed: `_async_remove` skips the unload, deletes the entry, and `async_remove` returns `{"require_restart": True}` once. The state lives on the entry, so it goes away with the entry. No separate record is kept.
**Strengths**: One source of truth. Each guard is a one-line check of `state.recoverable`.
**Weaknesses**: The restart requirement is reported only once, on removal. A re-added entry isn't guarded against the old entry's leftovers.
**Example**: `homeassistant/config_entries.py`, `ConfigEntryState`, `ConfigEntries.async_unload`/`async_setup`/`_async_remove`.
**Read**: config_entries.py (HA `dev`), the state enum and the unload, setup, and remove paths.

### Pattern 2: Time out, log, and proceed (accept the leak)

**Used by**: NetDaemon (3s `DisposeAsync` timeout), Node-RED (15s `nodeCloseTimeout`), and AppDaemon (no timeout; it logs `terminate()` exceptions).
**How it works**: A failed or timed-out teardown is logged, the instance is treated as gone, and reload or redeploy goes ahead. Node-RED added its timeout because a close that never finished blocked every deploy (#893, #698).
**Strengths**: Simple, and the reload path can't get stuck.
**Weaknesses**: Leaked work can collide with the new instance. Node-RED #2067 shows users hitting "port still in use" after a redeploy. Nothing tracks the condition, so no operator sees it.
**Read**: NetDaemon `AppModel/Internal/Application.cs`; Node-RED `runtime/lib/flows/Flow.js` `stopNode`; AppDaemon `app_management.py` `terminate_app`.

### Pattern 3: A separate record laid over the status that outlives the instance

**Used by**: none found. [no source found]

## Anti-Patterns

- Waiting on teardown with no bound: one hung hook blocks every reload. This was Node-RED before its timeout, and is AppDaemon today.

## Gaps

- Erlang/OTP supervisors, OSGi, and Kubernetes were not opened. Their general approach, escalating to a forced kill, doesn't apply to Python tasks and threads.
- pyscript's task cancellation on reload was not traced. Its reload path showed no unload-failure state.

## Relevance to Us

Hassette's needs-restart condition is the same idea as HA's `FAILED_UNLOAD`: a non-recoverable failure that refuses setup and reload. What sets hassette apart is that it stores the condition as a separate record laid over the status, which outlives the instance entry. No peer does that. HA keeps the state on the entry and lets it go with the entry. The other peers don't track the condition at all.

Once #4092 makes the registry the single owner of status, the overlay is the only place where the resolved status and the stored entry can disagree. The overlay's "survives removal" rule protects against a stop or prune removing a flagged entry. That rule stops mattering if paths that remove entries skip flagged ones, which they can safely do because stops of a flagged name are already refused.

Dropping the mechanism entirely (Pattern 2) is the NetDaemon/Node-RED approach. It would reverse specs 138–140: the refusal, the 409 response, the badge, and the guard against owner-id collisions. That is a user-visible behavior change of its own, not part of #4092.

## Recommendation

Fold the condition into the instance entry, following HA. An entry that is FAILED and carries `needs_restart` (or a non-recoverable marker) is never removed by stop, discard, or prune, and only `clear_all` clears it. Delete the separate `_needs_restart` map and the overlay branch in `_combine_instance_info`. Keep the wire shape (`status: failed` plus `needs_restart`) rather than adding a `ResourceStatus` member, since adding one would change the wire enum.

If the loud-failure posture of spec 138 is itself in question, removing the mechanism (Pattern 2) is a legitimate peer-backed choice. Evaluate it as its own issue against the owner-id collision it guards against.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py — `FAILED_UNLOAD`, recoverable guards, `require_restart` on removal
- https://github.com/net-daemon/netdaemon/blob/main/src/AppModel/NetDaemon.AppModel/Internal/Application.cs — 3s dispose timeout, log and proceed
- https://github.com/node-red/node-red/blob/master/packages/node_modules/@node-red/runtime/lib/flows/Flow.js — 15s close timeout, log and proceed
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/app_management.py — `terminate_app`, log exceptions, always clean up
- https://github.com/custom-components/pyscript/blob/master/custom_components/pyscript/__init__.py — reload path, no unload-failure state

### Issue trackers
- https://github.com/node-red/node-red/issues/893 (not opened) — a hung close blocked deploy
- https://github.com/node-red/node-red/issues/698 (not opened) — timeout added so closes can't hang forever
- https://github.com/node-red/node-red/issues/2067 (not opened) — a leaked port after redeploy
