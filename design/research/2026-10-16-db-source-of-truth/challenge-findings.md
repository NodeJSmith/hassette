# Challenge Findings

**Format-version:** 4
**Target:** /home/jessica/source/hassette/.claude/worktrees/wire-up-seeds-to-ui/design/research/2026-10-16-db-source-of-truth/research.md
**Critics:** systems-architect, data-integrity, structural-minimalist
**Likely-invalid:** 0

## Finding 1: Findings converge on the StatusProjector's dual write path (event-driven coalesced upserts plus a periodic full reconcile)

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** Synthesis
**Converges:** Findings 2, 3, 4, 5, 6, 7
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Six distinct findings from all three critics land on one mechanism: the `StatusProjector` as specified in research.md:193-208. It writes current state through two paths: per-key coalesced upserts driven by `app_state_changed`/`service_status` events, and a 30s full reconcile that rewrites from the registry. The reconcile also doubles as the session heartbeat, and history rows are appended only from the event path. Each finding attacks a different seam of that dual-writer shape and proposes its own local patch:
- a monotonic `seq` guard or in-writer snapshot so the reconcile cannot clobber a newer event write (Finding 3)
- splitting the heartbeat back out of the reconcile (Finding 4)
- adding more dirty triggers and moving signal ownership (Finding 5)
- choosing which path feeds history (Finding 6)
- a "load in progress" guard against mid-reload empties (Finding 7)

Finding 2 argues the event path exists only as a latency optimization and history source. By the brief's own recovery argument (research.md:202-203), every failure of the event path is corrected by the reconcile anyway. Patching each finding separately hardens a two-writer model that the initiative's own motivation ("two sources of truth are not worth their complexity") argues against. Should the projector's write model be re-evaluated as a whole, including whether the event-driven write path is needed at all, before any of these local fixes are written into issue 3?

**Evidence:** research.md:193-199 (subscribe, coalesce, upsert, reconcile on heartbeat), :202-203 (reconcile reads in-process truth, so it corrects any event-path failure), :208 (history appended only from the transition upsert, never backfilled), :337 (registry clears mid-read during teardown); `src/hassette/core/database_write_queue.py:199-258` (the caller builds the payload coroutine before admission, and admission and execution are separate awaits); `src/hassette/core/database_service.py:37-45, 299-314` (heartbeat timeout invariant and 3-strike escalation); `src/hassette/core/app_registry.py:126-134` (`block_app`/`unblock_apps` emit no event); `src/hassette/core/runtime_query_service.py:134-139, 211-219` (`apps_changed` relays `APP_LOAD_COMPLETED` independently of any projection).

**Design-challenge:** If the reconcile is what makes the design correct, what does a second, event-driven writer of the same rows buy that is worth a write-ordering race, a history/current divergence, and a trigger set that has to be kept complete?

**Deciding-factor:** Avoid writing six local patches (guards, extra triggers, ordering rules) into a mechanism that several critics independently argue is the wrong shape.

**Criteria:**
| | A: re-evaluate the projector first | B: keep the dual write path, fix findings individually |
|---|---|---|
| Risk of hardening the wrong model | Low: the mechanism is reconsidered before patches land | High: adds a seq guard, trigger list, history rule and reload guard to a two-writer design |
| Number of new rules in issue 3 | Decided by the re-evaluation, possibly fewer | At least 4-5 new rules or guards |
| Effort now | One focused design pass on issue 3 before the spec | Walk Findings 2-7 one by one |
| Preserves settled decisions | Yes: history ships with the projector, 30s cadence stays | Yes |
| Evidence base | Three critics, six findings, two HIGH structural from different critics | Same findings, addressed piecemeal |

**Options:**
- **A** *(recommended)*: Re-evaluate the `StatusProjector`'s write model before addressing Findings 2-7 individually. The re-evaluation must answer:
  - Is the event-driven write path needed, or only an event-driven wake?
  - Where is the in-process snapshot read relative to the single-writer FIFO?
  - Which writer is the source of `app_status_events` rows?
  - Who owns the reconcile cadence, and who owns the heartbeat?
  - Which inputs to the computed view must trigger a projection, and who emits the post-commit refetch signal?
  - How does the projector learn that a registry load or reload is in progress?
- **B**: Keep the dual write path as specified and address Findings 2-7 individually.

**Recommendation:** A. The convergence is strong: distinct critics found distinct defects in the same two-writer mechanism. Finding 2 shows the brief's own argument makes the event write path redundant for correctness. Re-evaluating first avoids writing guards that a different shape would not need.
**Pick-instead-if:** B: if sub-second status latency through a direct event-to-row write is a hard requirement that a wake-and-reconcile shape could not meet, so the two writers are unavoidable.

## Finding 2: The projector has two write paths for the same fact, recreating the split-brain the initiative removes

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Current rows are written by (a) a bus subscriber doing per-key coalesced upserts and (b) a 30s reconcile that rewrites everything from the registry. `app_status_events` is written only by path (a) and "never backfilled by reconcile". So by design, the history table and the current-status table can disagree: a dropped transition leaves current state healed and history gapped forever. The brief concedes the reconcile "reads the in-process truth, not the event stream". Path (a) therefore exists only as a latency optimization and as the source of history rows. Per-key coalescing, a bus subscriber that must follow `MARK_READY_HOOKS`, and a "missed bus event" failure class all exist to serve it.

**Evidence:** research.md:195-199, 202-203, 208, 385; `src/hassette/core/runtime_query_service.py:181-193` (the `app_state_changed` payload already carries `status`/`previous_status`); spec 087 Alternative B (`design/specs/087-db-manifest-union/design.md` ~329): the "writes per transition" objection is answered by coalescing, the very machinery a single reconcile path would not need.

**Design-challenge:** If the reconcile is the correctness mechanism, why does the event path write rows instead of only waking the reconcile?

**Deciding-factor:** One writer of current state, so current status and history cannot diverge by construction.

**Criteria:**
| | A: reconcile is the only writer, events only wake it | B: keep both write paths |
|---|---|---|
| Writers of current-state rows | One | Two (ordering must be guarded, see Finding 3) |
| History/current agreement | By construction (history derived from what was written) | Can diverge; gaps are permanent |
| Latency to UI | Debounced wake (~250ms) plus one transaction | Immediate per-key upsert |
| Machinery | Diff against last-written snapshot in memory | Per-key coalescing, upsert-from-event path, missed-event handling |
| Intra-window flaps (A→B→A) | Invisible to the diff | Captured only if events are logged uncoalesced |

**Options:**
- **A** *(recommended)*: Make the reconcile the only writer of current state. Events (`app_state_changed`, `service_status`) set a dirty flag that wakes it with a short debounce. One transaction upserts changed rows and appends an `app_status_events` row per diffed transition, then broadcasts the payload-free invalidation.
- **B**: Keep the event-driven coalesced upsert path alongside the reconcile, and resolve Findings 3, 5 and 6 individually.

