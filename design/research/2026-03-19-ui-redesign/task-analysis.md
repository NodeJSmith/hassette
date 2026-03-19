# Task Analysis: Hassette Web UI

**Date**: 2026-03-19
**Sources**:
- User interview (Jessica, sole developer and primary user)
- Community research (AppDaemon, Node-RED, HA Community, Airflow, PM2)
- Hassette GitHub issue history (all open/closed issues)
- Homelab git history (`homelab/hautomate` — Jessica's personal automation repo)

## Usage Pattern

The UI is a **diagnostic tool**, not a monitoring dashboard. The user pulls it up when something is wrong or suspected to be wrong — not for passive observation. There is no "keep it open on a second monitor" use case.

**Trigger events:**
- An automation didn't happen when it should have
- An automation fired when it shouldn't have
- A known state change or service outage is expected to cause failures

This means the UI's primary job is **answering questions fast**, not displaying ambient status. Every page should be optimized for a user who arrives with a hypothesis ("my garage door listener didn't fire") and needs to confirm or refute it quickly.

## Core Tasks (by frequency)

### T1: Diagnose why an event handler didn't fire (or fired unexpectedly)

**User's question**: "My garage door automation didn't run. Why not?"

**What they need to see:**
- The specific app's event handlers — which ones exist, what they listen for
- Recent invocations — when did each handler last fire?
- The values that caused (or didn't cause) a firing — e.g., "garage door state changed to `closed`, handler only fires on `open`"
- If it did fire: was there an exception? What was it?

**Current click path**: Apps > App Detail — shows listeners but no invocation history, no firing values, no filter/predicate visibility.

**Gaps**: No invocation history. No visibility into why a handler *didn't* fire (predicate evaluation results). No way to see the event payload that was evaluated.

**Future work (user-identified)**: Find the last event of type X with values Y that the user thinks *should* have fired their handler, and trace what happened — did the event arrive? Did the predicate reject it? Did the handler error?

### T2: Verify a scheduled job ran and check its results

**User's question**: "Did my nightly cleanup job run? How long did it take? Did it error?"

**What they need to see:**
- The specific app's scheduled jobs
- Whether each job fired, when, how long it took
- If any execution had an exception — what was the exception?

**Current click path**: Apps > App Detail — shows jobs but no execution history (stubbed as empty). Scheduler page exists but also has no history.

**Gaps**: Execution history is not wired to the UI at all (`scheduler_history_partial` returns `[]`). No duration, no error details, no success/failure indicators.

**Future work (user-identified)**: Pause/resume a scheduled job without stopping the entire app.

### T3: Check overall system health

**User's question**: "Is everything okay, or is something broken?"

**What they need to see:**
- Which apps are running, which are failed
- Health status needs a definition: how many exceptions = red vs yellow vs green? Do old exceptions age out?

**Current click path**: Dashboard — shows app status chips. Adequate for "is it running" but no error rate or health gradient.

**Gaps**: Binary running/failed status. No error rate, no "yellow" state. No time-based decay (an app that errored once 3 days ago looks the same as one erroring every minute).

**Entry point note**: The user said they almost never start at the dashboard. They usually know which app is the problem and go straight to it. The dashboard's value is for the less common "something is off but I don't know what" scenario.

### T4: Start/stop an app

**User's question**: "Stop this app" or "Restart this app."

**Current click path**: App Detail — action buttons exist and work.

**Gaps**: None identified. This works.

### T5: View and filter logs

**User's question**: "Show me what happened" or "Show me errors for this app."

**Current click path**: Logs page (global) or App Detail (app-scoped). Both have filtering.

**Gaps**: Functional but the user listed it as a core task. Live log tailing works via WebSocket.

## Tasks Surfaced by Community Research and Git History

The following tasks were not identified in the user interview but emerged from studying comparable tool communities, Hassette's own issue history, and the homelab automation repo's git log.

### T6: See what event arrived vs what handlers expected (silent match failures)

**User's question**: "An event fired but my handler didn't catch it. What did the event look like vs what my handler was matching on?"

**Evidence**:
- Homelab: `fix: use explicit TRADFRI event values in RemoteButton enum` — renaming a StrEnum silently broke all event matching. Invisible until the remote stopped working.
- Homelab: `fix bug, should only fire the correct one, not both` — predicate/filter issue where two handlers both fired.
- HA Community: "why didn't my automation fire" is the #1 forum question category.

**Why it matters**: This is a superset of T1. The handler *did* receive the event, but the payload comparison failed silently. The UI should show: "Event arrived on `event.tradfri_action`, value = `brightness_up_click`. Registered handlers expect: `toggle`, `up_button_click`. No match." This is the "missed-match view."

**Scope**: Near-term (enriches T1 invocation history). The predicate evaluation recording is future work but the event-arrived-vs-handler-expected comparison should be designed for now.

### T7: View live listener/job registrations (what's actually registered)

**User's question**: "What handlers does this app actually have running right now? Is my cron expression correct?"

**Evidence**:
- Homelab: garage_proximity app maintains its own `self.handlers: dict[Person, Subscription]` because there's no external visibility into active registrations.
- Homelab: `minute=5` instead of `minute="0/5"` — a cron expression that appeared to register but silently never ran on schedule.
- Issues: #96 ("Add scheduled tasks viewer"), #268 (source code display).

**Why it matters**: The current UI shows what the *database* recorded at registration time. The user needs to see what the *running process* actually has registered — which handlers are active, what entity they watch, what predicate/condition they use, when the next scheduled run is.

### T8: Change log level per app at runtime (no config edit, no restart)

**User's question**: "Set this app to DEBUG so I can see what's happening. Then set it back."

**Evidence**:
- Homelab: 7+ commits toggling log levels. Stale `log_level = "DEBUG"` settings in hassette.toml that were never cleaned up because the workflow (edit TOML → commit → redeploy → investigate → edit TOML → commit → redeploy) is too burdensome.
- Pattern: `switch log level to debug`, `reset log levels`, `switch a lot of infos to debugs`.

**Why it matters**: An entire class of commits would disappear. The UI should show current log level per app and let you change it with a click. Prominently display stale DEBUG settings.

### T9: See app initialization status (distinct from running)

**User's question**: "Hassette started but this app looks wrong. Did `on_initialize` complete? Did it error?"

**Evidence**:
- Homelab: `fail if not all apps start` commit — previously apps could fail to initialize silently.
- Homelab: `new_remote_app.py` wraps `on_initialize` in try/except defensively after silent failures.
- Issues: #316 ("Log failure reasons when resources fail to start"), #43 ("debug mode toggle for startup timeouts").

**Why it matters**: "Running" ≠ "initialized correctly." A failed or partial initialization should be visually prominent, not buried in logs. This is a distinct state from T3's binary running/failed.

### T10: Enable/disable individual apps from the UI

**User's question**: "Disable this app temporarily without editing config and redeploying."

**Evidence**:
- Homelab: 10+ commits across the full history toggling `enabled = false/true` in hassette.toml. Pattern: `disable garage proximity`, `disable otf for now`, `re-enable service call`, `disable garage door again`.
- Current workflow: edit TOML → git commit → docker-compose restart.

**Why it matters**: This extends T4 (start/stop). T4 works for the current session but doesn't persist across restarts. A UI toggle that sets `enabled` in config and takes effect immediately would eliminate an entire class of commits.

### T11: Invocation count + last-fired timestamp on the handler row itself

**User's question**: (Not a question — a trust signal.) "Has this handler been firing? When was the last time?"

**Evidence**:
- Community: AppDaemon issue #1009 — a handler showing "never executed, 0 fires" while actually running is trust-destroying.
- Issues: #268 (invocation drill-down).

**Why it matters**: The user shouldn't need to drill into history to see if a handler is alive. "47 invocations, last 3m ago" on the row itself is the difference between "working" and "I need to investigate."

### T12: HA connection state visible on arrival

**User's question**: "Is Hassette even connected to Home Assistant?"

**Evidence**:
- Community: AppDaemon users' zero-th question is always "is it connected?" before any app-level debugging.
- Applies especially to new users and post-outage scenarios.

**Why it matters**: A prerequisite for all other tasks. If HA is disconnected, no amount of handler debugging matters. Should be immediately visible, not buried in a status bar.

### T13: Plain-language summary of what each handler watches for

**User's question**: "What does this handler do?" — without reading source code.

**Evidence**:
- Community research (onboarding and returning-user need).
- Homelab: handler registrations like `on_state_change("binary_sensor.garage_door", ...)` have enough metadata to generate "Fires when binary_sensor.garage_door changes state."

**Why it matters**: Especially valuable for new users and for the "I haven't looked at this app in 3 months" scenario. Registration metadata (entity_id, event_type, predicate description) can generate this automatically.

### T14: Manual trigger for scheduled jobs ("run now")

**User's question**: "I want to test this job right now without waiting for the schedule."

**Evidence**:
- Issues: #96 (unchecked AC: "Ability to manually trigger a scheduled job from the UI").
- Community: Airflow's "Clear" (retry), Node-RED's manual trigger.

**Why it matters**: Extends T2 from read-only verification to active control. Eliminates the "wait for the cron to fire" debugging loop.

### T15: Inspect current app configuration values

**User's question**: "What is this app actually running with? What did I set `run_interval` to?"

**Evidence**:
- Issues: #129 (config snapshot in manifest), #324 (config file watching tests).
- Homelab: cron expression bug (`minute=5` vs `minute="0/5"`) — a config problem that would have been caught if the loaded config were visible.

**Why it matters**: Ground-truth check. "Is the running config what I think it is?" — without reading the TOML file.

### T16: Error rate trends (is it getting worse or better?)

**User's question**: "My app errored yesterday. Is it still erroring? More often or less?"

**Evidence**:
- Issues: #235 ("time-based decay for restart failure counter"), #268 (current-vs-all-time toggle).
- Task analysis T3 already identifies health gradient as a gap.

**Why it matters**: Distinct from T3's snapshot. This is temporal comparison — "should I investigate now or is this a known flaky thing?" Requires sparklines or rate displays, not just status badges.

### T17: Slow handler detection (performance diagnosis)

**User's question**: "Why is my home slow to respond? Which handler is taking too long?"

**Evidence**:
- Issues: #162 ("guards against blocking I/O"), #72 ("backpressure and queue overflow"), #267 (TelemetryQueryService design includes slow handler detection).
- Issue #268 AC includes duration in invocation drill-down.

**Why it matters**: Correctness ≠ performance. A handler that fires correctly but takes 8 seconds blocks the event loop. Requires duration-sorted views and slow-handler highlighting.

## Cross-App Views

**User assessment**: "Almost never" needed. The user thinks in terms of individual apps, not cross-app comparisons. This directly challenges the research brief's concern about losing the Bus and Scheduler global views — the user doesn't use them that way.

## Key Insights for IA Design

1. **App Detail is the center of gravity.** The user goes straight to the app they care about. The App Detail page needs to be the most capable page in the UI — not a summary that links elsewhere. Tasks T1, T2, T4, T6-T11, T13-T15, T17 all center on a single app.

2. **Invocation history is the #1 missing feature.** Both T1 (event handlers) and T2 (scheduled jobs) require seeing *what happened* — when, with what values, with what result. T6 (silent match failures) extends this to showing what happened when a handler *didn't* fire. This data exists in SQLite but isn't surfaced.

3. **The handler row should be information-dense.** T7 (live registrations), T11 (invocation count + last-fired), T13 (plain-language summary), and T17 (duration) all enrich the handler/job row itself. The row is not just a label — it's a status display. "Fires when light.kitchen → on | 47 invocations | last 3m ago | avg 12ms" tells the full story at a glance.

4. **The dashboard is a secondary entry point.** It matters for T3 ("I don't know what's broken") and T12 (HA connection state), but most visits skip it. Don't over-invest in dashboard complexity.

5. **Health needs a gradient, not a binary.** Running/failed is too coarse (T3). Error rate with decay is the meaningful signal (T16). App initialization status is a distinct state (T9).

6. **Runtime control eliminates entire commit classes.** T8 (log level toggle), T10 (app enable/disable), T14 (manual job trigger) each eliminate a repetitive edit-commit-deploy cycle. These are high-value, low-complexity UI additions.

7. **"Why didn't it fire?" is the hardest and most valuable question.** Showing what *did* happen is table stakes. Showing what *didn't* happen (T6: event-arrived-vs-handler-expected) is the differentiator. This is future work but should influence the IA now.

8. **Cross-app views can be deprioritized.** The user confirmed they almost never need them. Per-app views are the priority.

9. **New users have different entry tasks.** T12 (HA connection state) and T13 (plain-language handler summaries) matter most for someone who just installed Hassette. The UI should serve the expert diagnostic workflow without confusing new users.

## Task Priority Matrix

Tasks grouped by implementation horizon and value:

### Must-have for redesign (directly addresses user complaints)

| Task | What it solves |
|---|---|
| T1 + T6: Handler invocation history + match failure visibility | "Why didn't my automation run?" — the primary reason to open the UI |
| T2: Job execution history with duration and errors | "Did my job run?" — currently stubbed as empty |
| T3 + T9: Health gradient + initialization status | "Is everything okay?" — currently binary and missing init state |
| T7 + T11: Live registrations + invocation counts on rows | "What's this app actually doing?" — trust and orientation |

### High-value, low-effort additions

| Task | What it eliminates |
|---|---|
| T8: Runtime log level control | 7+ homelab commits per debugging session |
| T10: App enable/disable toggle | 10+ homelab commits across history |
| T12: HA connection state on arrival | Prerequisite confusion for new users |
| T13: Plain-language handler summaries | "What does this handler do?" without reading code |

### Future work (design for but don't build yet)

| Task | Why defer |
|---|---|
| T6 extended: Full predicate evaluation trace | Requires recording predicate evaluation results — backend work |
| T14: Manual job trigger ("run now") | Needs careful permission model |
| T15: Config value inspection | Needs config snapshot in manifest (partially exists) |
| T16: Error rate trends / sparklines | Valuable but not blocking |
| T17: Slow handler detection | Requires duration threshold configuration |

## Implications for the Research Brief

| Brief recommendation | Task analysis says... |
|---|---|
| Airflow-style 4-layer drill-down | Over-architecture. App Detail should show everything inline, not behind tabs. The user wants answers on one page. |
| Merge Bus/Scheduler into App Detail | Correct direction, but don't add tabs — keep the flat layout and enrich it with invocation history, counts, and summaries. |
| Restructure Dashboard with telemetry | Low priority. The dashboard is a secondary entry point. Invest in App Detail instead. Keep it simple: health overview + HA connection state. |
| Sessions page | Low priority. Session context could be a filter on App Detail, not a separate page. |
| Three visual directions | Still needed, but now informed by the primary task: "I'm here to diagnose a problem fast." The design should optimize for scanability and information density on App Detail, not ambient dashboard monitoring. |
| Phase 1 CSS / Phase 2 IA | Inverted. IA decisions (what data appears on App Detail, how handler rows are structured) must come before visual design. The handler row design is an IA decision, not a CSS decision. |
