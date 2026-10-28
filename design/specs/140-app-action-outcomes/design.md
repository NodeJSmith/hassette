# Design: Per-Instance Outcomes from App Action Endpoints

**Date:** 2026-10-28
**Status:** ratified
**Mode:** sketch
**Issues:** #3111
**Parent:** design/specs/134-resource-lifecycle-outcomes/design.md

## Summary

Breakdown item 8 of the Resource Lifecycle milestone ledger, implementing parent D15. Today the six app action
routes (`start`/`stop`/`reload`, app-wide and per instance, in `src/hassette/web/routes/apps.py`) await an
`AppHandler` facade method that returns `None`. They then read the registry back after the per-app-key lock is
released (`_failed_target_instances`, `_raise_if_target_failed`) to guess whether the action failed. That read
is racy across concurrent requests. A stop never shows a failure, because stop unregisters regardless. And
since #3110, every stop or reload that touches an index flagged needs-restart answers a generic 500
`action_failed`, even when the action itself succeeded.

This change makes each lifecycle action return what it did to each instance, decided under the app-key lock.
The routes map those outcomes worst-outcome-wins to 200/409/500 and list them in the body. Where each piece
lives:

- **Core outcome type and collector**: a per-instance outcome (index, instance name, result, needs-restart,
  reason), its result enum, and the per-request collector that holds one slot per targeted index (D1), in
  `src/hassette/core/app_lifecycle_common.py`, beside the other shared lifecycle types. The vocabulary is D2.
  Reload's merge rule is D6.
- **Producing outcomes**: the start/stop/reload paths in `src/hassette/core/app_lifecycle_start_stop.py`, the
  instance init and shutdown settle paths in `src/hassette/core/app_lifecycle_instances.py`, and the
  instance-creation funnel in `src/hassette/core/app_factory.py` (`create_instances`). The `AppHandler` facade
  (`src/hassette/core/app_handler.py`) passes them through.
- **Refusal logging**: the gate in `_create_instance_unlocked` and `AppFactory.create_instances` stops logging.
  It returns a refused outcome instead, and the callers with no response channel log it (Assumed: parent D12).
- **Status mapping**: `_run_app_action` in `src/hassette/web/routes/apps.py` applies worst-outcome-wins.
  `_failed_target_instances` and `_raise_if_target_failed` are deleted. Core-to-wire conversion goes in
  `src/hassette/web/mappers.py`. `WebApiError` (in `src/hassette/web/errors.py`) gains optional outcomes, which
  `_run_app_action` fills from the finished collector or from an `AppBlockedError` or `AppRemovedError` that
  carries them, and which the problem body builder writes as `outcomes`. In `src/hassette/exceptions.py`,
  `AppBlockedError` gains an optional outcomes attribute, and a new `AppRemovedError` (a `HassetteError`, mapped
  to `app_not_found`) carries one too (D1, D6). Every 202 the app action contract mentions changes with it: the
  `action_route` decorator's `status_code=202`, the six route docstrings (which become the OpenAPI
  descriptions), the in-module docstrings mentioning 202, and the "lying 202" comment in
  `src/hassette/exceptions.py`. The scheduler's run-now route keeps its 202 on purpose
  (`src/hassette/web/routes/scheduler.py`).
- **Wire**: the outcome model and its result literal in `wire/src/hassette_wire/apps.py` and `literals.py`;
  the `ActionResponse` reshape (D4); `ProblemDetail.outcomes` and the new `needs_restart` code in
  `wire/src/hassette_wire/problems.py`. Also `CODE_STATUS` and `CODE_DESCRIPTIONS` in
  `src/hassette/web/errors.py`, and `WebApiError` so it can carry outcomes into the problem body.
- **Client**: a `NeedsRestartError` (409) in `client/src/hassette_client/errors.py` `CODE_ERRORS`, subclassing
  `ConflictError` like the other permanent 409, `AppBlockedError`. Its docstring says it isn't retryable and
  persists until hassette restarts. `HassetteClient.action`'s "sending `start` or `stop` again is safe, since
  each converges" sentence excludes an instance that needs a restart, and its Raises list gains
  `NeedsRestartError`. Also `MIN_API_SCHEMA_VERSION` (D4).