**Recommendation:** A. It deletes per-key coalescing, the missed-event failure class and the history/current divergence. It keeps the settled "history ships with the projector" decision and changes only the mechanism.
**Pick-instead-if:** B: if every intra-debounce transition must reach history (flap detection is a requirement), or wake-plus-full-read latency proves unacceptable when measured.

## Finding 3: A reconcile snapshot computed before queue admission can overwrite a newer transition write

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The heal story is "reconcile reads in-process truth, so any lost write is corrected". That holds only if a reconcile write cannot itself clobber a fresher write. `submit()` takes a coroutine the caller already built, then waits for queue capacity (up to the 60s deadline) and for the worker to start it. If the projector builds the full-state payload from the registry, then calls `submit()`, a transition upsert for key K can be queued in between. FIFO order can then apply the older snapshot after the newer write, reverting K until the next reconcile, and that one can lose the same race again. The race is most likely when the queue is busy, which is exactly the failure the user asked about. The brief's "worst case 30s" becomes the typical case under saturation.

**Evidence:** `src/hassette/core/database_write_queue.py:199-258` (verified: the payload is a caller-built coroutine; `queue.put` and the worker-start wait are separate awaits under one deadline); research.md:196 (upsert "through awaited submit()", no ordering or version guard); research.md:337 (reload races cover transient empties only, not write ordering).

**Design-challenge:** Where exactly is in-process state read relative to the single-writer FIFO, and what prevents an older read from committing after a newer one?

**Deciding-factor:** Prevent stale-snapshot overwrites without adding per-row state that every writer and seed must maintain.

**Criteria:**
| | A: read in-process state inside the queued coroutine | B: per-row monotonic `seq` guard |
|---|---|---|
| New persisted state | None | A `seq` column on every projected table; seeds must write it |
| Correctness under reordering | Holds: the read happens at execution time, in FIFO order | Holds, if every writer uses the guard |
| Writer occupancy | Slightly longer (registry read inside the writer) | Unchanged |
| Works with a single-writer redesign (Finding 2) | Natural fit | Redundant there |

**Options:**
- **A** *(recommended)*: Require that the projector read registry and children state inside the coroutine the writer executes, at execution time, not before `submit()`.
- **B**: Add a monotonic `seq` (projector-owned counter) to every projected row, and guard every upsert with `WHERE excluded.seq > seq`.

**Recommendation:** A. It closes the race with no new persisted state or guard, and it composes with Finding 2's single-writer option.
**Pick-instead-if:** B: if multiple independent writers of the same rows must remain (Finding 1 resolved as B), and reading registry state inside the writer coroutine is not acceptable.

## Finding 4: Reconcile and heartbeat are fused into one cadence, breaking the heartbeat's timing invariant and coupling a DB-service crash path to projection work

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** systems-architect, data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The settled answer has "the reconcile run on the heartbeat" at 30s (research.md:199, 354). The 30s cadence is settled and not challenged here; coupling the two writes is. Three problems:
- **Timing invariant.** `_HEARTBEAT_WRITE_TIMEOUT_SECONDS = 30` is justified as "well under the default heartbeat interval (300s) so a timed-out attempt cannot overlap the next tick". At a 30s interval that invariant is gone. With `max_consecutive_heartbeat_failures = 3`, about 90s of a busy queue makes `serve()` raise `RuntimeError` and fails `DatabaseService`. A heavy full-state reconcile on a saturated queue then raises the chance of crashing the DB service, which is worse than the staleness it cures.
- **Ownership.** The heartbeat lives in `DatabaseService.serve()`, the lowest layer, which only knows the DB. The reconcile needs the registry and children. Either `DatabaseService` calls up into the projector (inverting the dependency direction `depends_on` needs) or two loops exist. If both count strikes, one slow attempt costs two.
- **Meaning.** `last_heartbeat_at` means "writer alive" and is what `_do_mark_orphaned_sessions` backfills into `stopped_at`. If it becomes "last successful reconcile", a failed reconcile compute in a live process (for example, the registry mid-teardown) stops the heartbeat and produces a falsely early `stopped_at` after a later crash.

