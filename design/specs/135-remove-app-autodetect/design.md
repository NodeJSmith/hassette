# Design: Replace app autodetection with an unconfigured-app warning

**Date:** 2026-10-20
**Status:** built
**Mode:** sketch
**Issues:** #3145

## Summary

Hassette autodetects apps: with `apps.autodetect` (default `true`), `autodetect_apps` in
`src/hassette/utils/app_utils.py` imports every `.py` file under `apps.directory` and loads every
`App`/`AppSync` subclass it finds, inventing a manifest (`auto_loaded=True`) for classes the user
never configured. That runs import-time side effects for unconfigured files and invents an app
identity the user never chose, which becomes permanent once #3095 (PR #3146) keys identity on
instance names.

This change removes autodetection entirely and replaces it with a log-only startup WARNING for each
direct `App`/`AppSync` subclass in `apps.directory` that no `[hassette.apps.<key>]` entry configures.
The warning exists for newcomers and quickstart users who drop a file in and wonder why nothing runs;
it is not a completeness check for experienced users, who can turn it off with one switch.

Homes:
- **The scan** (AST parse, no import) is a new module-level function in `src/hassette/utils/app_utils.py`,
  replacing `autodetect_apps`. It returns the unconfigured classes; it does not build manifests.
- **The warning text** is built next to `apps_dir_warning` in the same module, and logged from
  `Hassette.startup_tasks` (`src/hassette/core/core.py`), where the apps-directory warning is already logged.
- **The switch** is a field on `AppsConfig` (`src/hassette/config/models.py`), replacing `autodetect` (D6).
- **The built-in exclusions** stay a constant in `src/hassette/config/defaults.py`, renamed from
  `AUTODETECT_EXCLUDE_DIRS_DEFAULT` to `APP_SCAN_EXCLUDE_DIRS`; the `AppsConfig` docstring that cites it follows (D7).
- **`auto_loaded`** is deleted from every layer (D5): `AppDict`/`clean_app`, `AppManifest` and its
  `display_name` default (`config/classes.py`), the precheck skip in `run_apps_pre_check`, `app_registry.py`,
  the `app/app.py` docstring, telemetry (`insert_params.py`, `repository.py`), `schemas/app_snapshots.py`,
  `types/types.py`, `web/mappers.py`, `hassette_wire/apps.py`, the frontend "auto" badges (`apps-table-row.tsx`,
  `sidebar.tsx`, `app-detail-header.tsx`), generated OpenAPI/TS types, `hassette.schema.json`, and the
  `app_manifests.auto_loaded` column via a new `migrations_sql/014.sql`.

Out of scope: see D4 and D10, plus indirect subclasses (D1).

## Posture

- **Failure handling:** the scan never blocks startup or raises. Each file is parsed with `ast.parse(path.read_bytes())` inside a per-file `except Exception` that logs at DEBUG and skips the file, and the directory walk itself is guarded, so no file or unreadable subdirectory can stop startup; configured apps still report their real errors through the import path.
- **Compatibility:** breaks freely (pre-V1, clean breaks preferred). `apps.autodetect` and `auto_loaded` go away in config, DB, wire, and UI with no deprecation path; compat-gate entries and the footer are in D5 and D11.
- **Scope:** minimal (D1–D9 settle the specifics). No ignore lists, no base-class heuristics.
- **Rollout:** ships outright, before PR #3146; #3146 rebases onto it and drops its auto-loaded snake_case naming.
- **Hardening:** project defaults.
- **Altitude:** `build`; one session builds it against the current tree.

## Decisions

### D1: How does the scan find app classes?

**Deciding factor:** no side effects from files the user didn't configure.

| | A: AST parse, direct subclasses | B: import modules, any subclass |
|---|---|---|
| Side effects | none; files are only parsed | runs import-time code of unconfigured files |
| Coverage | classes whose bases visibly name `App`/`AppSync` | indirect subclasses too |
| Can run without `.env` loaded | yes | no (`core.py` orders it after the `.env` import for this reason) |
| Cost of a miss | a newcomer hint not shown | n/a |

