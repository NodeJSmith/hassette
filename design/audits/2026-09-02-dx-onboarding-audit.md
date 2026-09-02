# DX & Onboarding Audit — 2026-09-02

**Run 2 of the Fable audit series** (run 1: [backend core correctness](2026-09-02-backend-core-correctness-audit.md), issues #1797–#1813; run 3, committed next: frontend deep-dive).

**Scope:** app-author DX — API ergonomics, error-path quality, docs onboarding, the testing story — plus operational surfaces (CLI, telemetry API) where the DX journeys touch them. Deliberately narrowed so each facet gets depth; frontend gets its own full run.

**Method — live evidence, not code reading:**

- Executed the quickstart literally: `uv tool install hassette` (PyPI 0.52.0) in a clean directory against the live demo stack, TTY and piped.
- Three blind personas (fresh Sonnet agents, no audit context, docs-only rules, think-aloud journals): P1 newcomer first-automation, P2 testing-story, P3 debugging three seeded silent failures. Journals under the session scratchpad (`persona1..3/journal.md`).
- Caller-corpus sweep: `~/homelab/hautomate` (~9k lines of real hassette apps + tests, the one known power-user corpus) cataloged for friction patterns (`corpus-sweep.md` in scratchpad).
- Error lab: seven failure scenarios executed against 0.52.0 (missing/invalid token, SIGINT/SIGTERM timing, app-init crash, syntax error, missing config), isolated data dir.
- CLI + telemetry REST driven against the live demo instance (9 apps, seeded activity).

**Not covered this run:** Docker onboarding path, AppDaemon migration docs journey, the web dashboard beyond what P3's debugging needed (run 3), `hassette init`/scaffolding, helpers API DX.

**Corpus caveat:** hautomate is one power-user corpus, largely Claude-written; where it predates recent framework fixes I say so rather than counting stale pain as current debt.

---

## Thesis

The documentation is good — the troubleshooting page names the real traps, the testing docs carried a blind persona to a 3/3 pass in two runs, and the reference is thorough. The telemetry backend is rich. The exception messages (the newer ones) are exemplary. **The debt concentrates in four places:** (1) silent-by-design behaviors with no runtime signal — filtered events, entity typos, forgotten awaits at the API layer; (2) the async/sync three-surface split, which confused even the power user into shipping a never-working automation and documenting a falsehood in their own CLAUDE.md; (3) the error contract — mixed typed/stdlib raises, nothing exported, no guidance page, so callers guess catch-tuples (30 occurrences in the corpus); and (4) the first five minutes — a phantom log line the docs promise, a 30-second silent hang on Ctrl+C, and a flagship dashboard the quickstart never mentions.

A cross-cutting meta-finding: the framework has been fixing this user's pains (per-instance cache keys, forgotten-await detection, the test harness) faster than any channel tells existing users their workarounds are obsolete.

---

## Findings

Severity reflects app-author impact. Every finding is verified live unless marked otherwise.

### HIGH

#### F1. Ctrl+C shutdown: 30 seconds of silence (no SIGINT handler)

`server.py:27` registers a handler for SIGTERM only. Measured on a healthy, idle, single-app 0.52.0 instance:

- **SIGTERM → 1.0s**, acknowledged ("shutdown requested"), full orderly teardown log, "Hassette stopped."
- **SIGINT → 30.1s**, zero hassette output (no acknowledgment; logging is torn down by cancellation), then exit. The 30s is `total_shutdown_timeout_seconds`' default being burned on the disorderly path.

The quickstart flow itself sends users here — uvicorn prints "Press CTRL+C to quit." Blind persona P1 hit it twice, concluded the process was hung, and used `kill -9`. Docker/production (SIGTERM) is unaffected; the broken path is exactly the dev-terminal one newcomers live on.

**Fix shape:** register SIGINT alongside SIGTERM; conventional second-Ctrl+C-forces-immediate-exit; log the acknowledgment before teardown. `type:bug, area:core, size:small, priority:high`.

#### F2. Filtered events are invisible — silent listener failures are structurally undiagnosable

Listener telemetry counts `total_invocations/successful/failed/di_failures/cancelled` — there is **no counter for events that matched the entity but were dropped by `changed=`/predicates**. A listener whose filter drops everything shows 0 invocations, indistinguishable from "no events ever arrived." This is the exact shape of the corpus's real incident (a meeting-light handler that never fired because `changed=True` drops attribute-only changes — the user's CLAUDE.md carries a warning block about it).