Wording note: research.md:354 reads "`database.heartbeat_interval_seconds` defaults to 30". The current default is 300 (`config/models.py:86`; the brief's own line 154 says so, and line 199 says "replacing the 300s default"). Line 354 states the settled target, but should say "change the default from 300 to 30" so issue 2 does not read as a no-op.

**Evidence:** `src/hassette/core/database_service.py:37-45` (timeout comment, verified), `:299-314` (3-strike `RuntimeError`, verified); `src/hassette/config/models.py:86` (default 300), `:116` (3 strikes), `:169` (the 30 there is the WebSocket config); `src/hassette/core/session_manager.py:157-166` (`stopped_at = last_heartbeat_at`, verified); research.md:154, 199, 354, 384.

**Design-challenge:** Should "the process is alive" and "the heavy projection write finished" share one column, one timeout and one failure escalation?

**Deciding-factor:** Keep liveness meaning "writer alive", so a slow projection degrades a banner instead of killing the DB service.

**Criteria:**
| | A: split heartbeat and reconcile | B: keep them fused, re-derive constants |
|---|---|---|
| DB-service crash risk from slow reconcile | None: reconcile failure degrades `projection_lag_seconds` | Present: reconcile failures feed the 3-strike escalation |
| Meaning of `last_heartbeat_at` | Writer alive | Last successful reconcile |
| Dependency direction | Clean: each owns its own loop | `DatabaseService` must call up into the projector, or strike-counting is shared |
| Moving parts | Two loops at the same 30s cadence | One loop |
| Settled 30s cadence | Kept for both | Kept |

**Options:**
- **A** *(recommended)*: Split them. Keep a cheap `UPDATE sessions SET last_heartbeat_at` in `DatabaseService` at the settled 30s interval, and re-derive `_HEARTBEAT_WRITE_TIMEOUT_SECONDS` and the strike arithmetic for that interval (state the escalation timeline). Give the projector its own reconcile loop with `last_reconcile_ok_at`. Fix the line 354 wording.
- **B**: Keep the reconcile as the heartbeat. Re-derive the timeout and strike constants, and define which component counts a failed reconcile against the strike counter.

**Recommendation:** A. It preserves the settled cadence and the meaning of the orphan backfill, and removes the path where projection work crashes the DB service.
**Pick-instead-if:** B: if one write per tick is a hard constraint (measured write-queue pressure where a second tiny UPDATE every 30s matters).

## Finding 5: The projector's trigger set does not cover every input to the view it writes, and the retained `apps_changed`/`connectivity` signals fire before projection

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The projector writes the computed view (`build_manifest_info` output), but subscribes only to `app_state_changed` and `service_status`. Several inputs to that view emit neither:
- `block_app`/`unblock_apps` mutate `_blocked_apps` silently.
- `enabled`, the configured instance count and `only_apps` change on config reload.

These change the `blocked`/`disabled` status priority, the STOPPED placeholder instances and `instance_count`, and the projector learns about them only on the next reconcile. Meanwhile the brief keeps `apps_changed` and `connectivity` "as is" (research.md:242). `apps_changed` is relayed by `RuntimeQueryService` directly from `APP_LOAD_COMPLETED`, independent of any projection. A client refetching on that signal reads the DB before the projector writes the post-reload view. The brief's "signals go post-commit" invariant is applied to two of seven WS messages and violated by the one the UI uses after a reload. This is the stale-overlay bug class (#1893, #1894, #1895, #1609) relocated, not removed.

**Evidence:** `src/hassette/core/app_registry.py:126-134` (verified: no event on block/unblock); `src/hassette/core/app_lifecycle_config.py:139-145` (block/unblock on reload); `src/hassette/core/app_registry.py:311-317` (status priority reads `_blocked_apps`); `src/hassette/core/runtime_query_service.py:134-139, 211-219` (verified: `apps_changed` is a pure relay of `APP_LOAD_COMPLETED`); research.md:193-196, 237, 242.

**Design-challenge:** Should every WS refetch signal for DB-sourced data be emitted by the writer of that data?

**Deciding-factor:** No refetch signal can reach the client before the data it announces is committed.

**Criteria:**
| | A: projector owns all DB-sourced refetch signals | B: keep `apps_changed` as a relay, rely on reconcile |
|---|---|---|
| Post-reload refetch reads fresh data | Yes | No: up to one reconcile interval stale |
| Block/unblock/reload reflected promptly | Yes (marks projector dirty) | Only at next reconcile |
| Change surface | RQS stops subscribing to `APP_LOAD_COMPLETED`; projector emits `apps_changed` | None |
| Reintroduces stale-overlay bug class | No | Yes, for the reload path |

**Options:**
- **A** *(recommended)*: Make the projector's trigger "registry or children changed": `APP_LOAD_COMPLETED`, block/unblock and config reload also mark it dirty. The projector emits the single post-commit `apps_changed` signal, and `RuntimeQueryService.on_apps_changed` stops relaying `APP_LOAD_COMPLETED`. Apply the same rule to `connectivity` if HA connection is projected. State the invariant: every WS refetch signal for DB-sourced data is emitted by that data's writer.
- **B**: Keep `apps_changed` and `connectivity` as independent relays, and accept up to one reconcile interval of stale data after a reload-triggered refetch.

**Recommendation:** A. The signal that drives post-reload refetches is the one most likely to be watched, and the brief's own ordering invariant requires it.
**Pick-instead-if:** B: if Finding 13 resolves HA connectivity as live (removing `connectivity` from the question) and reload-time staleness of up to 30s is acceptable for `apps_changed`.

## Finding 6: Coalescing latest-per-key contradicts appending a history event per transition in the same transaction

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** systems-architect, data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Step 2 coalesces the latest state per key within a tick (research.md:195), and the settled history decision appends an `app_status_events` row "in the same transaction as each transition upsert" (research.md:208). STARTING → RUNNING → FAILED inside one tick yields one upsert, and either one event or three depending on an unstated choice:
- Events taken from the coalesced state leave gaps exactly where flapping happens.
- Events taken from the raw stream come from payloads (`previous_status`), while the current row comes from the registry at tick time. The two can disagree about the same instant.

The reconcile "does not backfill events", so a transition lost to a failed write leaves a permanent gap. History can say `running` while the state row says `failed`, with no marker. The "same transaction" guarantee holds only for the current row and the last event. (The settled decision that history ships with the projector is preserved; this is about which source feeds it.)

**Evidence:** research.md:195-196, 208, 385; `src/hassette/events/hassette.py:140-152` (payload carries `previous_status`).

**Design-challenge:** Is `app_status_events` a sink of the event stream or a record of what the current-state table actually transitioned through?

**Deciding-factor:** History must never contradict the current-state row it sits next to.

**Criteria:**
| | A: uncoalesced event-stream sink, best-effort | B: history derived from diffs of written current state |
|---|---|---|
| Agreement with current row | Can disagree; gaps on lost writes | By construction |
| Captures intra-tick flaps | Yes | No (with a debounced wake, the window is milliseconds) |
| Transactional tie to the upsert | None (own batch) | Same transaction |
| Fits Finding 2's single-writer option | Needs a separate subscriber | Natural fit |
| Honest labelling needed | Must be called a best-effort change log | "Sampled transitions" of current state |

**Options:**
- **A**: History is an event-stream sink. Append every event uncoalesced, in its own batch, with no transactional tie to the upsert, and label the table a best-effort change log.
- **B** *(recommended)*: History is derived from the current-state writer. Each written transition (old value → new value of the row) appends one event in the same transaction, and the brief states history has exactly the fidelity of current state.

**Recommendation:** B. It keeps history and current state consistent by construction, which is what a table that "exists so history accumulates" needs when no timeline UI is committed yet.
**Pick-instead-if:** A: if flap detection (every transition, including those that revert within a tick) is a requirement for the future timeline.

## Finding 7: Reconcile infers "app removed" from an empty registry read mid-reload and can write transient empties

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The brief notes that the registry "clears mid-read during AppHandler teardown" and says the projector "must tolerate this" (research.md:337), without saying how. A full-set reconcile taken mid-clear cannot tell "mid-swap" from "the user removed these apps". It can write transient STOPPED or empty rows and, under a diff-based history, spurious history events. This happens at every app reload, which is when the UI is being watched. The guess is "empty registry means empty"; the registry itself knows nothing about whether it is mid-swap.

**Evidence:** research.md:337; `src/hassette/core/runtime_query_service.py:53-58` (verified docstring: "every AppHandler read below tolerates concurrent AppHandler teardown (registry state clearing mid-read)").

**Design-challenge:** Should the projector be told when a load is in progress rather than guessing from the shape of what it reads?

**Deciding-factor:** The projector is told the registry's state rather than inferring it.

**Criteria:**
| | A: registry exposes load-in-progress; reconcile skips while set | B: reconcile keeps last-written rows when reads look empty |
|---|---|---|
| Inferred state | None: told by lifecycle | Heuristic: guesses "empty means mid-swap" |
| Genuine removals | Written correctly at load completion | Can be suppressed by the heuristic |
| New state | One generation/in-progress marker on the registry | None, but a rule that can become a root cause |
| Pairs with Finding 5 | `APP_LOAD_COMPLETED` wake runs reconcile once at completion | Independent |

**Options:**
- **A** *(recommended)*: The registry exposes a load-in-progress or generation marker (the lifecycle already knows when `APP_LOAD_COMPLETED` fires). The reconcile skips while a load or reload is in progress, and the completion wake runs it once.
- **B**: The reconcile tolerates transient reads heuristically, keeping last-written rows when the registry reads empty or partial.

**Recommendation:** A. It replaces a guess with a signal the lifecycle already has.
**Pick-instead-if:** B: if exposing a reliable in-progress marker from the registry proves impractical across every teardown path.

## Finding 8: Process-scoped runtime state is placed on session-less identity tables, so stale rows read as current

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** systems-architect, data-integrity, structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Issue 3 puts "derived status columns on `app_manifests`", and issue 6 puts guard counters, `next_run`, `fire_at` and `jitter` on `listeners` and `scheduled_jobs`. These are identity tables that outlive sessions; `app_manifests` is explicitly "No session_id FK -- a snapshot table". Consequences:
- **Dead status on identity rows.** For an app removed from config, nothing writes its row, so a derived `status = running` from the last session persists indefinitely. Today `overlay_runtime_state` supplies STOPPED/`in_current_config = False` for exactly this case. The brief says rows are "tagged with `session_id`", but `app_manifests` has no such column.
- **Upsert never removes rows.** An instance count dropping from 3 to 2, or an app removed from config, leaves the old row with its last status.
- **Restart and startup window.** After a restart, those columns hold the previous session's status until the first reconcile, which waits on bootstrap. Reads that filter on the latest session see no rows; reads that don't see old ones. The brief doesn't say which. This conflicts with issue 3's own Done-when ("a crashed session's rows are never reported as current").
- **Counters across sessions.** Guard counters are per-process; on identity rows they reset to 0 at restart with no attribution.
- **Which session is current is inferred.** Snapshot liveness uses `stopped_at IS NULL` plus heartbeat age, and `_do_mark_orphaned_sessions` has no cross-process guard. In live mode, the process knows its own `session_id` and could tell the read side instead.
- **Two writers on one row.** `persist_manifest` and the projector would write different columns of one row. Today's upsert names its columns explicitly, so this is a future risk, not a current bug.

**Evidence:** `src/hassette/migrations_sql/011.sql:6-7` (verified: no `session_id` FK); `src/hassette/core/app_registry.py:391-412` (`overlay_runtime_state` supplies STOPPED for absent apps); `src/hassette/core/app_lifecycle_config.py:42-60`; `src/hassette/core/telemetry/repository.py:203-216` (named-column upsert); `src/hassette/core/session_manager.py:81-84, 157-166`; research.md:75, 84-86, 199, 204, 218-221, 385.

**Design-challenge:** Should "not in the current session" mean STOPPED/not-in-config by construction (a join), rather than by a convention each reader must remember?

**Deciding-factor:** Staleness and removal are structural (a join against the current session), not inferred from whether a row was recently overwritten.

**Criteria:**
| | A: session-scoped runtime tables; live mode is told the session | B: columns on identity tables, plus replace-semantics or `seen_at` |
|---|---|---|
| Removed apps/instances | Absent from the current session's rows by construction | Requires replace-semantics delete or `seen_at` filtering in every read |
| Restart / crash staleness | Old session's rows never join as current | Old values sit on identity rows until overwritten |
| 087's objection to touching identity tables | Moot: identity tables unchanged | Identity tables gain mutable status |
| Read complexity | Joins to current/latest session | Filters on `seen_at`/session per read |
| Seed authoring | Seeds write rows per session | Seeds write status onto identity rows |
| Interacts with reconcile | No reconcile rule needed for removal | Adds a delete/`seen_at` rule to the reconcile (see Finding 1) |

**Options:**
- **A** *(recommended)*: Put all projected runtime state in session-scoped tables keyed `(session_id, ...)`, such as `app_instances`, an `app_runtime(session_id, app_key, ...)` and `listener_counters(session_id, listener_id, ...)`. Keep `app_manifests`, `listeners` and `scheduled_jobs` as identity only. In live mode, pass the current `session_id` to the read side (told, not inferred); only snapshot mode falls back to "latest session". State what reads show between session creation and the first reconcile.
- **B**: Keep status columns on the identity tables. Make the reconcile replace-semantics per session, or add a per-row `seen_at`/`generation` that reads filter on, and derive staleness from the session row.

**Recommendation:** A. It makes the dead-session rule a join rather than a convention, removes the need for a removal rule in the reconcile, and leaves 087's identity tables untouched.
**Pick-instead-if:** B: if per-session duplication of rows proves too costly for retention or seed authoring, and a single `seen_at` filter is acceptable in every read.

## Finding 9: Shutdown ordering means neither the final projected status nor `dropped_shutdown` can be captured

**Severity:** HIGH
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `finalize_session` runs in `before_shutdown`, before children stop. Two consequences share that root:
- **Final status.** Apps and services transition to STOPPED after finalize, while the DB drain budget is about 1.25s. The last projected state of a cleanly stopped session is therefore likely RUNNING. Snapshot mode would present it as a live-looking dashboard under "last known".
- **`dropped_shutdown`.** Issue 2 says "fix the `dropped_shutdown` ordering", but `flush_queue` (the only place `_dropped_shutdown` increments) runs inside `CommandExecutor.serve` during child shutdown and itself calls `submit()`. After `DatabaseService.on_shutdown` detaches the queue, `submit()` raises `WriteQueueUnavailableError`. A finalize moved after the flush can still fail silently, because `finalize_session` is guarded by `is_db_ready` and logs and swallows failures. That leaves `stopped_at` NULL and the final counters unwritten. A periodic snapshot can never contain `dropped_shutdown`, since it counts the final second, and the brief's Done-when ("no more than one heartbeat old") is silent on graceful shutdown.

**Evidence:** `src/hassette/core/core.py:645-677` (verified: counters read and `finalize_session` called in `before_shutdown`); `src/hassette/core/command_executor.py:242`; `src/hassette/core/execution_pipeline.py:188-230`; `src/hassette/core/database_write_queue.py:30-44, 124-136, 224-226`; `src/hassette/core/session_manager.py:135-143, 323-324`; research.md:180, 384.

**Design-challenge:** What is the last write a cleanly stopping session makes, and is it ordered after the state it records but before the queue closes?

**Deciding-factor:** A cleanly stopped session's final row reflects what actually happened at shutdown, and a failure to write it is visible.

**Criteria:**
| | A: final write after children stop and flush, before DB detach | B: no final write; reads derive "stopped" from the session row |
|---|---|---|
| Final status correct | Yes | Rendered as "stopped/last known" by the read rule, not stored |
| `dropped_shutdown` captured | Yes | Never (always 0 or absent) |
| Failure visibility | Counted and logged, not swallowed | n/a |
| Ordering complexity | One hook between child shutdown and `DatabaseService` detach | None |

**Options:**
- **A** *(recommended)*: Add a final projection and counter write after `flush_queue` (a hook in the `CommandExecutor` shutdown path), ordered before `DatabaseService` detaches. A failed final write is counted and logged rather than swallowed.
- **B**: Make no final write. Reads render any row of a session with `stopped_at` set as "stopped/last known", derived from the session row, and the brief documents `dropped_shutdown` as uncapturable on graceful shutdown.

**Recommendation:** A. Issue 2 already commits to fixing `dropped_shutdown`, which is impossible without a post-flush write, and the same hook fixes the RUNNING-at-stop problem.
**Pick-instead-if:** B: if inserting a hook between child shutdown and DB detach conflicts with the resource teardown ordering in `.claude/rules/resource-lifecycle.md`.

## Finding 10: "Self-heals within 30s" fails when the write path is the failing thing, and the lag banner reads projector-local state that can silently freeze

**Severity:** HIGH
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** data-integrity, structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The reconcile uses the same queue, single writer and `submit()` as the transition write that failed. Whatever dropped the transition (queue full, writer wedged, disk full) also drops the reconcile. A log storm fills the shared 2000-slot queue, and `submit()` then blocks the full 60s, twice the reconcile interval. Heal time is unbounded under sustained saturation, and the brief still asserts the 30s bound. The mitigation (`projection_lag_seconds` from an in-memory `last_reconcile_ok_at`) has gaps:
- If the projector crashes, hangs inside a long `submit()` or never starts, the value is absent or frozen, and the brief does not map "missing" to "degraded".
- If lag is computed only when the loop ticks, a blocked tick produces no update and no banner.
- `/telemetry/status` today swallows `AttributeError`/`RuntimeError` and returns zeros, so "no signal" renders as "no drops".

The user's key scenario (writes fail, reads work, the UI shows confident stale status) is only mitigated if lag is computed at request time.

**Evidence:** `src/hassette/core/database_write_queue.py:233-237, 260-288`; `src/hassette/web/routes/telemetry.py:101-110` (verified: `except (AttributeError, RuntimeError): overflow, exhausted, shutdown = 0, 0, 0`); research.md:38, 189, 202, 213.

**Design-challenge:** When the projector is the thing that is broken, what tells the UI?

**Deciding-factor:** A stuck or missing projector produces a visible degraded signal within a bounded time.

**Criteria:**
| | A: request-time lag, None = degraded, per-attempt timeout | B: reserved status lane in Layer A |
|---|---|---|
| Detects a wedged/missing projector | Yes (lag grows at read time; None after startup grace = degraded) | No: a lane does not detect a dead projector |
| Bounds a blocked tick | Yes (per-attempt timeout below the interval) | Partly (less contention) |
| Fixes write ordering (Finding 3) | No (separate concern) | No |
| New machinery | A timestamp read and a timeout | A second queue discipline, unmeasured need |
| Critic support | data-integrity, structural-minimalist; architect agrees on deferring a lane | Pushed back on by all three critics |

**Options:**
- **A** *(recommended)*: Compute `projection_lag_seconds` on read as `now - last_reconcile_ok_at` (monotonic). Treat `None` after a startup grace period as degraded. Bound each reconcile attempt with its own timeout shorter than the interval. Make `/telemetry/status` report a missing accessor as unavailable rather than zeros. Replace the brief's "self-heals within 30s" with the actual bound, or measure it before asserting it.
- **B**: Reserve capacity (a separate lane) for status writes in Layer A.

**Recommendation:** A. It detects the failure the user worried about, with no new queue. All three critics argue against building a lane before lag is measured.
**Pick-instead-if:** B: if measured reconcile lag under realistic log storms exceeds the banner threshold routinely, even with the per-attempt timeout.

## Finding 11: "Any lost write self-heals" overclaims; several persisted writes the UI reads are not in the reconcile

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The bottom line says reconcile means "any lost write self-heals within one interval" (research.md:38). The reconcile as specified rewrites app, instance and service rows, counters and gauges. Other awaited writes the design relies on are not rewritten:
- `mark_job_status`/`schedule_status` (the brief itself says "stale until the next transition", research.md:177)
- listener and job registration upserts, which produce the db ids that executions reference
- `persist_manifest`, whose failures are swallowed with a WARNING, and whose timeout path says the write "may still complete"

The strictness claim is false for those columns unless each has its own heal path.

**Evidence:** research.md:38, 177, 189; `src/hassette/core/app_lifecycle_config.py:55-80`; `src/hassette/core/telemetry/repository.py:241-260`.

**Design-challenge:** For each persisted column the UI reads, what heals a lost write?

**Deciding-factor:** The brief's reliability claim is exactly as strong as what the design enforces.

**Criteria:**
| | A: enumerate fields with their heal mechanism; scope the claim | B: extend the reconcile to rewrite every UI-read column |
|---|---|---|
| Claim accuracy | Exact | Exact |
| Reconcile payload | Unchanged | Grows (registrations, manifests, job status) |
| Effort | One table in the spec | Larger reconcile; may conflict with registration id semantics |
| Leaves real gaps visible | Yes, named per field | Closes them |

**Options:**
- **A** *(recommended)*: Add a table to the brief or spec listing every persisted column the UI reads and its heal mechanism (reconcile, next transition, next registration, none). Reword the bottom line to cover only the reconciled set.
- **B**: Extend the full reconcile to rewrite every UI-read column, including `schedule_status` and manifests.

**Recommendation:** A. It makes the claim honest at almost no cost, and lets each uncovered column be decided on its merits (next-run timing is handled in Finding 12).
**Pick-instead-if:** B: if a specific uncovered column (for example `schedule_status`) is shown to stay wrong long enough to mislead in practice.

## Finding 12: Issue 6 routes `next_run`/`fire_at`/`jitter` through the projector, but no reschedule event exists and an existing per-transition write already carries it

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** structural-minimalist, systems-architect, data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Issue 6 writes job timing "on reschedule via the projector (coalesced)" (research.md:388). The projector subscribes only to `app_state_changed` and `service_status`, so no event reaches it on reschedule. That leaves two choices, both bad:
- Invent a per-fire bus event on the scheduler's hottest path.
- Rely on the 30s reconcile, which makes `next_run` perpetually in the past for any job with an interval under 30s. That breaks the Done-when's "jobs (with next run)".

The write already exists. `persist_schedule_status` runs after every `Job.transition_to()`, and recurring jobs transition to SCHEDULED with a new `next_run` on every fire, issuing an awaited `UPDATE scheduled_jobs`. Widening that statement costs zero extra writes. This also answers the architect's concern that per-fire writes would load the shared FIFO (the UPDATE already runs per fire), and the data-integrity concern that a lost reschedule write stays stale: it heals on the next transition, the same as `schedule_status`.

**Evidence:** `src/hassette/core/scheduler_dispatch.py:92-93, 131-144, 208-217` (verified: `transition_to(SCHEDULED, next_run=...)` followed by `persist_schedule_status` per fire); `src/hassette/core/telemetry/repository.py:241-260` (verified: the UPDATE touches only `schedule_status` and reason); `migrations_sql/*.sql` (no `next_run`/`fire_at` column today, verified by grep); research.md:84, 194-195, 388.

**Design-challenge:** Why route a value through a new mechanism when the mutation site already writes the row on every change?

**Deciding-factor:** Correct next-run for every job interval at zero extra writes and no new events.

**Criteria:**
| | A: widen the existing per-transition UPDATE | B: write at reconcile plus add/remove/trigger change | C: projector-coalesced per reschedule (as written) |
|---|---|---|---|
| Extra writes | None | Fewer than per-fire | New per-fire event plus coalesced writes |
| Correct for sub-30s intervals | Yes | No (UI must render stale absolute time) | Only with a new per-fire event |
| New mechanism | None | None | New bus event on the scheduler hot path |
| Issue 6 depends on issue 3 | No | Yes (reconcile) | Yes |
| Heal on lost write | Next transition | Next reconcile | Next reconcile, if covered |

**Options:**
- **A** *(recommended)*: Extend `mark_job_status` to persist `next_run`, `fire_at` and `jitter` alongside `schedule_status`/reason at every transition. Issue 6 drops its dependency on the projector, and guard counters still ride the reconcile snapshot.
- **B**: Write `next_run` only at reconcile and on job add, remove or trigger change, and have the UI render the absolute timestamp.
- **C**: Keep the brief's design: projector-coalesced writes on reschedule, also included in the full reconcile.

**Recommendation:** A. The write already happens per fire, so persisting timing there is free, correct for every interval, and decouples issue 6 from issue 3.
**Pick-instead-if:** B: if measurements show the per-transition UPDATE itself is a write-queue bottleneck worth thinning. C: if job timing must be written together with other projected state in one transaction for a reason not stated in the brief.

## Finding 13: System health (services, HA connection, bootstrap, `/health` status): persist with a single derivation, or keep it on the live seam

**Severity:** MEDIUM
**Type:** Approach-now
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** systems-architect, structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The brief persists service status, HA connectivity and the bootstrap latch (inventory rows 6-8), then computes `ok`/`degraded`/`starting` in the query layer at read time. That has two problems:
- **Second, lossy derivation (architect).** The brief writes the computed app view to "keep one derivation in Python", but derives system status at read time. `get_system_status` branches on `has_ever_connected`, which the brief does not persist. Inferring it from `ha_connected_changed_at IS NOT NULL` is wrong after a restart with HA down at boot.
- **Wrong side of the line (minimalist).** These are properties of the process, not the automations. The brief's own argument that "a DB-sourced 'the DB is fine' signal dies with the thing it diagnoses" applies equally to "HA is connected". In live mode, the web server shares a process with the truth and would read it through a copy that lags by up to a tick. Persisting it also brings a new `service_status` table, the `IS_NOT_APP_ROLE` reconciliation (#2938), and dead-session `ha_connected=1` semantics.

The critics propose opposite fixes. The Done-when (research.md:376) names Diagnostics rendering "services" from a seed.

**Evidence:** `src/hassette/core/runtime_query_service.py:328-358` (`get_system_status` derives status from three live flags and children); `.claude/rules/core-startup.md` ("starting/ok/degraded" semantics on `has_ever_connected`); research.md:80-82, 156, 206, 213, 376, 387.

**Design-challenge:** Is "is HA connected, are my services up" automation state that a seed should express, or process state that only the live process can answer?

**Deciding-factor:** Meet the Done-when (seeded Diagnostics renders services and status) with one derivation and no lossy inputs.

**Criteria:**
| | A: project `system_status` and `has_ever_connected` as written columns | B: keep process health on the live seam | C: as written (persist inputs, derive at read) |
|---|---|---|---|
| Done-when (seeded Diagnostics services) | Met | Not met without relaxing it, or a single `sessions.services_json` | Met |
| Number of derivations | One (in process) | One (live) | Two (Python for apps, query layer for health) |
| Lossy input (`has_ever_connected`) | Fixed | n/a | Present |
| New schema | `service_status` table plus written status columns | None (or one JSON column) | `service_status` plus inputs |
| Live-mode freshness | Lags up to a tick | Exact | Lags up to a tick |
| `IS_NOT_APP_ROLE` mismatch | Must be settled | Disappears | Must be settled |

**Options:**
- **A** *(recommended)*: Persist system health, but project `system_status` (and `has_ever_connected` if the branch survives) as written columns computed once in the process, so the read side has no derivation and seeds can express DEGRADED/starting directly.
- **B**: Keep `/health` services, HA connection, bootstrap and status on the live seam. In snapshot mode, the Diagnostics services panel renders "unavailable" (or reads a single `sessions.services_json` written at reconcile). Relax the Done-when accordingly.
- **C**: Keep the brief as written.

**Recommendation:** A. It satisfies the Done-when the brief commits to and removes the second, lossy derivation. The user's stated preference is strict DB truth for state.
**Pick-instead-if:** B: if seeded Diagnostics showing services is not actually needed (screenshots and docs can come from the demo stack), so the `service_status` table and the #2938 reconciliation can be deleted. C: never; it keeps the lossy input.

## Finding 14: The live seam has no declared interface, and snapshot mode as "a second factory" forks the web app

**Severity:** MEDIUM
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** systems-architect, structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** In snapshot mode, the seam routes "answer `mode: snapshot`", actions return problem responses, and `/telemetry/status` has no drop counters. The brief names the seam as four routes but not as a contract. Today those routes depend on `RuntimeDep`, and the web app's remaining dependencies on Hassette all go through `request.app.state.hassette`: `config.web_api` for CORS, auth and trusted proxies, `log_retention_days`, action pre-flight checks, and the RQS WS fan-out. A second `create_fastapi_app(snapshot_db=...)` factory forks all of that, and each fork must track every middleware and router addition. Without a declared seam, each seam route grows an `if snapshot:` branch, or the snapshot factory wires a stub again, which is what `create_hassette_stub` is today and what the Done-when forbids. Option B names a `LiveOverlay`; the recommended Option A has no equivalent. `web-no-core` is claimed but not mechanized.

**Evidence:** research.md:288-294, 379, 391; `src/hassette/web/routes/health.py:13-27` (routes take `RuntimeDep`); `src/hassette/web/app.py:96-125`; `src/hassette/web/middleware.py:243-244`; `src/hassette/web/dependencies.py:60-77`; `src/hassette/web/routes/executions.py:83`.

**Design-challenge:** What is the one object the web layer depends on, such that live and snapshot modes differ only in what is passed in?

**Deciding-factor:** One factory and one dependency where the modes differ, so snapshot mode cannot drift from live mode.

**Criteria:**
| | A: one factory over `WebContext(config, telemetry, live: LiveSeam \| None)` | B: `LiveSeam` protocol with live and snapshot implementations, two factories |
|---|---|---|
| Factories to keep in sync | One | Two |
| Where mode branching lives | One `LiveDep` raising the 409/503 problem when `live is None` | Inside the snapshot implementation |
| `web-no-core` | True by construction | Still by convention for the factory |
| Compat-fixture generator | Same factory with a fake `LiveSeam` (Finding 15) | Snapshot factory plus separate fake |
| Sequencing | Moves part of issue 9 ahead of issues 4-7 | Fits in issue 5 |

**Options:**
- **A** *(recommended)*: Replace `app.state.hassette` with a small `WebContext(config, telemetry, live: LiveSeam | None)` and one `create_fastapi_app(ctx)`. Live mode passes a `LiveSeam` (probes, pipeline health, actions, WS broadcast); snapshot mode passes `None`, and a single `LiveDep` raises the problem response. Define it in or before issue 5.
- **B**: Define a `LiveSeam` protocol with live and snapshot implementations in issue 5, and keep a separate snapshot factory in issue 9.

**Recommendation:** A. It removes the fork rather than standardizing it, and gives the compat generator and dev script the same entry point.
**Pick-instead-if:** B: if replacing `app.state.hassette` before issues 4-7 creates sequencing conflicts with #2555 or the apps/mappers rewrite.

## Finding 15: The compat-fixture generator cannot move to the snapshot factory without losing the action and probe shapes it pins

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** Auto-apply
**Raised-by:** structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Issue 9 switches `generate_client_compat_fixtures.build_app()` to the snapshot factory "where possible". The generator builds with `app_action_mocks=True`, scheduler-trigger wiring and auth enabled, and generates probe and problem responses. Snapshot mode answers actions with 409/503, so success-shape fixtures for `POST /apps/{key}/start` and similar cannot come from it. The Done-when line "no longer uses `create_hassette_stub`" is therefore either unreachable for this tool or silently narrows what `client_compat` verifies.

**Evidence:** `tools/generate_client_compat_fixtures.py:261-281`; research.md:379 (Done-when) versus :391 ("where possible").

**Design-challenge:** How does the generator keep pinning action shapes once the stub is gone?

**Better-approach:** Amend the Done-when bullet at research.md:379 and the issue 9 text at :391 to say that `generate_client_compat_fixtures.py` reads GET fixtures from a real seeded DB and keeps a small typed fake for the live seam (actions, probes, pipeline health), replacing `create_hassette_stub` rather than dropping action-shape coverage.

## Finding 16: Config and schema persistence (issue 7) is inconsistent with the settled `source` 404 decision

**Severity:** MEDIUM
**Type:** Approach-now
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The user settled that `/apps/{key}/source` returns 404 in snapshot mode because user code is not stored in the telemetry DB. App config and schema are the same class of read: the brief calls them "a different kind of read" needing "class-load-time capture" and a "new code path". Issue 7 adds:
- `config_snapshots`, `app_config_json` and `config_schema_json`
- a masking-at-write step, so masked config now sits at rest in the DB (a security-sensitive path)
- a class-load hook

All so two config pages work in a dev-only mode. No Done-when bullet requires it except the self-imposed "no GET route outside the seam reads process memory". The settled source decision is not reopened; it is the precedent.

**Evidence:** research.md:89-92, 150, 155, 307, 375-379, 389; `src/hassette/web/routes/config.py:29-30`; `src/hassette/web/config_view.py:303-307`.

**Design-challenge:** If user code stays out of the telemetry DB, why does user config go in?

**Deciding-factor:** Consistency with the settled source decision and the fewest new persisted surfaces, against the user's "strictly everything" preference.

**Criteria:**
| | A: config on the live seam, delete issue 7 | B: keep issue 7 |
|---|---|---|
| Consistent with source 404 | Yes | No |
| New tables and hooks | None | `config_snapshots`, per-app config/schema columns, class-load hook |
| Masked config at rest | No | Yes |
| Config pages in seeded screenshots/docs | Unavailable | Available |
| User's strict preference | Relaxed to "automation state" | Met |
| `log_retention_days` hint (row 18) | Stays live | From `config_snapshots` |

**Options:**
- **A** *(recommended)*: Treat config like source. Live routes keep reading process memory, and snapshot mode answers "unavailable" through the live seam. Delete issue 7 and relax the Done-when's last bullet to "no GET route that renders automation state reads process memory".
- **B**: Keep issue 7 as written.

**Recommendation:** A. It matches the precedent the user already set for source, removes a masking-at-rest path, and cuts an issue no Done-when bullet needs.
**Pick-instead-if:** B: if seeded screenshots or docs of the Config page and Config tab are a real need, or "strict" is meant to cover config as well as state.

## Finding 17: New session-referencing tables have no retention story and can block session pruning

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** Auto-apply
**Raised-by:** data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `sessions` rows are pruned only when no `executions` or `blocking_events` row references them. New tables with a `session_id` reference (`app_instances`, `service_status`, `app_status_events`, and any session-scoped runtime tables) are not in that guard: depending on FK enforcement, they either block session pruning or are orphaned when their session is deleted. `app_status_events` is append-only with no retention target, so it grows without bound, and the size failsafe can delete only from the listed tables. The brief's "retention already protects current-state rows" (research.md:143) is true, but it doesn't address append-only history.

**Evidence:** `src/hassette/core/database_retention.py:293-297` (verified: the session-prune `NOT EXISTS` checks only `executions` and `blocking_events`); `src/hassette/core/retention_targets.py:76-81`; research.md:143, 385.

**Design-challenge:** Does every new table have a defined lifetime?

**Better-approach:** Add to issue 3's scope (research.md:385): each new session-referencing table is added to the session-prune guard in `database_retention.py` (or deleted with its session), and `app_status_events` gets an age-based retention target in `retention_targets.py` in the same migration issue.

## Finding 18: Drop accounting should use one taxonomy routed through one helper, with sampling shown separately from loss

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Classification:** Auto-apply
**Raised-by:** data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Issue 2 counts the uncounted drop paths (C6-C8, blocking-event enqueue) and fixes the C2 miscount, but leaves the mapping scattered across call sites. Layer A `enqueue()` returning `False` must be checked at each caller to be counted. `dropped_filtered` is intentional sampling, yet the brief places it next to real losses in one "dropped events" indicator, so operators will read sampling as data loss. Counters are per-process, so `sessions.dropped_*` is per-session, not lifetime, and the brief doesn't say how the UI presents that. (The critic also called the deferred-retry overflow at `execution_pipeline.py:177` a second miscount. That branch increments `_dropped_overflow` on a queue-full condition, which is the bucket the brief itself wants queue-full drops in, so that sub-claim is not carried here. C2 at :375 is confirmed.)

**Evidence:** `src/hassette/core/execution_pipeline.py:88, 172-180, 370-378` (verified); `src/hassette/core/command_executor.py:189-192`; research.md:172-181, 384.

**Design-challenge:** Is there one place that decides what kind of drop happened?

**Better-approach:** Add to issue 2's scope (research.md:384): define the drop taxonomy once (overflow, retry-exhausted, shutdown, non-retryable, no-session, filtered-by-sampling) and route every drop site through a single `record_drop(reason, count)` helper. The UI shows filtered-by-sampling separately from losses, and labels `sessions.dropped_*` as per-session.

## Finding 19: Every new UI-visible runtime field costs a migration, a projector line, a wire change and a seed change

**Severity:** TENSION
**Type:** Approach-later
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The brief acknowledges the cost (research.md:349), but the change surface is wide: a column, a projector line, a `SystemStatusResponse` change (`feat!:` plus a compat ignore), a seed scenario and a frontend type. Requirement drift is certain; the brief itself adds fields while designing (`projection_lag_seconds`, `only_apps_json`, `as_of`). With forward-only migrations and fatal rollback, each addition is expensive.

**Evidence:** research.md:131, 340, 349; `2026-06-16-telemetry-db-rollback-safety` as cited at research.md:131.

**Design-challenge:** Which fields need to be queryable columns, and which are diagnostic gauges that only need to be displayed?

**Side-a:** Strict columns for everything. Every field is typed, queryable and visible in the schema, and the `design-completeness.md` discipline already expects this for telemetry fields.
**Side-b:** Columns for queryable state, plus one JSON `runtime_gauges` column per session for diagnostic and gauge-like fields (`pending_wait_for`, drop snapshots, boot-issue detail), so adding a gauge needs no migration.
**Deciding-factor:** Will gauges ever be filtered, joined or aggregated in SQL, or only displayed?

**Criteria:**
| | Side A: strict columns | Side B: columns plus a JSON gauges column |
|---|---|---|
| Migration per new gauge | Yes | No |
| Queryability of gauges | Full | JSON functions only |
| Type safety at the DB boundary | Schema-enforced | Validated in the wire model only |
| Rollback exposure | Grows with each field | Bounded for gauges |
| Seed authoring | Per column | One JSON blob |

**Pick-instead-if:** Side A: if gauges will be queried or aggregated across sessions. Side B: if gauges are display-only and new ones are expected to appear often pre-v1.

## Finding 20: Single-writer head-of-line blocking from reconcile payload size

**Severity:** MEDIUM
**Type:** Approach-later
**Design-level:** No
**Classification:** User-directed
**Raised-by:** data-integrity
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Audience assumption: a deployment with hundreds of apps, instances, jobs and listeners, where the reconcile writes thousands of rows (listener and job counters, gauges) every 30s. The brief sizes the reconcile at 40-60 rows, which holds at about 3 known users. The writer is single and FIFO, so a bulk upsert blocks every execution batch behind it, coupling telemetry latency to status payload size. No action is needed now; the spec should state the assumption so it does not become silent debt.

**Evidence:** research.md:189, 338; `src/hassette/core/database_write_queue.py:47-88` (sequential worker, one item at a time).

**Design-challenge:** At what row count does the reconcile transaction become a latency problem for telemetry?

**Deciding-factor:** Make the sizing assumption explicit at negligible cost.

**Criteria:**
| | A: record the assumption and a row budget | B: no action |
|---|---|---|
| Cost | One sentence in the spec | None |
| Future visibility | Threshold named | Silent |
| Relevance at current user base | Low | Low |

**Options:**
- **A** *(recommended)*: Record the 40-60 row assumption and a row-count threshold at which reconcile batching or diffing is revisited.
- **B**: Take no action.

**Recommendation:** A. It costs one sentence. If Finding 2's diff-based single writer is adopted, the payload shrinks to changed rows anyway.
**Pick-instead-if:** B: if Finding 2 is resolved as A and the reconcile writes only diffs, making the payload size concern moot.

## Finding 21: The A-versus-B framing hides a smaller design that still meets the strict preference

**Severity:** TENSION
**Type:** Approach-now
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** structural-minimalist
**visibility:** presented
**disposition:** pending

**Why-it-matters:** The brief frames Option B as a clean prefix at about half the work and Option A as strict. If Findings 2, 12, 13, 14 and 16 go the minimalist way, the smallest design that meets the goals is neither. It would be a single reconcile-driven projector for app and instance status, `next_run` via the widened existing UPDATE, one `WebContext` factory, and config/services/source on the live seam: roughly seven smaller issues, keeping "automation state is in the DB, strictly". B's dividing line (counters, `next_run` and config stay in memory) is wrong for `next_run`, which is free to persist, and arguably right for config and services. The architect disagrees on scope: the Done-when needs `next_run` and counters persisted to avoid "—" cells, and a later move from B to A redoes the enrichment paths.

**Evidence:** research.md:276-331, 369, 393; `src/hassette/core/scheduler_dispatch.py:131-144`.

**Design-challenge:** Should the brief present the per-field placement decisions directly, instead of a prefix framing?

**Side-a:** Re-present the recommendation as "Option A-minus": state where `next_run`, counters, services and config each fall (DB or live seam) as explicit decisions, and size the initiative from those.
**Side-b:** Keep the A-versus-B framing with B as a clean prefix of A. It is simpler to read, and the per-field decisions can be made in the `/mine-sketch` spec instead.
**Deciding-factor:** Should the research brief carry the per-field placement decisions, or leave them to the spec?

**Criteria:**
| | Side A: A-minus with per-field decisions | Side B: keep A/B prefix framing |
|---|---|---|
| Accuracy of effort estimate | Reflects resolved findings | Overstates both options |
| Reader load | More decisions in the brief | Simpler choice |
| Where decisions are recorded | Brief | Spec |
| Depends on other findings' outcomes | Yes (2, 12, 13, 14, 16) | No |

**Pick-instead-if:** Side A: if Findings 12, 13 or 16 resolve toward the minimalist options, so the A/B line no longer matches the design. Side B: if most findings resolve toward the brief as written, or the spec is the intended place for the per-field decisions.
