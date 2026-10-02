# Design: Surface blocking-IO events in the web UI

**Date:** 2026-10-02
**Status:** ratified
**Mode:** sketch

## Summary

Blocking-IO detection writes every detected loop stall to the `blocking_events` table, but nothing reads it: no API route, no UI, no CLI (issue #1039). Users never learn their apps block the loop unless they open the SQLite file. A live production DB (hautomate) holds 52 events in one week: 13 attributed to apps (9 from `car_climate`, all in a synchronous Google Calendar client call at `calendar_service.py:98`), 35 `displaced`, 4 `framework`.

This change adds a read path and surfaces it so a user sees an actionable finding per app, e.g. "car_climate: 9 blocking calls from `scan_and_schedule` and `on_event_ending`, at `calendar_service.py:98 get_calendar_events` (calls `gcsa…get_events`), up to 534 ms — investigate".

In scope:
- A backend aggregation in the telemetry query layer (`src/hassette/core/telemetry/`, exposed through `TelemetryQueryService` in `query_service.py`) that turns rows into grouped findings by classifying their stored frames (D2, D14).
- Wire response models in `wire/src/hassette_wire/telemetry.py`, routes in `src/hassette/web/routes/telemetry.py`, regenerated schemas/types (`scripts/export_schemas.py --types`).
- UI: a per-app findings section on the app detail Overview tab (`frontend/src/components/app-detail/overview-tab.tsx`), a signal on the apps list (`frontend/src/pages/apps-table-row.tsx`, fed by `DashboardAppGridEntry`), and unattributed stalls on the diagnostics page (`frontend/src/pages/diagnostics.tsx`).
- CLI command per D11, docs (`docs/pages/core-concepts/blocking-io-detection.md`, `docs/pages/web-ui/`), demo/screenshot support per D12.

Out of scope: changing detection or attribution logic (the row only gains structured frames, D14); reading frames out of pre-existing rows' `source_location` text; enabling Tier 2 in production; WebSocket broadcast of blocking events.

## Decisions

### D1: What identifies one finding (the grouping key)?

**Deciding factor:** one finding per thing the user has to fix. The fix lives at a call site, not at a handler.

| | A: innermost app call site | B: handler/job | C: (handler, call site) pair |
|---|---|---|---|
| car_climate today | 1 finding (calendar_service.py:98), lists both handlers | 2 findings (scan_and_schedule, on_event_ending) with the same cause repeated | 2 findings, same call site repeated |
| Points at the code to change | yes, directly | no, user must dig into the handler | yes, but duplicated |
| Rows with no frames (e.g. the live DB's one attributed `garage_proximity` row has no captured stack; all pre-D14 rows) | need a fallback key | natural | need a fallback key |
| Matches the goal message | yes ("N events in X / Y, all at file:line") | partially | partially |

**Recommendation:** A. Group attributed rows by `(app_key, call site)`, where call site is the innermost app-code frame (D2) for Tier 1 rows and `primitive` + `source_location` for Tier 2 rows (labelled per D2 when the location isn't user code). Each finding lists every handler/job that reached it. Rows with no stored frames (no stack captured, or written before D14), or frames with no app frame, group under one per-handler finding marked "call site not captured".
**Pick B instead if** users mostly have one call site per handler and want findings to line up with the handlers tab. **Pick C instead if** the same helper is called from handlers with very different fixes.
**Reversibility:** easy (pure aggregation logic; no stored data changes)
**Ratified:** Chose call-site grouping over per-handler or per-pair, to get one finding per thing to fix, accepting a separate per-handler fallback key for rows without a captured app frame.

### D2: Which stack frame counts as "app code"?

**Deciding factor:** pick the frame the user wrote, in both container and bare-metal layouts, without guessing.

All options share a first pass: a frame whose path is under the app's manifest `app_dir` (`AppManifest.app_dir`, `src/hassette/config/classes.py:133`) is app code. For unattributed rows (D8), use the union of all manifests' `app_dir`s. They differ in the fallback, which applies only when no frame passes the first pass:

| | A: outside the interpreter's install prefixes (`sys.prefix`, `sys.base_prefix`, `sys.exec_prefix`) and no `site-packages`/`dist-packages` path segment | B: module-name stdlib check (`sys.stdlib_module_names`) + site-packages segment | C: no fallback (`app_dir` only) |
|---|---|---|---|
| Stdlib leaf (`ssl.py`, `weakref.py`) | excluded (under `base_prefix`) | excluded | excluded |
| Console-script frame (`/app/.venv/bin/hassette`, module `__main__`), the outermost frame of every live displaced stack | excluded (under `sys.prefix`) | picked as user code unless `__main__` is special-cased | excluded |
| `pip install --user` libs (`~/.local/.../site-packages`) | excluded (segment) | excluded | excluded |
| Helper outside `app_dir` (e.g. `/config/lib/util.py`) | caught | caught | missed → "call site not captured" |
| User path containing "hassette" (e.g. `/opt/hassette-config/...`) | caught | caught | only if under `app_dir` |
| Rows recorded under an older image (`python3.12` vs `3.13`) | excluded (same `/usr/local` prefix) | excluded | n/a |

**Recommendation:** A. It's the only fallback that excludes the launcher-script frame without a special case, and it's path-correct in both layouts. The live container confirms the layout: `sys.prefix=/app/.venv`, `sys.base_prefix=/usr/local`, stdlib `/usr/local/lib/python3.13`, user code `/apps/...`. The same classifier applies to every surface:
- Tier 1 stacks: walk innermost-first; the first frame that passes the first pass wins, else the first that passes the fallback, else "call site not captured".
- Tier 2 rows: the single stored `source_location`. If it isn't user code, the finding reads "detected inside `<top-level package>`" instead of presenting a library line as the place to fix.
- Diagnostics (D8).

The classifier lives with the frame model (D14), not in `app_utils.py`. It does not reuse `EXCLUDED_PATH_PARTS`, whose bare-substring `"hassette"` entry would exclude user paths and whose list has no stdlib marker. `find_user_frame` (load errors) stays unchanged. Hassette's own frames never appear in Tier 1 stacks because the watchdog filters them with `is_internal_frame`.
**Pick B instead if** stacks are ever analyzed by a different interpreter than the one that recorded them, so prefixes wouldn't match. **Pick C instead if** fallback false positives prove noisier than missed helpers.
**Reversibility:** easy
**Ratified:** Chose app_dir-then-outside-interpreter-prefixes over a module-name check or app_dir-only (re-evaluated after challenge), to classify user code correctly in container and bare-metal layouts including Tier 2 and diagnostics, accepting that prefix matching assumes the server classifies frames its own interpreter recorded.

### D3: Where does grouping and frame classification happen, and what's the API shape?

**Deciding factor:** one implementation shared by UI and CLI, with `app_dir` knowledge only on the server.

| | A: backend grouping | B: client grouping, `app_dir` added to the manifest response |
|---|---|---|
| One implementation for UI + CLI (D11) | yes | no: CLI reimplements grouping in Python or prints raw rows |
| App-frame classifier (D2) | needs the server's own interpreter prefixes (`sys.prefix` etc.), available only server-side | needs those prefixes exposed too, plus the rule duplicated in TypeScript; drift risk |
| Diagnostics (unattributed rows need app-frame detection against every app's `app_dir`) | server has config | diagnostics page must load all manifests |
| Payload | small summaries | full stacks for every row (~25 lines each); needs a cap either way |
| Row-level API for future consumers | not exposed (easy to add later) | yes |
| New wire surface | 2 routes + 1 grid field | 1 route + `app_dir` on the manifest (not exposed today; `wire/src/hassette_wire/apps.py` has only `filename`) |

**Recommendation:** A, because it's one implementation shared with the CLI, and D2's classifier depends on server interpreter state. Shape:
- `GET /api/telemetry/app/{app_key}/blocking` → `list[BlockingFinding]`, taking `TelemetryFiltersDep` (instance_index, since). Category A `db_degrades_to`. (Changed during the build; see the Build section: optional `instance_index`, omitted = every instance.)
- `GET /api/telemetry/blocking/unattributed` → the diagnostics payload (D8), taking `since`. Category A.
- `GET /api/telemetry/blocking/findings` → findings for every app, taking `since`; used by the CLI without `--app` (D11). Category A.
- `DashboardAppGridEntry` gains a `blocking_event_count` field, filled by a new enrichment query in `dashboard_app_grid` as a category-C site (failure → 0, response stays 200). This is a known blind spot under D13: a full DB outage still surfaces, because the manifest fetch 503s (`src/hassette/web/routes/telemetry.py:301`), but a failure of only this query reads as zero.

Fetch rows (DB I/O only) inside `execute()`, then classify and group in plain Python outside the block. `.claude/rules/web-api.md` and the `execute()` docstring in `query_service.py` require this. Volume is small (rows per app per window are low, and retention bounds the table), so grouping in Python over fetched rows is fine. Cap rows fetched per request at a module-level constant (default 1000, most recent first), and include a `truncated: bool` field in each response so the UI and CLI can say counts are partial when the cap is hit.

**Pick B instead if** a row-level event API is wanted anyway (e.g. a future all-events table view) and the CLI may show an ungrouped view.
**Reversibility:** easy
**Ratified:** Chose backend grouping over client-side grouping with `app_dir` exposed, to keep one implementation shared by UI and CLI, accepting that no row-level event API exists yet.

### D4: Which time window do the findings cover?

**Deciding factor:** consistency with every other telemetry view vs. not hiding a chronic problem after a restart.

| | A: global time-window preset (default since-restart) | B: fixed lookback (e.g. 7 d) regardless of preset | C: preset, but the apps-list count always uses 7 d |
|---|---|---|---|
| Consistent with other app telemetry | yes (`useScopedQuery` everywhere) | no; a second notion of "window" | mixed |
| After a deploy/restart | hidden until the call recurs | still visible | list visible, detail hidden: confusing |
| Answers "is my fix working?" | after a process restart, yes. After an in-process app reload (dev-mode file watcher, UI reload action), no: the window is process uptime (`frontend/src/utils/time-window.ts:19-21`), so read D6's last-seen time instead | no; old events linger for 7 d | partially |
| Complexity | lowest | low | highest |

**Recommendation:** A. Blocking calls in a real app recur (car_climate's fire daily), so since-restart surfaces them within a day. A production deploy restarts the process, which resets the window. Fix verification otherwise relies on D6's last-seen time (D13).
**Pick B instead if** the main use is periodic review of rare events that may not recur for days.
**Reversibility:** easy
**Ratified:** Chose the global time-window preset over a fixed lookback or a split window, to stay consistent with all other telemetry, accepting that events before a restart are hidden under the default preset and that an in-process app reload does not reset the window (see D13).

### D5: Where do per-app findings appear on the app detail page?

**Deciding factor:** seen without hunting, invisible when there is nothing to see.

| | A: Overview section, shown only when findings exist | B: new "blocking" tab | C: always-shown Overview section with empty state |
|---|---|---|---|
| Discoverability | high: on the landing tab | low: user must know to click | high |
| Noise when clean | none | an extra tab on every app | permanent empty panel on every app |
| Precedent | `ErrorSpotlight` in `overview-tab.tsx` renders only when `failingItems.length > 0` | — | — |

**Recommendation:** A. Place it directly after `ErrorSpotlight` (before `HandlerHealthGrid`). It renders nothing when there are no findings and while loading. On fetch failure it renders nothing and doesn't block the page.
**Pick B instead if** findings need room for a full event history table. **Pick C instead if** users should see positive confirmation ("no blocking calls detected").
**Reversibility:** easy
**Ratified:** Chose a conditional Overview section over a new tab or an always-shown section, to make findings visible on the landing tab with zero noise for clean apps, accepting no positive "all clear" confirmation.

### D6: What does each finding show?

**Deciding factor:** enough to act on without opening the DB, in a scannable line.

| | A: summary line + callee hint + expandable latest stack | B: summary line only | C: full event table per finding |
|---|---|---|---|
| Actionable | yes: call site, what it calls into, raw stack on demand | partly: no "why" | yes, but verbose |
| Stability of the "why" | callee frame (frame just inside the app frame, e.g. `gcsa…get_events`) is the same every event; leaf frames vary (ssl.read / do_handshake / connect) | — | shows all varying leaves |
| Scannability | high | highest | low |

**Recommendation:** A. Each finding shows:
- call site (`file:line in func`)
- the callee hint: the frame immediately below the app frame (for Tier 2, the `primitive`)
- the handlers/jobs that reached it, linking to their handler-detail pages
- event count, max and average stall in ms, last-seen relative time
- a disclosure that expands the most recent row's full stack

A Tier 2 finding labels the primitive (e.g. `time.sleep`) rather than a callee.

Path display (from challenge Finding 11; D8, D11 and D12 inherit it):
- Summary lines and CLI rows show app-code frames relative to their matching `app_dir` (e.g. `calendar_service.py:98`).
- Library frames show relative to their `site-packages`/`dist-packages` root (e.g. `gcsa/_services/events_service.py`), and stdlib frames as `stdlib/<path>`, the same convention #749 proposes for tracebacks.
- Fallback-classified user frames (D2) show absolute.
- The expanded stack shows each frame's absolute path verbatim.

The API returns both the display path and the absolute path, so UI and CLI don't re-derive it.
**Pick B instead if** stacks are judged too raw for the UI audience. **Pick C instead if** per-event timing patterns matter more than the aggregate.
**Reversibility:** easy
**Ratified:** Chose summary + callee hint + expandable latest stack over summary-only or a full event table, to make each finding actionable while staying scannable, accepting that only the most recent stack is viewable per finding. Path-display rule added after challenge (Finding 11): short relative paths in summaries, absolute paths in the expanded stack.

### D7: What signal appears on the apps list?

**Deciding factor:** the user notices without opening each app, and the list doesn't get noisier for clean apps.

| | A: small warn badge next to the status pill when count > 0 | B: new "blocking" column | C: nothing; detail page only |
|---|---|---|---|
| Notice without clicking in | yes | yes | no; defeats the goal |
| Noise for clean apps | none | an always-present column of "—" | none |
| Table width (already hides columns at `max-sidebar`) | ~no impact | costs a column | none |
| Threshold | any event in window | any | — |
| Absence of the badge | claims nothing (D13); may also mean the count query alone failed (D3) | same | — |

**Recommendation:** A. Show a `warn`-variant `Badge` reading e.g. "9 blocking" after the status pill when `blocking_event_count > 0`, with a tooltip/aria-label that says what it means. It links to the app's Overview. The count is attributed rows only, in the global window.
**Pick B instead if** you want sortable blocking counts across apps. **Pick C instead if** the list must stay strictly status-only.
**Reversibility:** easy
**Ratified:** Chose a conditional warn badge over a new column or no list signal, to make affected apps noticeable with no noise for clean ones, accepting that blocking counts aren't sortable.

### D8: How do unattributed stalls (`displaced` / `framework`) appear on diagnostics?

**Deciding factor:** show the loop-health signal without blaming an app, and without a permanent panel when the loop is healthy.

| | A: panel with summary + recent stalls (stack expandable), only when any exist | B: stats-strip counter only | C: grouped by leaf frame |
|---|---|---|---|
| Shows the 5 s stalls hautomate has | yes, with stacks | count only; no way to investigate | yes |
| Honest about attribution | yes: labels each row displaced vs framework and explains both | yes | yes |
| Leaf grouping value | — | — | low: leaves are incidental (weakref.remove inside whatever was allocating) |
| Precedent | `BootIssuesPanel` / `LoggingPanel` render only when non-empty | `buildDiagCells` | — |

**Recommendation:** A. Add a stats-strip cell "loop stalls" (warn tone when > 0), and a panel rendered only when there are stalls. The panel shows count, max stall and a reason breakdown, then the most recent N stalls. Each stall shows time, duration, reason, its innermost app-code frame if the stack has one (D2's classifier, against all manifests' `app_dir`s), and an expandable stack. The window is the global preset (D4).
**Pick B instead if** diagnostics should stay counters-only. **Pick C instead if** framework stalls cluster on a stable code path worth naming.
**Reversibility:** easy
**Ratified:** Chose a stats cell plus conditional recent-stalls panel over counter-only or leaf grouping, to make unattributed stalls investigable without blaming an app, accepting a list view rather than an aggregated one.

### D9: Should a `displaced` row whose stack contains app code be credited to that app?

**Deciding factor:** never blame the wrong app. The watchdog withheld attribution on purpose (`_classify_attribution` in `src/hassette/core/loop_watchdog.py`).

| | A: no; show the app frame on diagnostics only | B: yes, map the frame's file to an app via `app_dir` |
|---|---|---|
| Correctness | follows the watchdog's decision | can't disambiguate: all hautomate apps share one `app_dir` (`/apps/src/hautomate`), so a shared helper file maps to many apps |
| User still sees the evidence | yes, on diagnostics (D8) | yes, on the app |
| Complexity | none | file→app mapping + tie-breaking |

**Recommendation:** A.
**Pick B instead if** a reliable file→app mapping exists (e.g. one app per directory) and displaced rows dominate real findings.
**Reversibility:** easy
**Ratified:** Chose not to re-attribute displaced rows over file→app mapping, to never blame the wrong app, accepting that app code seen in displaced stacks only shows on diagnostics.

### D10: How do findings refresh while the page is open?

**Deciding factor:** fresh enough, with no new push channel.

Collapsed decision. Blocking events are not broadcast over the WebSocket. On app detail, invalidate the findings query on the same execution signals that already invalidate listeners/jobs (`useQueryInvalidator` with `handlerExecution`/`jobExecution` in `frontend/src/pages/app-detail.tsx`), because a blocking event is always produced by an execution. Nothing orders the execution-complete signal against the blocking row's separate write (`src/hassette/core/command_executor.py:754`), so a newly detected stall may not appear until the next execution or page load. Under D13 that lag is acceptable. The apps list and diagnostics use their existing refetch behavior.
**Pick a WS `blocking_event` broadcast instead if** near-real-time display matters. It adds a wire event type and a frontend handler.
**Reversibility:** easy
**Ratified:** Chose invalidation on existing execution signals over a new WS broadcast, to keep findings fresh without a new wire event, accepting that refresh follows execution completion rather than the stall itself.

### D11: Is the CLI in this change?

**Deciding factor:** cost once the route exists.

Collapsed decision. Include it: `hassette blocking` is a thin command over the two routes (≈25 lines, same shape as `cmd_log` in `src/hassette/cli/commands/log.py`), with `--app`, `--instance`, `--since`, `--json`. Without `--app` it lists findings for every app that has any, plus unattributed stalls. Human output is one row per finding (app, call site, callee hint, count, max ms, last seen). For "every app", the per-app route's `app_key` becomes optional via a sibling `GET /api/telemetry/blocking/findings` that returns findings for all apps in one query, using the same grouping code. That's one HTTP call instead of a manifest fetch plus N per-app calls.
**Pick defer instead if** the build runs long; the UI is the priority.
**Reversibility:** easy
**Ratified:** Chose to include the CLI over deferring it, to close #1039's CLI criterion while the shared query is fresh, accepting a slightly larger PR.

### D12: How do demo, screenshots and QA get realistic blocking data?

**Deciding factor:** visual evidence and docs screenshots that show a real finding, without polluting other screenshots.

| | A: extend seed scenarios only | B: deliberately-blocking demo app (`autostart=false`) | C: B + a docs screenshot entry |
|---|---|---|---|
| Anything consumes it today | no: `scripts/seed_db.py` has no consumer outside CLAUDE.md and old design docs; first use, unproven | yes: the demo stack is the standard visual-QA path (`.claude/rules/demo-and-screenshots.md`) | yes |
| Exercises the real pipeline (watchdog → DB → API → UI) | no, synthetic rows | yes | yes |
| PR visual evidence | ad hoc | via `scripts/capture_screenshots.py` | via `scripts/capture_screenshots.py` |
| Docs page shows the feature | no | no | yes |
| Risk to other screenshots | none | none (not started by default) | only entries after it, since started apps persist through the manifest run; place it near the end like `degraded_demo` |
| Effort | low, on an unused tool | medium | medium (+1 manifest entry and embed) |

**Recommendation:** C. Add a small `examples/` app with `autostart = false` in `examples/hassette.toml`. It makes a deliberate synchronous blocking call (well over the 100 ms watchdog threshold) on a short repeating schedule, from two handlers through one shared helper, so the call-site grouping (D1) shows. A `docs/screenshots.yml` entry starts it via `javascript: fetch('/api/apps/<key>/start',{method:'POST'})`, waits for the findings section's `data-testid`, and captures it. This follows the `degraded_demo` entry pattern; respect its ordering note. Seed scenarios stay untouched (`healthy` already inserts a minimal row; the schema doesn't change).
**Pick B instead if** you don't want a docs image to maintain. **Pick A instead if** you'd rather not add another example app.
**Reversibility:** easy
**Ratified:** Chose an autostart=false blocking demo app plus a docs screenshot entry over seed-only or demo-only, to exercise the real detection pipeline and show the feature in docs, accepting one more example app and screenshot-ordering care.

### D13: What does an empty findings view claim?

**Deciding factor:** the feature's job is to notice presence ("this app is blocking, go look"). Decide once what absence means, rather than defending it with per-gap machinery.

| | A: presence-only, best-effort; an empty view claims nothing; gaps documented | B: A + track/expose each instance's start time for "not seen since this app last started" | C: verified all-clear (instance epoch, drop counter, nullable count + "unknown" badge, polling) |
|---|---|---|---|
| In-process app reload doesn't reset the window (D4) | documented; verify via D6's last-seen time or a short preset | explicit "not seen since reload" | fixed |
| Dropped writes (Assumed, best-effort bullet) | documented; drops already log | same as A | drop counter on diagnostics |
| Badge reads 0 when only its enrichment query fails (D3) | documented; full DB outage still 503s | same as A | nullable count + unknown state |
| Refetch can beat the row's write (D10) | documented lag | same as A | polling |
| New state / wire surface | none (`AppInstanceResponse` has no start time today, `wire/src/hassette_wire/apps.py:8`) | runtime start-time tracking + manifest field | four additions across writer, API, UI |

**Recommendation:** A. In a best-effort diagnostic pipeline absence was never strong evidence; the writer itself calls these rows "diagnostic, not a completion contract". A production deploy restarts the process, which resets since-restart anyway. The docs page (`docs/pages/core-concepts/blocking-io-detection.md`) states that findings are best-effort and that "no findings" doesn't certify an app clean. No UI copy claims verification ("all clear", "fixed").
**Pick B instead if** fixes are mostly verified by hot reload. **Pick C instead if** the badge must be authoritative enough to alert on.
**Reversibility:** easy
**Ratified:** Chose a presence-only, documented best-effort contract over a reload cue or a verified all-clear (from challenge Finding 2), to keep the feature focused on noticing problems without new state, accepting that an empty view proves nothing and fix verification relies on last-seen times.

### D14: How do findings read stack frames?

**Deciding factor:** remove the text-format contract instead of guarding it. Pre-existing rows are not supported; they age out with retention.

| | A: co-located text format + regex parser, round-trip test | B: pinning test on `_capture_loop_stack` only | C: store structured frames on new rows |
|---|---|---|---|
| Parsing code | regex parser + shared format | regex parser | none |
| Drift risk | caught by test | caught, but the format is duplicated in the regex | none: one typed model is written and read |
| Pre-existing text rows | parsed (unneeded scope) | parsed | no frames → "call site not captured" (D1); age out via `retention_days` |
| Write-path change | none | none | nullable JSON column + event/model fields |
| Lines up with #749 (structured exception tracebacks) | no | no | yes: same frame shape |

**Recommendation:** C:
- Migration `013.sql` adds a nullable `frames` JSON column to `blocking_events`.
- A shared frame model `{filename, lineno, function, module}` (#749's `ParsedFrame` minus `is_user`/`code`, so #749 can reuse it) is captured innermost-first. The watchdog builds it in `_capture_loop_stack` from the frame objects it already walks; Tier 2 stores its single caller frame (`find_caller_frame` in `src/hassette/utils/source_capture.py`).
- `WatchdogEvent`, `MonkeypatchEvent` and `BlockingEvent` carry the list, and `insert_blocking_event` writes it. `source_location` text keeps being written unchanged for the warning message and raw display.
- `is_user` is never stored. It is decided at read time by D2, which needs `app_dir` and interpreter prefixes and may change.
- The expandable stacks in D6/D8 render from `frames`.
**Pick A instead if** the PR must make no schema or writer change.
**Reversibility:** hard (adds a persisted column; easy to stop reading, not to un-migrate)
**Ratified:** Chose storing structured frames on new rows over a text parser or a pinning test (from challenge Finding 10), to remove the text-format contract and align with #749, accepting a migration, a writer change, and no call sites for pre-existing rows.

## Assumed

- Nothing reads `blocking_events` today; this change adds the only reader. Evidence: `grep -rn blocking_events src client wire frontend/src` hits only the writer, schema docs and retention (`src/hassette/core/telemetry/repository.py:399`, `src/hassette/core/retention_targets.py:52`).
- The watchdog captures the loop thread's frames innermost-first, up to `_MAX_STACK_DEPTH` (30) before this change, with hassette-internal frames already removed by `is_internal_frame`. It then flattens them into `source_location` text, which D14 keeps writing. Evidence: `_capture_loop_stack` in `src/hassette/core/loop_watchdog.py:331-357`.
- Tier 2 `source_location` is `"<file>:<lineno>"` of the first non-hassette caller frame, with `primitive` set. Evidence: `MonkeypatchEvent.source_location` docstring, `src/hassette/core/block_io_guard.py:133`; `migrations_sql/005.sql`.
- Attributed rows carry `execution_id`, which joins `executions.execution_id` → `listeners`/`scheduled_jobs` (`handler_method`, listener `name` / job `job_name`). Unattributed rows carry no `app_key`/`execution_id`. Evidence: live DB join (6 of 6 attributed apps resolved); `_emit_stall` in `loop_watchdog.py:359`.
- `reason` is NULL for rows written before migration 007. Treat them by `source_tier` (`app` → attributed, `framework` → unattributed). Evidence: `BlockingEvent.reason` docstring in `src/hassette/schemas/log_models.py`.
- `blocking_events` growth is bounded by retention (age + size failsafe). Evidence: `src/hassette/core/retention_targets.py:52`.
- Blocking-event rows are best-effort. The writer ignores `enqueue()`'s result ("diagnostic, not a completion contract"). Rows drop when the shared write queue is full (logged at ERROR) or when the insert fails (logged at WARNING), and no counter records either. Evidence: `src/hassette/core/command_executor.py:745-758`, `src/hassette/core/database_service.py:602-610`, `src/hassette/core/telemetry/repository.py:441-446`.
- Telemetry routes degrade through `db_degrades_to`, and DB I/O inside `execute()` is kept separate from transform logic. Evidence: `.claude/rules/web-api.md`; `TelemetryQueryService.execute` in `src/hassette/core/telemetry/query_service.py:66`.
- New wire models need schema + TS type regeneration, checked by the pre-push hook and CI. Evidence: `.claude/rules/frontend-worktree.md`.
- The default UI time window is `since-restart`. Evidence: `frontend/src/state/store.ts:151`.
- PRs touching rendered frontend files need visual evidence. Docs and frontend ship in the same PR. Evidence: `.claude/rules/design-completeness.md`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
- `StackFrame` lives in `hassette_wire.blocking` and the classifier in `hassette.utils.stack_frames`: the frame is served on the wire, so the wire model is the single definition; the classifier needs server interpreter state, so it stays server-side next to capture/encode.
- `WatchdogEvent.stack_text` and `MonkeypatchEvent.source_location` became properties derived from `frames`: one source of truth for the text column and the structured column.
- The per-app route takes explicit `instance_index`/`since` instead of `TelemetryFiltersDep`: findings are attributed-only, so the dep's `source_tier` would be a dead parameter.
- Findings responses wrap the list in `BlockingFindingsResponse {findings, truncated}`: D3 requires `truncated` on each response, which a bare list can't carry.
- Rows for an app missing from the current config, and unattributed rows, classify against the union of every configured `app_dir`: the row's own app has no manifest to read.
- Tier 1 and Tier 2 events at the same line stay separate findings: D1's keys differ by construction (Tier 2's includes the primitive).
- Findings aggregate in SQL per distinct (stack, handler) before Python classifies anything, and the cap bounds those groups instead of events: a newest-1000-events cap let one chronic call site push older ones out and made counts approximate. Each distinct stack is classified once, filename answers are memoized per request, and grouping runs in `asyncio.to_thread` because it is pure-Python CPU work on the loop the watchdog measures. Diagnostics totals are SQL aggregates, so `UnattributedBlockingResponse` dropped `truncated`. Prior art: `design/research/2026-10-02-grouping-stack-events-into-findings/research.md`.
- D2's fallback also excludes the hassette package directory, not just interpreter prefixes: the live demo stack showed a source run (`python -m hassette`) leaves `hassette/__main__.py` (module `__main__`, so not dropped by `is_internal_frame`, and outside every prefix) on every stack, which the fallback would otherwise report as user code. This refines D2's "exclude the launcher frame" intent rather than changing it.
- Stdlib display matches any versioned `pythonX.Y` directory under an interpreter prefix: rows recorded by an older image still read as `stdlib/...`.
- Seed scenarios' `_BLOCKING_EVENT_COLUMNS`/`add_blocking_event` gained a `frames` column (default NULL): the schema-parity test requires it; no scenario data changed.
- New wire list fields have no defaults: defaulted lists generate optional TS fields, and these are always populated.
- The watchdog keeps up to 60 non-hassette frames per stack (`_MAX_STACK_FRAMES`), and skipped hassette frames no longer count toward the limit: the 30-frame walk noted under Assumed could end inside a deep library stack before reaching the app frame, which read as "call site not captured".
- `hassette blocking --app X` without `--instance` covers every instance. A multi-instance app's page with no instance selected is an app-wide overview (`MultiInstanceOverview`), not instance 0, so the per-app route's `instance_index` is optional: omitted, findings merge each call site across instances and list them in `instances`; given, only that instance's events count. Handler refs carry their own `instance_index` so links from the merged view land on the right instance.
- Expanded stacks render outermost-first via the existing `TracebackLines`, matching Python traceback order elsewhere in the UI. Diagnostics lists the 20 most recent stalls (`RECENT_UNATTRIBUTED_LIMIT`).
- The demo app uses two scheduled jobs (no HA entities needed) calling a `time.sleep` helper, so in dev mode both tiers record it.

## Addendum
