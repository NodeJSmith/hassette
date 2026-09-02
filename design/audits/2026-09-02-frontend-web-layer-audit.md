# Frontend + Web Layer Audit — 2026-09-02 (run 3)

**Scope:** The web dashboard end to end — `frontend/src/` (state, WS handling, query layer, pages,
components, utils) plus `src/hassette/web/` (routes, models, mappers, auth, middleware) as the
frontend's data-contract boundary. Both dimensions: data correctness (staleness, contract drift,
wrong/missing values) and visual/UX quality (live demo stack, screenshot matrix at 1440px and
390px).

**Not covered this run:** deep a11y audit (screen-reader walkthrough), the seeded-scenario DBs
(`large-volume`/`adversarial` states — demo-stack live data only), frontend test quality
(tracked separately, #1282), bundle/performance profiling (#1477 tracks code-splitting).

**Lenses:** correctness first, UX/polish second. Same method as runs 1-2: Fable reasoning as the
engine, two Sonnet reader agents for breadth (frontend long-tail, web layer) whose findings were
each re-verified against the actual code before making this report, and live verification on the
demo stack for anything probeable.

**Method — live evidence:**

- Demo stack (HA + hassette 0.52.0 + Vite), authenticated session, Playwright-driven browsing.
- Live probes: WS reconnect repro via `docker restart` of the hassette container with a
  half-failed app; `GET /api/scheduler/jobs` field inspection; 65-second uptime-label watch.
- Screenshot matrix: apps, app-detail (degraded multi-instance), handlers, logs, diagnostics,
  config at 1440×900; apps + logs at 390×844.

---

## Verdict up front

This is a **well-built frontend**. The store's reconnect atomicity, the WS message validation,
the exhaustively-`satisfies`-typed status maps, the staleness reasoning documented inline in
`appLiveStatus`, and the auth layer (timing-safe comparisons, no header-spoofable trust, WS/HTTP
sharing one auth decision function) are all better than typical production dashboards. The
findings below are real, but they are cracks in a good structure, not signs of rot. The dominant
theme: **the time-window/uptime model has a broken core assumption** (F1), and **WS-overlay state
has one missing invalidation** (F2, already tracked as #1610 — this run adds a live repro and a
scope extension).

---

## Findings

### F1. The since-restart window drifts forward with page-open time; uptime label frozen; runs/hr inflates — HIGH, live-confirmed

`ConnectedPayload.uptime_seconds` is stored once per WS connect (`store.ts:236`) and never
updated. Every consumer then treats it as if it were live:

- `resolveSince("since-restart")` (`time-window.ts:21`) computes `Date.now()/1000 −
  uptimeSeconds` **at each fetch** — the "restart boundary" moves forward one second per
  wall-clock second the tab is open. A dashboard open 2 hours silently excludes the first 2
  hours of post-restart telemetry from every since-restart query (listeners, jobs, activity,
  logs, dashboard grid). Since-restart is the **default preset**, so this is the out-of-box
  behavior.
- The status-bar uptime label renders `formatUptime(uptimeSeconds)` — frozen at its
  connect-time value. Live-confirmed: 65 s after a reconnect the label still read "up 1s".
- `apps.tsx:240-242` uses the static uptime as the runs/hr denominator: numerator (runs) grows,
  denominator stays frozen → the rate inflates the longer the tab is open.

**Fix shape:** store `restartEpochSeconds = Date.now()/1000 − data.uptime_seconds` in
`handleWsConnected`; `resolveSince` returns it directly; uptime label and runs/hr derive live
uptime as `now − restartEpochSeconds` (the existing 30 s `tick` already re-renders on schedule).
One store field change fixes all three symptoms.

### F2. Stale appStatus overlay survives reconnect and outranks fresh REST data — HIGH, live-confirmed → extends #1610

`handleWsConnected`'s `isReconnect` branch clears `serviceStatus` and the log buffer but not
`appStatus` (`store.ts:234-245`), and `appLiveStatus`/`instanceLiveStatus` give the WS entry
precedence over refetched grid/manifest data. The backend deliberately emits STOPPED correction
events so the WS cache can't stick on FAILED (`app_lifecycle_service.py:505-568`) — but only a
*connected* client sees them. Any status transition that happens while the client is
disconnected is lost forever.

**Live repro (this run):** started `degraded_demo` (instance 0 running, instance 1 failed → UI
"degraded"); `docker restart hassette-demo-hassette`; after the WS reconnected (fresh connected
payload, uptime reset) REST truth was `stopped, 0 instances` while the apps table still rendered
`degraded` — indefinitely, until a hard page reload.

**Already tracked as #1610**, which frames it as the multi-instance shrink + forward-probe case
and names the destructive consumer ("Stop all failing" palette action can stop a healthy app).
This run's contribution: a concrete every-restart repro, plus scope extension — the plain
single-key overlay path (`appStatuses[key]?.status ?? row.status`) is equally affected, no
forward probe or instance shrink required. Any app whose state changed across a disconnect
renders wrong. #1610's "simplest" option (clear `appStatus` in the reconnect branch, symmetric
with `serviceStatus`) fixes both shapes.

