---
proposal: "Make an app reload pick up changed helper and sibling modules under the apps directory, reloading every running app that depends on them (#4141), together with separating idempotent import from forced reload (#1697)."
date: 2026-11-27
status: Draft
flexibility: Exploring
motivation: "hautomate restarts the container on every deploy because reload can't be trusted to pick up helper changes; on 2026-11-13 the ~15 s restart window dropped an input_button press."
constraints: "Pre-v1: clean breaks, no compat shims. Framework whose callers live in other repos, so edge cases count even with no in-repo caller. One live Hassette per process."
non-goals: "Reloading modules outside the apps directory (installed packages, stdlib, hassette). State preservation across reload."
depth: normal
---

# Research Brief: Reloading Changed Helper Modules and Their Dependent Apps

**Initiated by**: "Research #4141 together with #1697: should reload re-import every changed module under the apps dir and reload every app that depends on it, or should #4141 be dropped?"

## Bottom line

- **Feasible, and the closest peer ships it.** AppDaemon 4.5 rewrote its app management to do exactly this (AST import graph, reload the transitive dependents). It deprecated `global_modules` because, in its own announcement, global-module reloading "never worked correctly". So "peers don't attempt it" is false and isn't grounds to drop #4141. The generic Python tools (Django, werkzeug, uvicorn) restart the process. Their argument ("dependencies are the enemy of a hot reloader") applies to in-place patching of live objects. Hassette tears each app down and builds it again, so it largely doesn't apply.
- **One acceptance criterion can't be met as written.** #4141 says a broken helper edit must leave every dependent app running, "matching #2481". **#2481 was closed as won't-fix**, citing a prior-art survey that found no peer loads new code before stopping the running instance. AppDaemon does the opposite: an import failure marks every dependent app `compile_error`. Either that criterion changes, or #2481's decision gets reopened. That is a decision for you, not something to settle inside the PR.
- **Don't ship it as one PR. Run it as a milestone of three issues.** #1697 comes first as its own bug fix, because the corpus hits it at startup today. Next comes an in-process "reload every app" built on a clean evict-and-reimport primitive. No dependency graph is needed for it, it is correct by construction, and it removes the container restart. Last is #4141's precise dependency-closure reload, layered on top. In hautomate, a change to `errors.py` or `notify.py` already reaches 27 to 33 of the 48 apps, so measure the second step before paying for the third.

## Context

