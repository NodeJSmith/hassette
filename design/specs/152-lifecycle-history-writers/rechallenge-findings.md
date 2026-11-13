# Challenge Findings

**Format-version:** 4
**Target:** /home/jessica/source/hassette/.claude/worktrees/3678/design/specs/152-lifecycle-history-writers/design.md (re-challenge, peer-divergence focus)
**Critics:** systems-architect, adversarial-reviewer
**Likely-invalid:** 0

Synthesis notes: SA = systems-architect, AR = adversarial-reviewer. Merged: SA1 + AR7 (Finding 3), SA2 + AR5 (Finding 4), SA3 + the closed-enum half of SA8 (Finding 5), SA4 + AR3 (Finding 10). Peer claims were re-checked against source where a finding rests on them: Prefect `core_policy.py` (`PreventDuplicateTransitions` at line 2077, `PreventPendingTransitions` at line 1774), Prefect `orm_models.py:161-181`, Gatus `storage/config.go:8-9` and `storage/store/sql/sql.go:309-311`. Things both critics confirmed hold and that are not findings: D1's bus-drain reason (`bus_service.py:759`), D2's rejection of Kubernetes counts, D3, D6's no-op callable, D7.

## Finding 1: Findings converge on writers remembering what they last wrote (D2's dedupe map and D4's `OutageLog` last state)

**Severity:** MEDIUM
**Type:** Structural
**Design-level:** Yes
**Likelihood:** routine
**Classification:** User-directed
**Raised-by:** Synthesis
**Converges:** Findings 2, 6, 7, 11, 12
**visibility:** presented
**disposition:** pending

**Why-it-matters:** Two writers each keep a memory of the last row they believe they wrote and decide from it whether the next event is a change. For app rows that's D2's map of last `(to_status, details)` per instance on `SessionManager`. For connection rows it's D4's "last state written" inside `OutageLog`. Five findings come at this memory from different directions. Finding 2: the peers D2 cites put that decision at the sender, not in a content-matching writer. Finding 11: the map advances on enqueue, not on a successful write. Finding 12: `OutageLog` advances on calling the callable, not on the row being queued. Finding 6: `OutageLog`'s state runs alongside `WebsocketService`'s own state machine. Finding 7: the map is temporary #1446 state that sits in the class owning the session lifecycle. Each finding proposes its own local patch, such as an evict wrapper, a bool return, a path-coverage test or a new class. Is the writer-side memory the right mechanism, or should it be re-evaluated before patching each finding? Re-evaluating is open-ended. It includes whether either writer needs the memory at all, and whether the failure modes are limitations to accept and document.

**When-it-bites:** The memory exists on every run, and every reader of the writer path has to hold it. The failures it causes (Findings 11, 12) are rare.

**Evidence:** design.md D2 (lines 71, 75, 78, 82); D4 line 116 ("The last state written and the outage start"); D6 line 166; Prefect `core_policy.py:2077-2107` (`PreventDuplicateTransitions`, sender-supplied `transition_id`); `database_write_queue.py:66-70`; `websocket_service.py:210-250`; parent 142 D11 lines 275-276.

**Design-challenge:** HA (`force_update`), Airflow (`ti_update_state` no-op) and Prefect (`transition_id`) all let the sender say what counts as a repeat. Kubernetes is the only surveyed peer that matches on content inside the writer. Is a writer guessing from content the shape to keep, or is it what makes the evict, advance and ownership rules necessary?

**Deciding-factor:** fix the mechanism once if it is the cause, or patch it locally if the local fixes are small and the mechanism is still needed.

**Criteria:**
| | A: re-evaluate the writer-side memory | B: keep it, address findings individually |
|---|---|---|
| Work now | Reopens ratified D2 (and possibly D4/D6) | Five small decisions; three of them recommend Accept or keep |
| Findings it could retire | 2, 7, 11, 12, and part of 6 | None; each is resolved on its own |
| Connection side | Still needs some state: `ConnectionState` has no `waiting_for_core` (`websocket_service.py:210-250`), so something has to notice a state change | Unchanged |
| App side | Sender-side marking runs into site 198 mixing new and stale failures (`app_lifecycle_start_stop.py:180-198`), which is D2 option B's cost | Unchanged |
| What peers do | HA, Airflow and Prefect decide at the sender, and Prefect does it with a sender-supplied key inside its funnel. Re-evaluating could move Hassette toward that (match) | Content matching in the writer matches Kubernetes `events_cache.go` only and diverges from HA, Airflow and Prefect |

**Options:**
- **A**: Re-evaluate the writer-side "last row written" memory (D2's map and D4's `OutageLog` last state) before addressing the converging findings individually. Open questions: does each writer need the memory at all? Can the sender say what's a repeat? Should the memory advance on the write outcome? Where should it live?
- **B** *(recommended)*: Keep the writer-side memory and address Findings 2, 6, 7, 11 and 12 individually.