### F3. Stale `?window=` URL param silently overrides the time window after navigation — MEDIUM-HIGH, code-confirmed

`TimePresetSelector` (mounted once in `StatusBar` above the router `Switch`, never remounts)
parses `?window=` into `urlWindowParam` in a **mount-only** effect
(`time-preset-selector.tsx:26-34`). Every scoped query computes its window as
`urlWindowParam ?? timePreset`. Every preset click writes `?window=` into the URL, so bookmarks
and shared links routinely carry it. Land on such a URL with a different stored preset, then
navigate anywhere in-app: the selector shows the stored preset as active while every query
silently keeps using the URL's window. Only a manual preset click resyncs. The UI and the data
disagree with no visible signal.

**Fix shape:** re-parse `?window=` on every location/search change, or demote it to a one-shot
initializer of `timePreset` and delete `urlWindowParam` entirely (simpler model, one less store
field).

### F4. `fire_at` is nulled for every non-jittered job in the jobs APIs — MEDIUM, live-confirmed

`enrich_jobs_with_live` (`web/utils.py`) gates `fire_at` on `live_job.jitter is not None`, but
`Job.set_next_run()` (`scheduler/classes.py:508-515`) sets `fire_at` unconditionally — jitter
only offsets it afterwards. Since jitter defaults to `None`, essentially every scheduled job
returns `fire_at: null` from `GET /api/scheduler/jobs` and `GET /api/telemetry/app/{key}/jobs`
despite holding a valid value. Live-confirmed on the demo stack: all non-jittered scheduled jobs
show `next_run=<ts>, fire_at=None`. UI impact is muted (job-detail prefers `next_run`), but the
field is documented API surface and any other consumer receives a silently wrong value. The one
test covering this path only exercises the jitter case and treats the bug as intended. Fix:
drop the jitter clause.

### F5. `app_activity` violates the telemetry module's documented `since` contract — LOW-MEDIUM

`routes/telemetry.py` documents "omit `since` for all-time aggregates"; every endpoint honors it
except `app_activity`, which substitutes `now − 24h` when `since` is omitted. The shipped UI
always sends an explicit `since`, so this only bites direct API consumers — who get silently
wrong "all-time" data. Either honor the contract or document the 24 h default in the endpoint.

### F6. Framework-tier handlers have no UI surface — MEDIUM, enhancement

`handlers.tsx:106` hard-filters `source_tier === "app"` — framework listeners/jobs are fetched,
then discarded, with no toggle; no other page shows them. The logs page *does* have an
app/framework tier toggle, and the CLI exposes `--source-tier`. An operator investigating
framework behavior (RQS listeners, StateProxy polling jobs) has telemetry in the DB and no way
to see it in the dashboard.

### F7. Sidebar groups degraded apps under the label "SLOW" — MEDIUM, UX terminology

`sidebar-groups.ts`: the `warn` group renders as "SLOW" but contains `degraded`,
`exhausted_cooling`, `stopping`, `shutting_down` — none of which mean slow. A half-crashed app
filed under "SLOW" actively misleads (screenshot evidence: `degraded_demo` with a failed
instance sat under "SLOW ⚠ 1"). Nothing in the product measures slowness. Rename to match the
tone key it already has ("WARNING" / "DEGRADED" / "ATTENTION").

### F8. Time and count columns truncate at ordinary viewports — MEDIUM, polish bundle

Screenshot-confirmed at 1440×900 (a common desktop size) and 390px:

- Apps table RUNS column: sparkline + count renders as "1…", "3…" — the count is unreadable.
- Logs table TIMESTAMP column clips its own seconds digit ("09/02 12:28:5…").
- Mobile logs WHEN column renders every row as "just …" (32px column, "just now" doesn't fit).
- Handlers table APP column truncates most app keys while TYPE/TRIGGER columns hold slack;
  NEXT RUN clips "completed" to "comple…".
- Related cosmetic: the failed-apps banner renders the app key twice ("degraded_demo —
  degraded_demo: …") because the error message already begins with the key.

Individually trivial; together they read as one issue: fixed column-percentage/px allocations
were tuned for one width and never re-checked at common sizes. Time and count cells should never
be the ones that give way.

### F9. `get_app_source` does blocking file I/O on the event loop — LOW

`routes/apps.py:415` calls `Path.read_text()` inside the async handler, stalling the loop
(including the HA WebSocket receive loop) for the read's duration. Small files today; trivial to
route through the sync executor or `anyio.to_thread`.

### F10. Execution rows without an execution_id are keyboard-focusable but inert — LOW-MEDIUM, a11y

`execution-table.tsx:244-263`: rows with `execution_id` absent get no `onKeyDown`, but still
receive a roving-tabindex stop. Mouse users see "not clickable" styling; keyboard users land on
a focusable row where Enter/Space silently do nothing. Skip such rows in the roving sequence (or
mark them `aria-disabled` and communicate it).

### F11. Log `rowKey()` treats a real `seq: 0` as absent — LOW

`log-table/types.ts:44-46`: `entry.seq ? … : …` — records that bypass `CorrelationFilter`
(early-startup, third-party loggers) carry the backend's explicit `seq: 0` fallback
(`logging_.py:91`) and fall back to a weaker `timestamp-logger-lineno` key that can collide
(React key collision → wrong row selected/highlighted). Use `entry.seq > 0` or key on
seq-presence explicitly.

### F12. `/logs/recent` defaults `source_tier=None` while every telemetry endpoint defaults `"app"` — LOW, discuss

Possibly deliberate (a raw log viewer arguably should default to everything), but it's the only
asymmetry of its kind in the layer and nothing documents it. Decide and write it down, or align
it.

### F13. `useQueryParams` parses `?foo` and `?foo=` inconsistently — LOW, discuss/drop

`use-query-params.ts:48-63`: bare key → `""` present; explicit-empty → dropped, contradicting
the hook's own "empty string = absent" doc. Only reachable via hand-edited URLs.

---

## Minor notes (not slated)

- The log stream's WS subscription level is set by whichever log table mounted last and is never
  reset on unmount — picking "All levels" on /logs leaves the stream at DEBUG until another
  table mounts or the socket reconnects. Waste, not incorrectness.
- App-detail for a failed app shows the same error string three times on one screen (banner,
  Last Error box, instance card). Acceptable for a monitoring tool; worth a squint in any
  future information-density pass.
- `useTelemetryHealth`'s docstring says fetch failure sets `telemetryDegraded = true`; the code
  deliberately only does that on HTTP 503 (the code is right, the comment is stale).
- WS broadcast drops for slow clients are logged server-side but invisible to the client — the
  frontend has no "you may have missed events" signal. Related to the #1610 family; the fix
  there (clear + refetch on reconnect) is the same medicine.

## Strengths (verified, keep doing this)

- **Store discipline:** `handleWsConnected`'s single-`set()` atomicity with its reasoning
  documented inline; selector-based subscriptions that keep pages off the fleet-wide render path
  (`use-scoped-execution.ts` is exemplary, including its documented one-extra-render bound).
- **Contract typing:** status maps typed as `Record` + `satisfies` so a new enum variant is a
  compile error at every consumer; generated REST + WS types with CI freshness enforcement.
- **WS hygiene:** validated messages with an exhaustiveness check, handshake timeout, backoff
  reset only on completed handshake, auth-rejection confirmed via REST before redirecting.
- **Auth layer:** timing-safe comparisons with the reachable `TypeError` path guarded, no
  header-spoofable proxy trust, stateless HMAC session cookies with sliding renewal, one shared
  auth-decision function for HTTP and WS. Reviewed adversarially; nothing found.
- **Degradation architecture:** the `db_degrades_to` category system matches its documented
  classification table at every spot-checked site; 503 vs legit-empty is distinguishable
  everywhere it matters.

## Issue tracking

Filed 2026-09-02 (F6/F12 held for discussion; F2 went as a comment, not a new issue):

| # | Finding | Disposition |
|---|---------|-------------|
| F1 | since-restart drift + frozen uptime + inflated runs/hr | **#1837** (bug, priority:high) |
| F2 | stale appStatus overlay after reconnect | **comment on #1610** — live repro + single-key scope extension |
| F3 | stale `?window=` override after navigation | **#1838** (bug) |
| F4 | `fire_at` nulled for non-jittered jobs | **#1839** (bug) |
| F5 | `app_activity` breaks documented since contract | **#1840** (bug) |
| F6 | framework-tier handlers invisible in UI | **#1847** (enhancement — tier toggle on handlers page, per discussion) |
| F7 | "SLOW" sidebar label for degraded apps | **#1841** (enhancement) |
| F8 | truncation family (time/count columns, banner dup) | **#1842** (enhancement, polish bundle) |
| F9 | blocking `read_text` in `get_app_source` | **#1843** (bug) |
| F10 | inert keyboard-focusable execution rows | **#1844** (enhancement, a11y) |
| F11 | `rowKey()` vs `seq: 0` | **#1845** (bug) |
| F12 | `/logs/recent` tier default asymmetry | **#1848** (docs — asymmetry confirmed deliberate, document it) |
| F13 | `?foo` vs `?foo=` parse inconsistency | **#1846** (bug) |