The scheduler side proves the model works: job telemetry *does* track `skipped` (predicate_demo: 73 skips in the JSON) — **but the CLI job table omits the column**, rendering `Total 68 / OK 0 / Fail 0`, arithmetic that visibly doesn't add up while hiding the one thing the operator needs.

**Fix shape:** (a) bus-side evaluated-but-filtered counter per listener (consider distinguishing `changed=`-drops from predicate-drops), surfaced in `/api/telemetry/.../listeners`, CLI, and dashboard; (b) add the Skipped column to `hassette job`. (a) is `type:enhancement, area:bus, area:database, topic:telemetry, size:medium`; (b) is `type:bug, area:cli, size:small`.

#### F11. `logging.captureWarnings(True)` black-holes every Python warning — including the forgotten-await guard

(Numbered out of order — found last, belongs in HIGH.)

The forgotten-await detection (`utils/await_guard.py`) is well built: `RegistrationHandle.__del__` emits `HassetteForgottenAwaitWarning` with app, call site, and "Did you forget 'await'?", verified working in isolation (immediate GC → warning caught). **In a running hassette process it is never seen.** `logging_.py:452` calls `logging.captureWarnings(True)`, routing all Python warnings to the `py.warnings` logger — which the logging configuration gives no route to console, JSON, or telemetry. Verified with a control: a bare `warnings.warn("PROBE-DIRECT-WARNING", RuntimeWarning)` in `on_initialize` produces zero output anywhere (even with `PYTHONWARNINGS=always`, which `captureWarnings` overrides).

Compounding it: the guard closes the inner coroutine specifically to suppress CPython's native "coroutine was never awaited" warning — so when its own warning is swallowed, the app author gets *strictly less* signal than plain Python would have given them. Blind persona P3, handed a forgotten-await bug, exhausted CLI, dashboard, and logs, found "no exception, no warning, no boot issue — total silence," and could only fall back to reading the code.

Every other warning in the process (user-dependency deprecations included) is swallowed by the same mechanism.

