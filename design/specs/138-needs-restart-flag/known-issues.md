# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A shutdown body that raised reads restart-safe

Status: resolved — fixed in PR #3550 review (2026-10-28): `SHUTDOWN_BODY_FAILED` is in `WORK_MAY_RUN_CAUSES`. The deferral's premise didn't hold: a user `on_shutdown` that awaits a task it cancelled lets `CancelledError` escape and aborts the body before child shutdown (`tests/unit/resources/lifecycle/test_shutdown_body_failed.py`). See `design/research/2026-10-28-needs-restart-convergences/prior-art.md`.
Recorded: 2026-10-27 (3109)
Source: ship-challenge
Reason not fixed now: accepted-limitation (at the time; since fixed, see Status)
Affected files:
- src/hassette/resources/teardown.py
- src/hassette/resources/lifecycle.py

Issue (as recorded, before the fix):
When a resource's shutdown body itself raises or is cancelled outside the coordinator's own cancel path, the coordinator replaces the body's evidence with a bare `SHUTDOWN_BODY_FAILED` report (`pending_tasks` dropped). `SHUTDOWN_BODY_FAILED` wasn't in `WORK_MAY_RUN_CAUSES`, so `is_restart_safe` was `True` and the instance wasn't flagged needs-restart, even though stages the body never reached may have left work running.

Why it was deferred:
Only a framework bug in the shutdown body triggers it; no routine path does. Peers split: Home Assistant treats a raised unload as non-recoverable, while AppDaemon and Node-RED log the error and treat the item as stopped (`design/research/2026-10-27-needs-restart-ship-findings/prior-art.md`, Q1). The user chose the simpler behavior; the operating docs say such an error is logged but doesn't flag.

Recommended follow-up:
If a raised shutdown body is ever seen in the field leaving work running, add `SHUTDOWN_BODY_FAILED` to `WORK_MAY_RUN_CAUSES` (one entry plus a predicate test) and note the exception to ledger 134 D18 in its addendum.

Acceptance criteria:
- A report carrying `SHUTDOWN_BODY_FAILED` makes `is_restart_safe` `False`, and an app instance whose body raised is flagged needs-restart.

## KI-002: A timed-out `AppSync` hook's worker thread isn't flagged

Status: open
Recorded: 2026-10-27 (3109)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/resources/teardown.py
- docs/pages/operating/index.md

Issue:
A blocking `on_initialize_sync`/`on_shutdown_sync` that outlives its bound keeps its worker thread running, but the hook is recorded as timed out and ended, so the instance isn't flagged needs-restart.

Why deferred:
Peers only log leaked threads (AppDaemon's long-callback warnings, HA's shutdown logs; `design/research/2026-10-27-needs-restart-ship-findings/prior-art.md`, Q3). The operating docs already say a timed-out sync handler's thread keeps running until it returns.

Recommended follow-up:
If users hit it, add one sentence to the needs-restart docs saying the flag doesn't cover a sync hook's worker thread, or record a thread-pending cause the predicate reads.

Acceptance criteria:
- Either the docs state the gap next to the needs-restart section, or a timed-out sync hook whose thread is still alive flags the instance.

## KI-003: The WS status event can carry a flag that disagrees with its status

Status: open
Recorded: 2026-10-27 (3109)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/runtime_query_service.py
- frontend/src/utils/app-data.ts

Issue:
`RuntimeQueryService.on_app_state_changed` takes `status` from the bus event and `needs_restart` from the registry at dispatch time, so a STARTING/RUNNING event for a replacement over a flagged index carries the flag, and the UI can briefly show RUNNING with a needs-restart badge while REST shows FAILED.

Why deferred:
The main trigger (a replacement over a flagged index) exists only until #3110 refuses it. The registry and REST stay correct. HA sends one consistent serialized entry per event (prior-art.md, Q5), so if it persists after #3110, follow that shape.

Recommended follow-up:
After #3110, re-check; if still reachable, take `status` from the D4 resolver whenever it returns a flag.

Acceptance criteria:
- A WS `app_status_changed` event never carries a non-null `needs_restart` with a status other than `failed`.

## KI-004: Apps removed from config while flagged are missing from boot issues

Status: open
Recorded: 2026-10-27 (3109)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_registry.py

Issue:
`get_full_snapshot` doesn't fold in apps that left the config but still have needs-restart records, so `collect_boot_issues` misses them. They still appear in `GET /api/apps`, `hassette status`/`hassette app`, and the UI badge.

Why deferred:
Needs a flag followed by removing the app from `hassette.toml` before a restart; every other surface still shows the flag.

Recommended follow-up:
Include orphaned flagged apps (`build_orphaned_flag_info`) in `get_full_snapshot`, with a test.

Acceptance criteria:
- An app removed from config while flagged appears in boot issues until restart.

## KI-005: An exception after `unregister_app` in `shutdown_instance` loses the outcome

Status: open
Recorded: 2026-10-27 (3109)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_instances.py

Issue:
Between `unregister_app` and the `settle_*` recording, a synchronous helper (formatting, logging) that raised would leave the index with no failure entry, flag, or event, so it reads STOPPED.

Why deferred:
Needs a framework bug in trivial synchronous helpers; extends the ledger's accepted Finding 8 class.

Recommended follow-up:
If seen, write the failure entry before any formatting in `settle_failed_stop`/`settle_failed_init`.

Acceptance criteria:
- A raising helper after the unregister still leaves a failure entry for the index.

## KI-006: `NeedsRestart.reason` has no display-only statement

Status: open
Recorded: 2026-10-27 (3109)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- wire/src/hassette_wire/apps.py

Issue:
`reason`, which also serves as the fallback `error_message` for a flagged index with no entry, isn't documented as human-readable text that may change.

Why deferred:
No known client parses it; other free-text wire fields carry no stability statement either. HA's `reason` is human text, with the state enum and translation keys as the machine channel (prior-art.md, Q6).

Recommended follow-up:
If a client starts parsing it, add a docstring line saying it's display text, and point machine consumers at `status`/`needs_restart` presence.

Acceptance criteria:
- `NeedsRestart.reason`'s docstring states it is display text.

## KI-007: A flagged instance's pending tasks don't trigger the process-exit hard exit

Status: open
Recorded: 2026-10-28 (3109, PR #3550 review)
Source: pr-review
Reason not fixed now: deferred to #3395
Affected files:
- src/hassette/core/core.py
- src/hassette/server.py
- src/hassette/core/app_lifecycle_instances.py

Issue:
`hassette run` hard-exits only when `Hassette.force_terminated_work` is non-empty, and only deadline owners write to it. A flagged instance whose teardown finished with tasks still pending (a failed init, or a completed stop) is never recorded there, so at process exit a pending task that swallows cancellation can hold the interpreter until the supervisor kills it. The same list can also name work that finished long ago (134 sketch-challenge F7, accepted).

Why deferred:
Adding the flagged instance's task names as a fifth writer patches a list no peer keeps. Home Assistant core, AppDaemon and uvicorn derive survivors from `asyncio.all_tasks()` and non-daemon threads at exit, wait with a bound, and log what is left. That answers both this gap and F7, but it changes D19's ratified trigger and the exit path, so it belongs with #3395's outcome ("names of work still running"). The supervisor's kill is the backstop meanwhile, as it is for HA.

Recommended follow-up:
In #3395, replace the recorded list with a bounded check of live tasks and non-daemon threads at exit, and hard-exit only when something survives it.

Acceptance criteria:
- At process exit, a pending task left by a flagged instance either finishes within the bound or triggers the hard exit.
- Work that finished before exit doesn't trigger the hard exit.