**Recommendation:** A. A miss only skips a hint, and users with base-class hierarchies aren't the warning's audience.
**Pick B instead if** the warning needed to be a completeness guarantee.
**Reversibility:** easy (internal to one function)
**Ratified:** Chose AST parsing of direct subclasses over importing modules, to keep unconfigured files side-effect free, accepting that indirect subclasses never warn and shared base classes may warn.

### D2: Which base-class spellings count as a direct subclass?

**Deciding factor:** catch what the docs and examples teach, nothing cleverer.

**Recommendation:** a base counts when, after stripping a subscript (`App[MyConfig]`), it is the name `App` or `AppSync`, or an attribute ending in `.App`/`.AppSync` (`hassette.App`). Import aliases (`from hassette import App as Base`) are not resolved. Only module top-level class definitions count (classes nested in functions or under `if TYPE_CHECKING:` are skipped), since the loader resolves `class_name` as a module attribute.
**Pick a stricter rule instead if** a bare `App` name from an unrelated library proves to be a common false positive. **Pick alias resolution instead if** the docs start teaching aliased imports.
**Reversibility:** easy
**Ratified:** Chose bare `App`/`AppSync` names and `.App`/`.AppSync` attributes (subscripts stripped) on module top-level classes over alias resolution or bare-names-only, to match what the docs teach and what the loader can resolve, accepting that aliased imports and nested classes never warn.

### D3: How is "already configured" decided?

**Deciding factor:** catch the newcomer who adds a second class to a file they already configured.

| | A: `(resolved file, class_name)` pair | B: resolved file path only |
|---|---|---|
| Second class in a configured file | warns | silent |
| Code | a set of pairs | a set of paths |
| Disabled manifests (`enabled = false`) | count as configured | count as configured |

**Recommendation:** A; same cost, and B is silent about exactly the newcomer case.
**Pick B instead if** multi-class files with deliberately unconfigured helpers become a common complaint.
**Reversibility:** easy
**Ratified:** Chose matching on (file, class) over file path only, to warn about a second class in an already-configured file, accepting a warning for deliberately unconfigured classes in configured files. "Configured" means a validated manifest, matched on `(manifest.full_path, manifest.class_name)` (the path the loader imports); an entry dropped for missing keys doesn't count, so it gets both the existing "Skipping app … missing required keys" warning from `clean_explicit_apps` and an unconfigured-class snippet.

### D4: Where does the unconfigured-app result surface?

**Ratified:** Chose log-only WARNINGs over a persisted "found, not configured" state in the DB, status CLI, and UI, to keep the change minimal and the DB free of a state no one acts on, accepting that users who only look at the UI won't see it.

### D5: What happens to `auto_loaded` in the wire model and DB?

**Ratified:** Chose dropping `auto_loaded` from the wire model, the `app_manifests` table (new `014.sql`), the API schemas, and the UI badges over keeping it, to leave no field that is always false, accepting a break in the released `hassette-client`: new entries in `tools/wire_compat_ignore.txt` (oasdiff ERR for the removed required property; the existing `apps/items/auto_loaded` line from spec 125 is a different path) and `tools/client_compat_ignore.txt` (released-client fixture failures), plus the D11 footer. No `API_SCHEMA_VERSION`/`MIN_API_SCHEMA_VERSION` bump: removing a required field adds no server dependency under the rule in `client/src/hassette_client/version.py`.

### D6: Name and shape of the switch that turns the warning off

**Deciding factor:** one obvious, discoverable key next to `apps.directory`.

| | A: `apps.warn_unconfigured: bool = true` | B: `apps.warn_unconfigured_apps: bool = true` | C: top-level `warn_on_unconfigured_apps` |
|---|---|---|---|
| Discoverable next to `apps.directory` | yes | yes | no |
| Redundant with section name | no | yes (`apps.…_apps`) | n/a |
| Matches existing top-level `allow_*` style | n/a | n/a | closer |