### What prompted this
In hautomate (48 app entries), every deploy is a `docker compose restart`. A helper change does nothing on reload (#3092 documented this), so nobody trusts reload. The restart leaves about 15 s with no listeners. On 2026-11-13 that swallowed a "Mail checked" `input_button` press. hautomate added a one-off startup catch-up (`a3ebdec`). hautomate's `CLAUDE.md` also records that `hassette.send` messages sent while hassette is disconnected are lost, which is another cost of deploying by restart.

The commit split is real but smaller than the issue's numbers. A re-count of the last 79 code commits found 43 that changed only one app's own file, 26 that touched a shared helper or package sibling, and 10 that touched several app files (the issue says 40/35). Either way, a third to nearly half of deploys need more than a per-file reload.

### Current state (verified in code)
- **Import.** `import_module` (`src/hassette/utils/app_utils.py:509-537`) calls `importlib.reload` whenever the module name is already in `sys.modules`. It has no "force" input, so every cache miss in `load_app_class` (`:427-506`) re-executes an already-imported module. That is #1697.
- **Class cache.** `LOADED_CLASSES` and `FAILED_TO_LOAD_CLASSES` are keyed by `(path, class)`. `force_reload` evicts only the one key being loaded (`:467-473`).
- **Change detection.** `AppChangeDetector.detect_changes` puts an app in `reimport_apps` only when `app.full_path` is among the changed paths (`src/hassette/core/app_change_detector.py:190-196`). The watcher already watches the whole apps directory (`HassetteConfig.get_watchable_files`, `src/hassette/config/config.py:290-300`). A helper save therefore produces an event, and `handle_change_event` drops it with "changed but no app changes detected" (`src/hassette/core/app_lifecycle_changes.py:343-344`).
- **Reload order is stop, then import, then start.** `_restart_apps_unlocked` (`app_lifecycle_changes.py`) stops every restart's instances, then creates every replacement. The class is loaded inside creation (`_start_app_unlocked` calls `factory.create_instances(force_reload=...)`, `src/hassette/core/app_lifecycle_start_stop.py:164`). Stops and starts run one app after another, not concurrently. Locks are taken per app key in sorted order (spec 139), which a multi-app cascade can reuse as is.
- **Autodetection no longer imports anything.** `#3158` replaced it with an AST scan (`find_unconfigured_app_classes`). #1697's acceptance criterion about autodetection re-executing modules is already met. Only the multiple-classes-per-module and import-versus-reload criteria remain.
- **Responses.** `ActionResponse` (`wire/src/hassette_wire/apps.py:190`) describes one `app_key`. A cascade that reloads other apps has nowhere to report them, so reporting one means a wire change plus `client_compat`, CLI and frontend work.

### Key constraints
Pre-v1, so a clean break is allowed. Spec 138's needs-restart gate and spec 139's lock discipline must hold for every app in a cascade. Per `.claude/rules/design-completeness.md`, docs and UI ship in the same PR as the behavior.

## Feasibility Analysis

### Hassette-specific hazards, and whether reloading the whole closure closes them

| Hazard | Where | Closed by reloading the full dependent closure? |
|---|---|---|
| Stale `from helper import x` bindings in dependents | Python semantics | Yes. Every importer is re-executed. |
| `isinstance` across generations: an emitted object reaching a handler annotated with the other generation's class | DI matching uses `isinstance` (`conversion/type_matcher.py:75-78`, `type_registry.py:197`). hautomate passes `announce.Announcement` between 6 emitters and `announcer` through `D.EventData` | Yes, as long as every app that names the class is reloaded together. **No** if the cascade only partly succeeds, for example an emitter restarts on the new generation while the announcer fails, or the reverse. |
| User `BaseState` subclasses registering themselves process-wide | `BaseState.__init_subclass__` writes `_STATE_CATALOG`, keyed by domain, last writer wins (`models/states/base.py:169-175`, `catalog.py`) | Mostly. Re-import overwrites the entry with the new class. A failed import partway through can leave the catalog pointing at a half-loaded generation. `snapshot_catalog()`/`restore_catalog()` already exist and can bracket the import. |
| User `TYPE_REGISTRY` converters and type-keyed `lru_cache`s (`type_utils.py:111`, `type_registry.py:398`) | Keyed by type object | Correct but leaky. Entries for old classes stay until the cache evicts them. Nothing breaks. |
| Per-app caches (`StateManager._domain_states_cache` and others) | Per-app resources | Yes. They die with the app instance. |
| Module-level state in helpers | hautomate has one: `light_flash.IN_FLIGHT` (`light_flash.py:44`) | Yes. All 4 users depend on `light_flash`, so they move together. A flash in flight during the reload behaves as it would across a restart. |
| Stopped or failed apps whose cached class predates the change | `LOADED_CLASSES` | Only if invalidation is per module, which is #1697. Otherwise the next Start brings back the old generation. |
| Dynamic imports (`importlib.import_module("apps.x")`) | Not visible to an AST scan | No. Document it as a limit, as AppDaemon does. hautomate has none. |
| Import cycles | — | Fine with evict-and-reimport, since Python's import machinery handles cycles the way it does at startup. hautomate has none. |
| Stale bytecode | Observed in the probe below: a same-size edit in the same second as the last compile re-imported the old code even with a fresh import | Not by reloading. The pyc check is mtime-seconds plus size. Rare for `git pull` deploys, plausible for a quick save during dev. Compare content hashes and drop the `cache_from_source` file of a changed module before re-importing. This applies to today's own-file reload too. |

**Probe, observed and run under the scratchpad's `probe/`.** A namespace package `myapps` holds `helper.py` (with a pydantic model) and `app.py`, which uses `from myapps.helper import ...`. Four results:

- Today's behavior: reloading only `app.py` keeps the old helper.
- Evicting every `myapps.*` entry from `sys.modules` and importing `myapps.app` again gives new code. An instance made before the eviction keeps running entirely on the old code. `isinstance(new_obj, OldClass)` is `False`. Pydantic forward references resolve. The parent package attribute is rebound.
- A broken helper, followed by restoring the `sys.modules` snapshot, leaves the previous generation intact.

**So evict-and-reimport is a usable primitive.** It needs no topological sort, because the import system reloads evicted helpers on demand and reuses the ones it didn't evict. It never runs new module code inside an old module object, which `importlib.reload` does, and which leaves deleted names behind.

### What would need to change

| Area | Files affected | Effort | Risk |
|---|---|---|---|
| Import primitive, module-keyed class cache, per-module content hash at import (#1697) | `utils/app_utils.py`, `core/app_factory.py` | Medium | Every app load goes through it. High fan-in. |
| Module dependency graph (AST) and changed-module detection | new module beside `app_utils.py` | Small to medium | Under-approximating is the bug class. Over-approximating is safe. |
| Change set and watcher mapping from a helper path to its dependent apps | `core/app_change_detector.py`, `core/app_lifecycle_changes.py` | Medium | `ChangeSet` gains a "why" per app for reporting. |
| Cascade lifecycle: stop the closure, evict and re-import once, start the closure | `core/app_lifecycle_changes.py`, `app_lifecycle_start_stop.py` | Medium | The manual reload path (`reload_app`) has to fan out too, not only the watcher path. |
| Reporting other apps a reload touched | `wire/src/hassette_wire/apps.py`, `client/`, `web/routes/apps.py`, CLI, frontend toast | Medium | Wire plus `client_compat`. Additive fields are safe. |
| Docs | `docs/pages/web-ui/manage-apps.md:75-93`, reload docs | Small | — |
| Tests | `tests/unit/test_autodetect_apps.py`, `tests/integration/test_app_factory_lifecycle.py`, new cascade tests | Medium | Needs `sys.modules` isolation between tests. |

### What already supports this
- Teardown and re-instantiation, which is AppDaemon's model, avoids the stale-instance class of bugs that in-place patchers such as IPython autoreload and jurigged never escape.
- `_restart_apps_unlocked` already stops everything first and creates everything after, under sorted per-key locks. That is the shape a multi-app cascade needs.
- The watcher already sees helper edits. Only the detector discards them.
- `snapshot_catalog`/`restore_catalog` exist for the state catalog.
- hautomate is close to a best case. Imports go through the synthesized package name (137 absolute, 12 relative). There are no cycles, no dynamic imports, no function-level imports, no custom `BaseState` classes, no registry calls, and no helper that touches the bus. There is one module-level mutable dict.

### What works against this
- **AC5 contradicts a recorded decision (#2481, won't-fix).** Under today's stop-then-import order, a broken helper leaves every dependent `FAILED`, as a broken app file does today. Keeping them running means loading before stopping, which is the feature #2481 declined.
- **#1697 is live in the corpus at startup.** `car_climate` imports `thermoscura`, and `vacuum_health` imports `vacuum_alert`, all of them app modules. Whichever loads second goes through `import_module`'s `reload` branch, so the importer keeps the first generation's bindings. It's harmless today (the shared functions are stateless), but it is exactly #1697's mixed-generation bug.
- **Wide blast radius for central helpers.** `errors.py` has 33 transitive dependents of the ~48 apps and `notify.py` has 27. For the commonest helper edits, precise dependency tracking spares only a minority of apps.
- **Gap length.** Stops and starts run sequentially, so the first app stopped in a 30-app cascade waits for every other stop and every init before its replacement runs. That is shorter than a container restart, since there's no HA reconnect, initial state load or `uv pip install`, but nobody has measured it.

## Prior art

Each claim is from a source the prior-art pass read. Clones are under the scratchpad's `priorart/`.

- **AppDaemon 4.5 does closure reload in place.** `dependency.py` parses each file with `ast` and yields only the top-level `import` nodes in the module body (`get_imports`), so imports inside `try`, `if` or functions are missed. `dependency_manager.py` keeps a forward and a reverse graph and closes over them with `find_all_dependents`. `app_management.check_app_updates` runs `_import_modules` (calls `importlib.reload` in `python_sort` topological order, `:1308`, `:819`), then `_stop_apps`, then `_create_and_start_apps`. The new code therefore runs before the old apps' `terminate()`. On an import failure, `safe_import` marks every dependent module and app `compile_error`, so they are not kept running. The bugs after the rewrite are mostly bookkeeping:
  - #2381: changes detected but mapped to `set()`
  - #2626: a module in a new folder isn't picked up until restart
  - #2508: improper cleanup of dependent apps
  - #2599: the graph is re-parsed on every loop, 2.2 s for 79 files
  - Before 4.5, users were told to restart: #944, #1135, #1509, #2187.
  - Release notes: https://github.com/AppDaemon/appdaemon/releases/tag/4.5.0. Announcement: https://community.home-assistant.io/t/announcement-appdeamon-4-5/894776
- **pyscript does transitive reload with its own interpreter.** It records imports at runtime per global context. Hassette can't copy it, because hassette apps are real `sys.modules` modules. https://github.com/custom-components/pyscript/blob/master/docs/reference.rst
- **NetDaemon and HA core require a restart.** NetDaemon v6: "You need to restart the add-on every time you change a file." HA documents that a custom integration update takes effect only after a restart. Neither gives a rationale.
- **Streamlit evicts every local module and re-runs.** Its comment reads: "determining all import paths for a given loaded module is non-trivial, … we simply unload all watched modules" (`local_sources_watcher.py:178`, verified). Its docs warn not to rely on class identity across reruns (#8180).
- **General tools.** Django, werkzeug and uvicorn restart the process. IPython autoreload patches in place and documents broken enum identity and `type(x) == A` checks (#12399). `deepreload` is deprecated. jurigged "cannot retroactively rebuild program state". `hmr`/uvicorn-hmr does a runtime-tracked dependent reload, but it is small and still has cycle handling and stale-state detection open.

**Tally.** In-process transitive reload: AppDaemon (shipping, with steady bookkeeping bugs), pyscript (own interpreter), hmr (small). Evict all and re-import: Streamlit. Process restart: Django, Flask, uvicorn, NetDaemon, HA core. No peer keeps dependents running when a helper fails to import.

## Options Evaluated

### Option A: Full #4141, a dependency-closure reload (milestone)

**How it works.** At import, hassette records each apps-dir module's resolved file path and content hash (#1697's bookkeeping) and builds a static import graph by AST. Any trigger (watcher event, Reload button, CLI, HA button) computes the changed modules by comparing hashes and takes the reverse closure to find the affected app keys, running or not. Under the sorted per-key locks it:

1. Stops every running instance in the closure.
2. Evicts the changed modules and every apps-dir module that imports one from `sys.modules`, along with their parent-package attributes and their per-module class-cache entries, and removes any stale pyc.
3. Brackets the imports with a `snapshot_catalog`/`restore_catalog`.
4. Creates every app in the closure, importing each app module once.

The response and log name each app it touched and why ("imports `notify`").

**Detection: AST, deliberately over-approximating.**
- Use `ast.walk`, not AppDaemon's top-level-only `body` scan, so imports inside `try`, `if`, `TYPE_CHECKING` blocks and functions all count. Over-reloading is safe. Under-reloading is the bug.
- Resolve relative imports against the package chain.
- `import a.b.c` depends on `a`, `a.b` and `a.b.c`.
- For `from pkg import name`, treat `name` as a submodule when `pkg/name.py` exists.
- Keep only modules whose resolved file is under the apps directory. Key on file path, not name. hautomate's container also pip-installs a copy of `hautomate` into site-packages.

Runtime alternatives are worse here:
- A `meta_path` finder or a `sys.modules` diff sees only a module's first import, so the second app to import an already-loaded helper never registers as a dependent.
- Patching `__import__` (as optimistic-reload does) is global and invasive.
- A scan of module globals catches `from x import y`, but misses function-level imports.

Dynamic `importlib.import_module` calls stay a documented limit.

**Failure policy (needs your call).**
- **A1, AppDaemon parity.** A failed import marks the dependents in the closure `FAILED`, with the error on each, as a broken app file does today. Add a cheap pre-stop `compile()` of every changed file and refuse the whole reload on a `SyntaxError`. That covers the commonest typo at almost no cost.
- **A2, keep dependents running.** Import the new generation into evicted slots before stopping anything, and restore the snapshot on any failure. The probe shows the mechanics work, and evict-and-reimport removes the hazard table #2481 cited for in-place reload. It still re-runs module top-level code while the old generation runs, it has no peer, and it reverses #2481.

**Pros**
- Precise. A leaf helper edit (`otf.models` has 5 dependents) leaves the other ~43 apps untouched.
- Closes #4141's motivation: almost every deploy becomes a reload.
- Matches the closest peer's model.

**Cons**
- The largest surface: graph, hash bookkeeping, cascade lifecycle, wire reporting.
- AppDaemon's bug history sits in exactly this bookkeeping.
- Little gain over Option B for central helpers.

**Effort estimate.** Large. It spans import, detection, lifecycle, wire, CLI, UI and docs.

**Dependencies.** None new. It uses `ast` and `hashlib`.

### Option B: In-process "reload every app" (generation reload, no graph)

**How it works.** It uses the same evict-and-reimport primitive as A, applied to the whole apps package. Hassette evicts every module whose file is under the apps directory, invalidates the whole class cache, and restarts every running app through `_restart_apps_unlocked` (stop all, then create all). The trigger is an explicit action (`hassette app reload --all`, `POST /api/apps/reload`, optionally a UI button). With automatic reloads on, it can also run when a non-app `.py` file under the apps dir changes. An app file that another module imports, such as `thermoscura`, has to count as non-app for this purpose. Without a graph, the safe rule is "any `.py` change other than a lone app file that nothing else has loaded triggers reload-all". The answer to "has anything else loaded it" can come from scanning loaded apps-dir modules' globals for the module, which is cheap.

**Pros**
- Correct by construction. Every app moves to the new generation together, so cross-generation `isinstance` mismatches and stale bindings can't happen.
- No dependency graph to under-approximate.
- Removes the container restart: the HA connection, state cache and process stay up, and there's no pip install.
- Built entirely from #1697's primitive plus existing lifecycle code. A later adds a graph on top without discarding anything (Streamlit stops at this shape on purpose).

**Cons**
- Every helper deploy restarts every app, which is a wider disruption than A for leaf helpers.
- The gap for the first-stopped app grows with the app count while stops and starts run sequentially, so it needs measuring and possibly concurrent stops and starts.
- It still needs a multi-app response shape.
- The failure policy question from A applies here too.

**Effort estimate.** Medium. Once #1697 is done, it's one new action, a watcher rule, response reporting and docs.

**Dependencies.** #1697.

### Option C: Drop #4141; fix #1697 and say clearly when a restart is needed

**How it works.** Ship #1697 (it is a real bug either way). Using its per-module content hashes, flag drift: when a module under the apps dir differs from what was imported and isn't an app's own file, show "code on disk differs from what's running; restart to apply" in `hassette status`, the app list and the UI, in the spirit of spec 138's needs-restart signal. Rewrite the docs warning to point at the signal.

**Pros**
- Small.
- Removes the "can't tell whether reload will pick it up" uncertainty the field report names.

**Cons**
- Doesn't address the dropped-event motivation. hautomate keeps restarting the container on about a third to half of deploys, and the 15 s window stays.

**Effort estimate.** Small to medium. Most of it is #1697.

**Dependencies.** #1697.

## Concerns

- **The chosen approach has a significant risk.** #4141's AC5 assumes #2481's behavior, which was explicitly declined. Shipping #4141 as written either quietly reverses #2481 or fails its own acceptance criterion. Decide A1 or A2 before sketching.
- **Partial cascade success is the one mixed-generation state left.** If app X in the closure fails to create while Y succeeds, Y may emit new-generation objects that X's replacement, started later, still matches. If X stays `FAILED`, it can't receive them anyway. Under A2 (keep the old X running), old X sits next to new Y, and hassette's `isinstance`-based DI matching (`type_matcher.py`) would reject Y's emitted objects at X's handlers. That case argues for A1.
- **New concepts to test.** Module generations, content-hash drift, closure computation, and `sys.modules` isolation in tests. The test suite will need a fixture that snapshots and restores `sys.modules` entries under the apps package, or tests will leak generations into each other.
- **Maintenance.** AppDaemon's bug history (#2381, #2508, #2599, #2626) concentrates in file-state bookkeeping: new folders, deleted files, renamed apps, re-scan cost. Hashing at import time and computing the closure only on a trigger (not every loop) avoids #2599's cost. Deleted and renamed modules still need explicit tests.

## Open Questions

- [x] AC5: AppDaemon parity (A1, dependents fail, plus a syntax precheck) or keep running (A2, which reopens #2481)? **Answered 2026-11-27: A1.** A `compile()` precheck of the changed files refuses the reload with every app untouched on a syntax error. Any other import failure puts the dependent apps in `FAILED` with the error shown. #2481 stays closed, and #4141's AC5 needs rewording to match.
- [x] How long is the no-listener gap for a full-closure or all-apps reload in hautomate today, with sequential stops and starts? It needs a timing run on the real deployment (`hassette log --since` around a reload), and it decides whether B alone meets the motivation and whether stops and starts should run concurrently.
  **Partly measured 2026-11-27, from the logs of the restart at 09:21 CST (read-only, no reload triggered).** The jessica-desktop container runs 60 app instances on v0.66.0. A container restart leaves no listeners for at least about 16 s, plus the `docker stop` time, which isn't logged. Breakdown: entrypoint and project install take 5.75 s, Hassette import 2.4 s, the HA websocket connection about 4.5 s, and all 60 apps initialize in 1.7 s (about 28 ms each, back to back). An in-process reload-all skips everything before the app phase. The reload path (`_restart_apps_unlocked`, `app_lifecycle_changes.py` around line 240) stops every app one after another, then starts them one after another. So the gap there is the sum of the stops plus about 1.7 s of starts. Still unmeasured: how long each stop takes, because shutdown isn't logged at INFO. At the current per-app start cost, sequential starts aren't the bottleneck, and running them concurrently isn't needed for step 2 unless stops turn out to be slow.
  **Stop cost measured 2026-11-27 at 10:09 CST** with a live single-app reload of `lost_button_app` (`hassette app reload lost_button_app --json --yes`). Its log lines: the app stopped in 24.9 ms ("Stopped app ... in 24.90 milliseconds"), and the forced re-import plus initialize finished 69 ms after the stop. Extrapolating to 60 instances on the current stop-all-then-start-all path: about 1.5 s of stops plus 1.7–4 s of re-imports and starts. The first app stopped gets its listeners back after roughly 3–5.5 s, against at least 16 s plus `docker stop` for today's container restart. That's an estimate from one quiet app, since an app with slow `on_shutdown` work would stretch it. **Conclusion: step 2 (an in-process reload-all) removes most of the gap as the code stands, and concurrent stops or starts aren't needed to meet the motivation.**
- [x] Is an explicit reload-all action plus `git pull` enough for the hautomate deploy flow, or does it need auto-reload on helper saves in prod (`allow_reload_in_prod` is on)? **Answered 2026-11-27: both.** Deploys use an explicit reload-all action, and the watcher also auto-reloads dependents on a helper save wherever file-watching reload is already allowed. Because the watcher can fire partway through a `git pull`, the sketch must settle how a half-updated tree is handled (the debounce window, and the precheck refusing it).
- [ ] Does `sys.modules["hautomate"]` in the container ever resolve to the site-packages copy that `scripts/docker_start.sh:439` installs, rather than the bind mount? From reading the code it shouldn't: `_ensure_on_sys_path` puts the apps parent first and `_ensure_namespace_package` synthesizes the package. This wasn't checked at runtime. It matters because "under the apps dir" has to be decided by file path.
- [ ] Should a cascade's multi-app response be a new field on `ActionResponse` or a new reload-all endpoint's response? Either is additive for `client_compat`.

## Recommendation

Don't drop #4141 because peers don't do it. AppDaemon, the closest peer, rebuilt itself around exactly this. The semantics (tear down, re-import, re-instantiate the whole closure) close the classic failure modes in hassette's case. The remaining risk sits in the bookkeeping and in AC5, and AC5 conflicts with a decision you already made. This verdict rests on AppDaemon's source, the probe and the corpus analysis.

Run it as a milestone and stage it so each step stands on its own. My view is that B delivers most of the field-report value. The corpus evidence for that is the fan-out of `errors.py` and `notify.py`. Whether B's gap is short enough is unmeasured.

1. **#1697 alone (bug, medium).** Make plain import idempotent (`importlib.import_module`). Make forced reload mean evicting and re-importing under the apps package. Key the class cache by module and invalidate it per module. Record each module's file path and content hash at import. This fixes the startup re-execution hautomate hits today and is the base for everything after.
2. **In-process reload-all (Option B, medium).** An explicit action, the watcher rule, multi-app reporting and docs, with failure policy A1 (chosen 2026-11-27). Then measure the gap on hautomate.
3. **#4141 narrowed to the precise closure (Option A's graph, medium).** Build it after step 2, and only if restarting every app on a helper deploy turns out to hurt. Otherwise park it, with "a leaf-helper deploy disrupted an unrelated app" as the trigger to pick it up.

Steps 2 and 3 can share one sketch, since the failure policy, the trigger rules and the reporting shape interact. They should still ship as separate PRs.

### Suggested next steps
1. Decide AC5 (A1 or A2), and amend #4141 or reopen #2481 to match.
2. Sketch #1697 via `/mine-sketch`, with the evict-and-reimport primitive and per-module hashes as its core decisions, and file the reload-all issue with #1697 as its blocker (`gh issue edit --add-blocked-by`).
3. Before building step 2, time a multi-app stop and start on hautomate to see whether stops and starts must run concurrently.

## Sources

- https://github.com/AppDaemon/appdaemon/releases/tag/4.5.0
- https://community.home-assistant.io/t/announcement-appdeamon-4-5/894776
- https://appdaemon.readthedocs.io/en/4.5.9/APPGUIDE.html
- AppDaemon issues #944, #1135, #1509, #2187, #2381, #2508, #2599, #2626 at https://github.com/AppDaemon/appdaemon/issues
- https://github.com/custom-components/pyscript/blob/master/docs/reference.rst
- https://netdaemon.xyz/docs/user/
- https://contributors.home-assistant.io/core/integrations/restart-required/
- https://community.home-assistant.io/t/reload-custom-integration/686155
- https://github.com/streamlit/streamlit/issues/8180
- https://ipython.readthedocs.io/en/stable/config/extensions/autoreload.html
- https://github.com/ipython/ipython/issues/12399
- https://ep2019.europython.eu/media/conference/slides/uVdVr3P-writing-a-python-autoreloader.pdf
- https://pypi.org/project/uvicorn-hmr/
- https://github.com/dandavison/optimistic-reload
- https://pydevtools.com/handbook/explanation/how-does-hot-reloading-work-in-python/
