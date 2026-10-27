---
topic: "Needs-restart flag after a timed-out or failed app hook (#3109 open decisions)"
date: 2026-10-27
status: Draft
---

# Prior Art: Needs-Restart Flag After a Hook Timeout

## The Problem

Issue #3109 (ledger `design/specs/134-resource-lifecycle-outcomes/design.md`, item 6) flags an app instance whose
failed or timed-out init or stop may have left work running. The ledger settles the big decisions (D5, D10, D11, D12,
D18, D19). A comb of the issue against current code left five implementation-level questions: how the shutdown that
cancels a failed init skips user hooks, what status a flagged instance shows, which teardown causes count toward the
"work may still be running" predicate, the wire/event shape of the flag, and where the CLI shows it.

Earlier briefs already cover most of the peer ground: `2026-10-18-lifecycle-outcomes/prior-art.md` (HA
`FAILED_UNLOAD`, `require_restart`, OTP start handoff), `2026-08-26-teardown-restart-safety/` (teardown evidence
orthogonal to `ResourceStatus`). This brief fills the gaps.

## How We Do It Today

- `Resource._shutdown_body` (`src/hassette/resources/base.py`) always runs `before_shutdown`, `on_shutdown`,
  `after_shutdown`. A failed init today skips shutdown entirely and runs `cleanup_failed_instance()` instead.
- `TeardownReport.is_restart_safe` is `not self.causes`: any cause is unsafe. `CHILD_SHUTDOWN_FAILED`,
  `CHILD_SHUTDOWN_TIMED_OUT`, `CHILD_RESTART_UNSAFE` exist in `teardown.py`.
- `AppRegistry` holds running or failed entries; a stop discards failure entries and emits STOPPED.
- Wire `AppInstance` has `status`, `error_message`, `error_traceback`; WS `AppStatusChangedData` carries status,
  previous status, exception and instance name. No needs-restart field anywhere.
- `hassette app` lists one row per app with an instance count; no per-instance view beyond `--instance` actions and
  `app health` / `app activity`.

## Patterns Found

### Pattern 1: Teardown hooks run only if setup completed (state-driven)

**Used by**: Home Assistant config entries, Erlang `gen_server`.
**How it works**: A failed or cancelled `async_setup_entry` leaves the entry in `SETUP_ERROR`; HA runs only the
framework-owned cleanup callbacks registered via `async_on_unload` (in a `finally`), never the integration's
`async_unload_entry`. Unloading a non-LOADED entry is a no-op. In OTP, `terminate/2` is not called when `init/1`
fails: "if you haven't completed initialisation then there is nothing to clean-up after" (Virding). The rule lives in
the framework's state machine, not in a flag the caller passes per attempt.
**Strengths**: user teardown can assume setup finished; no caller plumbing; one rule for every component.
**Weaknesses**: whatever setup acquired before failing leaks unless registered with framework cleanup.
**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config_entries.py

### Pattern 2: Distinct, sticky failed-unload state

**Used by**: HA (`ConfigEntryState.FAILED_UNLOAD`, non-recoverable), systemd (`failed`, cleared by `reset-failed`).
**How it works**: The condition is a status value that nothing but an explicit action clears (HA: process restart).
Reload and setup refuse while it holds. Stopping does not downgrade it.
**Strengths**: one place to look; gates operations. **Weaknesses**: the reason is free text beside the enum.
**Example**: https://contributors.home-assistant.io/core/integrations/config-entries/

### Pattern 3: Condition does not outlive the item (HA) — a documented gap

**Used by**: HA. Removing a `FAILED_UNLOAD` entry deletes it; the only trace is `{"require_restart": true}` in that
one response. Easy to miss.
**Example**: `_async_remove` in HA `config_entries.py`; https://community.home-assistant.io/t/tado-failed-to-unload/760594

### Pattern 4: One coarse "recoverable" predicate that assumes the worst