- **CLI**: `run_app_action` in `src/hassette/cli/commands/app.py` stops printing `status` (D4). It keeps its
  success message and lists no per-instance outcomes (Posture), and `--json` output carries the response as
  returned. Error statuses already exit 1 with the problem `detail`.
- **Frontend**: the "returns 202" comment and mocks (`frontend/src/components/shared/action-buttons.tsx`,
  `frontend/src/test/handlers.ts`), regenerated `openapi.json` and `generated-types.ts`. Restart-required text
  reaches the toast through the problem `detail`.
- **Docs**: `docs/pages/web-ui/api-errors.md` (new code, `action_failed` wording, the `outcomes` member), the
  app lifecycle docs' reload-refusal section, and the CLI commands page if it describes action output.
- **Parent Addendum**: a dated entry recording each rule beyond D15's text (D3 at least), as #3111's
  acceptance criteria require.

Prior art: `design/research/2026-10-28-app-action-outcomes/prior-art.md` (per-target result shapes, status
mapping, already-broken targets, partial failure) and `design/research/2026-10-28-app-action-outcome-plumbing/prior-art.md`
(how peers carry outcomes internally through gathers and multi-phase operations), on top of the HA findings in
`design/research/2026-10-18-lifecycle-outcomes/prior-art.md` and
`design/research/2026-10-27-needs-restart-ship-findings/prior-art.md`.

Out of scope: a UI view of the per-instance outcome list; changing the whole-request pre-checks
(`invalid_app_key`, `action_in_progress`, `app_not_found`, `instance_not_found`, `bootstrap_not_released`,
`app_blocked`), which keep answering before any instance is acted on. The exception is a reload of a blocked
app, whose stop half runs first (D6).

## Posture

- **Failure handling:** loud. Every per-instance failure or refusal reaches the response; no retries (parent
  Posture).
- **Compatibility:** break freely (pre-V1). Wire changes go through whichever compat lists actually fail, with
  a changelog entry and a `BREAKING CHANGE:` footer (parent Posture and Breakdown "Applies to all").
- **Scope:** minimal, D15 only. The frontend and CLI get the 202→200 fix, and restart text through the existing
  problem `detail` path. Neither gets a per-instance outcomes view.
- **Rollout:** ship outright; the frontend and CLI changes ship in the same release as the wire change.
- **Hardening:** project defaults plus the parent's "no silent states" rule. A refusal is reported once: in the
  response on HTTP, in one ERROR on paths with no response channel.
- **Concurrency:** the existing per-app-key lock (parent D6). Each outcome is decided under it; no new locks.
- **Altitude:** build; one session builds it from this ledger.

## Decisions

### D1: How do outcomes get from the lifecycle code to the route?

**Deciding factor:** each outcome is a recorded fact of this request, not inferred, and every targeted index
gets exactly one, even when a gather sibling or a later stage raises. The milestone's premise is "record
outcomes instead of inferring them". Prior art: `design/research/2026-10-28-app-action-outcome-plumbing/prior-art.md`.

