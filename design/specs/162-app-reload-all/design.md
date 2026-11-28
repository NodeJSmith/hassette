# Design: In-process reload-all for apps

**Date:** 2026-11-27
**Status:** built
**Mode:** sketch
**Issues:** #4498
**Prior art:** design/research/2026-11-27-helper-module-reload/research.md, design/specs/162-app-reload-all/peer-check.md

## Summary

An app reload re-imports only the app's own file (spec 161, `src/hassette/utils/app_utils.py` `load_module_record`). A change to a shared helper therefore takes effect only after a container restart. hautomate restarts on every deploy and so leaves no listeners for at least 16 s each time. On 2026-11-13 one of those restarts dropped a button press. This change adds **reload-all**. Before anything stops, it can refuse on an invalid `hassette.toml` or a syntax error in a module it's about to import (D7, D9, and D12 for how each trigger reports it). Otherwise it stops the apps it restarts (D1), evicts the app-code modules (D3), and starts them again, in D12's order. The HA websocket, state cache and process stay up throughout. It runs from three triggers:

- the web API
- the CLI
- a UI button

The file watcher also runs it, where file-watching reload is already allowed, when a helper changes. It follows the research brief's Option B with failure policy A1.

**Where each piece lives:**
- **What counts as app code.** One set of app roots, `app_roots(config)` (a function in `src/hassette/utils/app_modules.py`, taking the config): `apps.directory` plus every manifest's `app_dir`, and `HassetteConfig.get_watchable_files` consumes it for its app-directory entries (it still adds the config and env files itself), so the root list has one home. On top of it, one predicate, `is_app_code(path, roots)`, and one module set, `app_code_modules(roots)`, in a new leaf module `src/hassette/utils/app_modules.py` (no `core/` dependency), which also holds the precheck and D4's `ast` import reader. `app_utils.py` is already 780 lines against the 800-line `file-sizes` gate (re-challenge Finding 8). Eviction (D3), the precheck (D2) and the watcher trigger (D4) all use them (D3).
- **Eviction primitive.** `evict_apps_package(roots)` in `src/hassette/utils/app_modules.py`, removing each module through `app_utils.clear_app_module`. It evicts exactly `app_code_modules(roots)`. For each evicted module it removes the `sys.modules` entry, its `APP_MODULES` record (if any), its parent-package attribute and its cached bytecode. Because every removal goes through `clear_app_module`, `app_utils.py` stays the only code that removes app modules (spec 161 D1), and `app_utils.py` gains no lines against its size gate.
- **Precheck.** `precheck_apps_package(roots, enabled_app_files) -> SyntaxError | None` in `src/hassette/utils/app_modules.py`. It returns the first `SyntaxError` with its file and line, or `None`.
- **Triggers and refusals.** `WatcherTrigger` and `ManualReload` are frozen dataclasses in `src/hassette/core/app_lifecycle_common.py`. The refusal exceptions `ReloadConfigInvalidError` and `ReloadSyntaxError` go in `src/hassette/exceptions.py`; they are raised to the manual caller and mapped to the D7 and D9 problem codes in `web/routes/apps.py`. The busy case reuses the existing `action_in_progress` mapping.
- **Watcher-side classification.** Whether a changed path calls for a reload-all is decided in `reconcile_from_disk`'s `_plan_reload_all` (`src/hassette/core/app_lifecycle_changes.py`), not in the change detector, which stays a pure diff of manifests and paths. It uses `needs_reload_all` in `src/hassette/utils/app_modules.py`, which reads the loaded app-code modules' import statements with `ast` to tell whether another one imports a changed app module (D4). *(Amended by the ship-time challenge, Finding 2; see Build.)*
- **Restart set.** `AppRegistry.tracked_app_keys()` (`src/hassette/core/app_registry.py`): keys with any instance entry, live or FAILED (D1).
- **Orchestration.** One entry point, `reconcile_from_disk(trigger)` on `AppChangeReconcilerMixin` (`src/hassette/core/app_lifecycle_changes.py`), serves both the watcher (`handle_change_event` → `WatcherTrigger(paths)`; the reload-all is derived by D4's rule into a `ReloadAllPlan`) and the manual triggers (`AppHandler.reload_all(wait=...)` → `ManualReload(wait)`). The order is D12's. It returns per-app outcomes. `reconcile_from_disk` owns the stop → evict → create sequencing, and `_restart_apps_unlocked` splits at the eviction point into its existing stop and create halves. The previous config's app roots are captured before adoption (step 6), because eviction (step 8) needs the old and new roots. `refresh_config` splits into build-candidate and adopt, and `apply_changes` and `_restart_apps_unlocked` return or raise what they now only log.
- **Web API.** `POST /api/apps/reload` in `src/hassette/web/routes/apps.py`. New wire models (`ReloadAllResponse`, `AppReloadResult`) go in `wire/src/hassette_wire/apps.py`, and two new problem codes, `reload_config_invalid` (D7) and `reload_syntax_error` (D9), both 409, go in `wire/src/hassette_wire/problems.py`.
- **Client and CLI.** A client method in `client/src/hassette_client/client.py`, the CLI command in `src/hassette/cli/commands/app.py`, and its POST helper in `src/hassette/cli/client.py`.
- **UI.** A button on the Apps page (`frontend/src/pages/apps.tsx`), reusing `components/shared/action-buttons.tsx` conventions.
- **Docs.** `docs/pages/web-ui/manage-apps.md` ("What Reload Re-imports"), `docs/pages/cli/commands.md` (`app reload`), and the file-watcher/reload configuration docs. Regenerate frontend types after the wire changes (`uv run python scripts/export_schemas.py --types`). If the Apps page header is in a documented screenshot, regenerate it via `scripts/capture_screenshots.py` (`docs/screenshots.yml`), and attach PR screenshots (`.claude/rules/design-completeness.md`).

**Out of scope:**
- The precise dependency-closure reload (#4141, parked).
- Precheck or eviction on the existing single-app reload paths, which keep spec 161's own-file semantics.
- Concurrent stops and starts.
- Rolling back `sys.modules` on failure.
- A reload-all button in the HA integration (hass-hassette is another repo).
- Reloading modules outside the app roots (`apps.directory` and each manifest's `app_dir`), such as installed packages.

## Posture

- **Failure handling:** fail loudly, using policy A1. A syntax error refuses the whole reload, before anything stops. Any other import failure leaves the apps whose class failed to load in `FAILED` with the error shown. Apps whose modules imported start normally. No retries and no `sys.modules` rollback.
- **Compatibility:** internals may break freely (pre-v1). The web API change is additive (a new route, models and two problem codes), so `client_compat` passes without ignore entries. The single-app routes and `ActionResponse` don't change.
- **Scope:** the whole issue in one PR: web API, CLI, UI button, the watcher rule, and docs. #4141's closure stays out.
- **Rollout:** ships outright as a `feat:`, with no flag. The watcher rule fires only where file-watching reload is already allowed (`dev_mode` or `allow_reload_in_prod`, `src/hassette/core/app_handler.py:88`).
- **Hardening:** project defaults. One INFO summary line per reload-all (trigger, app count, outcome counts) plus the existing per-app lines. No new metrics. Restarts stay sequential: the measured gap is about 3–5.5 s (research brief, Open Questions).
- **Altitude:** build. One session builds it, and the ledger cites files.

## Decisions

### D1: Which apps does reload-all restart?

**Situation:** The issue says "restart every running app". The registry also holds keys whose instances are `FAILED`, and some autostart apps aren't running. The watcher's existing reimport path restarts a key when `should_auto_reconcile` is true (`src/hassette/core/app_lifecycle_service.py:233`): the key is in the registry, or it's a dormant autostart app. A fixed helper is exactly what should recover an app that failed on the broken version.

**Deciding factor:** recover apps that failed on the old code, without starting apps someone stopped.

| | A: `should_auto_reconcile` keys (registry + dormant autostart) | B: only keys with a live instance | C: every enabled app | D: AppDaemon parity (A, minus keys whose last import failed) | E: keys with any tracked instance entry (live or FAILED) |
|---|---|---|---|---|---|
| App FAILED on the old helper | Retried and recovers | Stays FAILED until a manual start | Retried | Retried if it failed at runtime; skipped if its import failed | Retried (a FAILED entry is kept) |
| Autostart app that isn't running | Started (as a container restart would) | Not started | Started | Started | Not started: a stopped app has no entry, so a manual stop stands |
| `autostart=false` app the user never started | Left alone | Left alone | Started (wrong) | Left alone | Left alone |
| Consistency | Same rule as the watcher's per-app reimport today | New rule | New rule | New rule | New rule; reads only the registry's existing entries |
| Peers | AppDaemon's `admin/app/reload` seeds the running apps, then starts every configured, non-disabled app not running and not `compile_error` (`app_management.py` `check_app_config_files`), so failed-at-runtime and stopped apps are retried | none found | pyscript.reload restarts every global context with no running filter | AppDaemon exactly; its `compile_error` skip fits a closure reload, where an unchanged file won't import differently | none found; AppDaemon's admin reload starts stopped apps |

Every app that isn't restarted loses its module record anyway (D3), so its next start imports the new generation.

**Recommendation:** E, because it recovers apps that failed on the broken helper, leaves a manual stop standing, and reads only state the registry already keeps.
**Pick A instead if** reload-all should start stopped autostart apps as a restart would. **Pick B instead if** FAILED apps should wait for a manual start too.
**Reversibility:** easy
**Ratified:** Chose E for both the manual and the watcher trigger: restart every app key with any tracked instance entry, live or FAILED (`AppRegistry` keeps a FAILED entry with its error and stores no entry for a stopped instance, `app_registry.py:44-66`), and never start a key without one. Rejected: `should_auto_reconcile`, live-only, every-enabled, and AppDaemon parity. This recovers apps that failed on the broken helper while a manual stop stands, with no new state. It accepts that an autostart app with no entry, which after bootstrap means someone stopped it, waits for a manual start; its record is evicted, so that start imports fresh.

*Amended at ship time (Finding 10): the restart set also takes every key whose lock is busy, so a start under way finishes first and restarts on the new code; see Build.*

### D2: Which files does the `compile()` precheck check?

**Situation:** A1 refuses the reload on a syntax error "in a changed file". Only app modules have a content hash (`AppModuleRecord.content_hash`, spec 161). Helpers have no record, so "changed" isn't known for them without new bookkeeping. `compile()` on a source file costs well under a millisecond for a typical module.

**Deciding factor:** catch the typo that's about to be imported, without new bookkeeping and without blocking on files nobody imports.

| | A: every `.py` under the app roots | B: files of app-code modules now in `sys.modules`, plus every enabled app's file | C: only files whose hash changed since import |
|---|---|---|---|
| Catches a typo in a loaded helper | Yes | Yes | Yes, but needs a hash on every helper (new bookkeeping) |
| A broken scratch file or test file nobody imports | Blocks every reload-all | Ignored | Ignored |
| A new helper with a typo that an edited app now imports | Caught | Not caught: the import fails and that app goes FAILED (A1's fallback) | Not caught (no prior record) |
| Cost on 60 apps / ~100 files | Every file | Only loaded files | Smallest, plus the bookkeeping |
| Peers | AppDaemon compiles nothing ahead; a failed import marks dependents `compile_error` | same | same |

**Recommendation:** B, because it checks exactly what the reload is about to re-import and needs no new state. A new broken file falls through to A1's FAILED path, which is the posture anyway. The loaded set is `app_code_modules(roots)` (D3). A loaded module whose file no longer exists, such as a helper a pull deleted, is skipped by the precheck and still evicted, so its importers fail at import and go FAILED (A1), rather than the reload being refused.
**Pick A instead if** you'd rather refuse on any broken `.py` in the apps dir, accepting that a stray file can block deploys.
**Reversibility:** easy
**Ratified:** Chose the files of `app_code_modules(roots)` (D3) plus every enabled app's file over every `.py` or only hash-changed files, to check what the reload will re-import with no new bookkeeping. It accepts that a brand-new helper with a typo shows up as the importing app's FAILED import rather than a refusal. A loaded module whose file no longer exists is skipped by the precheck and still evicted, so deleting a helper never refuses the reload and its remaining importers go FAILED (A1).

### D3: Which modules count as app code for eviction?

**Situation:** Apps import helpers through the synthesized package (`hautomate.notify`). But `_ensure_on_sys_path(app_dir)` also makes `import notify` work under a bare name, and hautomate's container pip-installs a second copy of `hautomate` into site-packages. A name-prefix rule would miss the bare names and could hit a site-packages copy.

**Deciding factor:** evict exactly the modules whose code comes from the app roots.

**Recommendation:** match by file, bounded by `is_app_code` (see Ratified). Evict every `sys.modules` entry whose `__file__` passes it, whatever its name. Keep the synthesized namespace package entry itself, but delete each evicted submodule's attribute from its parent package. The research brief recommends keying on file path, not name.
**Pick a name-prefix rule instead if** you want to stop supporting bare-name imports of helpers.
**Reversibility:** easy
**Ratified:** Chose matching by resolved `__file__` inside the app roots over a package-name prefix, so bare-name imports are evicted, accepting a walk over `sys.modules` on each reload-all. It uses one predicate shared by eviction, the precheck (D2) and the watcher trigger (D4). `is_app_code(path, roots)` is true when the resolved path is inside one of the app roots (`apps.directory` plus every manifest's `app_dir`; the loader imports from and the watcher watches every one), no part of the path relative to that root is in `APP_SCAN_EXCLUDE_DIRS` (`app_utils.py:46`), and the path is not under `sys.prefix`, `sys.base_prefix` or hassette's own package directory. `app_code_modules(roots)` is every `sys.modules` entry whose `__file__` passes it. An apps directory that contains a virtualenv (`examples/hassette.toml` sets `directory = "."`) therefore never evicts installed packages. Also accepted (sketch challenge, Finding 18): evict-and-reimport reruns every app-code module's top level, so module-scope side effects (handlers, threads, sessions, `atexit` hooks, `BaseState` registrations) repeat on each reload-all and the old generation's copies aren't released; the Docs step notes it on "What Reload Re-imports". Also accepted (re-challenge, Findings 10 and 11): no `importlib.invalidate_caches()` call, so on a coarse-mtime filesystem a helper created within one directory-mtime tick of the last import can be missed and its importers go FAILED until the next reload-all; and namespace sub-packages with no `__file__` aren't evicted, so a deleted helper directory leaves an empty package object in `sys.modules` until restart.

### D4: Which watcher changes trigger reload-all?

**Situation:** Today a changed `.py` path that isn't a configured app's `full_path` is dropped with "changed but no app changes detected" (`src/hassette/core/app_lifecycle_changes.py:343-344`). A changed app file reimports only that app. But some app modules are also imported by other apps (hautomate: `car_climate` imports `thermoscura`, `vacuum_health` imports `vacuum_alert`), so a per-app reimport leaves the importer on the old generation. 43 of 79 recent hautomate commits touched one app's own file only, so turning every edit into a reload-all costs the dev loop.

**Deciding factor:** every app ends up on one generation (the issue's acceptance criterion 4), without restarting everything on a single-app edit.

| | A: any changed `.py` that isn't an app's own file | B: A, plus an app file that another loaded apps-dir module imports | C: any `.py` change | B′: as B, but "imports" read from `ast` import statements |
|---|---|---|---|---|
| Helper edit | reload-all | reload-all | reload-all | reload-all |
| Lone app-file edit | per-app reimport (today) | per-app reimport (today) | reload-all, restarting every app | per-app reimport (today) |
| `thermoscura` edit | per-app; `car_climate` keeps the old code | reload-all | reload-all | reload-all |
| `vacuum_alert` edit (`vacuum_health` imports `str` constants) | per-app; `vacuum_health` keeps old values | per-app: the globals scan can't see a `str`'s origin | reload-all | reload-all |
| Mechanism | path check | path check + a scan of loaded apps-dir modules' globals for the module or an object whose `__module__` is it | none | path check + an `ast` read of loaded app-code modules' `import`/`from` nodes, relative imports resolved |
| Miss | importers of app modules | function-level or dynamic imports of an app module (documented limit) | none | dynamic imports only |
| Peers | — | AppDaemon reloads the dependents of an app file too (AST graph) | Streamlit unloads every watched module on any change | AppDaemon 4.5's AST graph; research brief |

**Recommendation:** B′, because it closes both mixed-generation cases hautomate already has (B's globals scan misses `vacuum_health`'s `str` constants), keeps lone app edits cheap, and runs only on a watcher event.
**Pick B instead if** you'd rather inspect globals than parse source, accepting the plain-value miss. **Pick A instead if** you'd rather carry no import analysis and accept documenting app-imports-app as needing a manual reload-all. **Pick C instead if** simplicity matters more than the dev-loop restarts.
**Reversibility:** easy
**Ratified:** Chose reload-all for any changed apps-dir `.py` that isn't an app's own file, plus an app file another loaded app-code module imports, read from that module's `ast` `import`/`from` nodes with relative imports resolved (a globals scan would miss `vacuum_health`'s `str`-constant imports), over a path-only rule or reloading on every change, so app-imports-app stays on one generation while lone app edits stay per-app, accepting a documented miss for dynamic imports (`importlib.import_module`) of app modules. "Apps-dir `.py`" means a changed path passing `is_app_code` (D3). Also accepted: an event that carries only a created or deleted directory (`collapse_changed_paths` drops children of a reported directory) triggers nothing until the next relevant edit or a manual reload-all.

### D5: How does a `git pull` burst become one reload against the settled tree?

**Situation:** The watcher (`src/hassette/core/file_watcher.py`) groups changes and emits once a 500 ms poll finds no new changed path, grouping for at most 3 s from the first change. A typical pull writes all its files within well under 500 ms of each other, so it gives one event. A pull that is split across two events would reload against a half-written tree. The precheck catches a syntax error, but not an `ImportError` caused by a mismatch between two files. `_change_event_lock` serializes handling, so the second event's reload-all runs after the first and fixes it.

**Deciding factor:** no new mechanism unless the existing grouping demonstrably fails.

| | A: the existing grouping; a split pull self-heals on the next event | B: add a settle wait (no apps-dir `.py` mtime change for 1 s) before the precheck | C: raise the grouping cap |
|---|---|---|---|
| Typical sub-second pull | one reload | one reload | one reload |
| A pull longer than 3 s | Two reloads; apps briefly FAILED between them | One reload, after the wait | One reload if within the new cap |
| Added latency on every save | none | ≥1 s | none |
| New code | none | a polling loop | a constant |
| Peers | Every peer found uses a fixed window or poll: pyscript drains events 50 ms apart up to 500 ms; watchfiles defaults to a 50 ms quiet step and a 1.6 s cap; AppDaemon and Django poll every 1 s | none found that checks mtime stability | — |

**Recommendation:** A, because the grouping already waits for a quiet poll, and a pull long enough to split heals itself within seconds. A test pins that a burst inside the window produces one reload-all.
**Pick B instead if** you've seen deploys take multiple seconds to write files.
**Reversibility:** easy
**Ratified:** Chose the existing watcher grouping over a settle wait or a larger cap, to add no new mechanism, accepting that a pull longer than the 3 s cap reloads twice and leaves apps briefly FAILED until the second reload heals them.

### D6: What does the manual route do when another app action is running?

**Situation:** The single-app routes answer 409 `action_in_progress` at once if any action holds or is queued for that key (`_require_no_action_in_progress`, `src/hassette/web/routes/apps.py:134`, spec 139). Reload-all needs the restart and orphan keys' locks (D12 step 5), taken in sorted order, after `_change_event_lock`. The watcher path already waits for locks (`apply_changes`).

**Deciding factor:** consistent, prompt answers from the API.

| | A: 409 `action_in_progress` if any key is busy, then take all locks | B: wait for every lock | C: caller chooses: `?wait=true` waits, default answers 409 |
|---|---|---|---|
| Matches single-app routes | Yes | No | Yes by default |
| Request hangs behind a slow `on_shutdown` | No | Yes, possibly a long time | Only when the caller asks to wait |
| Deploy script behavior | Retries on 409 | Blocks | Picks: `hassette app reload --all --wait` blocks, plain fails fast |
| Surface | none | none | One query parameter plus a CLI flag; the client method takes `wait: bool = False` |
| Peers | none found that rejects | AppDaemon serializes reloads on `check_updates_lock` (a second call waits, then runs its own pass); HA service calls block | kubectl/Helm offer a caller-chosen `--wait` (semantics not confirmed) |

**Recommendation:** C (the user's suggestion), because each caller knows whether it would rather block or retry, and the default keeps the "busy means 409" contract.
**Pick A instead if** you want no new parameter. **Pick B instead if** deploy scripts should never have to retry.
**Reversibility:** easy
**Ratified:** Chose a caller-chosen `wait` query parameter (default false answers 409 `action_in_progress` naming the busy key, or saying another reload is running when `_change_event_lock` is held; true waits for every lock in the busy set, D12 step 5), with a matching CLI `--wait` and client argument, over always-409 or always-wait, so deploy scripts can block while interactive callers fail fast. Accepted: a waiting request has no server-side bound, so only the client's HTTP timeout limits it. Also accepted (sketch challenge, Finding 17): while a `wait=true` request waits, it holds `_change_event_lock` and the keys already taken, so watcher events queue and single-app actions on those keys answer 409 until the wait ends.

*Amended at ship time (Finding 10): a start or reload of one app answers 409 `action_in_progress` while a reload runs; see Build.*

### D7: Does a manual reload-all also re-read the config?

**Situation:** The single-app reload doesn't re-read `hassette.toml`. The watcher path always does (`refresh_config`), and then applies orphans, new apps and config diffs. A deploy that changes both code and `hassette.toml` on an install without file-watching reload would, under "code only", pick up the code but not the config. A container restart, the thing this replaces, picks up both.

**Deciding factor:** reload-all can stand in for a container restart.

| | A: code only | B: re-read config, then reload-all, through the shared entry point (D12) |
|---|---|---|
| Deploy changing code + toml, watcher off | Config change missed | Both applied |
| Invalid toml | Irrelevant | Refuses the whole reload-all before stopping anything (409 `reload_config_invalid` / ERROR log), as HA's `reload_all` does |
| Removed / added apps | Ignored | Stopped / started, as the watcher does |
| Code shared with watcher path | Separate entry | One path, under `_change_event_lock` |
| Peers | none found | AppDaemon re-reads `apps.yaml` on every update pass; pyscript.reload re-reads its YAML first; HA `reload_all` re-reads every domain's YAML, and first runs `async_check_ha_config_file`, raising on an invalid config before reloading anything (`components/homeassistant/services.py`) |

**Recommendation:** B, because "reload all" should leave the process as a restart would, and sharing the watcher's path means one code path to test.
**Pick A instead if** you want reload-all to mean code only and config changes to keep going through the watcher or a restart.
**Reversibility:** easy
**Ratified:** Chose re-reading the config through the shared entry point with `reload_all` forced (D12), under `_change_event_lock`, over a code-only reload, so a manual reload-all leaves the process as a restart would. An invalid config refuses the whole reload-all before anything stops, as HA's `reload_all` does: the manual route answers 409 with a new `reload_config_invalid` problem code naming the error, and the watcher path logs it at ERROR. This accepts one more problem code. A config-only edit with no reload-all keeps today's keep-old-config behavior. Under D6, a held `_change_event_lock` (a watcher reconcile in flight) counts as busy: 409 by default, wait when `wait=true`.

### D8: What status does `POST /api/apps/reload` answer when some apps fail?

**Situation:** Single-app actions map the worst outcome to the status (spec 140): any `failed` gives 500 `action_failed`, any `refused` gives 409 `needs_restart`, otherwise 200. Each error body carries `ProblemDetail.outcomes`, a flat list of `InstanceOutcome`, which can't hold several apps. In a batch of 60, one failing app is routine under A1.

**Deciding factor:** a caller can tell success from partial failure without losing the per-app detail.

| | A: worst-outcome status, with a new `ProblemDetail.app_outcomes` field for per-app detail | B: 200 whenever the reload ran; `ReloadAllResponse` lists each app's outcomes plus counts |
|---|---|---|
| Consistency with spec 140 | Same mapping | Differs: a batch result, not an action verdict |
| `curl -f` / script detects partial failure | From the status | From `counts.failed > 0` |
| Wire change | A new `ProblemDetail` field, plus the response model | The response model only |
| Client / CLI handling | Parse two shapes | One shape; the CLI exits 1 when anything failed |
| Peers | HA `reload_all` raises on the first domain failure (no per-item results); no API found that puts per-item results in an error body | Elasticsearch `_bulk` answers 200 with `errors: true` and per-item status (it declined 207 as WebDAV-only, elastic/elasticsearch#60442); AppDaemon answers 200 and logs |

Under either option, a precheck refusal and a busy key (D6) are problem responses, because nothing ran.

**Recommendation:** B, because batch APIs that report per-item results (Elasticsearch `_bulk`) put them in a 2xx body, and it keeps one response shape with no new `ProblemDetail` field.
**Pick A instead if** "non-2xx means something went wrong" across every app action matters more than one shape.
**Reversibility:** hard (a wire contract the released client will parse)
**Ratified:** Chose 200 whenever the reload ran, with `ReloadAllResponse` carrying each app's outcomes plus counts (`succeeded` / `failed` / `refused`, defined in D12 step 10), over spec 140's worst-outcome status with a new `ProblemDetail.app_outcomes`. This gives one response shape and matches batch APIs that report per-item results (Elasticsearch `_bulk`). It accepts that `curl -f` doesn't catch a partial failure, so callers read `counts.failed`, and the CLI exits 1 when it is non-zero. Refusals before anything ran (D6 busy, D7 invalid config, D9 syntax error, D12 pre-release) stay problem responses.

*Amended at ship time (Findings 6 and 7): each app result carries an `action`, and the CLI also exits 1 when an app was refused; see Build.*

### D9: How is a precheck refusal reported?

**Situation:** The issue requires a refusal that names the file and line, with every app left running. The watcher path has no caller to answer.

**Deciding factor:** the deploy operator sees exactly what to fix.

**Recommendation:** a new problem code, `reload_syntax_error` (409), whose `detail` reads `<path>:<line>: <msg>`, where `<path>` is relative to the app root that contains the file (D3), with no structured field yet. The watcher path logs the same text at ERROR, and nothing is stopped.
**Pick a structured `ProblemDetail.syntax_error` (`file`, `line`) instead if** a client will link to the location soon (adding it later is additive).
**Reversibility:** hard (wire)
**Ratified:** Chose a 409 `reload_syntax_error` problem whose `detail` reads `<path>:<line>: <msg>`, with `<path>` relative to the app root that contains the file (D3), and no structured field, over adding `ProblemDetail.syntax_error` or using absolute paths. There is no consumer to jump to the location yet, adding an optional field later is additive while removing one breaks the released client, and root-relative paths stay short in toasts and logs. It accepts that a client wanting the location parses `detail`, and that same-named files in two roots read alike. The watcher path logs the same text at ERROR and stops nothing.

### D10: What is the CLI shape?

**Situation:** `hassette app reload <key> [instance] [--yes]` reloads one app and asks for confirmation (`ACTIONS_REQUIRING_CONFIRMATION`, `src/hassette/cli/commands/app.py:40`). The issue suggests `--all`.

**Deciding factor:** discoverable next to the single-app reload, and hard to misuse.

| | A: `hassette app reload --all` (key optional; `--all` with a key or instance is a usage error) | B: `hassette app reload-all` |
|---|---|---|
| Discoverability | In `app reload --help` | Separate command in the `app` list |
| Argument rules | Mutual exclusion to enforce | None |
| Confirmation | The same prompt as reload, `--yes` to skip, required in `--json` mode | same |
| Peers | kubectl declined an `--all` flag (kubernetes/kubectl#1751) and uses "no name = all"; pm2 and supervisorctl use a positional `all` keyword | HA exposes `reload_all` as its own service |

**Recommendation:** A, because it's where a user looking to reload goes, and the issue names it. Usage errors: `--all` with a key or instance, neither a key nor `--all`, and `--wait` without `--all` (single-app routes have no `wait`). It confirms like reload and requires `--yes` in `--json` mode. Because the CLI's default request timeout is 10 s (`DEFAULT_TIMEOUT`, `src/hassette/cli/client.py:29`), `--all` requests use no read timeout under `--wait` and a 120 s one without it, so a timeout on a started reload is unlikely: under `--wait` it can't happen, and without it only a reload slower than 120 s hits it.
**Pick B instead if** you'd rather avoid the optional-positional-plus-flag rules.
**Reversibility:** easy (CLI is pre-v1)
**Ratified:** Chose `hassette app reload --all [--wait] [--yes]` over a separate `reload-all` command, so it sits where users look for reload. It accepts four usage errors: `--all` with a key, `--all` with an instance, neither a key nor `--all`, and `--wait` without `--all`. It confirms like reload and requires `--yes` in `--json` mode. An `--all` request uses no read timeout under `--wait` and 120 s without it, so a timeout on a started reload can only happen without `--wait`, on a reload slower than 120 s; connect errors still fail fast. Also accepted (sketch challenge, Finding 20): the usage-error rules that come with an optional key.

### D11: Where does the UI expose it?

**Situation:** The acceptance criteria require the action in the UI. The Apps page (`frontend/src/pages/apps.tsx`) lists every app. The app detail page is per-app, where reload-all doesn't belong.

**Deciding factor:** findable where you look at all apps, and hard to hit by accident.

**Recommendation:** add a "Reload all" button in the Apps page header, behind a confirm dialog. When it finishes, a toast shows the `succeeded`, `failed` and `refused` counts and names the failed apps. A refusal toasts its problem `detail` verbatim (for a syntax error, `file:line: msg`).
**Pick a menu item instead of a button if** the header is crowded.
**Reversibility:** easy
**Ratified:** Chose a "Reload all" button in the Apps page header behind a confirm dialog, with a result toast (counts, failed app names, a refusal's `file:line`, or the busy key), over an overflow-menu item, so it's findable where all apps are listed; the UI never sends `wait=true`.

### D12: How does a manual caller enter the reconcile pipeline, and in what order?

**Situation:** The watcher's pipeline (`handle_change_event` → `apply_changes` → `_restart_apps_unlocked`) serves a caller that never waits for an answer. It returns `None`, only logs per-app outcomes (`app_lifecycle_changes.py:231`), defers silently before bootstrap release (`:346-364`), keeps the old config on an invalid toml without raising (`:379-383`), and awaits inside `refresh_config` before the key locks (`:387-388`). The manual route (D6–D9) needs a result, refusals that arrive before anything stops, and an atomic busy answer. Added by the sketch challenge (its Finding 1, a convergence of Findings 4, 7, 8, 9 and 10).

**Deciding factor:** give the manual caller its result, its refusals and an atomic busy answer, deciding them once rather than as five patches.

| | A: one entry point with a fixed order (below) | B: patch each property separately on the drafted pipeline |
|---|---|---|
| Code paths | One, for watcher and manual | One pipeline plus a separate orchestrator |
| Outcomes reach the route | Returned by `_restart_apps_unlocked` | Needs its own fix |
| Pre-release manual call | 409 `bootstrap_not_released` | Silent deferral unless patched |
| Busy check vs awaits | `_change_event_lock` tested and taken first; each key lock tested and taken in one synchronous pass | Separated by awaits unless patched |
| Old instances lazily importing during shutdown | Not possible for instances that stopped cleanly: eviction follows the last stop, orphans included | Possible if eviction precedes the stops |
| Peers | AppDaemon sends admin reload and file-change pass through one `check_app_updates(mode=...)`, serialized on one lock (peer-check.md) | — |

The entry point takes a trigger value, not flags: `WatcherTrigger(paths)` or `ManualReload(wait)`. The trigger decides how refusals are delivered (raised to a manual caller, logged for the watcher) and how busy is handled (a manual call follows `wait`, the watcher always waits). `reload_all` is derived inside, never passed in.

The order:
0. Take `_change_event_lock`. If it's held, a manual `wait=false` call answers 409 `action_in_progress` at once (D6, D7). Every other call waits. Every later step runs under it.
1. Admission. Before bootstrap release, a manual call raises `AppBootstrapNotReleasedError` (the existing 409 `bootstrap_not_released`) and runs nothing. A watcher event keeps today's deferral.
2. Build a candidate config without committing anything. `refresh_config` splits into build and adopt, using the seam `HassetteConfig.reload()` already has between validating a candidate and swapping it in (`config.py:475-489`). The candidate also carries its resolved `only_apps` blocked set and its app roots (D3), computed without committing either.
3. If the candidate is invalid, a manual call raises `reload_config_invalid` (D7) and runs nothing. A watcher event logs it at ERROR and continues with the current config standing in for the candidate, with no reload-all (the refusal covers only the reload-all part).
4. Detect changes against the candidate (or the current config, per step 3), producing the `ChangeSet` with `reload_all`. A manual trigger forces `reload_all`. A watcher trigger takes it from D4's rule, classifying each path against that config's manifests, unless step 3 refused: then `reload_all` is false, and a helper-only edit does nothing beyond the ERROR log. When `reload_all` is set, the syntax precheck runs over the candidate's roots (D2, D9). A failure raises `reload_syntax_error` to a manual caller, which runs nothing. For a watcher event it is logged at ERROR, `reload_all` is cleared, and the event continues as a non-reload-all reconcile: the changed app files' own reimports, config diffs, orphans and new apps all still run, so an app whose own file has the typo goes FAILED as it does today. This matches step 3's rule that a watcher refusal covers only the reload-all part.
5. Build the key sets:
   - **Restarts:** the D1 set (keys with a tracked entry) when `reload_all` is set, together with the diff's reimport and reload keys. Keep only keys that are enabled in the candidate, aren't in the candidate's blocked set (step 2), and aren't orphans. A key in both sources restarts once, as a full reimport.
   - **Orphans:** stopped and not recreated. These are keys the candidate removes, disables or `--app`-excludes; the detector already treats disabling as removal (`app_change_detector.py:177-185`), so an app disabled in the candidate is an orphan, never a restart.
   - **New apps:** started if autostart, as `apply_changes` does today.

   Restarts, orphans and new apps are disjoint. The busy set is the restart and orphan keys; new-app keys are locked later by their own `start_app`. Take the locks of every restart and orphan key in sorted order, each one exactly once, testing `busy` in the same synchronous pass as each take with no await between test and take. Under `wait=false`, the first busy key releases the locks already taken and answers 409 `action_in_progress` naming it. Under `wait=true`, it waits (D6).
6. Adopt the candidate: swap `hassette.config`, set the registry's manifests, resolve `only_apps`, and persist the manifests to the DB. This happens only once every lock is held, so a refusal never leaves the config, the registry and the DB describing a config that isn't running.
7. Stop every orphan and every restart instance.
8. Evict (D3), only when `reload_all` is set, after the last stop and before the first create. Eviction uses the union of the candidate's and the previous config's roots, so modules loaded from an `app_dir` the same edit removed are evicted too.
9. Create every restart's replacements, then start the new apps (each `start_app` takes its own key's lock, as today).
10. Return the per-app outcomes and send `HASSETTE_EVENT_APP_LOAD_COMPLETED` so dashboards refetch. Restart outcomes come from `_restart_apps_unlocked`, orphan outcomes from their stops, and new-app outcomes from `start_app`. D8's `counts` has three wire fields, `succeeded`, `failed` and `refused`, and tallies every app in the result (restarts, orphans, new apps) by its worst instance result: `failed` if any instance failed, else `refused` if any was refused, else `succeeded`.

A watcher event without `reload_all` runs the same steps, skipping the precheck and eviction, which is today's per-app reimport and config reconcile. The "no app changes detected" gate (`app_lifecycle_changes.py:342`) and the `has_changes` gate in `_reconcile_changes` count `reload_all`, so a helper-only edit isn't dropped. The pre-release replay needs no reload-all: no app module is imported before release, so the first imports read the edited files.

**Recommendation:** A, because one ordered entry point gives the manual caller its result, its refusals before anything stops and an atomic 409, and lets no old instance (orphans included) import new code during shutdown. It accepts signature changes through `refresh_config`, `apply_changes` and `_restart_apps_unlocked`, plus a one-line reload-all log (sketch challenge Finding 19, accepted).
**Pick B instead if** you'd rather keep the drafted pipeline and fix each property in isolation.
**Reversibility:** easy (internal)
**Ratified:** Chose one `reconcile_from_disk(trigger)` entry point for watcher and manual triggers, in the order 0–10 above, over patching the drafted pipeline. The trigger value (`WatcherTrigger(paths)` or `ManualReload(wait)`) sets refusal delivery and busy handling. The config is built as a candidate, carrying its blocked set and roots, and validated first. `reload_all` is derived after detection. Every refusal (busy event lock, admission, invalid config, syntax precheck, busy key) comes before any commit. A watcher refusal cancels only the reload-all part, and the rest of the event runs as a normal reconcile. The candidate config, registry manifests and DB are adopted only once the restart and orphan locks are held. Restarts are filtered to enabled, unblocked, non-orphan keys so each lock is taken once. Stops precede eviction, which covers the old and new roots. Counts are `succeeded`/`failed`/`refused` across every app in the result. This gives the manual caller its result, its refusals and an atomic 409, a refused reload leaves nothing half-applied, and no cleanly stopped instance can import new code during shutdown. It accepts splitting `refresh_config` into build and adopt, signature changes through `apply_changes` and `_restart_apps_unlocked`, and a one-line reload-all log (sketch challenge Finding 19). Also accepted (re-challenge, Finding 9): an instance whose stop walked away, flagged needs-restart, can keep running old-generation work that imports new modules after eviction, until a process restart.

*Amended at ship time (Finding 2): `reload_all` is a `ReloadAllPlan` built after detection, not a `ChangeSet` field, and the gates check the plan; see Build.*

## Assumed

- **The manual reload has no settings gate.** The single-app reload routes are always available, and only the watcher subscription is gated on `dev_mode or allow_reload_in_prod`. "Gated by the same reload settings as a single-app reload" therefore means the manual reload-all is always available, with the same bootstrap-released and `--app` filter admission rules. Evidence: `src/hassette/web/routes/apps.py:438-445` (no gate); `src/hassette/core/app_handler.py:88`.
- **Restart is stop-all then start-all under sorted locks.** `_restart_apps_unlocked` stops every restart, then starts every one, and its caller holds every key's lock, taken in sorted order. Evidence: `src/hassette/core/app_lifecycle_changes.py:125-141, 215`. Reload-all keeps this shape and evicts between the two loops (D12).
- **After eviction, a start imports fresh.** No record is current, so `load_module_record` imports fresh even without `force_reload`. Stopped and disabled apps' next start also imports the new generation. Evidence: `src/hassette/utils/app_utils.py:394-399, 484-500` (`is_current` checks `sys.modules`).
- **The sibling-instance class rule doesn't trigger.** Every instance is stopped before any create, so `AppFactory.load_class`'s "running key's new instance gets its siblings' class" rule never applies during reload-all. Evidence: `src/hassette/core/app_factory.py`, spec 161 D3.
- **Refusal and admission carry over.** A flagged needs-restart instance is refused per instance (spec 139) and reported as `refused`. An `--app`-blocked key isn't restarted (D12 step 5). Evidence: `src/hassette/core/app_factory.py:81-83` (per-instance refusal).
- **Module identity holds.** Evict-and-reimport gives new code to every importer, and `isinstance` between objects of one generation holds. Instances created before eviction keep the old code until stopped. Evidence: `design/research/2026-11-27-helper-module-reload/research.md`, "Probe" paragraph under Feasibility Analysis.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- Refusal exceptions stay in `hassette.exceptions`, which is split to make room (user's choice): `HassetteError` moves to `exception_base.py` and the state-registry family to a new `state_errors.py`, both re-exported. `exceptions.py` was at 799 of the 800-line `file-sizes` gate, and `check_module_boundaries.py` forbids `web → core`, so the refusals couldn't go in `core/`.
- A third refusal, `ReloadBusyError` (its message names the busy app, or says another reload is running), maps to the existing `action_in_progress`: the D6 busy answer needs an exception to cross from the lifecycle to the route.
- `_change_event_lock` becomes an `AppKeyLock`, so a `wait=false` call sees a queued reconcile as busy, not only a held one (D6, D12 step 0).
- Eviction also drops every `APP_MODULES` record under the roots, not only those of modules in `sys.modules`: a failed import leaves a record with no module, and a plain load would reuse that failure, so an app that failed on the old helper couldn't recover (D1).
- Restart halves are `_stop_restarts_unlocked` / `_create_restarts_unlocked`; `_restart_apps_unlocked` is removed. `apply_changes` takes every orphan, reimport and reload lock first, then runs an `adopt` hook (commit candidate + fold unblocked apps), so the candidate is committed only once the locks are held (D12 step 6). Orphans stop through `_stop_orphan_unlocked` under that held lock instead of `stop_app`.
- `reconcile_from_disk` always returns a `ReconcileResult` (empty when nothing applied), so `AppHandler.reload_all` needs no None check.
- The wire counts are a nested `ReloadAllCounts` model (`counts.succeeded/failed/refused`, as D8 names them), and `AppReloadResult` also carries the app's worst `result`, which the UI toast and CLI summary use.
- The config-invalid refusal's message lists validation errors as `location: message` without the rejected values, since the message reaches the web API and a rejected value can be a secret. The watcher's ERROR log keeps the full error.
- A manual reload-all's INFO summary is logged by the web route (with the request source, as single-app actions are); the lifecycle logs the summary only for a watcher reload-all, so each reload-all logs one line.
- `app_code_modules` resolves and classifies each module directory once, then resolves only the files in app-code directories: resolving every loaded module's path took ~375 ms per watcher event and made hot-reload tests time out. (A raw-prefix prefilter did this first; the ship-time challenge replaced it, Findings 3 and 12.)
- The API schema goes to 8 (`API_SCHEMA_VERSION`, `MIN_API_SCHEMA_VERSION`), because the client's `reload_all` calls a route the latest release lacks (`.claude/rules/client-schema-floor.md`).
- The D1 restart set is recorded on `ReloadAllPlan.restart_keys` when the reload-all is planned, and `apply_changes` restarts a tracked key only if it still has an instance entry once its lock is held: a `wait=true` reload-all that waited behind a user's stop would otherwise restart the stopped app through the watcher's autostart rule.
- The queued pre-release reconciliation is read when a reconcile starts but cleared only when it commits (`_adopt`), so a manual refusal (syntax error, busy key) leaves it for bootstrap's replay (D12: every refusal before any commit).
- The validation-error summary (`location: message`, no rejected values) is one function, `validation_error_summary` in `utils/exception_utils.py`, used by the config-invalid refusal and the web API's `validation_failed` detail. The route's worst-outcome problem code reads `worst_result`, so the failed > refused > succeeded ranking has one home.
- `_change_event_lock` is renamed `_reconcile_lock`: it serializes every reconcile, watcher, manual and replay.

**Changes from the ship-time challenge** (2026-11-28; each one the user's pick, recorded in `review-log.jsonl`):
- The reload-all plan is one `ReloadAllPlan(restart_keys, evict_roots) | None` that `reconcile_from_disk` builds and `apply_changes` takes, replacing `ChangeSet.reload_all`, `ChangeSet.tracked_restarts`, the `evict_roots` keyword and the `ValueError` that kept them in step. `AppChangeDetector` is back to a pure diff; this amends the Summary's "Watcher-side classification" home (Finding 2).
- `needs_reload_all` and the syntax precheck run in a worker thread (`asyncio.to_thread`) over a `sys.modules` snapshot taken on the loop, and both reload-all summary lines carry `duration_s` (Finding 3). Eviction stays on the loop, since it mutates `sys.modules`.
- Each `AppReloadResult` carries a required `action` (`reload`, `stop`, `start`, the wire `AppAction` values), set from the bucket `apply_changes` handled; the CLI and the toast summarize by it. Core's result is `ReconcileResult` of per-app `AppResult(action, outcomes)`, with `ReconcileAction` mirroring the wire values as `OutcomeResult` mirrors `InstanceResult` (Findings 6 and 15). Amends D8's response shape.
- `hassette app reload --all` exits 1 when any app failed or was refused, matching the single-app commands and the UI (Finding 7). Amends D8's Ratified exit rule ("exits 1 when `counts.failed` is non-zero").
- A start or reload of one app answers 409 `action_in_progress` ("A reload is still running") while the reconcile lock is busy, checked with the route's other busy check so nothing suspends before the key lock; and the D1 restart set also takes every running-config key whose lock is busy, so a start already under way finishes first and is restarted on the new code (Finding 10). Amends D1 and D6.
- Eviction failures are logged at ERROR and the creates still run, so the response reports those apps as reloaded although some may be on modules the eviction missed; the log line is the signal (Finding 9); the precheck reports a `ValueError` from `compile` (a NUL byte before Python 3.12) as a syntax error, with a missing line shown as 0 (Finding 11). `ReloadBusyError.app_key` is gone (Finding 14).
- The UI says "Reload all refused" only for the four refusal codes; any other error says the reload may not have finished (Finding 5). `action_in_progress`'s descriptions cover a running reload (Finding 8).
- Docs say a reload-all applies the apps configuration, and other `hassette.toml` settings need a restart (Finding 1). The root fix, adopting only the app-facing config on every reload as AppDaemon and HA do, is #4524.
- The D5 burst test pins hassette's half: one watcher event carrying several helper paths reloads once. Grouping a burst of saves into that one event is watchfiles' debounce, which no hassette test drives.
