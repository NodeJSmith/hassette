# Design: Separate app import and reload semantics

**Date:** 2026-11-27
**Status:** built
**Mode:** sketch
**Issues:** #1697
**Prior art:** design/research/2026-11-27-helper-module-reload/research.md

## Summary

App class loading and module reloading share one path today. `import_module()` (`src/hassette/utils/app_utils.py:509-537`) calls `importlib.reload` whenever the module's canonical name is already in `sys.modules`. Every miss in the class cache therefore runs the app file again, including at startup when a second app class lives in the same file, or when one app module imports another. hautomate hits the second case today: `car_climate` imports `thermoscura`, and `vacuum_health` imports `vacuum_alert`. The class cache (`LOADED_CLASSES`/`FAILED_TO_LOAD_CLASSES`, `app_utils.py:37-38`) is keyed by `(path, class)`, and a forced load clears only its own key (`app_utils.py:462-468`), so classes from different runs of one module can sit in the cache together.

The change:
- A plain load imports each app module at most once, with `importlib.import_module`.
- `importlib.reload` goes away. When a forced reload re-imports, it does so by eviction and a fresh import.
- The cache shape, when a forced reload re-imports, which class a running key's new instance gets, and stale bytecode are all settled in Decisions below.

**Where each piece lives:**
- The loader, the per-module record, the clear function, the content hash, the eviction logic and the `.pyc` removal stay in `src/hassette/utils/app_utils.py`, which already owns module identity (`_module_name_for`, `_ensure_namespace_package`).
- The rule for which class a new instance of an already-running app key gets goes in `AppFactory.load_class` (`src/hassette/core/app_factory.py`). The factory already holds the matching `force_reload` guard (`app_factory.py:95-114`), which moves there.

**In scope:**
- The loader, the cache, and the factory's use of both.
- The internal helpers `app_cache_key`, `class_already_loaded`, `class_failed_to_load`, `get_class_load_error` and `get_loaded_class`, with every caller and test that uses or patches them: `tests/unit/app_factory/test_app_factory.py`, `tests/unit/utils/test_load_app_class.py`, `tests/integration/test_app_factory_lifecycle.py` and `tests/support/app_staging_helpers.py`.
- The per-instance Reload route's comment and docstring (`web/routes/apps.py:476-487`).
- Regression tests.
- User docs. Reload no longer re-runs an unchanged file, and a per-instance Reload with live siblings no longer picks up edits. The pages that describe what Reload does need both changes: `docs/pages/web-ui/manage-apps.md` ("What Reload Re-imports"), `docs/pages/cli/commands.md` (`app reload`), and `docs/pages/getting-started/home-assistant-integration.md` (the reload button).

**Out of scope:** reloading the apps-dir modules that import a reloaded module, reload-all, the `compile()` precheck, and a drift signal in the UI. Those belong to #4498, #4141 and Option C.

## Posture

- **Failure handling:** fail loudly. A forced reload that fails to import records the failure, and the app goes `FAILED` as it does today, which is the brief's A1 policy. The removed module is not restored to `sys.modules`.
- **Compatibility:** break freely for internals. The class-cache globals and the helper functions over them can change shape, and every caller in `src/` and `tests/` moves in the same PR. The user-facing `force_reload` parameters on `AppHandler` and the lifecycle classes keep their signatures.
- **Scope:** minimal, #1697 only. Dependent-module reload, reload-all, the `compile()` precheck and drift reporting are out. Acceptance criteria that reach into those get reworded on the issue, not built here.
- **Rollout:** ships outright as a `fix:`, with no flag.
- **Hardening:** project defaults. Keep the existing INFO line for each forced reload, and add no new metrics or caching.
- **Altitude:** build. One session builds it, and the ledger cites files.

## Decisions

### D1: What shape does the class cache take?

**Situation:** `LOADED_CLASSES` and `FAILED_TO_LOAD_CLASSES` are two flat dicts keyed by `(module path, class name)`. When a module fails to import, the error is stored under the class key that triggered the import, so a sibling class from the same file misses the cache and tries the failing import again, running its top-level code a second time. Clearing "everything from this module" means scanning both dicts for keys with a matching path. #4498 will add more per-module state, such as the content hash and its eviction bookkeeping.

**Deciding factor:** one coherent per-module unit that invalidation and #4498 can both act on.

| | A: Per-module record | B: Keep flat dicts, invalidate by path scan |
|---|---|---|
| Forced-reload invalidation | Pop one entry | Filter two dicts by path |
| Module import failure | Stored once on the module. On a plain load, every sibling class raises it without importing again. A forced load after a module-level failure always retries (D2), so a broken multi-key file in one reload batch runs once per key | Stored per class key. Siblings import again and fail again |
| Room for #4498's per-module state (hash, generation) | A field on the record | A third parallel dict keyed by path |
| Diff size | Rewrites the cache and its helpers, and every test that touches the dicts directly | Smaller. The helpers keep their key shape |
| After a failed forced import | The record holds the failure. The parent package's attribute still points at the pre-reload module | Same |
| Peers | AppDaemon 4.5 keeps per-module state (its dependency manager tracks modules, with apps hanging off them) | unknown |