| | A: Return values threaded up | B: Per-request collector, passed explicitly | C: Registry read under the lock |
|---|---|---|---|
| Source of truth | Each settle step returns the outcome it decided | Each settle step records its outcome into the request's collector | Registry snapshot before vs after, inside the lock |
| Outcomes decided before an unexpected raise (post-ready reconcile, a `gather_all` sibling) | Lost unless every level catches | Kept: slots fill as decisions happen | Kept: they're in the registry |
| Every targeted index gets exactly one outcome | A rule each path must follow | Targets declared up front; one finish step fills any empty slot | Derived from state |
| Shared class-load failure | Fan out by hand at each level | One slot per target, with a reason naming the shared cause | Needs a registry change (today it records one index) |
| "What this call did" vs target state | Yes | Yes | No: newly vs already flagged and "already running" need a before-snapshot |
| Signatures changed | About 10 internal (`shutdown_instance`, `initialize_instance(s)`, `create_instances`, `create_single_instance`, `_create_instance_unlocked`, the `_*_unlocked` bodies, `flag_instance_needs_restart`) plus 6 public and 6 facade | The same set gains a collector parameter; public and facade methods return it | Only the 6 public and 6 facade |
| Hidden state | None | One explicit object, passed as a parameter (never a contextvar) | None new, but it's inference |
| Other callers (`apply_changes`, `start_apps`, process exit) | Ignore the return, or log refusals from it | Get a collector back, or pass a throwaway one | Unaffected |
| Peers | AppDaemon mixes returns and state, and `stop_app` drops `terminate_app`'s `False` | kubelet `PodSyncResult` (one `SyncResult` per action and target); trio's "store each child's result keyed by target" | HA and NetDaemon keep state on the target; HA's races (#117756, #111784) came from reading it outside the deciding lock |
| Documented pitfall | Missed levels | The cross-phase merge (kubelet overwrites the earlier phase's error), settled in D6 | Reading outside the lock |

How the collector behaves (option B):

- It lives in `src/hassette/core/app_lifecycle_common.py` beside the outcome type. It is created by each public
  start/stop/reload method once it holds the lock and knows its targeted indices: the configured indices for
  start and reload; for stop, the configured indices plus any tracked orphan outside them; and the single index
  for per-instance actions. A stop target flagged needs-restart reports `refused` (D3), whether or not it is
  still tracked. Checked first. Any other untracked stop target reports `succeeded` with the reason "already
  stopped".
- A slot is written at most once per phase. Gather children record their own outcome before returning, so a
  raising sibling can't erase it.
- A class-load or config failure that affects every index records `failed` in each `to_create` slot, with a
  reason naming the shared cause (systemd's `JOB_DEPENDENCY` pattern), not just at `to_create[0]`.
  `create_single_instance` records its validation failure instead of being detected by `registry.get(...) is
  None`.
- `flag_instance_needs_restart` passes back `AppRegistry.flag_needs_restart`'s bool, so the slot can say
  whether this request flagged the index.
- One finish step, in the public method, fills any slot still empty as `failed`. When an exception escaped
  (D5), the reason is that exception's message. The public methods return the finished outcomes.
- An action whose manifest is gone once it holds the lock raises a new `AppRemovedError` instead of returning
  silently, and the route maps it to `app_not_found`, never a 200 with no outcomes. That covers a start or
  reload whose manifest vanished while it waited in `_admit_start`, and a reload whose manifest is gone after
  its stop half ran.
- `AppRemovedError` and `AppBlockedError` carry the collector's finished outcomes when they escape after slots
  were filled: a reload's stop half, before the create half was refused (D6) or found nothing to create.
  `WebApiError` passes them into the problem body.

**Recommendation:** B. It keeps decided outcomes through an unexpected raise without catch code at every level,
gives a shared failure a home, and enforces the one-outcome-per-index invariant in one place. It is also the
peer pattern built for multi-target, multi-phase operations.
**Pick A instead if** a mutable object travelling through the lifecycle paths costs more than per-level catch
code. **Pick C instead if** the smallest diff matters most and the before/after inference is acceptable.
**Reversibility:** easy (internal signatures only)
**Ratified:** Chose a per-request collector passed explicitly through the lifecycle paths over threading return values or reading the registry under the lock, to keep every decided outcome through gathers and unexpected raises and give each targeted index exactly one outcome, accepting one mutable object passed through about ten internal signatures. First ratified as return-value threading; reopened at the sketch challenge (Finding 1, converging Findings 2–4) after `gather_all` met D1's own Pick-B condition and peer source (kubelet, trio, HA, AppDaemon) showed the collector shape. At the sketch comb, chose stop targeting every configured index plus tracked orphans, with untracked ones `succeeded` "already stopped", over a 200 with an empty list; and a reload whose manifest vanished after its stop half answering `app_not_found` with the stop outcomes over a 200.

### D2: What does one instance's outcome say on the wire, and what is the needs-restart code called?

**Deciding factor:** a client can tell, per instance, what this request did and whether hassette must restart,
and the status mapping can be computed from the outcome without extra lookups. D15 lists four outcomes
(succeeded / failed / refused / needs restart), but "needs restart" can come with either a failure (newly
flagged → 500) or a refusal (already flagged → 409). A single enum value can't say which.

| | A: `result` (succeeded / failed / refused) + `needs_restart: bool` | B: one four-value `result` (succeeded / failed / refused / needs_restart) | C: echo each targeted `AppInstance` snapshot |
|---|---|---|---|
| Says what this request did | Yes | Yes, except a flagged instance loses failed-vs-refused | No: it's state after the action, not the action's result |
| Status mapping from the entry alone | Yes: failed → 500, refused → 409 | No: needs a second field or a lookup to choose 500 or 409 | No |
| Names each instance needing a restart (D15) | `needs_restart` on every entry, set for newly flagged and already flagged alike | Only if `needs_restart` covers both cases, which it can't with failed | Via `needs_restart` on the snapshot |
| Fields | `instance_index`, `instance_name`, `result`, `needs_restart`, `reason: str \| None` | Same, minus `needs_restart` | The full `AppInstance` |
| Matches peers | systemd keeps precondition results (`dependency`, `skipped`) apart from `failed`; SQS splits faults with `SenderFault`; needrestart and HA's `require_restart` keep "restart needed" beside the result | No peer folds "restart needed" into the result enum | EC2 `StopInstances` reports per-instance previous/current state, not a result |

Shared by every option: `result` is an open literal (Assumed: wire convention). An index the action left in its
target state is `succeeded`, with a reason saying so (e.g. "already running"). The 409 code for a refusal is
`needs_restart`, matching the existing `AppInstance.needs_restart` field name. Each entry's `reason` carries
the failure message, the refusal text (the flag's reason and time, today's `AppRegistry.refusal_for` line), or
`None` for a plain success.

Valid pairs, stated in the wire model's docstring: `succeeded` with `needs_restart` false; `failed` with
`needs_restart` true (this request flagged it) or false (a plain failure); `refused` with `needs_restart` true
(the only refusal today). `needs_restart` means "this index is flagged needs-restart after this request". A
client that meets an unknown `result` must not assume success.

**Recommendation:** A, because it is the only shape where each entry alone decides the status, and it keeps
HA's split of "what happened" from "needs a restart".
**Pick B instead if** a flat four-value enum matters more than per-entry status mapping, accepting that the
route consults a second source for flagged entries. **Pick C instead if** clients want full post-action state
and can live without "what did this request do".
**Reversibility:** hard (published wire shape)
**Ratified:** Chose a `result` enum (succeeded / failed / refused) plus a separate `needs_restart` bool, with `instance_index`, `instance_name` and `reason`, the stated valid pairs, and the 409 code `needs_restart`, over a four-value enum or echoed `AppInstance` snapshots, to let each entry alone decide the status and keep "restart needed" beside the result as peers do, accepting a published wire shape that is hard to change later and (sketch challenge, Finding 13) that every problem body's schema carries the optional app-action `outcomes` member until a second route family needs per-item results.

### D3: How does an action report an index that was already flagged before it ran?

**Deciding factor:** honesty about the zombie, with one rule for every action. Parent D15 settles start and
reload: the gate refuses a flagged index, refused gives 409, and a partly successful bulk request returns an
error code (ratified). It doesn't say what a **stop** reports for an already-flagged index (#3111's first case).
Nothing is stopped there: the instance is already unregistered, and `_discard_failed_indices` only drops its
failure entry and re-emits FAILED.

| | A: Refused everywhere (409) | B: Stop succeeds with `needs_restart`, start/reload refuse | C: Already-flagged is informational everywhere |
|---|---|---|---|
| Stop, flagged-only target | 409 `needs_restart` | 200, entry `succeeded` + `needs_restart` | 409 `needs_restart` (nothing acted on) |
| Stop, flagged sibling | 409; body shows the siblings stopped | 200; body names the flagged one | 200; body names the flagged one |
| Reload, flagged sibling | 409 (D15 as ratified) | 409 (D15 as ratified) | 200; supersedes D15's bulk rule |
| Does a 200 ever coexist with a running zombie in the targets | Never | Yes, for stop | Yes, for every action |
| Frontend toast (minimal change, reads only `detail`) | Error toast naming the instance and "restart hassette" | Success toast for stop, unless the frontend reads outcomes | Success toast, unless the frontend reads outcomes |
| Peers | HA refuses unload and reload of a `FAILED_UNLOAD` entry, the only peer state where work may still run | HA's *removal* of such an entry proceeds with `require_restart` | Docker (304) and systemd (`failed` ≈ `inactive`) treat stopping an already-dead target as a no-op success, but there the work has ended; AppDaemon/Node-RED treat it as stopped (rejected by parent D11/D12) |
| Hassette's stop is closest to | HA's unload: the app stays configured and can be started again | HA's removal, which deletes the entry's config | — |
| New rule beyond D15 (Addendum) | Stop treats an already-flagged index as refused | Stop reports an already-flagged index as succeeded | Already-flagged entries don't count toward the status unless every target is one |

The flagged-only target answers 409 `needs_restart` under every option; that is #3111's third case.

Whatever the status, the problem `detail` of a 409 or 500 from an app action names each instance that didn't
succeed, with its reason, and summarizes what the others did (e.g. "Stopped 2 of 3 instances of 'lights';
'kitchen' needs a hassette restart (flagged at …: …)"). The CLI and the frontend toast read only `detail`, so
this line is their whole view of a partial outcome. Client users read `exc.problem.outcomes`, and no typed
accessor is added.

**Recommendation:** A, because a 200 then never covers a zombie the user asked to stop. It is one rule for
all three actions. A hassette stop keeps the app configured, so it is HA's unload, not its removal, and HA
refuses unload of `FAILED_UNLOAD`. Peers' no-op stop of a dead target doesn't apply, because a flagged
index's work hasn't ended. And under the minimal frontend it is the only
option where the toast says a restart is needed. It costs a 409 on every whole-app action for that app until
hassette restarts, with the body listing what the siblings did.
**Pick B instead if** a stop should mean "hassette is no longer managing it", as in HA's removal, and the
apps-page badge is enough to show the zombie. **Pick C instead if** whole-app actions on an app with one zombie
should keep working quietly until restart, accepting that the minimal frontend shows a success toast.
**Reversibility:** easy (status mapping in one route helper)
**Ratified:** Chose reporting an already-flagged index as refused on every action (409 `needs_restart`) over stop succeeding with `needs_restart` or treating it as informational, so a 200 never covers a zombie the user acted on and stop matches HA's refusal to unload a `FAILED_UNLOAD` entry, accepting that every whole-app action on that app answers 409 until hassette restarts. At the sketch challenge (Finding 5), chose a `detail` composition rule naming each non-succeeded instance and summarizing the rest over also adding a typed `outcomes` accessor on the client errors, so the CLI and toast see partial outcomes without growing the client's public surface. At the same challenge (Finding 6), chose keeping `NeedsRestartError` under `ConflictError` with docstrings that say it isn't retryable and that stop no longer converges for a flagged instance, over a direct `HassetteHTTPError` child, so released and new clients agree on the class family, accepting that a blanket `except ConflictError` retry catches it. Also accepted (Finding 12) that a failed or refused HTTP action leaves only the lifecycle-layer log of its cause, with no route-level line naming the request, unlike the success INFO line.

### D4: What does `ActionResponse` look like after the change?

**Deciding factor:** the success body says what happened, with no field left over from the 202 contract. D15
keeps `app_key`, `action` and `instance_index` and adds the outcomes. It doesn't say what happens to
`status: "accepted"`, which described a 202 that is now a 200 for a finished action.

| | A: Drop `status`; `outcomes` required; bump `MIN_API_SCHEMA_VERSION` | B: Keep `status: "accepted"`; `outcomes` required; bump | C: Keep `status`; `outcomes` defaults to `[]`; no bump |
|---|---|---|---|
| Body honesty | Outcomes say what happened; no stale field | "accepted" contradicts a finished action | Same as B |
| Released clients parsing the new body | Fine: `status` has a default in their model | Fine | Fine |
| New client against a floor-version server | Fails until the floor moves, so the bump is required (client-schema-floor rule) | Same | Parses, but sees `[]` and can't tell "no outcomes" from "old server" |
| Compat lists | OpenAPI diff flags the removed property (`tools/wire_compat_ignore.txt`) | None for `status` | None |
| CLI/frontend | CLI stops printing `status` | None | None |
| Keeps `OpenAcceptedStatus` | Yes: `telemetry.py` still uses it | Yes | Yes |
| Peers | Synchronous bodies (AIP-233's sync methods, SQS, EC2, the Supervisor) report results with no "accepted" field | No synchronous peer keeps one | Same as B |

**Recommendation:** A, because pre-V1 break-freely allows it and a 200 body that says "accepted" would mislead.
The floor bump follows from making `outcomes` required, which B needs too.
**Pick B instead if** existing scripts read `status` and the field should stay as a constant.
**Pick C instead if** the floor bump must wait for a different release, accepting a silent `[]` against older
servers.
**Reversibility:** hard (published wire shape)
**Ratified:** Chose dropping `status` and making `outcomes` required, with an API schema floor bump, over keeping `status: "accepted"` or defaulting `outcomes` to `[]`, so the synchronous body reports only what happened as peers' synchronous bodies do, accepting a `tools/wire_compat_ignore.txt` entry for the removed property and a new client that needs a server at the bumped schema. At the sketch challenge (Finding 11), also accepted as a known limitation that a newer CLI pointed at an older server reports version skew only after the action has already run (the CLI never calls `check_server_version`), so a retried reload can run twice.

### D5: What does a request report when a lifecycle body raises unexpectedly partway through?

**Deciding factor:** D15's "the body always lists every instance's outcome", even on the unexpected path. Today
the public methods catch `Exception` ("Failed to stop app …"), log it and return, and the route's read-back
maps whatever ended up in the registry. With threaded outcomes (D1), an exception escaping a body loses the
outcomes decided before it.

| | A: Catch at the public method; targets with no outcome report `failed` with the exception's message | B: Let it propagate; the route answers 500 `action_failed` with no outcomes |
|---|---|---|
| Body lists every targeted instance | Yes | No |
| Outcomes decided before the raise | Kept | Lost |
| Callers with no response channel (`apply_changes`, `start_apps`) | Unchanged: still never see the exception | Each must catch it (`start_apps` already uses `gather(return_exceptions=True)`; `apply_changes` would need new handling) |
| Log | One ERROR with the traceback, as today | Route logs a WARNING with `exc_info`, as `_await_operation` does today |
| Code | The existing `except Exception` blocks call D1's finish step, which fills the empty slots | Delete the blocks, add caller handling |
| Peers | Non-atomic batch APIs (SQS, EC2) report handled items plus failures for the rest | Kubernetes `DeleteCollection`'s bare 504 with no progress was filed as a bug; Google's AIP-233 returns one error only because its sync batches are atomic, which hassette's aren't |

**Recommendation:** A, because it keeps D15's contract on every path and leaves the no-channel callers alone.
**Pick B instead if** an unexpected exception should look different on the wire from a recorded failure.
**Reversibility:** easy
**Ratified:** Chose catching at the public method and reporting every target without an outcome as failed with the exception's message over letting the exception propagate, to keep D15's every-instance listing on the unexpected path and leave the no-channel callers unchanged, accepting that an unexpected exception looks like a recorded failure on the wire.

### D6: How does a reload combine its stop half and create half for one index?

**Deciding factor:** one entry per index that tells the truth about the state the reload left it in: no 500 over a
running, freshly reloaded instance, and no 409 over a failure this request caused. Reload runs a stop half and a
create half on the same index under one lock (`reload_app`, `_reload_instance_unlocked`). A stop half that
newly flags the index makes the create half's gate refuse it immediately.

| | A: Worst of both halves, newly flagged on top | B: The create half decides, except a newly-flagging stop half stands |
|---|---|---|
| Restart-safe stop timeout, then a good create | `failed`, 500, while the new instance runs | `succeeded`, with the stop timeout in `reason` |
| Stop half newly flags | `failed` + `needs_restart`, 500 | Same; the gate's refusal doesn't overwrite it |
| Fits D2's "left in its target state is `succeeded`" | Conflicts | Matches |
| Posture "loud" | Via status | Via status for flags and failures; a clean-timeout stop only via `reason` |
| Peers | — | HA `async_reload` and AppDaemon `_stop_apps`: a failing stop half stands; kubelet's last-writer-wins merge is the documented bug B avoids |

A reload of an app blocked by `--app` stops it first and then raises `AppBlockedError`. The route still answers
409 `app_blocked`, and its problem body carries the stop half's outcomes, since the stop really happened.

**Recommendation:** B, because a reload that left a working instance shouldn't report failure, and a stop that
created a zombie must not be relabelled a refusal.
**Pick A instead if** a stop timeout during reload should always fail the request by status.
**Reversibility:** easy
**Ratified:** Chose letting the create half decide, except a stop half that newly flags the index stands as `failed` + `needs_restart`, over worst-of-both-halves, so a reload that left a working instance reports success and a zombie this request created is never relabelled a refusal, accepting that a clean stop timeout during reload is visible only in `reason` and the server log's ERROR. Ratified at the sketch challenge (Finding 1, converging Finding 4). At the sketch comb, chose holding the Posture over having the CLI render success-entry reasons, accepting that a CLI or UI user doesn't see that clean timeout.

## Assumed

- **Carried from parent D15:** worst outcome wins. Any `failed` entry, or any entry this request newly flagged,
  gives 500 `action_failed`. Otherwise any `refused` gives 409 (`needs_restart`). Otherwise 200. A partly
  successful bulk request returns an error code. 409 and 500 bodies are `ProblemDetail`s with an optional
  `outcomes` extension member. `ActionResponse` keeps `app_key`, `action` and `instance_index`. A stop whose
  hook timed out is `failed` with a "timed out" reason, whether or not work is still pending. Evidence: parent
  D15's Ratified line; `settle_failed_stop` in `src/hassette/core/app_lifecycle_instances.py` already produces
  the timed-out failure and its reason.
- **Carried from parent D12 and #3111's acceptance criteria:** the gate returns a refused outcome. Only the
  callers with no response channel log the refusal ERROR (the restart start in `_start_for_restart`,
  `apply_changes`'s autostart loop in `src/hassette/core/app_lifecycle_changes.py`, and bootstrap `start_apps`
  in `src/hassette/core/app_lifecycle_service.py`). HTTP paths don't log it. Today both funnels log it
  unconditionally (`_create_instance_unlocked` in `app_lifecycle_start_stop.py`; `AppFactory.create_instances`).
  This supersedes the interim rule in the parent's 2026-10-28 Addendum entry for #3110. Every no-channel caller
  logs refusals through one shared helper over the returned outcomes. Both `_start_for_restart` branches
  (including the `create_one` gather) and `start_apps`' gather, which today inspects only exceptions, go
  through it. A refused index reached through `apply_changes` and through `bootstrap_apps` must emit exactly
  one ERROR.
- **Carried from parent D11:** the `AppRegistry` needs-restart record stays the instance's persistent state.
  An outcome is what one request did, and both are set in the same step under the app-key lock. The flag-time
  ERROR in `flag_instance_needs_restart` (`app_lifecycle_instances.py`) still names each new needs-restart
  state, which satisfies the "no silent states" rule without the refusal log.
- **Carried from parent D6:** one per-app-key lock covers decide, stop, gate and create, and every registry
  write for a key happens under it, except process-exit teardown (`shutdown_all` in `app_lifecycle_instances.py`
  takes no lock). An exit-time flag can therefore land while an HTTP stop is mid-teardown. That request then
  reports the index as already flagged, but the process is exiting and the response may never be delivered.
  Evidence: spec 139 (#3110), `_get_app_key_lock` uses in `app_lifecycle_start_stop.py`, `shutdown_all`.
- The whole-request pre-checks in `_run_app_action` and `_await_operation` (invalid key, action in progress,
  not found, instance out of range, bootstrap not released, `--app` blocked) answer before any instance is
  acted on and carry no outcomes. The exceptions are a reload of a blocked app and a reload whose manifest
  vanished, which have already run their stop half (D1, D6). Evidence: `src/hassette/web/routes/apps.py`;
  `reload_app` in `app_lifecycle_start_stop.py`.
- Every wire literal is open (`Annotated[Literal | UnknownValue, LenientValue(...)]`), so a server-added value
  doesn't break a released client. Evidence: `wire/src/hassette_wire/literals.py`.
- The CLI renders any non-2xx response's problem `detail` and exits 1 (`HassetteCLIClient`'s
  `is_success` → `handle_http_error`, `src/hassette/cli/client.py` and `client_errors.py`). The frontend's
  `performAction` toasts the thrown error's message, which `apiFetch` takes from the problem body. Evidence:
  `frontend/src/components/shared/action-buttons.tsx`, `frontend/src/api/client.ts`.
- A new `ProblemCode` needs entries in `CODE_STATUS`, `CODE_DESCRIPTIONS` and the catalog page, and either a
  `CODE_ERRORS` class or `GENERIC_CODES` in the client. Guard tests fail otherwise. Evidence:
  `.claude/rules/web-api.md`; `tests/unit/web/test_error_mechanism_guard.py`.
- A client that newly requires a response field bumps `MIN_API_SCHEMA_VERSION` in the same PR, and
  `tools/check_client_floor.py` fails until it does. Evidence: `.claude/rules/client-schema-floor.md`.
- A removed response property fails the OpenAPI diff (`tools/wire_compat_ignore.txt`). `client_compat` fails
  only if a released client can't parse the new responses, and a stale entry fails, so neither list gets an
  entry until a check actually fails. Evidence: parent Breakdown "Applies to all".
- The status change and the `ActionResponse` reshape are breaking. The PR title takes `!` and the body ends
  with exactly one `BREAKING CHANGE:` footer. Evidence: CLAUDE.md "Changelog".
- Tests that pin today's contract and change with it: `tests/integration/web_api/test_app_action_in_progress.py`
  (202), `test_problem_details.py` (`action_failed` rows), `test_endpoints.py`,
  `tests/integration/test_apps_reload_gate.py`, `tests/unit/core/test_app_lifecycle_service*.py`,
  `tests/support/web_mocks.py` (`app_action_mocks`), `tests/unit/cli/test_commands_app.py`,
  `tests/unit/test_wire_vocabulary_typing.py`, `frontend/src/test/handlers.ts`.
- #1698, which #3111 supersedes, is already closed. Evidence: `gh issue view 1698`.

## Build

- [ ] Core: lifecycle methods return per-instance outcomes; the gate returns refusals and only no-channel callers log them; the route maps outcomes worst-outcome-wins; registry read-back deleted
- [ ] Wire and consumers: outcome model, `ProblemDetail.outcomes`, `needs_restart` code, `ActionResponse` reshape, 200 status, client error class and schema floor, regenerated OpenAPI/TS, frontend and CLI, compat lists if checks fail
- [ ] Parent Addendum entry for rules beyond D15
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
- The outcome dataclass and result enum live in `src/hassette/schemas/app_outcomes.py`, not `core/app_lifecycle_common.py`: `web` may not import `core` at runtime (`web-no-core` in `tools/check_module_boundaries.py`), and the route and mapper need the type. The collector (`ActionOutcomes`) and `log_refusals` stay in `core/app_lifecycle_common.py`.
- `start_app` and `start_instance` raise `AppRemovedError` for a missing manifest before admission too, not only under the lock: the route already pre-checks the manifest, so this is the same race one step earlier, and returning no outcomes would have answered 200 with an empty list.
- A per-instance start or reload whose index left the config while it waited reports that index `failed` ("the index is no longer in the app's config"), where it used to return silently.
- `stop_instance` no longer special-cases an untracked out-of-range index: there is nothing to stop, so its outcome settles as `succeeded`, "already stopped", like any untracked target.
- `_await_operation`'s `ValueError`/`RuntimeError` → `action_failed` mapping is removed: D5 has every public lifecycle method catch and record unexpected exceptions, so the mapping was unreachable; anything else that escapes is an `internal_error`.
- `AppRegistry.refusal_for` (a full log line) became `refusal_reason` (the outcome's `reason`: "needs a hassette restart (flagged at …: …)"), and `log_refusals` builds the no-channel ERROR line from the outcome, so the HTTP `detail` and the log share one wording.
- Problem bodies are dumped with `exclude_none`, so `outcomes` is absent (not `null`) on every error that isn't an app action that acted on an instance.
- Tests that drive one lifecycle step directly pass `tests/support/outcomes.py`'s `AnyIndexOutcomes`, which targets each index on first write; per-request contract tests go through the public methods.