**Recommendation:** A. It sits where the scan's input lives and reads naturally as `[hassette.apps] warn_unconfigured = false`.
**Pick B instead if** you want the key self-explanatory when quoted without its section. **Pick C instead if** you'd rather group it with other top-level startup toggles.
**Reversibility:** easy now, a breaking rename later
**Ratified:** Chose `apps.warn_unconfigured: bool = true` over `apps.warn_unconfigured_apps` or a top-level key, to sit next to `apps.directory` without repeating the section name, accepting the key is less self-explanatory quoted alone. With `warn_unconfigured = false` the scan is skipped entirely and the generic "No apps found or configured" warning fires exactly as it would with no app classes present; a test pins both.

### D7: What happens to `apps.exclude_dirs`?

**Deciding factor:** remove config whose job is gone, unless the scan still needs it.

| | A: drop it; keep built-in exclusions | B: keep it for the scan |
|---|---|---|
| Config surface | smaller | unchanged |
| User with a helper dir full of `App` subclasses | turns the warning off (D6) | can exclude just that dir |
| Fits "one global switch" scope | yes | adds a second knob |
| Built-in `.venv`/`__pycache__`/`.git` skipping | kept (renamed constant) | kept |

**Recommendation:** A. With a global switch, a per-directory exclusion is the ignore list the scope stance ruled out; the built-in exclusions still keep virtualenvs out of the scan.
**Pick B instead if** you want users to be able to silence a `lib/` directory without losing the warning elsewhere.
**Reversibility:** easy to re-add; removing it is breaking (posture accepts)
**Ratified:** Chose dropping `apps.exclude_dirs` and keeping only the built-in exclusions over keeping it for the scan, to hold the scope to one global switch, accepting that a user with a helper directory of app classes turns the warning off entirely, that an `apps.directory` pointed at a project root walks vendored trees (other than `node_modules` and `site-packages`, which join the built-in exclusions so a broad directory's scan stays bounded) and may warn once per third-party `App` subclass, and that an apps directory under a folder named like a built-in exclusion (built-ins match absolute path parts) never warns.

### D8: When does the scan run?

**Deciding factor:** show the hint where a newcomer will see it, without repeated noise.

| | A: startup only | B: startup + `hassette run --check` | C: startup + every config reload |
|---|---|---|---|
| Newcomer running `hassette run` | sees it | sees it | sees it |
| Docker add-on (`docker_start.sh` runs `--check` first) | once, in server log | twice (check stderr + server log) | once per reload |
| Dev-mode reload noise | none | none | repeats on each config reload |
| `--check` contract (stdout is shell vars only) | untouched | needs stderr only, already the pattern | untouched |

**Recommendation:** A. Startup is where the apps-directory warning already lives; `--check` output in the add-on is followed immediately by the server's own startup log, so B duplicates it.
**Pick B instead if** `--check` is used on its own as a pre-flight tool outside Docker. **Pick C instead if** you expect people to add config entries in dev mode and want the warning to update live.
**Reversibility:** easy
**Ratified:** Chose startup only over also running in `--check` or on config reload, to show the hint once where the apps-directory warning already lives, accepting that a config reload doesn't refresh it.

### D9: Warning shape, and its interaction with "No apps found or configured"

**Deciding factor:** a newcomer can copy the fix straight from the log.

| | A: one WARNING per class, with a TOML snippet | B: one aggregated WARNING listing classes |
|---|---|---|
| Copy-paste fix | yes (`[hassette.apps.<key>]` with `filename`, `class_name`) | list only |
| Noise with many unconfigured classes | N lines (switch off via D6) | 1 line |

With either, when no apps are configured but unconfigured classes were found, the generic "No apps found or configured in apps directory" warning is replaced by the unconfigured-class warning(s), so a newcomer sees one cause, not two. The generic warning still fires when the directory holds no app classes at all.

**Recommendation:** A; the audience is newcomers, and the snippet is the help. The suggested `<key>` is the snake_case of the class name, as a suggestion only (the user writes it). The snippet's `filename` is the file's path relative to `apps.directory` as posix (both resolved before `relative_to`), so a class in `apps/lights/foo.py` gets `filename = "lights/foo.py"`, which `clean_app` joins back onto `app_dir`. A test pins that a snippet for an app in a subdirectory, pasted as config, loads.
**Pick B instead if** you expect multi-class directories to be common among people who leave the warning on.
**Reversibility:** easy
**Ratified:** Chose one WARNING per class with a paste-ready TOML snippet whose `filename` is relative to `apps.directory` (replacing the generic "no apps" warning when classes were found) over one aggregated warning, to give newcomers a fix that loads as pasted, accepting N lines for N unconfigured classes. "Loads as pasted" holds across every snippet at once: a suggested key that matches a configured key (validated or not), an `AppsConfig` field name, or an earlier suggestion in the same startup takes the first free `_2`/`_3`/... suffix, chosen over a file-stem suffix because a stem can collide again and needs a numeric fallback anyway. Each warning also says "If this is a base class, configure the apps that subclass it instead", since D1 lets shared base classes warn. When no apps were found and the scan skipped `.py` files it couldn't parse, the "No apps found" warning names each one with its error, chosen over a per-file WARNING so broad directories with vendored or newer-syntax files stay quiet whenever apps exist.

### D10: Ordering against PR #3146, harness default, and the instance-name fallback

**Ratified:** Chose landing this change before PR #3146, leaving the test harness's default instance name at main's `ClassName.0` and `AppRegistry._resolve_instance_name`'s `{class_name}.{index}` fallback unchanged, to keep the two PRs off each other's lines, accepting that #3146 rebases onto this and owns the harness's switch to user-chosen names and the fallback fix.

### D11: What does an existing user see on the first start after upgrading?

**Deciding factor:** one coherent upgrade story within "breaks freely", with no migration-only code.

| | A: loud break + footer guidance | B: A plus a retired-keys hint in the unknown-key error | C: keep the DB column for rollback |
|---|---|---|---|
| Leftover `autodetect`/`exclude_dirs` (TOML or `HASSETTE__APPS__AUTODETECT`/`__EXCLUDE_DIRS`) | `ConfigError` from spec 128's unknown-key check; footer says delete them | same, error names the fix | same as A |
| Migration-only code to remove later | none | a retired-keys table (declined in spec 128) | a dead column |
| Unconfigured apps on a shared base class | stop loading with no warning; footer says every app needs an entry, base-class apps included | same as A | same as A |
| Rollback to an older image | blocked by `014.sql` like any migration release ("upgrade the binary or remove the database manually", `core/database_service.py`) | same | works |

**Recommendation:** A. It follows the `extend_exclude_dirs` removal precedent (`tests/unit/config/test_unknown_keys.py`, `removed-apps-key` case): a loud failure plus release-note guidance.
**Pick B instead if** Docker users with the env var in a compose file are expected to hit a restart loop without reading release notes. **Pick C instead if** users are expected to roll back across this release specifically.
**Reversibility:** easy (footer wording and tests)
**Ratified:** Chose a loud break with footer guidance over a retired-keys hint or keeping the DB column, to keep the upgrade story in one place with no migration-only code, accepting that leftover keys fail startup until deleted, base-class apps stop silently until configured, and rollback past `014.sql` needs the telemetry DB removed. The `BREAKING CHANGE:` footer names `apps.autodetect`, `apps.exclude_dirs`, `HASSETTE__APPS__AUTODETECT`, and `HASSETTE__APPS__EXCLUDE_DIRS` and says to delete them, and says every app now needs a `[hassette.apps.<key>]` entry, including apps built on a shared base class. It also says that an autodetected app's history stays under its old key (`<apps dir name>.<module path>.<ClassName>`, e.g. `apps.lights.LightsApp`, the key the Apps page shows), listed as not in the current config until retention clears it, unless the entry reuses that key as a quoted table name (`[hassette.apps."apps.lights.LightsApp"]`, verified to load); and that `hassette-client` and `hass-hassette` must be updated along with the server, since released clients fail on the apps endpoints without `auto_loaded`. Unknown-key tests pin both removed keys in their TOML and `HASSETTE__APPS__*` env forms.

### D12: What does the add-on's seeded first run show?

**Deciding factor:** what a newcomer sees on their very first add-on start.

| | A: ship the seed entry active | B: keep it commented; let the warning teach |
|---|---|---|
| First start does something visible | yes, the example runs | a WARNING with a snippet |
| Teaches "every app needs an entry" | by example | by the warning |
| Example app runs on first start (as today) | yes | no |

**Recommendation:** A; a working first run shows the entry format directly, and the warning still covers the newcomer's second file.
**Pick B instead if** the first run should demonstrate the warning itself.
**Reversibility:** easy
**Ratified:** Chose shipping `docker/addon/seed/hassette.toml` with `[hassette.apps.example_app]` uncommented over leaving it commented, to keep a working first run that shows the entry format, accepting that the add-on's first start doesn't demonstrate the warning. The seed header and `docs/pages/getting-started/addon/configuration.md` are rewritten to say each app needs an entry.

## Assumed

- The harness already builds explicit, non-auto-loaded manifests on main; only `TestConfig`'s `{"autodetect": False}` default references autodetect. Evidence: `src/hassette/testing/app_harness.py` `synthesize_manifest` (no `auto_loaded`, `instance_name` `ClassName.0`); `src/hassette/testing/config.py:116,148`.
- `set_validated_app_manifests` is called from startup, config reload, and the harness; with autodetect gone it validates explicit entries only, so it no longer needs to run after the `.env` import (the ordering comment in `core.py` goes). Evidence: `core/core.py:164-165`, `config/config.py:478`, `testing/_harness.py:93`.
- `run_apps_pre_check` skips `auto_loaded` manifests only because they were already imported by autodetect; with none left, the skip is deleted. Evidence: `utils/app_utils.py:142`.
- `app_manifests.auto_loaded` has no index, view, or FK, so `ALTER TABLE app_manifests DROP COLUMN auto_loaded` in `014.sql` is sufficient. Evidence: `migrations_sql/011.sql`.
- `hassette_wire.apps` declares `auto_loaded: bool` as required, so the newest released client fails to parse responses without it, which `uv run nox -s client_compat` will report, and the oasdiff gate (`tools/check_wire_compat.py`) reports the removed required response property as ERR (entries per D5). Evidence: `wire/src/hassette_wire/apps.py:48`; CLAUDE.md (Workspace Packages).
- Spec 133 D5 (snake_case default for auto-loaded apps) and spec 128's autodetect references are superseded; 133 is `ratified` (not terminal) and gets an `## Addendum` entry, 128 is `built` and gets one too. Evidence: `design/specs/133-log-identity-axes/design.md`, `design/specs/128-config-paths-and-unknown-keys/design.md`.
- Removing the "auto" badges changes rendered `.tsx`, so the PR needs a Screenshots section or the `no-visual-change` label, and schemas/types regenerate via `uv run python scripts/export_schemas.py --types`. Evidence: `.claude/rules/design-completeness.md`.
- Tests, tooling, and fixtures outside `src/` depend on autodetect or carry `auto_loaded`, and change at build time. The list below is the notable subset, not exhaustive; the build works from `grep -rniE "auto_loaded|autodetect|auto-detect|auto_detect"` over `tests/`, `tools/`, `scripts/`, `frontend/src/`, `wire/tests/`, `docs/`, and `src/` (the hyphenated form catches prose). `tests/integration/database/test_database_service_migrations.py` likely asserts the migration head and moves to 014. System tests that relied on discovery get explicit `[hassette.apps.*]` manifests (`tests/system/test_app_lifecycle.py`, `test_cli_smoke.py`, `test_hass_hassette.py`, `test_startup_without_ha.py`, `test_project_layouts.py`, `test_sigint_shutdown.py`, `tests/system/conftest.py`); `{"autodetect": False}` test dicts are deleted (`tests/data/config/hassette_apps.toml`, `tests/unit/cli/test_commands_run.py`); `tests/unit/test_autodetect_apps*.py` are deleted or rewritten for the scan; seed, tooling, mock, and frontend fixtures drop `auto_loaded` (`scripts/seed_scenarios/base.py`, `tools/client_compat_live_state.py` including its "seven keyword arguments" count, `tests/e2e/mock_fixtures/manifests.py`, `tests/support/*`, `tests/integration/test_dashboard_without_ha.py`, `frontend/src/test/{factories,config-fixtures}.ts`, `wire/tests/test_lenient.py`, `tests/TESTING.md`); `config/classes.py:215`'s `display_name` default loses its `auto_loaded` branch. `tests/unit/tools/fixtures/client_floor/v0.55.0-openapi.json` is a frozen release spec and stays unchanged. Evidence: grep for `auto_loaded`/`autodetect` across `tests/`, `tools/`, `scripts/`, `frontend/src/test/`, `wire/tests/`.
- The external `NodeJSmith/hassette-addon` repo (written by the `bump-addon` release job) was not inspected; before merge, grep it for `autodetect`, `exclude_dirs`, `HASSETTE__APPS__AUTODETECT`, and `HASSETTE__APPS__EXCLUDE_DIRS` and remove any hit before this release ships, or every add-on user hits D11's unknown-key failure. Evidence: CLAUDE.md (Workspace Packages, `bump-addon`); this repo's `docker/` has no references.
- Docs that teach "drop a file in and it runs" must change: `docker/addon/seed/hassette.toml`, `docker/addon/seed/apps/example_app.py`, `docs/pages/getting-started/addon/configuration.md`, `docs/pages/getting-started/docker/index.md`, `docs/pages/core-concepts/configuration/index.md`, `docs/pages/core-concepts/configuration/snippets/file_discovery.md` (including its `--check` note), `docs/pages/getting-started/home-assistant-integration.md` ("An auto-detected…" display-name line), `docs/pages/testing/factories.md`, the `check_config` docstring in `src/hassette/cli/commands/run.py` ("Autodetected apps are skipped…"), `examples/hassette.toml`, `examples/README.md`, `scripts/demo_apps/hassette.toml`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- Startup's apps-directory warnings come from one pure function, `app_startup_warnings` in `utils/app_utils.py`, which `startup_tasks` logs: D6/D9's behavior is then pinned by asserting its return value rather than by capturing logs.
- The scan walks with `os.walk`, which skips unreadable directories instead of raising, and prunes built-in exclusions by directory name; the apps directory's own absolute parts are checked once up front.
- The suggested key uses pydantic's `to_snake`, already a dependency, rather than a new helper.
- System tests configure their fixture apps through `app_entries`/`with_app_entries` (`tests/system/conftest.py`), which build entries from the scan keyed by class name, so existing class-name lookups (`find_app`, `TOGGLED_APP in key`) keep working; the SIGINT test passes the same entries as nested `HASSETTE__APPS__<KEY>__<FIELD>` env vars (a JSON value on the key is ignored; see `known-issues.md` KI-001).
- `make_test_config` drops its `apps` default entirely instead of replacing it: with no autodetect there is nothing to turn off.
- `examples/hassette.toml` and `scripts/demo_apps/hassette.toml` gain an explicit `security_monitor` entry, the one example that relied on autodetect.
- The Quickstart (`docs/pages/getting-started/index.md`) also relied on autodetect; it now creates `hassette.toml` with a `[hassette.apps.my_app]` entry, and its sample output shows the `my_app` key. The Apps-page doc drops the "auto" chip row.
- `tools/wire_compat_ignore.txt` repeats #2509's identical `/api/apps … auto_loaded` line under #3145, so this break stays accepted if that older block is cleared first.
- The `--check` test now writes an unconfigured app that raises on import and asserts `--check` neither imports it nor prints a warning (D8).
- `LATEST_MIGRATION_VERSION` in `hassette.testing.config` moves to 14 with `014.sql`.
- The external add-on repo was checked (shallow clone, 2026-10-20): no `autodetect`, `exclude_dirs`, or `HASSETTE__APPS__*` references.
- The scan returns an `AppScan` (unconfigured classes plus unreadable files) so `app_startup_warnings` can name unparseable files in "No apps found" (D9) without a second walk.