Under A, the module path maps to a record holding:
- the module's canonical name and the module object itself
- the class objects loaded from it
- failures per class (missing attribute, not an `App`, a failing `validate_init_method`)
- at most one module-level import failure

The record is the only owner of "which generation is current". Reusing a record (a plain load, or a forced load the D2 gate skips) requires `sys.modules.get(name) is record.module`. On a mismatch, the loader calls `importlib.import_module` and adopts whatever module that returns: a fresh import if the name is absent, or the object already there. It then rebuilds the record, with no hash if the module wasn't imported by this call. A reused record keeps its classes and its per-class failures as they are, because the same bytes give the same result. One clear function removes an app module's `sys.modules` entry and its record together. It is the only code that removes app modules. Clearing only the class cache, without its module entry, isn't possible.

**Recommendation:** A, because it makes "one module, one generation" a single object instead of a property two dicts have to keep in step, and #4498 extends that same object.
**Pick B instead if** you'd rather keep this diff minimal and let #4498 reshape the cache when it adds per-module state.
**Reversibility:** easy (internal only, with no consumers outside the repo)
**Ratified:** Chose a per-module record that owns the module object (verified against `sys.modules` before reuse) over flat dicts with a path scan, so invalidation and module failures act on one object #4498 can extend. This accepts a larger rewrite of the cache helpers and the tests that touch them. It also accepts that after a failed forced import the parent package's attribute still points at the pre-reload module, so `from <pkg> import <mod>` reaches it and a call-time import re-runs the file (#4498 removes parent attributes).

### D2: When does a forced reload actually run the module again?

**Situation:** `_restart_apps_unlocked` (`src/hassette/core/app_lifecycle_changes.py`, starting at line 215, with its starts at 244-245) stops every app in a change batch, then starts each one with `force_reload=True`. When one file holds two configured app keys and the file changes, both keys land in the batch. Under a plain "remove and re-import on every forced call" rule, the module runs twice: A's classes come from the first run and B's from the second. That is the mixed-generation bug again, one layer up. The issue also asks that each module's content hash be recorded at import.

**Deciding factor:** one run per module per reload, without threading new state through the lifecycle.

