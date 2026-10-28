---
topic: "Peer handling of needs-restart edge cases (hassette #3109 ship-time challenge)"
date: 2026-10-27
status: Draft
---

# Prior Art: Needs-Restart Edge Cases at Ship Time

## The Problem

The ship-time challenge of #3109 raised edge cases around the needs-restart flag: a teardown body that raises, actions on an already-flagged instance, leaked sync worker threads, lock time during a failed init's teardown, event/snapshot consistency, and whether the reason string is display-only. This brief records what peers do for each, so each finding is weighed against real practice. It extends `design/research/2026-10-27-needs-restart-flag/prior-art.md`.

## How We Do It Today

See `design/specs/138-needs-restart-flag/design.md` (D4 resolver, D5 predicate, D9 ordering) and its build calls.

## Answers by Question

**Q1.** Split. HA treats it as possibly running: `async_unload` catches the exception, logs it, and sets FAILED_UNLOAD with `str(exc) or "Unknown error"` (L1185-1205), a non-recoverable state. AppDaemon treats it as stopped: `terminate_app` logs the error and returns False, but `finally` sets `running = False`, clears callbacks/futures and sets state "terminated" (app_management.py L378-399). Node-RED treats it as stopped: `stopNode` races `close()` against `nodeCloseTimeout` (default 15 s), catches the "Close timed out" rejection or error, calls `node.error(...)` and moves on (Flow.js L765-785). NetDaemon: [no source found].

**Q2.** HA: `ConfigEntries.async_unload` raises `OperationNotAllowed("The config entry '<title>' (<domain>) with entry_id '<id>' cannot be unloaded because it is in the non recoverable state ConfigEntryState.FAILED_UNLOAD")` (~L2636). `async_reload` goes through that path, and the HTTP reload view maps `OperationNotAllowed` to 403 `"Entry cannot be reloaded"` (components/config/config_entries.py L150-152). The WS disable path catches it and returns `{"require_restart": True}`. Removal of a FAILED_UNLOAD entry still proceeds, with `require_restart` true (L2410-2411). So HA reports an error for the action on a sticky-failed item; it has no multi-item group action, so a "group failed because one sub-item was pre-failed" case does not arise [no source found for peers with groups].

**Q3.** AppDaemon only logs: "Excessive time spent in callback" warnings repeated each threshold multiple, plus a "now complete after N seconds" warning, and busy-thread sensors (threading.py L305-330, L393-400). The app has no status flag. HA logs "Timed out waiting for ... the shutdown will continue" (core.py L1223-1316) and never reports it as entry state. In short, log only, not a status.

**Q4.** HA holds `setup_lock` through the whole of `async_setup_entry` failure handling, including `_async_process_on_unload` in the `finally` (L1042-1044); there is no separate shorter cleanup bound in `ConfigEntry.async_setup` (I found no timeout there). Timeouts live at the integration level (`SLOW_SETUP_MAX_WAIT = 300` in setup.py L85), not per-entry cleanup. The lock is also held for the whole reload (`async_reload`, ~L2688). Node-RED bounds each node close at 15 s. No peer shows a separate shorter cleanup bound.

**Q5.** HA sends one consistent snapshot: `config_entries/subscribe` emits `entry.as_json_fragment` (L717), a cached serialization of state, reason and translation fields built together (config_entries.py L708-735). The cache is cleared on state change (L704). The two cannot disagree within one event, though a later event may supersede it. Other peers: [no source found].

**Q6.** Partly. HA stores `reason: str | None` alongside optional `error_reason_translation_key/domain/placeholders`; the reason is a human string (`str(exc)` or e.g. "Unload not supported"), and docs describe it as the message the user sees. I found no explicit statement that it is not machine-parseable; the machine-readable channel is the translation key and the `state` enum. Dev docs: https://developers.home-assistant.io/docs/config_entries_index/. Other peers: [no source found].

## Patterns Found
### Pattern 1: Sticky non-recoverable "unload failed" state
**Used by**: Home Assistant
**How it works**: Unload exception -> FAILED_UNLOAD (non-recoverable); unload/reload are refused until restart. The state records "may still be running".
**Strengths**: Never falsely claims stopped. **Weaknesses**: Needs restart; reload returns a generic 403.
**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config_entries.py (L1185-1205)

### Pattern 2: Best-effort teardown, always mark stopped
**Used by**: AppDaemon, Node-RED
**How it works**: Error in terminate()/close() is logged and teardown proceeds; item is treated as stopped.
**Strengths**: No stuck state, simple. **Weaknesses**: Leaked work is invisible beyond logs.
**Example**: https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/appdaemon/app_management.py (L378-399)

### Pattern 3: Log-only warnings for runaway sync work
**Used by**: AppDaemon (HA shutdown logs "Timed out waiting for ..." too, core.py L1223-1316)
**How it works**: Periodic warning plus admin sensor; no status flag on the app.
**Strengths**: cheap. **Weaknesses**: not machine-queryable per app.
**Example**: https://raw.githubusercontent.com/AppDaemon/appdaemon/4.4.2/appdaemon/threading.py (L311-320)


## Recommendation

Peers split on the strictest cases: HA treats a raised unload as non-recoverable and refuses later actions with an explicit error, while AppDaemon and Node-RED log and treat the item as stopped. None of them fail a group action because one member was already failed, none flag a leaked worker thread beyond logging, and none put a shorter bound on failed-setup cleanup than on setup itself. HA's live events are one consistent snapshot. NetDaemon and pyscript were not searched (coverage gap).

## Sources
- https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py (raw: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config_entries.py)
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/config/config_entries.py
- https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/appdaemon/app_management.py (terminate_app L365-415)
- https://raw.githubusercontent.com/AppDaemon/appdaemon/4.4.2/appdaemon/threading.py (L305-330, L388-400)
- https://raw.githubusercontent.com/node-red/node-red/master/packages/node_modules/%40node-red/runtime/lib/flows/Flow.js (L29, L765-785)
- https://developers.home-assistant.io/docs/config_entries_index/
(URLs not live-verified.)
