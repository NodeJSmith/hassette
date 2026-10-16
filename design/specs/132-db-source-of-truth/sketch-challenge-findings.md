# Challenge Findings

**Format-version:** 4
**Target:** /home/jessica/source/hassette/.claude/worktrees/wire-up-seeds-to-ui/design/specs/132-db-source-of-truth/design.md
**Critics:** operational-resilience, contract-caller
**Likely-invalid:** 1

## Finding 1: Findings converge on the projection-freshness signal (D8's in-memory, live-seam-only lag)

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** Synthesis
**Converges:** Findings 3, 11, 12, 13
**visibility:** presented
**disposition:** applied

**Why-it-matters:** Four findings from both critics reach one mechanism from different directions. D8 computes freshness as an in-memory monotonic timestamp exposed only on `/telemetry/status` and the web UI banner. Every other reader gets no freshness signal. Finding 3: `/health` and `/api/apps` (which hass-hassette and `hassette status` poll) keep reporting `ok`/running after the projector wedges. Finding 11: a crashed session's per-app rows read as RUNNING. Finding 12: a stopped session's stored `/health` status reads as current in snapshot mode. Finding 13: `as_of` comes from a heartbeat that a seed, or a `DatabaseService` loop independent of the projector, wrote. Each finding proposes its own read-time rule (a live-mode `/health` downgrade, a crashed-session render rule, a forced snapshot `degraded`, a seed `stopped_at` stamp). D8's own deciding factor says the system must never show confident stale status, and every one of these consumers does. The question is whether the freshness signal should be redesigned, or even moved to a different layer, instead of patched four times. One possibility is a persisted fact that every reader applies in the one place runtime rows join to their session.

**Evidence:** design.md D8 (lag "now minus the projector's last successful write (monotonic clock)", on `/telemetry/status` only), D9 (`/health` "becomes a plain read"), D15 (`as_of` from `stopped_at`/`last_heartbeat_at`), D6 (live vs snapshot session selection); `wire/src/hassette_wire/health.py:38-72` (no timestamp or lag field); hass-hassette `coordinator.py:99-103` (polls `get_health`, `get_apps` only); `src/hassette/core/session_manager.py:145-168` (orphaned sessions backfilled only at next startup).

**Design-challenge:** If the only consumer told about staleness is the web UI's live-mode banner, who else is "never shown confident stale status"?

**Deciding-factor:** whether one freshness mechanism, applied once, can replace four separate read-time patches.

**Criteria:**
| | A: re-evaluate the freshness mechanism | B: keep D8's mechanism, fix 3/11/12/13 individually |
|---|---|---|
| Rules added to readers | Settled once by the re-evaluation | Up to four separate read-time rules in different routes and modes |
| Consistency across live, snapshot, crashed and seeded sessions | One answer for all four | Each case answered separately; they can disagree |
| Touches ratified decisions | D8 and D15 reopened together | D8, D9 and D15 each amended separately |
| Cost now | One focused re-evaluation | Four smaller edits |
| Evidence strength | Two critics, four findings, and D8's own deciding factor | Same evidence, treated piecemeal |

**Options:**
- **A** *(recommended)*: Re-evaluate the projection-freshness mechanism before addressing Findings 3, 11, 12 and 13 individually. Open questions: is freshness in-memory or persisted; which clock defines it (projector run, write commit, heartbeat); is it applied at read time in one shared place or per route; does it reach `/health`, `/api/apps`, snapshots and released clients; how does it relate to `as_of` and to D15's "process state unknown" label; and is a separate freshness signal needed at all once those questions are answered.
- **B**: Keep D8's mechanism and address Findings 3, 11, 12 and 13 individually.

**Recommendation:** A. Two critics working independently landed on the same gap. Each local fix adds a read-time rule that has to agree with the others. D8's deciding factor is broken for every consumer outside the live-mode web UI, so the mechanism is the problem rather than any one route.
**Pick-instead-if:** B: you're content for non-UI consumers (hass-hassette, the CLI, released clients) and snapshots to carry no freshness signal, and only want the live web UI covered.

## Finding 2: Findings converge on D19's issue cut for wire and consumer changes (the `/health` and WS `connected` rewrite)

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** Synthesis
**Converges:** Findings 4, 5, 6, 14
**visibility:** presented
**disposition:** applied

**Why-it-matters:** Four contract-caller findings come down to how D19 spreads edits to `SystemStatusResponse` and `ConnectedData` across issues and releases. Finding 4: required fields are removed outright, which breaks released clients and the client-compat gate. Finding 5: a new `/health` start-time field has no name and no issue. Finding 6: issue 8 can land before the `/health` field it reads, and `/health` is edited in #2806, issue 7, issue 8 and issue 9. Finding 14: `connected` drops required fields that stale browser bundles still validate against. Each proposes its own sequencing patch. D12's own deciding factor is "rewrite `SystemStatusResponse` once", yet D9, D13, D14 and D15 each change it in a different D19 row. The question is whether D19's cut should be re-evaluated as a whole for these wire surfaces, rather than adding a dependency edge here and a defaulted field there. The operational-resilience critic did not reach D19. This convergence rests on one critic plus the ledger's own D12.

**Evidence:** design.md D12 (deciding factor "rewrite `SystemStatusResponse` once"), D13, D14, D15, D19 table rows 4-9; `wire/src/hassette_wire/health.py:46-47` (`uptime_seconds`, `entity_count` required, no default); `wire/src/hassette_wire/ws.py:77-79` (`ConnectedData` required fields); `frontend/src/hooks/use-scoped-query.ts:76-80`; `tools/check_client_compat.py` module docstring; `tools/client_compat_release.py` (fixtures typed by newest published release reachable from HEAD).

**Design-challenge:** D12 says the response is rewritten once, so why do four D19 rows each edit it?

**Deciding-factor:** whether the wire surfaces get one coherent landing plan or four independent patches to a ratified table.