| | A: Re-import on every forced call | B: Re-import only when the content hash changed since the last successful import | C: One re-import per module per reload batch (batch token) |
|---|---|---|---|
| Two app keys from one file in one batch | Two runs, mixed generations | One run. The second key's forced load sees a matching hash and uses the current module | One run |
| Reload button on an unchanged file | Runs the module again | Restarts the app without running the module again. Module-level code doesn't re-run | Runs the module again |
| Reload after a failed import (for example a broken helper that's since fixed, with the app file unchanged) | Retries | Retries, because a failure is never hash-gated | Retries |
| What the hash is used for | Nothing in #1697. Recording it would be dead data, so it's deferred to #4498 | Gating the re-import, and #4498 reuses it for change detection | Nothing in #1697 |
| Layers touched | Loader only | Loader only. The hash lives on the D1 record (under B on D1, a parallel dict) | Lifecycle, then factory, then loader: a new parameter at each step |
| Peers | — | AppDaemon 4.5 re-imports changed modules (with `importlib.reload`, in dependency order) inside one update pass (`research.md` line 94). Its change check isn't verified | AppDaemon's update pass is effectively a batch (same source) |

The hash is a SHA-256 of the file's bytes (`hashlib.file_digest`). The loader reads it *before* importing, inside the same `try` that records load failures, and stores it on the record only if the import succeeds. So a save racing the import errs toward one extra re-import, never toward a hash that is ahead of the running code. The one exception is the read-only apps dir that D4's Ratified line accepts. A module that is already in `sys.modules` when its first class load happens (pulled in by another app module's import, like `thermoscura` by `car_climate`) gets a record with no hash, so its next forced load re-imports it. The forced-reload INFO line that Posture keeps (`app_utils.py:462-468`) is reworded to say whether the module was re-imported or found unchanged and reused, with a short hash.

**Recommendation:** B, because it gives one run per module from the loader alone (for modules that imported successfully; after a module-level failure, every forced load retries, per D1's failure row) and gives the issue's content hash a real job. The only behavior lost is re-running an unchanged file's top-level code on a manual Reload, and today that re-run already can't pick up a changed helper, since the helper stays cached.
**Pick A instead if** a manual Reload must always re-run module top-level code (for example, modules that read files or the environment at import), and you accept the double run for multi-key files until #4498. **Pick C instead if** you want both one run per batch and an unconditional re-run on Reload, at the cost of a parameter through three layers.
**Reversibility:** easy
**Ratified:** Chose hash-gated re-import over re-importing on every forced call or a batch token, to get one run per module per reload from the loader alone, accepting that a manual Reload of an unchanged file doesn't re-run its top-level code, and that a save landing between two sibling keys' forced loads in one batch can put them on different generations until the next reload, which that same save triggers.

### D3: What class does a new instance of an already-running app key get after a sibling reload?

**Situation:** `AppFactory.create_instances` ignores `force_reload` while an app key has live instances (`app_factory.py:95-114`). The point is that two instances of one app key never run classes from different runs of the module. Per-module invalidation crosses that rule. Suppose app keys A and B share `foo.py`, B is running, and a forced reload of A clears B's cached class with the rest of the module. If one B instance is then recreated on its own (`reload_instance`, or a config change that adds an instance), it loads the new class while B's other instances run the old one. Today the opposite happens: B's cache entry survives, so B stays on the old code but stays consistent. The guard also already has a hole. The per-instance path `_create_instance_unlocked` (`core/app_lifecycle_start_stop.py:423`) calls `AppFactory.load_class` directly, and the web route's per-instance Reload always passes `force_reload=True` (`web/routes/apps.py:480-487`). So clicking Reload on one instance of a running multi-instance app after an edit already splits that key's classes.

**Deciding factor:** keep the existing "one class per running app key" rule without making the loader's cache aware of whether an app is running.

| | A: The factory reuses the live instances' class | B: Accept the split and log a warning | C: A forced reload also restarts sibling app keys from the same file |
|---|---|---|---|
| B's instances agree on one class | Yes | No. A recreated instance gets the new class | Yes, and they're all on the new class |
| Stale class reachable through the cache | No, because the old class is reachable only through B's live instances | No | No |
| Where it lives | `AppFactory.load_class`, the funnel both `create_instances` and `_create_instance_unlocked` go through (see Summary). While `registry.get_live_apps(app_key)` is non-empty, `force_reload` is downgraded and the type of the first live instance is the class, forced or not | Loader logs which other classes in the module were cleared | Lifecycle fans the reload out to other app keys and reports them. That's #4498's multi-app response work |
| Cost | Small | Smallest | Large, and it overlaps #4498 |
| How often it happens | Needs two app keys in one file, a reload of one, then a lone instance created for the other. Rare, but silent when it does | Same | Same |
| Live instances already disagree (an orphan from an older generation) | A new instance gets whichever class the registry lists first | n/a | n/a, because every instance restarts |
| Per-instance Reload of an edited file while siblings run | That instance restarts on its siblings' class. The edit arrives through the app-level Reload. A single-instance app has no live siblings once it stops, so it is unaffected | Picks up the edit, so the key splits | Not addressed. C restarts other keys, not this key's siblings, so the key splits |
| Peers | — | — | AppDaemon stops and recreates every app that depends on a changed module (`research.md` line 94) |

**Recommendation:** A, because it extends a rule the factory already enforces to the case per-module invalidation creates, for a few lines in the same place.
**Pick B instead if** you'd rather rely on #4498's reload-all to make this case moot and keep the factory unchanged. **Pick C instead if** sibling keys should always move to the new code together now, not after #4498.
**Reversibility:** easy
**Ratified:** Chose having `AppFactory.load_class` reuse the live instances' class on every instance-creation path, forced or not, over accepting the split or restarting sibling keys. This keeps one class per running app key without making the cache aware of which apps are running. It accepts that sibling keys stay on old code until they are reloaded themselves, that a per-instance Reload with live siblings doesn't pick up an edit, and that when live instances already disagree (an orphan from an older generation), a new instance gets whichever class the registry lists first.

### D4: How does a forced re-import avoid stale bytecode?

**Situation:** Python's source loader reuses `__pycache__/<mod>.cpython-XY.pyc` when its recorded source mtime (whole seconds) and size match the file. The brief's probe showed a same-size edit saved within the same second re-importing the old code (`research.md` hazard table, "Stale bytecode"). Removing the module from `sys.modules` doesn't help, because the `.pyc` is still on disk.

**Deciding factor:** a forced re-import always compiles the current source, with the fewest moving parts.

**Recommendation:** before each forced re-import, delete the module's `importlib.util.cache_from_source(path)` file. A missing file is ignored. Any other `OSError` (for example a read-only bind mount) is logged at WARNING, and the import goes ahead.
**Pick something else instead if** apps dirs are often read-only with prebuilt `.pyc` files, in which case compile with hash-checked pycs (`py_compile` with `PycInvalidationMode.CHECKED_HASH`). The Dockerfile's prebuilt `.pyc` files cover hassette itself, not the bind-mounted apps (`Dockerfile:55-56`). In the one real deployment (hautomate on jessica-desktop, checked 2026-11-27), the apps dir is bind-mounted read-write, and the container user owns the `__pycache__` directories and can write to them.
**Reversibility:** easy
**Ratified:** Chose deleting the module's cached `.pyc` before each forced re-import over hash-checked pycs, so a forced re-import always compiles current source with the fewest moving parts, accepting a WARNING and possibly stale bytecode on a read-only apps dir. Because of D2's hash gate, later Reloads then skip until the file changes again.

## Assumed

- The startup pre-check, not autodetection, is where apps get imported at startup. Autodetection is AST-only (`find_unconfigured_app_classes`, `app_utils.py:235-285`). `run_apps_pre_check` (`app_utils.py:142-175`, called from `core/startup_tasks.py:44`) loads every enabled manifest's class through `load_app_class_from_manifest`. With idempotent import, its results stay in the cache and lifecycle loading reuses them without running anything again. The pre-check keeps importing, since surfacing import errors before startup is its purpose. The issue's acceptance criterion about autodetection gets reworded to the pre-check. Evidence: code as cited, and `research.md` line 34, which is right about autodetection but misses the pre-check.
- A forced reload removes only the target module's own `sys.modules` entry. The apps-dir modules it imports, and the ones that import it, are untouched, and #4498 covers them. For importers that bound names (`from x import y`) this keeps today's behavior. An importer that holds the module object (`import apps.x as m`) used to see new code, because `importlib.reload` ran it in the same object; after eviction it keeps the old object until it reloads too. The ship-time challenge kept eviction (the brief's choice, `research.md` line 63, and #4498's primitive) and documented the change on the reload pages. Evidence: Posture scope, and `research.md` step 2.
- `importlib.import_module` on a removed submodule of the synthesized namespace package re-imports it and rebinds the parent package's attribute. Evidence: the brief's probe (`research.md` lines 57-63).
- A failed import leaves no entry in `sys.modules`, because the import system removes a partially executed module. So under fail-loudly the next load attempt imports from scratch, with no extra cleanup. Evidence: the language reference's loading rules ("If loading fails, the loader must remove any modules it has inserted into `sys.modules`", https://docs.python.org/3/reference/import.html#loading).
- `force_reload=True` stays the only class-loading path that can run an already-imported module again (D2 and D3 decide when it actually does). Evidence: `app_factory.py:212`, plus the callers in `core/app_lifecycle_start_stop.py:164,423` and `web/routes/apps.py:444,487`.
- `web/config_view.py:341` reads a loaded class through the cache (`cached_class` under D1) and is the only caller outside `core/`. After a sibling key's forced reload re-imports a shared file, a stopped key's class is gone from the new record until that key loads again, so its config view masks every string meanwhile (`known-issues.md` KI-001).

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- A failure raised before the module name resolves (a missing file) is recorded with `name=None`, so it stays current until a forced load retries it, matching the old per-class cached failure; a test pins it.
- A forced load that fails before its eviction (the hash read on an unreadable file) still removes the module before recording the failure, so a later plain load can't adopt the old module with no error shown. This follows Posture's "not restored to `sys.modules`".
- `AppFactory.load_class` keeps a plain-load check of `cached_load_error` before calling the loader. The loader would re-raise the same failure; the check only keeps it from being logged at ERROR on every attempt, as before.
- Every forced load now logs its INFO line (re-imported or unchanged, with a 12-character hash prefix), not only those that found a cache entry.
- `tests/integration/test_app_factory_lifecycle.py::test_factory_force_reload_reloads_class` is deleted: under D2 a forced load of an unchanged shared fixture file reuses the class, and the re-import cases are pinned in `tests/unit/utils/test_load_app_class.py` against temp apps dirs.
- Beyond the three docs pages in Summary, `docs/pages/core-concepts/configuration/index.md` (file watcher), `.claude/rules/demo-and-screenshots.md` and `.claude/skills/ui-qa/references/harness.md` described the old reload behavior and are updated; the reimport docstrings in `app_change_detector.py` and `app_lifecycle_changes.py` now say "if the file changed".
- `AppFactory.load_class` reuses a live instance's class only when that instance was built from the manifest's file and class name (`built_from`, reading the instance's `app_manifest`); otherwise the class comes from the loader. D3 as ratified took the first live instance's type unconditionally, which would hand new instances the old class if a stop failed during a rename. The check keeps D3's rule wherever the classes actually match, and the dropped `force_reload` now logs at INFO instead of DEBUG. Both came from the ship-time challenge.