**Used by**: HA (`state.recoverable` gates unload, reload, setup; an unload that returned False and one that raised
both give `FAILED_UNLOAD`, "we can't assume the integration is still loaded, most likely it has partially unloaded
itself"). Erlang supervisors, Kubernetes and systemd back cooperative stop with a hard kill.
**Strengths**: one predicate, consistent. **Weaknesses**: coarse; a hook that raised but finished still blocks
reload.

### Pattern 5: Status enum + reason, full object on every live event

**Used by**: HA `config_entries/subscribe` (initial snapshot, then `{type, entry}` with the whole entry, so clients
never refetch). Kubernetes `status.conditions` (`{type, status, reason, message, lastTransitionTime}`) is the heavier
alternative, built for many independent facts.
**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/config/config_entries.py

### Pattern 6: List shows the aggregate, detail shows per-instance

**Used by**: `systemctl list-units --failed` / `systemctl status <unit>`; `kubectl get deploy` / `get pods`.

## Anti-Patterns

- Running user teardown after a failed setup, forcing it to handle half-initialised state.
- Treating a timed-out hook as finished.
- Surfacing the condition once, in one response, where callers can miss it (HA's removal path).

## Relevance to Us

1. **Hook skip.** Both peers with an answer use a general state rule, not a per-attempt flag. hassette already has the
   state: the init either completed (`mark_ready`) or didn't. A rule in `_shutdown_body` ("user shutdown hooks run only
   if init completed"), with framework stages (task bucket, `cleanup()`, children) still running, matches HA's
   split between user unload and framework `async_on_unload` callbacks. It reaches services too; that is what HA does
   for every integration, but it is wider than D18 ratified (apps only).
2. **Status of a flagged instance.** HA's state is sticky: stopping a `FAILED_UNLOAD` entry does not make it
   NOT_LOADED. D11 already chose a separate record over a status value; the peer lesson that carries over is
   stickiness. A flagged instance should report FAILED for as long as the flag holds, including after a stop that
   would otherwise discard its failure entry.
3. **Survives removal.** D11 deliberately goes further than HA (record survives unregistration and config edits),
   which avoids HA's documented miss-it-once gap. No change.
4. **Predicate.** HA keeps one predicate and is coarser than D18. Keeping one name matters more than the exact
   coarseness: redefine `is_restart_safe` rather than add a second predicate. For the child causes, HA's "can't assume
   it's still loaded" argues that a child whose `shutdown()` raised or timed out gives incomplete evidence, the same
   class as `COORDINATOR_FAILED`.
5. **Wire and events.** HA carries the full object on every event. A nullable nested field matches "one fact with a
   reason" better than a conditions array. Putting it on `AppStatusChangedData` mirrors HA; the flag is set in the
   same moment the FAILED event fires.
6. **CLI.** Peers keep list views aggregate and put per-instance state in a detail view. `hassette app` can mark the
   app row, with per-instance detail elsewhere.

## Recommendation

- Pattern 1 for the hook skip, applied at the user-code boundary: `App`, which is what HA's rule covers (integrations,
  not core services). A general Resource rule was checked against the code and rejected. Children initialize after the
  user hooks, so a failed `on_initialize` leaves `Bus`/`Scheduler` uninitialized, and their `on_shutdown` is what
  removes the app's listeners and jobs. Framework services would also lose `on_shutdown` after a partial init. Outcome:
  apps-only per-attempt flag (ledger Addendum 2026-10-27).
- Pattern 2's stickiness for status: flagged means FAILED until restart.
- Pattern 4: one predicate under the existing name; child shutdown raised or timed out counts as incomplete evidence.
- Pattern 5: nullable nested `needs_restart` object on `AppInstance`, also carried on the status-change event.
- Pattern 6 for the CLI.

Coverage gaps: pyscript and Node-RED were not searched; AppDaemon and NetDaemon have no comparable mechanism that the
search found; the Kubernetes pod-lifecycle page and HA's 2025-02-19 blog post were only partially read. URLs were not
live-verified.

## Sources

### Reference implementations
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/config_entries.py — setup failure, unload, reload, remove, `recoverable`
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/config/config_entries.py — WS subscribe payloads, reload `require_restart`
- https://github.com/net-daemon/netdaemon/pull/816 — NetDaemon disposal handling (inconclusive)

### Blog posts & writeups
- https://erlang.org/pipermail/erlang-questions/2010-December/055078.html — `terminate` not called after `init` failure
- https://erlang.org/pipermail/erlang-questions/2008-August/037450.html — `terminate` skipped without `trap_exit`
- https://www.hasscn.top/developers/blog/2025-02-19-new-config-entry-states — mirror of HA blog on new entry states (snippet only)
- https://community.home-assistant.io/t/tado-failed-to-unload/760594 — users stuck in FAILED_UNLOAD until restart
- https://community.home-assistant.io/t/appdaemon-terminate-error/10320 — AppDaemon terminate behavior

### Documentation & standards
- https://contributors.home-assistant.io/core/integrations/config-entries/ — config entry states
- https://developers.home-assistant.io/docs/integration_setup_failures — setup retry guidance
- https://appdaemon.readthedocs.io/en/latest/APPGUIDE.html — AppDaemon initialize/terminate
- https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ — pod conditions, Terminating
- https://kubernetes.io/docs/tasks/configure-pod-container/attach-handler-lifecycle-event/ — preStop/postStart hooks
- https://www.freedesktop.org/software/systemd/man/latest/systemctl.html — failed state, reset-failed, list-units --failed