**Criteria:**
| | A: re-evaluate D19's cut for wire surfaces | B: patch Findings 4, 5, 6, 14 individually |
|---|---|---|
| Consistency with D12's "rewrite once" | Restored by design | Still spread across rows; patches add edges |
| Main-branch states between merges | Considered as a whole | Each patch fixes one known gap; others may remain |
| Released-client and stale-bundle breakage | Decided once (staging or coordinated release) | Decided per field |
| Reopens ratified decisions | D19 (and possibly D14's breaking-change framing) | D19 amended four times |
| Cost now | One re-cut | Four small edits |

**Options:**
- **A** *(recommended)*: Re-evaluate D19's issue cut for the wire and consumer changes before addressing Findings 4, 5, 6 and 14 individually. Open questions: how many issues touch `SystemStatusResponse` and `ConnectedData`, and in what order relative to #2806; whether removals are staged across releases or coordinated with a hass-hassette release; which issue owns the new `/health` start-time field and its consumers; where seed runtime rows and the generator's `WebContext` adoption land relative to the route switches; and whether issue 5 changes any WS message shape.
- **B**: Keep D19's cut and address Findings 4, 5, 6 and 14 individually.

**Recommendation:** A. D12 already commits to rewriting `SystemStatusResponse` once, and D19 contradicts it. Each local patch fixes one ordering gap but leaves the cut that produced the gaps in place. Re-cutting once is cheaper than four amendments to a ratified table.
**Pick-instead-if:** B: you'd rather keep the ratified nine-issue table intact and accept a few added dependency edges and per-field staging notes.

## Finding 3: Projection freshness is not persisted or exposed; `/health`, `/api/apps`, `as_of` and snapshots read a wedged projector as healthy

**Severity:** HIGH
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller, operational-resilience
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** After D9, `/health` `status`, `websocket_connected` and `services`, plus `/api/apps` statuses, are the last committed projection. D8 puts the staleness signal only on `/telemetry/status` and the web-UI banner. hass-hassette polls only `get_health()` and `get_apps()` (coordinator.py:99-103), and `hassette status` reads `/health`. So a wedged projector or a failing write path leaves `/health` at `status: ok` with HTTP 200, and `/api/apps` showing running apps, indefinitely. D15's `as_of` comes from `last_heartbeat_at`, which `DatabaseService` writes independently of the projector (D3 splits them), so a dead projector with a live heartbeat gives a current-looking `as_of` over stale rows. D8's "last successful write" also needs one sentence of precision. D1.2 reads the snapshot inside the job, so every run submits a job, including no-op runs. The ledger should state that a no-op run counts, so lag doesn't grow in an idle, healthy system. Both critics proposed persisting `projected_at` per session. The contract critic also proposed a read-time `degraded` downgrade on live `/health`, and explicitly rejected a 503, which would flip Docker probes and hass-hassette to unhealthy over a display lag.

**Evidence:** design.md D3, D8, D9 ("Lags up to one projector run"), D15; `wire/src/hassette_wire/health.py:38-72` (no timestamp or lag field); hass-hassette `custom_components/hassette/coordinator.py:99-103` (verified via `gh api`); `src/hassette/core/session_manager.py:157-166` (heartbeat is the liveness fact).

**Design-challenge:** A 200 with no timestamp lets every poller infer "current". Why does only the web UI get told otherwise?

**Deciding-factor:** pollers and snapshots get the same staleness signal as the UI banner, without turning a display lag into a probe failure.

**Criteria:**
| | A: persist `projected_at` per session; expose it (and `projection_lag_seconds`) on `/health`; live `/health` downgrades `status` to `degraded` in-band past the banner threshold | B: persist `projected_at` and expose it on `/health` only, no status downgrade | C: keep D8 as ratified (lag on `/telemetry/status` only) |
|---|---|---|---|
| hass-hassette and CLI see a wedged projector | Yes, as `degraded` | Only if they read the new field (released clients ignore unknown fields) | No |
| Snapshot `as_of` reflects projection, not heartbeat | Yes | Yes | No |
| Probe semantics | Unchanged (in-band, 200) | Unchanged | Unchanged |
| New state / heuristics | Persisted timestamp plus a read-time downgrade rule | Persisted timestamp | None |
| Wire change | Additive field with default | Additive field with default | None |

**Options:**
- **A** *(recommended)*: Persist `projected_at` per session (updated by every successful run, including no-ops, in the same transaction). Use it for `as_of` and for lag in both modes, expose it on `/health`, and have live-mode `/health` downgrade `status` to `degraded` in-band (never 503) when lag exceeds the banner threshold.
- **B**: Persist and expose `projected_at` (and use it for `as_of`) but leave `status` as stored.
- **C**: Keep D8 as ratified.

**Recommendation:** A. It is the only option where existing pollers, including the released client that ignores unknown fields, actually stop reporting a wedged projector as healthy, and it keeps probe status codes unchanged. If Finding 1's re-evaluation is chosen, this finding is superseded by it.
**Pick-instead-if:** B: you want `status` to stay a pure stored derivation (D9's single derivation) and accept that only updated consumers see staleness. C: non-UI consumers aren't in scope for the "never confident stale" guarantee.

## Finding 4: Removing required `uptime_seconds` / `entity_count` from `/health` breaks the released client, hass-hassette, and the repo's client-compat gate

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** `SystemStatusResponse.uptime_seconds` and `entity_count` are required with no default. Lenient parsing absorbs unknown fields and enum values but not missing required ones (`errors.py:84`), so released clients raise `ResponseValidationError`. hass-hassette pins `hassette-client==0.56.0` and maps that error to a poll error (coordinator.py:117-123). After this change every installed integration's entities go unavailable until hass-hassette ships against a new client, and `check_server_version` only guards new-client/old-server. The repo's own `client_compat` check types fixtures by the newest published release reachable from HEAD, so `GET /api/health` fails on the PR, and that check has no deliberate-break escape. `check_wire_compat.py` also blocks `response-required-property-removed` unless `tools/wire_compat_ignore.txt` gets lines. D14 mentions only `feat!:` plus a footer. This would be the first required-field removal from `/health`. #2806 removes only defaulted fields.

**Evidence:** `wire/src/hassette_wire/health.py:46-47`; `client/src/hassette_client/errors.py:80-88`; hass-hassette `manifest.json` (`hassette-client==0.56.0`) and `coordinator.py:99-123` (verified via `gh api`); `tools/check_client_compat.py` docstring; `tools/client_compat_release.py` docstring; `tools/check_wire_compat.py:58-61` (`REVERSED_BLOCKING_CHECK_IDS`); `tools/wire_compat_ignore.txt` header.

**Design-challenge:** Pre-v1 permits clean breaks, but does it permit breaking the project's own external integration with no coordinated release?

**Deciding-factor:** no window in which the released hass-hassette is broken, at the lowest coordination cost.

**Criteria:**
| | A: two-step: default the fields (or stop emitting while the model keeps a default) in release N, delete in N+1 | B: one-step removal, merged only together with a hass-hassette release pinning the new client; ignore-file lines and client-compat handling listed in D14/D19 | C: one-step removal as ratified |
|---|---|---|---|
| Released hass-hassette broken | Never | Only for users who upgrade hassette before the integration | Until hass-hassette ships |
| Client-compat gate on the PR | Passes | Needs a documented bypass or baseline bump | Fails |
| Consistent with pre-v1 "no shims" | A one-release default is a temporary shim | Yes | Yes |
| Coordination cost | Two PRs across releases | Cross-repo release timing | None, but CI is red |

**Options:**
- **A** *(recommended)*: Two-step removal. Defaulted fields in release N, deleted in N+1, with the ordering stated in D19.
- **B**: One-step removal coordinated with a hass-hassette release, with the `wire_compat_ignore.txt` lines and the client-compat handling written into D14/D19.
- **C**: Keep D14 as ratified.

**Recommendation:** A. It is the only option where neither the repo's gate nor the external integration breaks, and the one-release default has a scheduled removal, so it fits the staged-migration shape rather than being a lingering shim. If Finding 2's re-evaluation is chosen, decide this there.
**Pick-instead-if:** B: you'd rather keep a strict no-shim line and can time a hass-hassette release with the hassette one. C: never, while the client-compat check fails the PR with no escape.

## Finding 5: D13 relies on a `/health` start-time field that no decision defines, and `/health` `uptime_seconds`'s fate is unspecified

**Severity:** HIGH
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** D13 says since-restart "reads the current session's `started_at` from `/health`", but `SystemStatusResponse` has no such field. D9 lists exactly what it writes, with no start time, and D15 adds only `mode`/`as_of`. The field the frontend keys its whole since-restart window on has no name, type, or owner issue. The CLI renders `/health.uptime_seconds` through `CliFormat("uptime")` and the docs cite it. Whether `/health` keeps `uptime_seconds` is not stated. Computing "now minus `started_at`" is wrong for a stopped session in snapshot mode, and a persisted value is stale.

**Evidence:** `wire/src/hassette_wire/health.py:38-72` (no start-time field; `uptime_seconds` annotated `CliFormat("uptime")`); `frontend/src/hooks/use-scoped-query.ts:71-82`; design.md D9, D13, D15; `src/hassette/cli/commands/status.py:33` (per critic).

**Design-challenge:** Which field, in which issue, feeds the frontend's since-restart window, and what does the CLI show for uptime afterwards?

**Deciding-factor:** a named field landing with its consumer, and a stated answer for CLI uptime.

**Criteria:**
| | A: add `session_started_at` (instant) to `/health`; keep `uptime_seconds` computed live-only (null/absent in snapshot) | B: add `session_started_at`; remove `uptime_seconds`; CLI derives uptime from `session_started_at` | C: leave as ratified |
|---|---|---|---|
| Frontend since-restart has a defined source | Yes | Yes | No |
| CLI and docs | Unchanged | CLI and docs change in the same issue | Undefined |
| Wire break | Additive (plus nullability if snapshot omits it) | Removes a required field (see Finding 4) | Undefined |
| Snapshot correctness | Uptime absent where meaningless | CLI must handle a stopped session | Undefined |

**Options:**
- **A** *(recommended)*: Add `session_started_at` to `/health`, in the same D19 issue as the frontend change that consumes it, and keep `uptime_seconds` as a live-only value.
- **B**: Add `session_started_at`, remove `uptime_seconds`, and move the CLI to derive uptime, all in one issue.
- **C**: Leave D13 as ratified.

**Recommendation:** A. Naming the field is pure precision that D13 implies. Keeping `uptime_seconds` avoids a second required-field removal (Finding 4) and leaves the CLI alone. If Finding 2's re-evaluation is chosen, decide this there.
**Pick-instead-if:** B: you want `/health` to carry no request-time-computed values at all (D9's "plain read") and accept the CLI change. C: never; the frontend has no defined source.

## Finding 6: D19 leaves main in states where wire, frontend, generator and seeds disagree

**Severity:** HIGH
**Type:** Structural
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** Each issue squash-merges to main, from which releases ship. (1) Issue 8 depends only on 5 but reads the `/health` start time that issue 7 adds. If 8 lands first, `use-scoped-query.ts:76` keeps `waitingForUptime` true and since-restart queries never fetch. Issue 8 also carries D14's `entity_count` removal, in an unordered series with #2806 and issue 7 editing the same response. (2) Issue 5 "moves the `apps_changed` broadcast" and emits payload-free invalidations, but the frontend overlay that consumes payload messages is removed only in issue 8. The ledger doesn't say issue 5 keeps today's message shapes. (3) Issue 4 changes `create_fastapi_app`, which the compat-fixture generator, `web_api_service.py`, the schema export, and many tests call, but the generator switch is assigned to issue 9. (4) Issues 6 and 7 switch reads to runtime tables while the seed scenarios that write runtime rows land in issue 9, so client-compat generation (the `empty` coverage gap), e2e, and demo seeds return empty data in between.

**Evidence:** design.md D19 table rows 4-9; `frontend/src/hooks/use-scoped-query.ts:76-80`; `frontend/src/hooks/use-websocket.ts:96-99` (invalid WS messages logged and dropped); `tools/generate_client_compat_fixtures.py:248-269`; `tools/client_compat_live_state.py:1-12`; `tools/client_compat_coverage.py` (`empty` kind).

**Design-challenge:** Does every D19 row leave all consumers on main working at merge time?

**Deciding-factor:** every merge to main leaves wire, frontend, generator and seeds consistent.

**Criteria:**
| | A: re-cut dependencies: 8 depends on the issue adding the start-time field; `/health` edits ordered in one sequence; issue 5 keeps current WS shapes; seed runtime rows and generator `WebContext` adoption move into issues 4 and 6/7 (or an early seed issue after 5) | B: keep the table, add a note that each issue must leave main green and fix gaps during build | C: keep D19 as ratified |
|---|---|---|---|
| Known red-main windows | Closed by structure | Left to builders to discover | Open |
| Issue 9's scope | Snapshot mode only | Unchanged | Unchanged |
| Reopens ratified D19 | Yes | Minimally | No |
| Risk of rework | Low | Medium (generator edited twice) | High |

**Options:**
- **A** *(recommended)*: Re-cut D19's dependencies and scope as described.
- **B**: Keep the table with a "each issue leaves main green" requirement.
- **C**: Keep D19 as ratified.

**Recommendation:** A. All four gaps are visible now from the table and the code, and B leaves them for each builder to rediscover. If Finding 2's re-evaluation is chosen, it supersedes this.
**Pick-instead-if:** B: you expect issues to be built close enough together that interim breakage is tolerable. C: never; issue 8 before 7 blocks since-restart queries.

## Finding 7: Log persistence can starve the projector's awaited `submit()`, and D8 has no remedy

**Severity:** HIGH
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** applied

**Why-it-matters:** Log batches use `enqueue()` → `put_nowait`, and the projector uses `submit()` → `await queue.put(...)` on the same 2000-slot queue. `asyncio.Queue.put_nowait` checks only `full()`, not waiting putters. When the worker frees a slot it wakes the first waiting putter via a scheduled callback, and a log flush (`call_soon_threadsafe`) that runs first takes the slot. Under a sustained storm (an app in an error loop), the projector's `put` can wait out its whole deadline. With a per-attempt timeout under 30s, every attempt fails, lag passes the banner threshold, and the UI goes degraded because of the storm, whose own ERROR logs feed the same queue. The heartbeat shares the exposure, so a storm also walks `DatabaseService` toward its 3-strike restart. D8 framed contention as an unmeasured latency risk, but this is a starvation mechanism.

**Evidence:** `src/hassette/core/database_write_queue.py:233` (`wait_for(queue.put(...))`) vs `:277` (`put_nowait`); `src/hassette/logging_.py:313-325` (log flush via `enqueue`, drops counted only when full); `src/hassette/config/models.py:78` (`write_queue_max=2000`), `:110` (`write_submit_timeout_seconds=60`); CPython `asyncio/queues.py` put/put_nowait semantics; design.md D8.

**Design-challenge:** Why accept a mechanism where a droppable producer can repeatedly beat the one writer the whole design depends on?

**Deciding-factor:** a log storm cannot falsely degrade the UI or restart the DB service, without building the general write lane D8 rejected.

**Criteria:**
| | A: one-slot priority path for awaited writes (worker checks a single pending projector/heartbeat job before `queue.get()`) | B: log persistence yields (drops or defers) while `submit()` putters are waiting | C: keep D8; add a log-storm test as a milestone ship-gate and derive the banner threshold from it |
|---|---|---|---|
| Removes starvation | Yes | Yes | No; measures it |
| Reopens D8's ratified choice | Partly (a narrow slot, not a lane) | No (change is in log persistence) | No |
| New machinery | One slot in the worker | One check in `enqueue` | A test |
| Log loss during storms | Unchanged | More drops while awaited writes wait | Unchanged |

**Options:**
- **A**: Add a one-slot priority path for awaited writes in the worker.
- **B** *(recommended)*: Have `enqueue()` treat waiting `submit()` putters as "full" (drop and count), so awaited writes always get the next free slot.
- **C**: Keep D8 and add a storm test as a ship-gate.

**Recommendation:** B. It removes the starvation with one check, at the point that causes it, and doesn't reopen D8's rejection of a second queue discipline. Logs are already the droppable path by contract.
**Pick-instead-if:** A: you'd rather keep log drops unchanged and accept a narrow worker-side slot. C: you want to measure first and accept that a storm may degrade the UI until then.

## Finding 8: A timed-out projector write may still commit; the in-memory baseline and DB disagree and history rows duplicate

**Severity:** HIGH
**Type:** Gap
**Design-level:** Yes
**Classification:** Auto-apply
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** applied

**Why-it-matters:** D1.3 diffs against the "last committed snapshot" and D8 wraps each attempt in its own timeout. `submit()` documents that a started write "may commit", and that a caller bounding it with its own timeout gets no outcome. If the projector's timeout fires after the worker starts the job, the transaction (including `app_status_events` rows) may commit while the projector treats it as failed, keeps the baseline, and the next run appends the same history rows again. That leaves permanent duplicated lifecycle history. Because all jobs serialize on the single writer, the job itself is the only party that knows the outcome.

**Evidence:** `src/hassette/core/database_write_queue.py:199-258` (docstring: "Once the worker has started the write it is awaited to completion, because it may commit; a caller that must also bound a wedged in-progress write ... wraps this call in its own timeout"); design.md D1.3, D1.7, D2, D8.

**Design-challenge:** What is the projector's baseline when its write attempt has an unknown outcome?

**Better-approach:** Add to D1 item 3: "The baseline is advanced by the write job itself, immediately after its commit, never by the projector task from the result of its await. Jobs serialize on the single writer, so the next job always diffs against what actually committed, and a timed-out attempt needs no reconciliation."

## Finding 9: Failed projector writes retry with no backoff, and each failure logs back into the failing path

**Severity:** HIGH
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** applied

**Why-it-matters:** D1.7 says a failed job "leaves its keys dirty; the next run, or at latest the next resync, rewrites them". With the DB full, locked or the queue wedged, the projector may retry every debounce (~250ms) plus the attempt timeout, logging an ERROR each time. Those ERRORs are persisted through the same write queue (`logging_.py`), so the projector's failure feeds the queue it is failing on. The ledger doesn't say whether a dirty key left by a failure schedules an immediate re-run, and states no backoff, rate limit, or log deduplication on a write path whose blast radius is now the whole UI. Classified User-directed because the fix adds state (a backoff timer and a failing/recovered flag).

**Evidence:** design.md D1.2, D1.7, D8; `src/hassette/logging_.py:313-325`; `src/hassette/core/database_service.py:529-541` (heartbeat logs every failure with `logger.exception`).

**Design-challenge:** What bounds the projector's retry rate and log volume when the DB is the thing failing?

**Deciding-factor:** a failing DB produces one clear signal, not a self-amplifying log and retry storm.

**Criteria:**
| | A: exponential backoff (floor ~250ms, ceiling the resync interval); ERROR on entering failing, INFO with failure count on recovery; the lag banner is the steady-state signal | B: no backoff; failed keys wait for the next resync only, with logs deduplicated | C: keep D1.7 as written |
|---|---|---|---|
| Retry rate under sustained failure | Bounded, ramps to one per resync | One per resync | Unbounded (debounce cadence, if re-runs trigger) |
| Log feedback into the queue | One ERROR per failure episode | One per resync unless deduped | One per attempt |
| Recovery latency after a transient failure | Fast (starts at the floor) | Up to one resync interval | Fast |
| New state | Backoff timer and failing flag | Failing flag | None |

**Options:**
- **A** *(recommended)*: Exponential backoff with transition-only logging, and the lag banner as the steady-state signal.
- **B**: Failed keys wait for the next resync, with deduplicated logs.
- **C**: Keep D1.7 as written.

**Recommendation:** A. It bounds both retry rate and log feedback while keeping fast recovery from a one-off failure, and it leaves D8's lag signal as the user-visible indicator.
**Pick-instead-if:** B: you want the simplest bounded behavior and accept up to 30s of extra staleness after a transient failure. C: never; the feedback loop through log persistence is real.

## Finding 10: D7's final write has no owner, no dirty marks, no budget, and no durable failure signal

**Severity:** HIGH
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** applied

**Why-it-matters:** (1) `Hassette.before_shutdown` calls `self._bus.remove_all_listeners()` first, so the projector's subscription is gone before children stop, and shutdown transitions mark nothing dirty. The final run must be an unconditional mark-all, which the ledger doesn't say. (2) At final-run time the registry is mid-teardown, and D1.6 says what not to infer but not what a stopped app's row should say. (3) The final wave gets about a second of shutdown budget, `drain_write_queue` is capped, and the run may wait behind a deep queue. If the budget lapses, `_force_terminal` skips `on_shutdown`. (4) "Counted and logged" is unobservable: the count dies with the process, and the ERROR log goes through persistence whose queue is detaching. (5) `_do_finalize_session` already catches and logs every exception, and D7 moves it later without saying it stops swallowing. (6) The only hook that sits "before DB detach" without new ordering is `DatabaseService.on_shutdown`, which would have to call up into the projector.

**Evidence:** `src/hassette/core/core.py:645-677` (verified: `remove_all_listeners()` then `finalize_session` in `before_shutdown`); `src/hassette/core/session_manager.py:282-324` (verified: `except Exception: logger.exception`); `src/hassette/resources/shutdown_budget.py:19-45`; `src/hassette/core/database_write_queue.py:30-44`; `src/hassette/core/database_service.py:243-276`; design.md D1.6, D7.

**Design-challenge:** Who runs the final write, with what dirty set, in what budget, and where does its failure become visible?

**Deciding-factor:** the final write is placed by the existing wave mechanism and its failure is observable after the process exits.

**Criteria:**
| | A: projector is a `Resource` child with `depends_on=[DatabaseService, CommandExecutor]`; final run is mark-all, takes a bounded slice of the final wave, and records failure durably without the DB (stderr line plus a flag surfaced in the next session's startup) | B: `DatabaseService.on_shutdown` calls into the projector before detaching | C: keep D7 as written; settle at build time |
|---|---|---|---|
| Ordering mechanism | Existing wave/`depends_on` | Upward call from DB service (dependency inversion) | Unspecified |
| Dirty set | Explicit mark-all | Must still be specified | Unspecified |
| Failure observable after exit | Yes | No (log via detaching queue) | No |
| Fit with `.claude/rules/resource-lifecycle.md` | Native | Inverts dependencies | Unknown |

**Options:**
- **A** *(recommended)*: Pin the owner as a `Resource` child with `depends_on`, mark-all on the final run, a bounded budget from the final wave, a durable non-DB failure signal, and finalization that no longer swallows.
- **B**: Hook the final run into `DatabaseService.on_shutdown`.
- **C**: Keep D7 as written.

**Recommendation:** A. It gets ordering from the mechanism the framework already uses, answers every unspecified point, and turns "counted and logged" into something an operator can see after shutdown.
**Pick-instead-if:** B: making the projector a dependency-ordered child conflicts with how it must subscribe to the bus at bootstrap. C: you're willing to have the builder settle six open points unreviewed.

## Finding 11: Rows of a crashed or force-terminated session read as confidently "running"

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** On crash, OOM kill or force-terminal there is no final write, so the session's `app_runtime` rows keep their last projected status (RUNNING). Only the `sessions` row is repaired, and only at the next startup (`_do_mark_orphaned_sessions`). D15 labels the session "process state unknown", but per-app rows carry no qualifier, and D6's "latest session" fallback in snapshot mode serves exactly this case.

**Evidence:** `src/hassette/core/session_manager.py:145-168`; design.md D6, D7, D15.

**Design-challenge:** Why does the session get a "process state unknown" label while its apps still say RUNNING?

**Deciding-factor:** per-app status never reads more confident than its session's state.

**Criteria:**
| | A: read-time rule in the single place runtime rows join to the session: for a non-live session that didn't finalize successfully, app statuses render as `unknown (last known: <status>)` | B: rely on D15's session-level label only |
|---|---|---|
| Confident stale per-app status | Eliminated | Remains |
| Implementation | One join-level rule | None |
| Applies to snapshots of crashed sessions | Yes | Banner only |

**Options:**
- **A** *(recommended)*: Add the read-time "last known" rule at the session join.
- **B**: Keep D15's session-level label only.

**Recommendation:** A. It applies D8's "never confident stale" principle to the per-app rows a user actually looks at, in one place. If Finding 1's re-evaluation is chosen, this is decided there.
**Pick-instead-if:** B: snapshot mode of crashed sessions is rare enough that the session banner suffices.

## Finding 12: In snapshot mode `/health` serves the stored `status` / `websocket_connected` as if current

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** Audience assumption: a snapshot served to something other than the Vite UI (CLI via `HASSETTE_URL`, or the released client). D4 makes snapshot mode dev-only, so this only matters if someone points a client at it. D7 stores the true final state and D9 stores `system_status` computed in-process, so a cleanly stopped session's `/health` reports `ok`, `websocket_connected: true`, and running services. `SystemHealthStatus` has no "stopped" value. The only signals are the new `mode`/`as_of` fields, which a released client ignores as unknown, so a CLI pointed at a snapshot sees a healthy live system. That contradicts D15's deciding factor.

**Evidence:** design.md D7, D9, D15; `wire/src/hassette_wire/health.py:43` (`status: OpenSystemHealthStatus`).

**Design-challenge:** Can a snapshot be "never mistaken for a live system" when the only distinguishing fields are ones existing clients drop?

**Deciding-factor:** a snapshot reads as not-live to every client, including released ones.

**Criteria:**
| | A: snapshot branch forces `status: degraded` and `websocket_connected: false` at read time | B: add a `stopped` status value (lenient parsing absorbs it in released clients) | C: rely on `mode`/`as_of` only |
|---|---|---|---|
| Released CLI/client sees not-live | Yes | Yes (as unknown value) | No |
| Wire change | None | Enum addition | None |
| Semantics | "degraded" is approximate | Precise | n/a |

**Options:**
- **A** *(recommended)*: Force `degraded`/`false` in the snapshot read branch.
- **B**: Add a `stopped` enum value.
- **C**: Rely on `mode`/`as_of`.

**Recommendation:** A. It needs no wire change and covers released clients. If Finding 1's re-evaluation is chosen, this is decided there.
**Pick-instead-if:** B: you want the status to say precisely what happened and accept an enum addition. C: snapshot mode stays strictly dev-only with the Vite UI as its sole consumer.

## Finding 13: "Latest session" is undefined for snapshot reads, and seed `as_of` comes from a generator-written heartbeat

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** Audience assumption: more than one `sessions` row with null `stopped_at` (crash then restart, which the design anticipates in D15's "process state unknown" label). D6 tells live mode its session, while snapshot mode falls back to "the latest session" by an unstated rule (max `started_at`? max id?). D15's `as_of` is that session's `stopped_at` or `last_heartbeat_at`. For a seed, the heartbeat is whatever the generator wrote, so a seed with null `stopped_at` is labeled "process state unknown" and `as_of` is inferred from a generated heartbeat. Readers infer the age of the data from a value no process produced.

**Evidence:** design.md D6, D15, D16; `scripts/seed_scenarios/base.py:23, 355-360`.

**Design-challenge:** What single rule picks "the latest session", and should a seed look like a crashed process?

**Deciding-factor:** one session-selection rule shared by every snapshot read, and seeds that present as cleanly stopped.

**Criteria:**
| | A: define "latest session" once (a shared query used by every snapshot read); `serve_seed.py` stamps `stopped_at` to the anchor | B: define the shared query only | C: leave as ratified |
|---|---|---|---|
| Consistent session across snapshot routes | Yes | Yes | Not guaranteed |
| Seeds labeled "process state unknown" | No | Yes | Yes |
| Effort | Small | Smaller | None |

**Options:**
- **A** *(recommended)*: Define the shared latest-session query and have `serve_seed.py` stamp `stopped_at`.
- **B**: Define the shared query only.
- **C**: Leave as ratified.

**Recommendation:** A. Both parts are small, and they remove an inferred value from the snapshot banner. If Finding 1's re-evaluation is chosen, this is decided there.
**Pick-instead-if:** B: seed scenarios intentionally include an un-finalized session to exercise the "process state unknown" label. C: never; routes could pick different sessions.

## Finding 14: Payload-free `app_status_changed` / `service_status` shapes are undefined, and `connected` losing required fields silently disables the "server updated" banner in open tabs

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** skipped

**Why-it-matters:** (1) "Payload-free invalidations of the queries that read the affected data" can't target anything without a key, and a keyless message duplicates the existing `apps_changed`. `AppStatusChangedData` requires `status`, so any reduction is a wire model, `ws-schema.json` and generated validator change, and the ledger doesn't say which fields remain. (2) `ConnectedData` requires `uptime_seconds`, `entity_count` and `app_count`, enforced by the generated validator. A tab running the old bundle after a server upgrade, the exact case `isVersionChange`/`serverUpdated` exist for, gets a `connected` that fails validation. `use-websocket.ts:96-99` logs and returns, the reconnect invalidate-all and `handleWsConnected` never run, and the "reload" prompt never appears.

**Evidence:** `wire/src/hassette_wire/ws.py:9-24, 69-80`; `frontend/src/api/ws-validator.generated.ts:79, 1021` (per critic); `frontend/src/hooks/use-websocket.ts:96-99, 107-122, 177-183`; `frontend/src/state/store.ts:228-235` (per critic); design.md D13.

**Design-challenge:** What does a payload-free status message carry, and how does a stale bundle still learn it should reload?

**Deciding-factor:** targeted invalidation, and the upgrade prompt keeps working across the version that changes `connected`.

**Criteria:**
| | A: keep `app_status_changed`/`service_status` with identifying keys only (`app_key`, `index` / `resource_name`); removed `ConnectedData` fields become optional-with-default for one release | B: merge status changes into keyless `apps_changed`; same one-release default on `ConnectedData` | C: as ratified (shape unspecified, one-step removal) |
|---|---|---|---|
| Invalidation precision | Targeted | Broad refetch | Unspecified |
| Stale bundle sees "server updated" | Yes | Yes | No |
| Wire messages | Two reduced models | One fewer message type | Unspecified |

**Options:**
- **A** *(recommended)*: Keyed reduced messages, plus optional-then-remove for `ConnectedData`.
- **B**: Fold status changes into `apps_changed`, plus optional-then-remove for `ConnectedData`.
- **C**: Leave D13 as ratified.

**Recommendation:** A. It keeps invalidation targeted and preserves the one mechanism that tells users with stale bundles to reload. The sequencing half belongs to Finding 2 if that re-evaluation is chosen.
**Pick-instead-if:** B: status changes are rare enough that a broad refetch costs nothing and one fewer message type is worth it. C: never; the message shape has to be decided before issue 8.

## Finding 15: A 30s heartbeat cuts tolerance to writer occupancy from about 15 minutes to about 90 seconds

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** applied

**Why-it-matters:** `max_consecutive_heartbeat_failures=3` at 300s tolerates about 15 minutes of an unresponsive writer before `serve()` raises and `DatabaseService` restarts. At 30s, three strikes tolerate about 90s. Retention is one fire-and-forget job (`enqueue_if_ready(self._do_run_retention_cleanup)`) that loops up to 100 batches × 1000 rows per target while holding the single writer, and the size failsafe is another. A large first retention pass after upgrade, a size-failsafe drain, or a log storm (Finding 7) can plausibly produce three strikes. In the new design a restart also closes the read connection that every GET route now depends on (Finding 16). D3 says the constants are "re-derived" but no derivation exists when a legitimate maintenance job can outlast any timeout under 30s. Today's constant comment sizes the 30s timeout against a 300s interval.

**Evidence:** `src/hassette/core/database_service.py:37-45` (timeout sizing comment), `:278-322` (escalation in `serve()`), `:529-541`; `src/hassette/config/models.py:86, 100-107, 116`; `src/hassette/core/database_retention.py:119-150` (verified: one enqueued job, batched loop per target); design.md D3.

**Design-challenge:** How can the strike count be re-derived for 30s when a legitimate maintenance job can occupy the writer for longer?

**Deciding-factor:** liveness escalation fires on a wedged worker, not on legitimate queue occupancy.

**Criteria:**
| | A: count a strike only when the worker made no progress (e.g. `_executing_future` unchanged across attempts) | B: measure strikes in wall-clock time (keep ~15 minutes of tolerance) | C: keep count-based strikes, re-derive constants as D3 says |
|---|---|---|---|
| False restarts from retention/failsafe | Eliminated | Reduced to pre-change levels | Likely on large DBs |
| Detects a real wedge | Yes | Yes, slower | Yes, fast |
| New state | Last-seen executing job | Timestamp of first failure | None |

**Options:**
- **A** *(recommended)*: Progress-based strikes.
- **B**: Wall-clock tolerance.
- **C**: Count-based strikes with re-derived constants.

**Recommendation:** A. It separates "worker wedged" from "worker busy", which is what the heartbeat was meant to detect, and works at any interval.
**Pick-instead-if:** B: you'd rather not touch the worker's internals and accept slower wedge detection. C: retention passes are reliably short at real deployment sizes.

## Finding 16: Required DB plus all-reads-from-DB turns a `DatabaseService` restart into a full-UI outage with no stated degraded behavior

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** applied

**Why-it-matters:** Before this change a DB restart cost only the telemetry tabs. Afterwards `read_db` raises `RuntimeError` from `on_shutdown`/`_force_terminal` until `on_initialize` finishes again, so `/health`, `/apps` and every WS-triggered refetch fail together, while the live-seam `/telemetry/status` still answers. The ledger doesn't say what the UI shows during the restart window. It also doesn't address restart-budget exhaustion (3 per 120s, TRANSIENT): the apps keep running while the UI stays blank permanently. D1.8 protects app start from a slow DB, but nothing protects the operator's view.

**Evidence:** `src/hassette/core/database_service.py:92-97` (verified: TRANSIENT, budget 3/120s), `:187-197` (verified: `read_db` raises when not initialized), `:243-276`; design.md D6, D9, D12, D20.

**Design-challenge:** What does the operator see while the DB is restarting, or after it has given up?

**Deciding-factor:** a DB outage shows one clear state in the UI and never gets the container killed for a UI-only failure.

**Criteria:**
| | A: state the contract: one blocking "database unavailable" UI state driven by the live seam; probes stay green; named reads may degrade to the last cached response | B: per-route DB-unavailable problems as D20 says, no unified UI state | C: leave unspecified |
|---|---|---|---|
| Operator sees a coherent state | Yes | Scattered errors | Undefined |
| Container killed over UI failure | No (stated) | Unstated | Unstated |
| Budget exhaustion visible | Yes, via live seam | Partly | No |
| Frontend work | One state | Per-route error handling | Unknown |

**Options:**
- **A** *(recommended)*: State the DB-unavailable UI contract, probe behavior, and cached-read allowance.
- **B**: Keep D20's per-route problem responses only.
- **C**: Leave unspecified.

**Recommendation:** A. The live seam already survives a DB outage, so driving one UI state from it is cheap and turns a blank UI into an explained one.
**Pick-instead-if:** B: DB restarts are rare enough that per-route errors suffice. C: never; budget exhaustion leaves a silent blank UI.

## Finding 17: `TelemetryStatusResponse` can't express "unavailable" counters without breaking released parsers, and projector degradation's HTTP status is unspecified

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** applied

**Why-it-matters:** The counters are `int = 0`. D8's "unavailable, not zeros" most naturally encodes as `null`, which a released client parsing into `int` rejects with `ResponseValidationError`, and this probe path is parsed with `status_model_on_503=True`. D8 also says a never-succeeded projector "reports degraded". On this route, `degraded: true` currently always comes with HTTP 503 ("A probe ... the CLI and container health checks read it as data"), so a projector problem would read as a database outage to container health checks. The ledger doesn't say whether projector degradation maps to 503 or stays in-band. Classified User-directed because the 503 question changes probe behavior.

**Evidence:** `wire/src/hassette_wire/telemetry.py:378-386` (verified); `src/hassette/web/routes/telemetry.py:74-112` (verified: 503 with `degraded=True` only on `TelemetryUnavailableError`; zeros on `AttributeError`/`RuntimeError`); `client/src/hassette_client/client.py:249-256` (per critic); design.md D8.

**Design-challenge:** Is a stuck projector a database outage to a container health check?

**Deciding-factor:** released parsers and container probes keep working while the new signals become expressible.

**Criteria:**
| | A: counters stay non-nullable ints; add `counters_available: bool = True` and `projection_lag_seconds: float \| None = None`; projector degradation stays in-band at 200 | B: same fields, but projector degradation returns 503 | C: as ratified (encoding and status unspecified) |
|---|---|---|---|
| Released client parses | Yes | Yes | Breaks if `null` is used |
| Container probe on projector lag | Stays healthy | Goes unhealthy (restarts possible) | Unspecified |
| Signal visible to UI and CLI | Yes | Yes | Unspecified |

**Options:**
- **A** *(recommended)*: Additive defaulted fields; projector degradation never changes this probe's HTTP status.
- **B**: Additive fields; projector degradation returns 503.
- **C**: Leave D8 as ratified.

**Recommendation:** A. It is additive, keeps released parsers working, and stops a display-lag problem from triggering container restarts. Where `projection_lag_seconds` lives may move if Finding 1's re-evaluation is chosen.
**Pick-instead-if:** B: you want orchestrators to restart a process whose projector is stuck. C: never; the encoding must be settled before issue 7.

## Finding 18: Snapshot mode has no WebSocket, but the frontend infers liveness from its socket and D15 never defines `/api/ws` in snapshot mode

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** Auto-apply
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** applied

**Why-it-matters:** `overview-tab.tsx:91-97` dims the overview when `connection !== "connected"`. `system-health.tsx` renders the dot and an "unreachable" hint keyed to the socket, and `use-websocket.ts` retries forever. With `live=None` there is no WS broadcast, so the Done-when render ("with a snapshot banner") would show a dimmed overview, a red connection dot, and a retry loop. D15 names `/health.mode` as the signal but never says the connection UI consumes it, or what `/api/ws` does in snapshot mode. This is a missing behavior that D15's deciding factor implies.

**Evidence:** `frontend/src/components/app-detail/overview-tab.tsx:91-97` (verified); `frontend/src/components/shared/system-health.tsx:60-85`, `frontend/src/pages/diagnostics.tsx:101` (per critic); `frontend/src/hooks/use-websocket.ts`; design.md D10, D15.

**Design-challenge:** Should the frontend be told the server's mode, or keep guessing it from whether a socket opened?

**Better-approach:** Add to D15: "In snapshot mode `/api/ws` is not mounted (404). The frontend does not open a socket when `/health.mode === "snapshot"`, and connection-dependent UI (overview dimming, the connection dot, the unreachable hint) derives its state as `mode === "snapshot" ? "snapshot" : wsState`, never from socket absence alone."

## Finding 19: The new `snapshot_mode` problem code trips client and compat-coverage gates that issue 9 doesn't list

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Classification:** Auto-apply
**Raised-by:** contract-caller
**visibility:** presented
**disposition:** applied

**Why-it-matters:** Every `ProblemCode` must be in exactly one of `GENERIC_CODES` or `CODE_ERRORS`, or the client's tests fail. `tools/client_compat_coverage.py` fails generation when a `ProblemCode` has no request that answers it, and per D10 the generator always passes a fake `LiveSeam`, so no fixture can produce `snapshot_mode`. Released clients resolve the unknown code by status to `ConflictError`, the same class as retry-later codes, which D15 says callers shouldn't retry. None of this is in D19 issue 9.

**Evidence:** `client/src/hassette_client/errors.py:30-45` (verified: "a code added on the server fails the client's tests until someone decides which it belongs to"); `tools/client_compat_coverage.py` (`problem` kind, `EXCLUDED`); `wire/src/hassette_wire/problems.py:26-33` (per critic); design.md D10, D15, D19.

**Design-challenge:** What happens in the client and the compat gates on the day `snapshot_mode` is added?

**Better-approach:** Add to D19 issue 9's scope: classify `snapshot_mode` in the client (a non-retryable class in `CODE_ERRORS`, or `GENERIC_CODES`); handle compat coverage (an `EXCLUDED` entry with its reason, or a `live=None` stub variant); and document the code as non-retryable on its `ProblemCode` docstring.

## Finding 20: D18's sizing assumption ignores counter rows that change on every handler invocation

**Severity:** MEDIUM
**Type:** Approach-later
**Design-level:** Yes
**Classification:** User-directed
**Raised-by:** operational-resilience
**visibility:** presented
**disposition:** applied

**Why-it-matters:** Audience assumption: users with hundreds of listeners/jobs per session (a framework with unknown external apps; the ledger itself says in-repo usage is not evidence of demand). D6/D17 put listener and job guard counters in per-session tables that the projector rewrites. A busy listener's counter changes continuously, so after any activity every resync rewrites every active listener/job row, and the "tens of rows" argument doesn't hold for counters. The ~1,000-row revisit threshold is a read-the-logs trigger, and nothing emits row counts per run.

**Evidence:** design.md D6, D17, D18.

**Design-challenge:** What tells anyone the 1,000-row threshold was crossed?

**Deciding-factor:** one projector run can't hold the single writer for long, and crossing the threshold is observable.

**Criteria:**
| | A: emit per-run changed-row count and duration, and chunk the upsert into bounded transactions now | B: emit per-run metrics only; chunk when the threshold is seen | C: keep D18 as ratified |
|---|---|---|---|
| Writer hold time bounded | Yes | Only after someone notices | No |
| Threshold observable | Yes | Yes | No |
| Effort | Small | Smaller | None |
| Atomicity of one run | Split across transactions (history rows must stay with their upserts) | Single transaction | Single transaction |

**Options:**
- **A**: Metrics plus chunked transactions now.
- **B** *(recommended)*: Emit per-run changed-row count and duration now; chunk only when it shows up.
- **C**: Keep D18 as ratified.

**Recommendation:** B. D18 already asks to revisit at a threshold, and B makes the threshold observable without giving up D2's same-transaction history guarantee before there's evidence it's needed.
**Pick-instead-if:** A: you expect deployments with hundreds of busy listeners soon and would rather bound writer hold time up front. C: you're comfortable with an unobservable threshold.

## Likely Invalid

### LI-1: Payload-free WS invalidations lose their only delivery guarantee on WS reconnect
**Original-severity:** MEDIUM
**Raised-by:** operational-resilience
**Claimed:** A signal missed during a socket drop is invisible because the ledger names no resync for status queries, so the UI infers "nothing changed". The critic says it did not confirm whether the frontend invalidates on `connected`, and asks for invalidate-all on every reconnect.
**Actually:** `frontend/src/hooks/use-websocket.ts:107-122` already runs `void queryClient.invalidateQueries()` (every TanStack query) whenever a `connected` message arrives on a reconnect (`isReconnect = hasConnectedRef.current`). D13 changes message payloads and removes overlay stores. It doesn't touch the `connected` handler, and the `connected` message itself survives D13 (it "keeps `version`").
**Why-invalid:** The requested reconnect resync already exists in the code path that D13 leaves in place, so invalidations missed during a drop are recovered by the invalidate-all on reconnect. The remaining risk is a stale bundle failing to validate `connected`, which skips this handler, and that is Finding 14's concern, not a missing resync.