**Recommendation:** B. On the connection side some state is unavoidable, because the existing state machine has no `waiting_for_core`. On the app side the alternative still has to split site 198's new failures from stale ones, the cost that already sank D2 option B. The member findings' failures are rare, and their local fixes are small or are accepts. The peer evidence leans away from content matching in the writer, but it doesn't show that the memory causes harm here.
**Pick-instead-if:** A: Finding 2's corrected Prefect picture (dedupe in the funnel by a key the sender supplies) changes your view of D2, and you'd rather settle the app and connection writers together than patch them one at a time.

## Finding 2: D2's peer row misstates Prefect; Prefect dedupes inside its funnel by a sender-supplied key

**Severity:** MEDIUM
**Type:** Approach-now
**Design-level:** Yes
**Likelihood:** routine
**Classification:** User-directed
**Raised-by:** adversarial-reviewer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D2's peer row (option B column) and its Peer divergence line say "HA, Airflow and Prefect dedupe at the source and record whatever reaches the writer". Prefect doesn't fit that. Its orchestration rules run inside `set_flow_run_state`, the same funnel that writes the row. `PreventDuplicateTransitions` rejects a transition whose sender-supplied `transition_id` matches the current state's. `PreventPendingTransitions` rejects PENDING→PENDING. PR 9447 deliberately keeps a genuine RUNNING→RUNNING. So Prefect dedupes in the writer, as Hassette does, but by a key the sender supplies, and it keeps genuine identical repeats. Hassette instead matches on content and collapses them. D2's divergence line therefore explains the wrong divergence. Hassette matches Prefect on where the dedupe happens and differs on the key. The reason for that difference is never stated.

**When-it-bites:** Every reader of D2's reasoning, today. In behaviour: an app whose class fails construction, started again with `start_app` (not reload, which sends STOPPED in between), produces the same FAILED with no event in between, and the timeline shows one row however many times it's retried. The ledger accepts this in D2's Ratified line, but the acceptance leans on the misstated peer row.

**Evidence:** design.md line 76 (peer row), line 79 (divergence), line 82 (Ratified); peer-check.md lines 15, 34; Prefect `src/prefect/server/orchestration/core_policy.py:2077-2107` (`PreventDuplicateTransitions`: "clients set an optional transition_id ... If the run's next transition has the same transition_id, the transition will be rejected") and `:1774-1802` (`PreventPendingTransitions`); Prefect PR 9447 (RUNNING→RUNNING allowed for infrastructure restarts), PR 11695; `app_lifecycle_start_stop.py:180-198` (site 198 re-sends new and stale failures together).

**Design-challenge:** The sender knows when it's re-syncing a cache, and the writer can only guess from content. Prefect lets the sender say so. Is D2's content match a reasoned divergence, or one that rests on a misread peer?

**Deciding-factor:** rows record changes with the least writer state, and D2's stated peer evidence is accurate.