**Fix shape:** wire `py.warnings` into the logging pipeline (console + capture + a listener-telemetry/boot-issue surface for `HassetteForgottenAwaitWarning` specifically — it names the owning app, so it can land on that app's dashboard card). Add a regression test that a warning emitted in app code reaches the console. `type:bug, area:core, topic:errors, priority:high, size:small`.

### MEDIUM

#### F3. The async/sync three-surface split ships real silent bugs

Three surfaces coexist: async `self.api.*`, sync `self.states.*`, and `.sync.*` facades for `AppSync` apps. Corpus evidence of the cost:

- `front_door_camera_app.py:52` calls async `Api.get_state_value` **un-awaited in a sync method** — the busy-check compares a coroutine object and is silently always-false. Shipped, in production.
- hautomate's own CLAUDE.md canonizes the confusion: "State reads — synchronous, no await" — flatly wrong for `self.api` (right for `self.states`).
- Forgotten-await guarding covers bus/scheduler registration and Api's write trio (`fire_event`/`call_service`/`set_state`) but **not Api read methods** — `get_state_value`, the exact method in the shipped bug, is unguarded. (And what is guarded is currently inaudible — see F11.)

**Fix shape:** extend `guard_await` to Api read coroutines; fix F11 so any of it is heard; add a docs matrix page: what may be sync where (apps × handlers × registration × api/states), including that `HandlerType` officially accepts sync handlers (`handlers.md` currently opens "A handler is an async method," under-telling the contract). `type:enhancement, area:api, topic:dx, size:medium` + docs follow-up.

#### F4. No error contract: callers guess catch-tuples (30 occurrences)

The API surface raises a mix of typed hassette exceptions and bare stdlib ones (`api/methods.md` documents `ValueError` and `RuntimeError` raises); almost nothing is exported from the top-level package (only the two warning classes); there is no error-handling concept page (what happens when a handler raises, what `api.*` can raise, what's retryable). Corpus result: a guessed `(OSError, TimeoutError, ValueError, RuntimeError)` tuple repeated ~30 times, growing per-app to 7 exception types, plus a comment documenting the discovery that some `HassetteError` subclasses escape the stdlib catch.

**Fix shape:** decide and document the raise-contract per API method; export the exception hierarchy (or bless `hassette.exceptions` in docs); consider a curated `RECOVERABLE_HA_ERRORS` tuple; add an error-handling concept page (handler exceptions are already isolated + telemetered — say so). `type:enhancement, area:api, topic:errors, topic:dx, size:medium`.

#### F5. Every shutdown ends with spurious ERRORs (extends #1810)

Every orderly SIGTERM shutdown — healthy runs included — logs two ERROR-level `RuntimeError: TaskBucket(Hassette.SchedulerService.TaskBucket) is sealed and rejected new work: scheduler:remove_jobs`, plus a stray "WebSocket connection reset by peer" ERROR. The last thing an operator ever sees is a scary error. #1810 (run 1) covers the sealed-bucket family but claims "normal teardown ordering avoids this — the reachable window today is force-terminal"; this evidence shows the ordinary path hits it on every out-of-box run. **Action: comment on #1810 extending scope + raising priority, not a new issue.** Repro: quickstart config, `kill -TERM`, read the tail.

#### F6. Quickstart promises output that cannot happen; connection success is never logged

`docs/pages/getting-started/snippets/run_output.txt` shows `INFO hassette ... ─ Connected to Home Assistant`. That string exists nowhere in `src/` — the only connect log is `logger.debug("Connected to WebSocket at %s")` (`websocket_service.py:416`), invisible at defaults. The newcomer's #1 question — "did my token work?" — is answered by silence; blind persona P1 independently flagged the mismatch. Related first-run noise: ~25 lines of framework internals on the console (dependency-graph dump, 11× "Waiting for dependencies", manifest JSON, interleaved bare-uvicorn lines) burying the "Hello from Hassette!" payoff, and a WARNING that fires on the *default* config (0.0.0.0 bind + no trusted_proxies — if the default warns, the default or the warning is wrong; a token-login UI on 0.0.0.0 by default also deserves a deliberate decision).

**Fix shape:** promote connection-established (and lost/re-established) to INFO — it's a state transition per the project's own logging rules; quiet the startup internals to DEBUG in console mode; reconcile `run_output.txt` with reality; decide loopback-vs-0.0.0.0 default. `type:bug, area:websocket, size:small` + `type:enhancement, area:core, topic:dx`.

#### F7. Quickstart never mentions the dashboard; web-API auth is undiscoverable from where it bites

The web UI — the flagship differentiator — appears in the quickstart only as a buried log line ("Open http://127.0.0.1:8126 to log in"). P1's single biggest time sink: `hassette status` returning `Error 401: Not authenticated` with no pointer to the separate web-API-token concept; the 401 text doesn't match the docs' own documented message, and `cli/configuration.md` isn't linked from the quickstart. Also verified: against a *wrong*-credential loopback target the CLI silently attaches the local instance's `.web_api_token` (multi-instance trap) and the 401 names neither the credential source used nor a remedy — the docs explicitly promise "a 401 naming the remedy."

**Fix shape:** quickstart section for the dashboard; 401 message that names the credential source tried + the fix; link the auth page from the error. `type:bug, area:cli, topic:dx, size:small` + docs.

#### F8. CLI under-selects from its own excellent telemetry

- `hassette app` shows `Invoc/1h` (listener invocations only) and **no health/error column**, while the same backend reports `health_status: "critical"`, `error_rate: 78.7`, `total_job_errors: 122` for a demo app. An app failing 109×/hour renders as "running, 1 invocation."
- The data *is* reachable via `hassette app health <key>` — but nothing in the listing hints that drill-down exists, and it prints `error_rate 78.83597883597884` (unformatted).
- `--app <nonexistent-key>` returns the same bare `No results.` as a real-but-quiet app — no existence validation, no "known apps" hint, no cross-hint ("0 listeners; this app has 1 scheduled job — try `hassette job`").

**Fix shape:** Health + Err columns in `hassette app`; validate `--app` keys; disambiguate empty results; format percentages. `type:enhancement, area:cli, size:small` (bundle).

#### F9. App-init failures are logged three times

One `ValueError` in `on_initialize` produces three stacked ERROR tracebacks (hook runner, init coordinator, `AppLifecycleService`). The behavior is otherwise right — framework stays up, user file:line named. Log once at the layer that owns the decision; DEBUG elsewhere. `type:bug, area:core, topic:errors, size:small`.

#### F10. Registration accepts entity IDs that cannot match

"Hassette does not error on a non-existent entity ID. The handler simply never fires" — a documented checklist item (troubleshooting.md #1) that could be a runtime signal instead: the state proxy holds the full entity list at registration time. Warn (log + listener telemetry flag + dashboard badge) when a literal, non-pattern entity ID matches nothing, tolerant of entities created later. Same family as F2 — silent-by-design, observable-in-principle. `type:enhancement, area:bus, topic:dx, size:medium`.

### LOW / DISCUSS

- **D1. `name=` ceremony on every registration.** PR #922 made `name=` mandatory for DB-upsert identity; no recorded consideration of auto-deriving (`ClassName.handler` + topic — equally stable), requiring explicit names only on `DuplicateListenerError` collision. Would erase the most-typed parameter in the API for the majority case. Worth a design discussion, not a defect.
- **D2. P/C/D/A conceptual load vs observed usage.** The corpus uses P×1, C×2, and none of the richer D variants; filtering is done imperatively in handler bodies. The layered design is principled, but docs could bless the built-in kwargs (`changed_to`/`changed_from`/`debounce`) as the 90% path and position P/C as advanced composition. Docs-emphasis change, not API change.
- **D3. Typed-state distrust (contracts mostly verified, distrust is behavioral).** 10+ redundant `if not new_state:` guards under `D.StateNew`, 12× defensive `(KeyError, AttributeError)` around `states[...]`, `getattr()` on typed `ClimateState` attributes 4×, isinstance + type-ignore for light-group member lists. Verified: the `D.StateNew` raises-contract holds (`ensure_present`, dependencies.py:85 — the guards are dead code), and group membership is typed (`AttributesBase.entity_id: list[str] | None`, base.py:47) with an `is_group` property (base.py:122) the corpus never found — though the base model's own pyright-ignores there suggest the typing is awkward even internally. Remaining unknown: the ClimateState `getattr` pattern. Fix shape: a docs statement strong enough to let authors delete these guards + a look at the group-entity ergonomics; investigate the climate attrs case.
- **D4. Stale event-entity replays.** The corpus hand-rolls an `event_age_seconds` guard (~18 lines per button app) against HA-restart replays. Note: a generic `max_event_age=` would NOT fix this — replays carry a fresh `time_fired`; the staleness signal is the event entity's ISO state value. Fix shape is an `EventState`-aware freshness predicate (e.g. `P.EventEntityFresh(max_age=10)`). Small enhancement.
- **D5. `call_service` swallows the most natural wrong call.** `**data` means a bare `entity_id=` kwarg lands in service data, where HA happens to tolerate it — the wrong form works, so the `target=` contract is unlearnable (the corpus uses both, and its CLAUDE.md declares `target=` a MUST without knowing why). Consider detecting `entity_id` in `**data` and either promoting it to `target` or warning.
- **D6. No restart/backoff primitive for app background loops.** `task_bucket.spawn()` exists, is documented, and logs crashes (ERROR) — but a crashed loop stays dead, so the corpus hand-rolled ~50 lines of supervision (bedtime) and ~60 lines of init retry (laundry) while the framework keeps `restart_spec` internal-only. Discuss exposing a minimal supervised-loop helper. (The corpus's "asyncio swallows exceptions" complaint is a discoverability miss — spawn already observes them.)
- **D7. Raw repr leak:** job telemetry's `predicate_description` renders `<bound method PredicateDemo.is_motion_detected of <PredicateDemo ...>>` beside a polished `human_description`. Cosmetic.
- **D8. Log-table tracebacks are framework-heavy** — user code is 2 of 10 frames in a typical handler error; consider folding framework frames in CLI/dashboard rendering.
- **D9. Docs nits from personas:** first-automation's `light.porch` not flagged as substitute-me (P1); seed-vs-simulate ordering rule split across two testing pages; `freeze_time`'s xdist warning lives on a different page from `freeze_time` itself (P2).

### META — fixes outrun the channel that announces them

Per-instance cache keys (the corpus still namespaces manually, 8×), forgotten-await detection (corpus CLAUDE.md still calls it a silent footgun), and the mature test harness (corpus tests still hand-roll `App.__new__` + AsyncMocks + 55 sleeps, with its own comment admitting "AsyncMock silently accepts any call shape") all solved pains the one known power user still works around — and one corpus doc claim is now factually wrong ("state reads are synchronous"). Consider an "for app authors: you can now delete X" section per release in `operating/upgrading.md`, fed from changelog entries. `type:documentation, topic:dx, size:small` (process, mostly).

---

## Strengths (genuine, keep doing these)

- **The testing story is excellent now.** A blind persona reached 3/3 passing tests — including the hard cancel-pending-job-on-retrigger shape — in 2 runs, with `freeze_time`/`advance_time`/`trigger_due_jobs` working first try, named `DrainTimeout`/`DrainError`, `assert_call_count`, and the `hassette[test]` extra.
- **The newer exception classes are exemplary** — `ListenerNameRequiredError`/`DuplicateListenerError` print the fix with a code sample; structured attributes throughout; `FailedMessageError.code` for programmatic handling.
- **The troubleshooting page names the real traps** (entity typo, `changed_to=True`, attribute-only changes, forgotten await) — it matches what actually bites users.
- **CLI tables are good operator surfaces** — per-listener OK/Fail/Avg/Last, `registration_source` carrying the actual registration code in telemetry, `boot_issues` in status.
- **Failure isolation behaves right:** app crashes don't take the framework down; syntax errors leave it serving for fix-and-reload; missing-token and invalid-token messages are clear (redacted token, exact env vars named).
- **DI works as advertised** for the newcomer path — P1: "zero friction, exactly as documented."

## P3 — debugging persona (results, verified)

Setup: a blind persona was handed a running app with three seeded bugs matching the audit's silent-failure classes, instructed to debug from the observability surfaces first (CLI → dashboard → logs → docs), reading code only as a last resort.

| Seeded bug | Localized by | Attempts | Verdict on the surfaces |
|---|---|---|---|
| Entity-ID typo (`movment_backyard`) | CLI — `hassette listener --json` showed the wrong target string immediately | 1 | Excellent; called it "the single most useful command all session" |
| Forgotten `await` on registration | **Nothing.** CLI + dashboard showed only the *absence* of a listener; no warning, error, or boot issue anywhere. Fell back to reading code | 3 (exhausted) | Worst gap — see F11; independently corroborates it end-to-end |
| `.upper()` on a `bool` state value (DI type confusion) | CLI — `hassette log --app` full traceback, exact file:line; the dashboard's failing-handlers card surfaced it proactively too | 1 | Excellent |

All three fixed and verified live (0% error rate after). Verification notes on P3's claims: the forgotten-await silence is independently reproduced (F11 lab); the typo-diagnosis and traceback claims match its journal and screenshots. Two P3 claims carry caveats: its "loopback `.web_api_token` auto-fallback never worked" experience is consistent with the multi-instance token trap in F7 but may involve shared-data-dir contamination between audit instances, so it is folded into F7 rather than counted separately; and its "dashboard Reload served stale code" hit is at least partially a known limitation (CLAUDE.md documents stale-module reuse when reloading *failed* apps) — worth checking whether the running-app path has the same hole before filing.

P3's dashboard-specific findings, banked for run 3 (frontend): handler cards don't show the subscribed entity/target (would have solved the typo bug from the dashboard alone); the failing-handlers summary card is genuinely good (beat the CLI to bug 3); Reload-vs-restart semantics need surfacing in the UI.

## Issue slate — walked through with Jessica 2026-09-02, filed as #1815–#1834

| Finding | Disposition |
|---|---|
| F1 SIGINT silent hang | **#1815** (bug, high) |
| F11 warnings black hole | **#1816** (bug, high) |
| F2a listener filtered counter | **#1817** (enhancement) |
| F2b job-table Skipped column | **#1818** (bug) |
| F3 guard Api reads + sync/async docs matrix | **#1819** (enhancement; depends on #1816 for audibility) |
| F4 error contract | **#1820** (enhancement) |
| F5 sealed-bucket ERRORs every shutdown | **comment on #1810** (scope extension: reachable on the ordinary path, not just force-terminal) |
| F6 connect INFO log + quickstart output | **#1821** (bug) + **#1822** (startup noise + default-bind decision) |
| F7 401 message/docs + auth-resolution rethink | **#1823** (immediate fix) + **#1824** (design discussion, per Jessica's call to split) |
| F8 CLI display bundle | **#1825** (enhancement) |
| F9 triple-logged init failure | **#1826** (bug) |
| F10 unknown-entity registration warning | **#1827** (enhancement) |
| D4 event-entity freshness predicate | **#1828** (enhancement) |
| D5 call_service targeting contract | **#1829** (filed non-prescriptive per Jessica — surfaces the tension, doesn't pick promote-vs-warn) |
| D6 supervised background loops | **#1830** (design discussion) |
| D7 predicate_description repr | **#1831** (bug) |
| D8 traceback frame folding | **#1832** (enhancement; linked to #749) |
| D9 docs followability nits | **#1833** (documentation) |
| META upgrade-notes discipline | **#1834** (documentation) |
| D1 `name=` auto-derivation | **Dropped** — Jessica: keep explicit identity required |
| D2 P/C docs re-emphasis | **Dropped** — single Claude-written corpus too weak a signal |
| D3 typed-state distrust bundle | **Dropped** — legacy corpus behavior, not tracked |