**Criteria:**
| | A: keep the content map; correct the peer row and the divergence line | B: funnel takes a required re-sync/record argument (Prefect's sender-key shape); drop the map |
|---|---|---|
| Writer state | The map, plus its evict rules | None |
| A future re-sync site | Covered automatically | Must choose at the call; the D1 structural test forces it through the funnel, but it can choose wrong |
| Site 198 | Unchanged | Must split new failures (just recorded by `create_instances`) from stale ones, which is D2 option B's cost |
| Genuine identical repeat (repeated `start_app` of a broken class) | One row | One row per send that is not marked re-sync |
| Removes Findings 7 and 11's map concerns | No | Yes |
| What peers do | Matches Kubernetes (content key in the writer, `events_cache.go:52-67`). Diverges from Prefect, which uses a sender key in the funnel, and from HA and Airflow, which dedupe at the source | Matches Prefect (`transition_id` checked in the funnel, `core_policy.py:2077`) and HA's `force_update` idea that the source decides. Diverges from Kubernetes |

**Options:**
- **A** *(recommended)*: Keep the content-equality map. Rewrite D2's peer row and divergence line: Prefect dedupes inside its funnel by a sender-supplied `transition_id` and records genuine repeats (PR 9447). Hassette matches it on where the dedupe happens and differs on the key, because site 198 sends new and stale failures together, and a content key covers future re-sync sites without each one choosing.
- **B**: Add a required re-sync/record argument to the funnel, mark stale re-sends at site 198 (and 399 if it is a re-sync), split site 198's new failures from stale ones, and drop the map.

**Recommendation:** A. With the peer row corrected, D2's reason still holds in a narrower form. Site 198 really does mix new and stale failures, so B has to do the split that was the main cost of D2 option B. A also covers re-sync sites automatically, where B depends on each author choosing correctly. The peer row must be fixed under either option, because as written it misdescribes Prefect.
**Pick-instead-if:** B: you'd rather keep no writer state and make every send site say what it is, and you accept the site-198 split work. Picking B also resolves Findings 7 and 11 for app rows.

## Finding 3: `from_status` means something different for each row kind

**Severity:** MEDIUM
**Type:** Structural
**Design-level:** Yes
**Likelihood:** routine
**Classification:** User-directed
**Raised-by:** systems-architect, adversarial-reviewer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** One column has three meanings. On app rows it's the sender's `previous_status`, NULL at sites 198, 208, 399 and 466. On connection rows it's whatever state `OutageLog` last advanced to, which Finding 12 shows can name a row that was never written. On block rows it's always NULL. Without knowing the kind and the send site, a #4084 reader can't tell "no prior state" from "the sender didn't say". The ledger's reason for keeping the column does hold for one case. The outcome events (`send_outcome_event` at `app_lifecycle_instances.py:129, 263`) carry `previous_status=STARTING`, and no STARTING event is ever sent. So an app row's `from_status` records a transition that has no row of its own. For connection rows the value can be derived from the previous row. For block rows it carries nothing.

**When-it-bites:** Every `hassette timeline` render that wants to show "X → Y" (#4084). The schema is marked "Reversibility: hard" (D5 line 153).

**Evidence:** design.md D5 lines 143, 146-148, 151; `app_lifecycle_start_stop.py:198, 208, 399, 466` (no `previous_status`), `:227` (`previous_status=info.status`); `app_lifecycle_instances.py:129, 263` (outcome rows from STARTING, which is never sent), `:459`; peer-check.md line 18 (no peer state table has a "from" column; Prefect's *event* payload carries `intended.from/to`, `models/events.py:72-79`).

**Design-challenge:** Should a column be stored when its meaning depends on which code wrote the row?

**Deciding-factor:** each stored value means one thing and carries information the reader can't derive from row order.

**Criteria:**
| | A: drop `from_status` | B: keep it for app rows only; NULL on connection and block rows | C: keep as designed; document it as "sender hint, NULL when not said" |
|---|---|---|---|
| Meanings of the column | None | One (the sender's previous status) | Three |
| Information lost | The never-sent STARTING hop on outcome rows | None (connection "from" comes from the previous row) | None |
| Finding 12's lie path | Gone | Gone | Remains |
| NULL ambiguity on app rows | n/a | Remains at 4 sites (documented) | Remains, plus on other kinds |
| Departs from parent D2's column list | Yes | Partly | No |
| What peers do | Matches the HA `states` (`old_state_id`) and Prefect `flow_run_state` (order) state tables, which have no from column | Connection and block rows match those tables. App rows match Prefect's event payload (`intended.from`, sender knowledge) | Diverges from every surveyed state table |

**Options:**
- **A**: Drop `from_status`. #4084 derives "from" with `LAG(to_status)` over (session, app, instance).
- **B** *(recommended)*: Keep `from_status` for app rows only, where it is the sender's `previous_status`. Write NULL on connection and block rows, and say in D5 that readers use row order for those kinds.
- **C**: Keep it as designed, and document it on the docs page and in #4084 as "sender hint, NULL when not said".

**Recommendation:** B. It keeps the one piece of information the reader can't derive, the STARTING hop that never gets its own row. It also removes the connection-row value that can name a state that isn't in the table (Finding 12). That leaves the column with one meaning. B matches peers where they agree (order-derived "from") and keeps Prefect's sender-knowledge shape only for the kind where the sender knows something.
**Pick-instead-if:** A: you'd rather match the peer state tables exactly and treat the STARTING hop as known from the lifecycle (RUNNING always follows STARTING). C: parent D2's "from and to status" for every kind matters more than one meaning per column.

## Finding 4: The first connection's outage length is contradicted between D4 and D5

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** Yes
**Likelihood:** routine
**Classification:** Auto-apply
**Raised-by:** systems-architect, adversarial-reviewer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D4 lists "Hassette starts while HA is starting" as recorded, and parent D2 asks for that outage's length in the row. Yet the D4 table and D5 both say the first `connected` row has no outage length. D4's own rule measures the length "from the first non-`connected` row since the last `connected`", which has no anchor when there has been no `connected` yet. The existing code backs the "absent" reading. `record_connected` computes a duration only when `was_ever_connected`, and `record_core_wait` never sets `disconnected_at`. A callable built on today's fields would silently drop the one number parent D2 asked for.

**When-it-bites:** Every Hassette start that races an HA start, such as a host reboot where both come up together. That's routine for an add-on install.

**Evidence:** design.md line 111 ("The first connection of the process writes `connected` with no outage length"), line 112, line 116 ("the outage start" as new state), line 120, line 147 ("absent on the first connection"); `websocket_reconnect.py:314-319` (`record_core_wait` sets no gap start), `:321-332` (duration only when `was_ever_connected`); parent 142 D2.

**Design-challenge:** The doc lists the outage start as new state, but never says that the existing `disconnected_at` doesn't cover a start where only core waits happened.

**Better-approach:** In D4's option D "Rows written" cell, the recommendation, and D5's connection bullet, replace "absent on the first connection" with this rule. The `connected` row carries the outage length whenever a non-`connected` row came before it in this process, measured from the first such row since the last `connected` or since `OutageLog` was built. The length is absent only when the process's first row is `connected`. Note in D4 that the outage start is D4's new field, set by both `record_failure` and `record_core_wait`, not `disconnected_at`, which a start with only core waits never sets (`websocket_reconnect.py:314-319`). Add a Build test for the case where HA starts first.

## Finding 5: The `kind` CHECK constrains the axis most likely to grow, and the divergence isn't called out

**Severity:** MEDIUM
**Type:** Approach-later
**Design-level:** Yes
**Likelihood:** plausible
**Classification:** User-directed
**Raised-by:** systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D5 constrains `kind CHECK IN ('app','connection','block')` and leaves statuses open, giving "easy to change" as the reason statuses stay open (D4 line 123). But parent D1 generalized this table precisely so more sources can join, and `scheduler` or `session` rows are the obvious next ones. SQLite can't alter a CHECK in place, so a fourth kind needs a table-rebuild migration. D5's reversibility line names only the columns. D5's peer line doesn't mention that peers leave their kind-like discriminator open.

**When-it-bites:** The first time a fourth source joins. The cost is a rename-and-copy migration on a table bounded by retention, not data loss. A rebuild is cheap for a solo project with few users, which is why this stays MEDIUM.

**Evidence:** design.md line 143 (CHECK on `kind`), line 123, line 153; `migrations_sql/025.sql:13-15` (CHECK convention); `migrations_sql/009.sql:10` ("Part B: executions.status CHECK constraint must allow 'skipped'", a rebuild done for a CHECK change), `012.sql:95` (rename-and-copy); parent 142 D1.

**Design-challenge:** If the per-kind Pydantic model already gates every insert through the one writer, what does the database-level CHECK add?

**Deciding-factor:** the cheapest path to a fourth source without losing integrity, and a stated reason for any divergence from peers.

**Criteria:**
| | A: drop the CHECK on `kind`; the per-kind model enforces the set | B: keep the CHECK; say in D5 that a new kind is a table rebuild and why |
|---|---|---|
| Adding a fourth kind | No migration for the constraint | Rebuild migration (precedent: 009 Part B) |
| Integrity on insert | Writer-only (the one insert path) | Writer and database |
| Repo convention | Diverges (`025.sql`, `012.sql` CHECK enum-like columns) | Matches |
| What peers do | Matches HA (`event_type` is free text via the `event_types` table) and Kubernetes (`involvedObject.kind` is a free string). Prefect avoids the question by using separate tables per kind (`flow_run_state`/`task_run_state`) and constrains only its status axis with `sa.Enum(StateType)` (`orm_models.py:168-170`) | Diverges from HA and Kubernetes. No surveyed peer CHECK-constrains a multi-source discriminator. The reason would be repo convention |

**Options:**
- **A**: Drop the CHECK on `kind`, and note in D5 that the per-kind model is the only enforcement.
- **B** *(recommended)*: Keep the CHECK. In D5's reversibility line and peer line, state that adding a kind is a rebuild migration (as 009 did) and that the CHECK follows the repo's enum-column convention, which HA and Kubernetes don't.

**Recommendation:** B. The repo constrains every enum-like column, and it already has a working rebuild precedent. The table is small and bounded by retention, so a rebuild costs little. What's missing is the stated divergence and cost, not the constraint.
**Pick-instead-if:** A: you expect several new kinds soon, such as scheduler, session or #1446's projector, and a rebuild each time outweighs a database-level guard behind a single writer.

## Finding 6: `OutageLog` keeps a second connection state alongside `WebsocketService`'s state machine

**Severity:** MEDIUM
**Type:** Structural
**Design-level:** Yes
**Likelihood:** routine
**Classification:** User-directed
**Raised-by:** adversarial-reviewer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `WebsocketService.set_connection_state` already owns `ConnectionState` transitions. D4 and D6 add a parallel "last state written" inside `OutageLog`, inferred from which of `record_failure`, `record_core_wait` and `record_connected` was called. `waiting_for_core` happens while the service is in CONNECTING with the socket open. `record_failure` can fire from CONNECTING, from a core wait, or from CONNECTED. The two owners have to agree on every path, including the rebuild at the top of `serve()`. If a future reconnect path skips a call, the rows go wrong and nothing signals it.

**When-it-bites:** This is a cost in the code's shape. The implementer pays it now, and so does every later change to the reconnect path.

**Evidence:** `websocket_service.py:210-250` (`set_connection_state`), `:321` (rebuild), `:349-373` (`handle_connection_failure`), `:429-455` (core wait), `:483-496` (`mark_connected`); design.md D4 line 116, D6 lines 160-169.

**Design-challenge:** Which component owns "what state is the connection in"? Can a row writer that infers that state from call order be kept honest without a test that drives every path?

**Deciding-factor:** one source of truth for connection state, without reopening D6's ratified home for the gap and flap logic.

**Criteria:**
| | A: keep `OutageLog` as the row owner; state the invariant and add a path-coverage test to Build | B: pass the service's state into each `OutageLog` call, so the row follows the state machine |
|---|---|---|
| State owners | Two, kept in agreement by a test | One, plus `waiting_for_core`, which `ConnectionState` lacks and must be passed separately |
| Changes to ratified D6 | None | The callers' signatures change; D6's "state comparison in one place" moves partly to the service |
| Catches a skipped call on a new path | Only if the test covers that path | Yes for `ConnectionState` transitions |
| What peers do | No surveyed peer persists reconnect history (D6 line 170), so there is nothing to match | tenacity passes its own `RetryCallState` into each `before`/`after`/`before_sleep` callback (peer-check.md line 53). The owner hands the state in, which matches B |

**Options:**
- **A** *(recommended)*: Keep `OutageLog` as the owner. State in D4 that its last-written state is derived only from the three calls, and add a Build test that drives startup core wait, HA restart, PARK, a flap and the `serve()` rebuild, then asserts the row sequence.
- **B**: Pass the service's `ConnectionState` (plus core-wait status) into each `OutageLog` call, so rows follow the service's state machine.

**Recommendation:** A. `ConnectionState` has no `waiting_for_core`, so B still needs a second signal. D6 put the gap and flap facts in `OutageLog` for good reason. A test across every path pins the agreement at low cost. B matches tenacity's pattern of handing in state, but that pattern is about reading the owner's state, and A's callable already gets called by the owner at each transition.
**Pick-instead-if:** B: you expect the reconnect path to change often enough that a test covering today's paths will fall behind.

## Finding 7: The temporary dedupe map and drop pacing land on `SessionManager`

**Severity:** TENSION
**Type:** Approach-now
**Design-level:** Yes
**Likelihood:** routine
**Classification:** User-directed
**Raised-by:** systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `SessionManager` (257 lines) owns the session record. The ledger adds the enqueue method, D2's dedupe map, a drop counter covering three paths, and WARNING pacing copied from `ApiWriteRecorder.warn_drop`. When #1446's projector replaces the app writer (parent D1), the map and its evict rules have to be cut out of a class that also runs the session lifecycle. Parent D11 already composes a helper class for near-misses (`BusService` composes it), so a composed writer object would follow the same parent decision. The critic also says the Posture's "once per episode" wording doesn't match the pacing, which is by interval. That part is weak: `warn_drop`'s own docstring says "one WARNING per drop episode" (`api_write_recorder.py:214-215`).

**When-it-bites:** Today, for anyone reading `SessionManager`, and again at #1446 when the map has to be removed.

**Evidence:** design.md line 21, line 22, Assumed line 197; parent 142 D11 lines 275-276 (near-miss helper composed by `BusService`; "Pick C instead if being able to delete each writer on its own, such as the lifecycle writer at #1446, is worth two more shutdown positions"); `api_write_recorder.py:201-224`; `session_manager.py` (257 lines).

**Design-challenge:** Does "writers go through `SessionManager`" (parent D11) mean the code lives on `SessionManager`, or only that writes route through it?

**Deciding-factor:** fewest new pieces, set against how cleanly #1446 can remove the temporary map.

**Criteria:**
| | A: keep the writer, map and pacing on `SessionManager` | B: a small `LifecycleWriter` that `SessionManager` composes (enqueue, map, pacing), sharing the pacer with `ApiWriteRecorder` |
|---|---|---|
| New pieces | None | One small class (no new shutdown position) |
| #1446 removal | Delete a field and its rules from `SessionManager` | Delete or shrink one class |
| Pacing duplication | A copy of `warn_drop` | Shared |
| Parent D11 fit | Literal reading | Mirrors D11's own composed near-miss helper |
| What peers do | unknown (parent D11's peer row is "unknown" for every option) | Prefect splits its funnel's rules into separate classes such as `PreventDuplicateTransitions`, which is closer to B, but that's an analogy, not a surveyed comparison |

**Options:**
- **A** *(recommended)*: Keep the writer state on `SessionManager` as ratified.
- **B**: Put the enqueue, map and pacing in a small `LifecycleWriter` composed by `SessionManager`, and share the pacer with `ApiWriteRecorder`.

**Recommendation:** A. The map is bounded and temporary, and removing it at #1446 is a few lines either way. B adds a class to save a smaller future diff. Sharing the pacer instead of copying it can be decided at build time under either option.
**Pick-instead-if:** B: `SessionManager` grows past a size you're comfortable with once the writer lands, or you want #1446 to delete the app writer as one unit, as parent D11's option C framed it.

## Finding 8: D4's peers record a monitored target's health, but Hassette records its own link

**Severity:** TENSION
**Type:** Approach-now
**Design-level:** No
**Likelihood:** routine
**Classification:** User-directed
**Raised-by:** systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D4's Ratified line chose option D "to match how Gatus, Uptime Kuma, HA's recorder and Kubernetes store connection history". Gatus and Uptime Kuma record a remote target's health from a monitor. This table records Hassette's own client connection to HA, and D6 says "no surveyed peer persists reconnect history at all". The row-per-change conclusion probably still holds, because that's the common shape for status history whoever records it. But the peer line says "match" without naming the gap. The closest self-reporting peer is the kubelet's node conditions, which the row already cites for `lastTransitionTime`.

**When-it-bites:** Every reader who weighs D4 on its peer evidence.

**Evidence:** design.md line 118 (peer row), line 121 (divergence), line 124 (Ratified), line 170 (D6: no peer persists reconnect history); peer-check.md lines 17, 70.

**Design-challenge:** Is "matches Gatus/Uptime Kuma" evidence for a client's own connection log, or only for status-history shape in general?

**Deciding-factor:** an accurate peer line, without reopening a choice that holds on other grounds.

**Criteria:**
| | A: add a clause to D4's peer divergence line | B: leave the line as is |
|---|---|---|
| Accuracy | States that Gatus and Uptime Kuma record a monitored target, that the kubelet is the closest self-reporting peer, and that no peer persists its own client connection history (D6) | Implies a direct peer match |
| Changes the decision | No | No |
| What peers do | Gatus and Uptime Kuma are target monitors (`storage/store/sql/sql.go`, `monitor.js`). The kubelet reports its own node condition. NetDaemon fires `OnConnect`/`OnDisconnect` but persists nothing. The row shape matches; the subject diverges | Same facts, unstated |

**Options:**
- **A** *(recommended)*: Add one clause to D4's Peer divergence line: Gatus and Uptime Kuma store a monitored target's health; the kubelet's node conditions are the closest self-reporting peer; no surveyed peer persists its own client connection history (D6).
- **B**: Leave the line as is.

**Recommendation:** A. It's one clause, and it makes the user's chosen criterion, stated divergence, true without changing the decision.
**Pick-instead-if:** B: you read "row per change" as a general status-history shape, where who is observing doesn't matter.

## Finding 9: D1 says it "matches Airflow 3", but Airflow's per-site calls are the failure the funnel avoids

**Severity:** TENSION
**Type:** Approach-now
**Design-level:** No
**Likelihood:** routine
**Classification:** User-directed
**Raised-by:** adversarial-reviewer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D1's peer row lists Airflow 3 as "direct calls at each transition; sites were missed twice". That is call-site writers, the shape parent D2 rejected. Option A is a single funnel, and only Prefect matches it. The structural test that bans other sends departs from both peers, since Airflow has no guard and Prefect needs none because its API is the only path. Yet the divergence line reads "matches Prefect and Airflow 3".

**When-it-bites:** Every reader weighing D1 against peers.

**Evidence:** design.md line 53 (peer row), line 56 (divergence); peer-check.md lines 14, 27-28 (Airflow: direct writes in `ti_run`/`ti_update_state`, sites missed in PRs 61932 and 59639, "No structural guard").

**Design-challenge:** Is a peer whose shape caused the bug you're guarding against a match?

**Deciding-factor:** an accurate peer line.

**Criteria:**
| | A: reword to "matches Prefect; avoids Airflow 3's per-site calls" | B: leave "matches Prefect and Airflow 3" |
|---|---|---|
| Accuracy | Airflow is named as what the funnel and structural test avoid | Airflow reads as a match, though it lacks the funnel |
| What peers do | Prefect funnel (`set_flow_run_state`) matches. Airflow 3's per-site calls diverge, and the structural test exists because of them | Same facts, misread |

**Options:**
- **A** *(recommended)*: Reword D1's Peer divergence line to "matches Prefect's funnel; avoids Airflow 3's per-site calls, whose missed sites (PRs 61932, 59639) the structural test guards against".
- **B**: Leave the line as is.

**Recommendation:** A. It's one line, and as it stands it misdescribes the peer. The peer-check brief (line 14) has the same wording, but it is a dated research artifact, so only the ledger needs the edit.
**Pick-instead-if:** B: you read "matches Airflow 3" loosely as "the writer is called directly rather than through a bus listener", which is true of Airflow.

## Finding 10: Connection-row growth is estimated at one flap a minute, but the backoff cap allows one every few seconds

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** Yes
**Likelihood:** rare
**Classification:** User-directed
**Raised-by:** adversarial-reviewer, systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D4's figure is about 86,000 rows, 15-20 MB over 30 days, and assumes a flap every minute. The Posture requires parent D12's 25 MB figure to hold for connection rows. But the Fast curve resets only after a stable (120 s) connection, so during a flap `fast_attempt` keeps climbing and the delay settles at the 5 s cap. A link that connects and then drops can flap roughly every 10 s. At 2 rows per flap that's about 520,000 rows, roughly 100 MB over 30 days, about 4x the parent's figure. An attempt that waits on core before dropping adds a `waiting_for_core` row, making 3 rows per flap. The table is exempt from the size failsafe, so only `retention_days` (default 30) bounds it. Smaller point: D4's numbers imply 175-230 B per row, while the parent assumes 150 B.

**When-it-bites:** A link flapping for days at the backoff cap, such as HA accepting connections and dropping them, or a misbehaving proxy. That's rare. When it happens, it's the very incident the table exists to explain, and the rows stay for the whole retention window.

**Evidence:** `websocket_reconnect.py:41` (`FAST_BACKOFF_CAP_SECONDS = 5.0`), `:178-187` (`fast_attempt` resets only on a stable connection), `:402-411`; `websocket_service.py:429-455` (core-wait loop); `config/models.py:91` (`retention_days = 30`); design.md line 35 (Posture), line 117 (Growth); parent 142 D12 line 295 (150 B/row, 25 MB, failsafe-exempt).

**Design-challenge:** The Posture states a size bound, but the design bounds connection rows only by how fast the failures arrive.

**Deciding-factor:** whether a rare, multi-day flap at the backoff cap is worth carrying flap-coalescing or a size bound.

**Criteria:**
| | A: coalesce flaps inside an `OutageLog` episode (D4 option B's close point) | B: remove the failsafe exemption for connection rows | C: Accept, restating the figure at the cap |
|---|---|---|---|
| Worst-case growth | About 2 rows per episode | Bounded by the failsafe | About 100 MB over 30 days at a flap every 10 s |
| New mechanism | An episode-close point (rejected in D4 as "doesn't exist yet"; `flaps` and `episode_started_at` do exist) | A change to the failsafe order and to parent D12 | None |
| Evidence kept during the incident | Episode summary only | Oldest connection rows deleted under pressure | Every flap |
| How often it pays off | Rare | Rare | n/a |
| What peers do | No peer coalesces flaps (peer-check.md line 71: no flap marker found) | Matches Gatus, which caps events per endpoint by count (`storage/config.go:9` `DefaultMaximumNumberOfEvents = 50`; `sql.go:309-311`) | Matches Uptime Kuma and HA, which bound by age only. Diverges in that Hassette also exempts the table from its size failsafe |

**Options:**
- **A**: Coalesce flaps inside an open `OutageLog` episode into one row that carries `flaps` and total time when the episode closes.
- **B**: Take connection rows off the failsafe exemption (or cap them by count, like Gatus).
- **C** *(recommended)*: Accept as a known limitation: a link flapping at the backoff cap for days can grow connection rows to about 100 MB over the retention window, bounded only by `retention_days`.

**Recommendation:** C. The case is rare, the growth is bounded by retention, nothing is lost silently, and the rows are the evidence for exactly that incident. Recording the limitation means fixing the Posture's "must hold" sentence and D4's Growth cell to state the cap-rate figure, and adding to D4's peer line that Gatus caps events by count while Hassette bounds them by age only.
**Pick-instead-if:** A: you expect flapping links often enough that per-flap rows would bury the timeline anyway. B: disk size on small installs matters more than keeping every flap.

## Finding 11: A write that fails after being queued is neither counted nor evicted from the dedupe map

**Severity:** MEDIUM
**Type:** Gap
**Design-level:** No
**Likelihood:** rare
**Classification:** User-directed
**Raised-by:** adversarial-reviewer
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D2's map advances when `enqueue` returns True. The write can still fail after that. The worker catches the coroutine's exception and only logs "Unhandled error in enqueued DB write", and a withdrawn item is skipped. The map then says "written", so a later identical event is skipped and that state has no row until the status changes. The Posture says "every dropped row is counted", but this path isn't one of the three counted paths. `ApiWriteRecorder` has the same gap.

**When-it-bites:** A full disk, a locked database, or a constraint violation. These are rare. The worker logs them at ERROR, so they aren't silent, but the lost row is never retried and later identical rows are suppressed.

**Evidence:** `database_write_queue.py:44-50` (withdrawn item skipped), `:66-70` (exception logged, no counter); design.md line 31 (Posture), line 78 (map advances on enqueue), line 203 (Assumed); peer-check.md line 21.

**Design-challenge:** "Counted" covers drops before queueing. Is that the claim the Posture means to make?

**Deciding-factor:** whether a rare post-enqueue failure, already logged at ERROR, is worth a wrapper on every lifecycle write.

**Criteria:**
| | A: wrap the queued coroutine to count under the `PipelineCounter` and evict the map entry on exception | B: Accept, and narrow the Posture's wording |
|---|---|---|
| New mechanism | A wrapper on every lifecycle write | None |
| Posture accuracy | "Every dropped row is counted" becomes true | Reworded to "every row dropped before it is queued" |
| Rows suppressed after a failure | None | Identical rows until the status changes |
| What peers do | Matches Kubernetes, where a failed sink write never suppresses a later event (design.md line 76, `event.go`) | Matches the queue-drop counting in the OTel semconv (`queue_full`, `already_shutdown`), which covers dropped items, not export failures (peer-check.md line 21). Diverges from Kubernetes on suppression |

**Options:**
- **A**: Wrap each queued lifecycle write so an exception increments the same `PipelineCounter` and evicts the D2 entry.
- **B** *(recommended)*: Accept as a known limitation: a lifecycle write that fails after being queued is logged at ERROR by the write worker but not counted, and its D2 entry stays advanced. Narrow the Posture to "every row dropped before it is queued is counted".

**Recommendation:** B. The failure is logged at ERROR, it's rare, and a real status change still writes. The wrapper would run on every write to guard a disk-full case, which tends to show up in other tables too.
**Pick-instead-if:** A: you want the loss count in #4084 to be complete, including write failures, rather than queue drops only.

## Finding 12: `OutageLog` advances its last state on calling the callable, not on the row being queued

**Severity:** MEDIUM
**Type:** Fragility
**Design-level:** No
**Likelihood:** rare
**Classification:** User-directed
**Raised-by:** systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** D2 evicts an app instance's map entry when an enqueue fails, so a drop never hides a later row. Connection rows don't get the same rule, because D6's callable returns nothing. After a dropped `waiting_for_core` or `disconnected` row, `OutageLog` still treats that state as written. Later rows in the same state are skipped, and the next row's `from_status` names a state that isn't in the table. The outage length survives because it's held in `OutageLog`, which is the ledger's stated reason for storing it.

**When-it-bites:** A full queue during a reconnect storm, when the queue is already under pressure. That's rare. The drop is counted and logged at WARNING.

**Evidence:** design.md line 116 (D4 new state), line 147 (connection `from_status`), line 166 (D6 callable), line 75 (D2 eviction for app rows).

**Design-challenge:** The app writer and the connection writer handle a failed enqueue differently, and nothing in the ledger says why.

**Deciding-factor:** consistency with D2's own drop rule, set against a rare failure that is already counted.

**Criteria:**
| | A: callable returns whether the row was queued; `OutageLog` advances only on True | B: Accept |
|---|---|---|
| New mechanism | A return value and one branch | None |
| Consistent with D2's app rule | Yes | No |
| `from_status` lie after a drop | Gone (also gone under Finding 3 option B) | Remains |
| What peers do | Matches Kubernetes, where a failed sink write never suppresses a later event (design.md line 76) | Diverges from Kubernetes. The rest of the peers have no writer-side state |

**Options:**
- **A**: Have the D6 callable return whether the row was queued, and advance `OutageLog`'s last-written state only on True.
- **B** *(recommended)*: Accept as a known limitation: after a dropped connection row, `OutageLog` still treats that state as written, so the gap's later same-state rows are skipped (the drop is counted and the outage length survives).

**Recommendation:** B. It's rare, the drop is already counted with a WARNING, and the outage length survives. If you pick Finding 3 option B, the `from_status` part goes away and only the skipped same-state rows remain.
**Pick-instead-if:** A: you want the connection writer's drop rule to match D2's app rule exactly, for consistency within the ledger.

## Finding 13: `details` JSON has no version marker

**Severity:** TENSION
**Type:** Approach-later
**Design-level:** No
**Likelihood:** rare
**Classification:** User-directed
**Raised-by:** systems-architect
**visibility:** presented
**disposition:** pending

**Why-it-matters:** `details` is validated by per-kind models on write and carries no version key. If a model changes, #4084's reader can't tell an old-model row from a new one within one retention window.

**When-it-bites:** Only when a details model changes in a way that isn't additive. Retention limits old rows to `retention_days`, so the window is short. Rare.

**Evidence:** design.md lines 134, 150 ("the models are the only place its keys are defined"), line 138 ("Adding a field: No migration"); Prefect `orm_models.py:176-180` (`state_details` as a Pydantic column with a default, no version key).

**Design-challenge:** Does a retention-bounded table with only additive model changes need a schema version?

**Deciding-factor:** whether a version key earns its keep against a 30-day window of mixed rows.

**Criteria:**
| | A: add a `v` key to every `details` object | B: Accept |
|---|---|---|
| New state | A version field and the rules for bumping it | None |
| Reader handling | Branch on `v` | Models use defaults, so readers tolerate missing keys |
| What peers do | No surveyed peer versions its extras, so this diverges | Matches Prefect (`state_details` Pydantic model with defaults, `orm_models.py:176-180`), HA attributes and Airflow `log.extra`, none of which carry a version |

**Options:**
- **A**: Add a version key to each `details` object.
- **B** *(recommended)*: Accept as a known limitation: `details` carries no version, so models change only by adding optional fields and readers tolerate missing keys within the retention window.

**Recommendation:** B. It matches every peer with JSON extras, retention limits mixed rows to one window, and D5 already says fields are added without a migration. One sentence in D5 saying changes are additive covers it.
**Pick-instead-if:** A: you expect a details field to change meaning, not just be added, while old rows are still retained.
