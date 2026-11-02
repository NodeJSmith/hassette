# Design: Address app instances by name

**Date:** 2026-11-02
**Status:** ratified
**Mode:** sketch
**Issues:** #3100
**Parent:** design/specs/133-log-identity-axes/design.md
**Prior art:** design/research/2026-11-01-rekey-history-by-instance-name/prior-art.md

## Summary

Instance routes, wire models, `hassette-client`, the CLI's `--instance` and frontend URLs still address an instance by its position in the config list, so a reorder points a bookmark, script or status update at a different instance. Storage (#3098, spec 142) and the registry (#3099, spec 143) already key on the name. This change moves every address to the name and removes the interim index-to-name lookups, finishing the *Instance Identity* milestone.

Where each piece lives:

- **Instance routes:** `src/hassette/web/routes/apps.py`. The path parameter becomes `/apps/{app_key}/instances/{instance_name}/{start,stop,reload}`. `_require_valid_instance_index` becomes a name check against the manifest's configured names, and `_orphan_instance_permitted` becomes a name check against `registry.get_instances`, and orphans stay addressable for `stop` only. An unknown name answers `INSTANCE_NOT_FOUND`, whose description in `wire/src/hassette_wire/problems.py` moves to the name. `_run_app_action` and `ActionResponse` carry `instance_name`.
- **Telemetry and log filters:** `src/hassette/web/dependencies.py` replaces `InstanceIndexQuery`, `OptionalInstanceIndexQuery` and `DEFAULT_INSTANCE_INDEX` with one optional `instance_name` query parameter, and deletes `instance_name_filter`. `TelemetryFilters`, `src/hassette/web/routes/telemetry.py` and `src/hassette/web/routes/logs.py` pass the name straight to the queries, which already take it (spec 142). `GET /logs/recent` keeps requiring `app_key` with an instance filter.
- **Registry and outcomes:** `AppRegistry.instance_name` and `display_index` (`src/hassette/core/app_registry.py`) are deleted. `resolve_instance_info(s)` keeps returning configured names in config order, then orphans sorted by name, which is the order of `AppSummary.instances`. `ActionOutcomes` (`core/app_lifecycle_common.py`) and its callers, `_targets` in `core/app_lifecycle_start_stop.py` and the shutdown path in `core/app_lifecycle_instances.py`, stop carrying a display index.
- **Wire models and schemas (D1):** `wire/src/hassette_wire/apps.py`, `blocking.py`, `logs.py`, `telemetry.py`, `ws.py`; `src/hassette/schemas/app_outcomes.py`, `app_snapshots.py`, `listener_models.py`, `log_models.py`; `src/hassette/web/mappers.py`. `core/telemetry/registration_queries.py` selects `instance_name` for `ListenerSummary` and `JobSummary`. `ExecutionCompletedData.instance_index` is dropped with no replacement, since the frontend doesn't read it. `AppInstance` and `ActionResponse` docstrings move from index order to config order. `core/telemetry/blocking_findings.py` builds `BlockingFinding.instances` as D1 and D7 state.
- **Migration (D1):** new `src/hassette/migrations_sql/020.sql` drops `instance_index` from `log_records`, `blocking_events`, `listeners` and `scheduled_jobs`. Its writers and readers go with it: `core/telemetry/insert_params.py`, `repository.py`, `blocking_queries.py`, `core/registration.py`, `core/database_service.py`, `core/command_executor.py`, `core/execution_record_builder.py`, `core/execution_pipeline.py`, `core/bus_service.py`, `core/scheduler_dispatch.py`, `core/block_io_guard.py`, `core/loop_watchdog.py`.
- **`App.index` removal (D2):** the constructor parameter, attribute and `_APP_PUBLIC_API` entry in `src/hassette/app/app.py`; `core/app_factory.py`; `HassetteAppStateEvent.from_app` and `AppStateChangePayload` (`src/hassette/events/hassette.py`) and their use in `core/runtime_query_service.py`; the log identity stamp (`src/hassette/logging_.py`, `logging_processors.py`); the registration fill in `scheduler/scheduler.py`, `bus/bus.py` and `bus/listeners.py`. `resolve_instance_name` (`config/classes.py`) changes as D2 states.
- **Detector docstring (D6):** `ChangeSet.has_any_change` and `metadata_apps` in `src/hassette/core/app_change_detector.py`.
- **Client:** `client/src/hassette_client/client.py`. `action(instance: str | None)` and every telemetry method's `instance_name` parameter replace their index forms. `telemetry_filters` sends `instance_name`.
- **CLI:** `src/hassette/cli/client.py`, `cli/types.py`, `cli/commands/app.py`, `cli/commands/blocking.py`. `--instance` takes a name. `resolve_instance`, `resolve_instance_with_name`, `resolve_instance_or_none` and `_name_for_index` collapse to the check D4 settles. `app start|stop|reload --json` output replaces `instance_index` with `instance_name`, including under `outcomes`, the "server confirmed instance" warning compares names, and `fmt_instances` in `cli/commands/blocking.py` loses its index fallback.
- **Frontend addressing:** `frontend/src/utils/app-routes.ts` (`?instance=<name>`, `parseInstanceParam`), `frontend/src/api/endpoints.ts`, `pages/app-detail.tsx` (`isAddressableInstance` becomes membership in `manifest.instances`), `pages/apps-table-row.tsx`, `components/app-detail/multi-instance.tsx`, `components/app-detail/blocking-findings.tsx`, `components/shared/action-buttons.tsx` (`InstanceRef` loses `index`), `utils/breadcrumb-trail.ts`, `hooks/use-breadcrumbs.ts`, the query keys that carry an index, and `buildAnnotationMap` (`components/app-detail/code-tab.tsx`), which dedupes handler names per line because the parent page's rows span instances (D3).
- **Live status:** `frontend/src/state/store.ts`, `hooks/use-websocket.ts`, `utils/app-data.ts` (D5). `appStatusKey(app_key, instance_name)`. `AppStatusChangedData.instance_name` and `AppStateChangePayload.instance_name` become required, and the app key stays in the key because an orphan can briefly share a name with an instance under another app key (spec 143 D1).
- **Compatibility artifacts:** `tools/client_compat_ignore.txt`, `tools/wire_compat_ignore.txt`, regenerated schemas and frontend types (`uv run python scripts/export_schemas.py --types`), and `API_SCHEMA_VERSION` (`wire/src/hassette_wire/health.py`) going to 5 with `MIN_API_SCHEMA_VERSION` (`client/src/hassette_client/version.py`) following, per `.claude/rules/client-schema-floor.md`.
- **Doubles and fixtures:** `scripts/seed_scenarios/`, `tools/client_compat_live_state.py`, `tests/support/`, `tests/e2e/mock_fixtures/`, `src/hassette/testing/_simulation.py`, `src/hassette/testing/app_harness.py`, and any harness or event helper that takes `index`, which takes `instance_name` instead (D2).
- **Docs:** `docs/pages/cli/commands.md`, `cli/workflows.md`, `cli/configuration.md`, `core-concepts/apps/configuration.md`, `web-ui/python-client.md`, `web-ui/api-errors.md`, `web-ui/manage-apps.md`, `testing/harness.md`, plus affected `docs/_static/web_ui_*.png` through `scripts/capture_screenshots.py`.

**Out of scope:** moving stored history on a rename (parent D11 accepts a new history). Backfilling names on old rows. Bumping `hassette-client` in `hass-hassette`, which is that repo's own change, prepared in advance and released as soon as the new client is on PyPI (see D1).

## Posture

- **Failure handling:** loud and minimal, as in the parent. An action on an unknown name answers 404, with no fallback to another instance.
- **Compatibility:** break freely, pre-v1, as the parent accepts for instance routes, URLs and the client. `feat!` with one `BREAKING CHANGE:` footer, plus `client_compat` and `wire_compat` ignore entries. The footer is the one migration note: routes, client calls, `--instance` and URLs take names; the CLI's `--json` keys change; plus each accepted consequence in D1, D2, D3 and D4. An old `?instance=0` bookmark gets the URL correction D8 settles, with no translation layer.
- **Scope:** every acceptance criterion in #3100: routes, wire, client, CLI, frontend, columns, interim lookups, regenerated types, docs and screenshots.
- **Rollout:** one PR with one migration, shipped outright, no flag. No release separates this from #3098 and #3099.
- **Hardening:** project defaults.
- **Altitude:** `build`. One session builds it next, and this ledger cites files.

## Decisions

### D1: Does an integer position survive anywhere on the wire or in storage?

**Situation:** Parent D11 says `instance_index` becomes "display order only". Spec 143's Summary says #3100 removes it from wire models and tables. The issue names only `log_records`, `blocking_events`, `LogEntry.instance_index`, `BlockingInstanceRef.index` and `BlockingHandlerRef.instance_index`. But the integer also sits on `AppInstance.index`, `InstanceOutcome.instance_index`, `ActionResponse.instance_index`, `AppStatusChangedData.index`, `ExecutionCompletedData.instance_index`, `ListenerSummary.instance_index`, `JobSummary.instance_index`, and the `listeners` and `scheduled_jobs` columns (no longer in any index since migration 018). The stored values are written at registration or log time, so they go stale on a reorder that restarts nothing. Everything that needs order already gets it: `AppSummary.instances` is an ordered list.

**Deciding factor:** one identity on the wire and nothing positional left for a caller to misuse.

| | A: Remove it everywhere; order is list position | B: Keep only `AppInstance.index`, derived per response | C: Keep a display field on every model, as parent D11 worded it |
|---|---|---|---|
| Wire models with an index | None | One | All ten, with names added beside them |
| What identifies a row | `instance_name` everywhere; `ListenerSummary` and `JobSummary` gain `instance_name: str`, selected from the stored column, since neither carries it today (framework rows show the stored `__hassette__`). The global Handlers page shows it on each row (`frontend/src/pages/handlers-rows.tsx`), since that page mixes instances and `.claude/rules/design-completeness.md` requires a queryable field to be visible | Same | Index and name |
| Tables with the column | None; drop from all four | None; drop from all four | All four, stale after a reorder until the next upsert or forever for logs |
| Can a client still address by position | No field to try | Tempting; one field invites it | Yes |
| New code | None; the migration and deletions | The order derivation stays in `AppRegistry` | Refresh paths, or accepting stale values |
| Sorting that used the index | `BlockingFinding.instances` sorts by name, since the builder has no list order to keep | Same | Unchanged |
| Released `hassette-client` 0.61 (pinned by `hass-hassette`) | Required fields gone, so parsing fails: `AppInstance`, `InstanceOutcome`, `ActionResponse`, `JobSummary`, and the blocking refs. Defaulted fields, so it parses and reports instance 0 or none: `ListenerSummary`, `LogEntry`. Ignore entries, integration bump needed | Same for all but `AppInstance` | Parses, but an `instance` index it sends answers 404 on the changed routes, and its `instance_index` query parameter is ignored |
| Peer behavior | No peer has a comparable positional field (spec 142 D3); AppDaemon keys on the name | unknown | No peer does this |

**Recommendation:** A, because list position already gives display order, and a field called "index" is exactly the thing this milestone exists to remove. It supersedes parent D11's "display order only" wording and extends the issue's column drop to `listeners` and `scheduled_jobs`.
**Pick B instead if** some consumer needs order on a single instance outside its list. **Pick C instead if** keeping the released client parsing matters more than a clean wire.
**Reversibility:** hard (wire contract and a column drop)
**Ratified:** Chose removing the integer position from every wire model and all four tables, with order given by list position, over keeping one derived field or a display field everywhere, with `ListenerSummary` and `JobSummary` gaining `instance_name: str` so unfiltered rows stay attributable, so nothing positional is left to misuse, superseding parent D11's "display order only" wording and extending the issue's column drop to `listeners` and `scheduled_jobs`, accepting that released `hassette-client` 0.61 fails to parse the changed responses, or silently reports instance 0 or none for `ListenerSummary` and `LogEntry`, and that `hass-hassette` is fully unavailable from the add-on update until its own release pins the new client, a one-time window the release pipeline's order makes unavoidable (`bump-addon` runs in the release workflow, before the integration can pin a client that is on PyPI), and that a stale caller's `instance_index` query parameter is ignored and answers with every instance, both stated in the `BREAKING CHANGE:` footer (see Posture).

### D2: Does `App.index` survive?

**Situation:** `App.index` is a required constructor argument and is listed in `_APP_PUBLIC_API` (`src/hassette/app/app.py:42`). It's frozen at construction (spec 143 D3), and it goes stale after a reorder, add or remove (spec 143 KI-002). Its readers are `HassetteAppStateEvent.from_app`, the log identity stamp, and `Scheduler._resolve_registration_context` and bus registration, which fill `instance_index` on rows. With D1's A, every reader goes. Nothing in docs, `examples/` or the hautomate corpus reads `self.index`. `resolve_instance_name` (`src/hassette/config/classes.py`) has two callers and takes a required `index` for its error text: `AppManifest` validation, which has a block position, and `App.__init__`, which loses its value under A. `docs/pages/testing/harness.md` documents `index` on the harness.

**Deciding factor:** no public attribute that can be wrong.

| | A: Delete it, with the constructor parameter | B: Keep it, refreshed by `set_manifests` | C: Keep it frozen |
|---|---|---|---|
| Can be wrong | No | Between refreshes only | Yes |
| Readers left after D1's A | None needed | None | None |
| Public surface | Smaller; migration note | Unchanged, with a writer to maintain | Unchanged, misleading |
| Harness `index` argument | Removed; instances selected by name | Stays | Stays |
| `resolve_instance_name` | `index: int \| None = None`: `AppManifest` validation still passes the block's position so a load error can name the block, `App.__init__` passes none and still validates, and the message omits the position when there's none | Unchanged | Unchanged |
| Peer behavior | unknown | unknown | unknown |

**Recommendation:** A, because nothing would read it.
**Pick B instead if** D1 keeps an index for each instance. **Pick C instead if** you want no change to the `App` signature now.
**Reversibility:** easy (pre-v1)
**Ratified:** Chose deleting `App.index`, its constructor parameter and the harness `index` argument, with `resolve_instance_name` taking an optional position for config-load errors only, over keeping it refreshed or frozen, so no public attribute can be wrong, accepting a breaking change to the public `App` surface and the harness with a migration note.

### D3: What does a telemetry route mean when no instance is given?

**Situation:** `TelemetryFilters.instance_index` defaults to 0, so `GET /telemetry/app/{key}/health` and its siblings report the first configured instance. The blocking and log routes use an optional index, where absent means every instance. A default of "first" is positional: reorder the config and the same request reports a different instance. The frontend's app detail page relies on it (`resolvedInstanceIndex = instanceIndex ?? 0`), including on the multi-instance parent page, where it loads instance 0's listeners and jobs for the Code tab's line annotations.

**Deciding factor:** the same request means the same thing after a reorder.

| | A: Absent means every instance | B: Absent means first in config order | C: Required on these routes |
|---|---|---|---|
| Stable across a reorder | Yes | No | Yes |
| Single-instance app | Same result as today until a rename. After one, health totals include the old name's executions within the query window, until retention removes them. Handler and job lists exclude retired rows | Same as today | Every caller must also pass the name it configured |
| Multi-instance app, no filter | App-wide totals. The parent page fetches every instance's listener and job rows, whose only reader there is the Code tab | First instance, as today | 422 |
| Consistency | Matches blocking and logs | Two meanings of absent | Two rules |
| Whole-app views (the multi-instance parent page) | Served by the default | Needs its own way to ask | Needs an explicit way to ask for all instances, which is more route design |
| Queries | Already accept `None` as no filter (spec 142) | Needs a registry lookup, so `instance_name_filter`'s logic stays | None |
| Peer behavior | unknown | unknown | unknown |

**Recommendation:** A, because the parent page is a real view of a multi-instance app as a whole, so app-wide data has to be askable, and this gives it with no new route design. It also lets `instance_name_filter` go whole.
**Pick B instead if** existing scripts rely on `hassette app health --app x` meaning instance 0 on a multi-instance app. **Pick C instead if** you'd rather make every multi-instance query explicit.
**Reversibility:** easy
**Ratified:** Chose treating an absent instance as every instance, over first-in-config-order or requiring it, so the same request means the same thing after a reorder and `instance_name_filter` goes, accepting that a multi-instance request with no filter now returns app-wide totals, and that app-wide totals include retired names within the query window, an exception to "renaming starts a new history" tracked in #3751. This settles only what absence means for #3100; reworking how these routes treat a missing instance is out of scope and goes with #3751.

### D4: What happens when a read filter names an instance that doesn't exist?

**Situation:** Actions on an unknown name answer 404 by posture. Reads are different: telemetry rows outlive their instance, so a renamed instance's old name still has history until retention deletes it. Today an unmatched index resolves to a label that matches no row, so the API returns empty, and the CLI's `resolve_instance` errors on an unknown name with the list of known names (`_instance_not_found`).

**Deciding factor:** no registry lookup on the read path, and a CLI typo doesn't look like "no activity".

| | A: API returns empty; CLI checks against the app's instances first | B: API returns empty; CLI just passes it through | C: API answers 404 for a name not tracked or configured |
|---|---|---|---|
| CLI typo | Error listing known names, as today | Silent empty result | Error from the server |
| Retired name's history | API and client can read it; CLI refuses it | Readable everywhere | Unreachable |
| `--instance 0` from an old script | Error listing names | Silent empty result | Error |
| Read-path code | None on the server; the CLI keeps `_fetch_instances` and `_instance_not_found` | None | A registry check on every filtered query |
| Peer behavior | unknown | unknown | unknown |

**Recommendation:** A, because it keeps today's CLI error and the server stays a plain filter.
**Pick B instead if** reading a retired name's history from the CLI matters more than catching typos. **Pick C instead if** you'd rather have one rule for reads and actions than keep old history reachable.
**Reversibility:** easy
**Ratified:** Chose an API that returns empty for an unmatched name with the CLI checking the app's instances first, over a CLI pass-through or a server 404, so the server stays a plain filter and a CLI typo still errors with the known names, accepting that the CLI refuses a retired name whose history the API and client can still read.

### D5: Which instances does an app's rolled-up status count?

**Situation:** `liveIndices` (`frontend/src/utils/app-data.ts`) takes the cached `row.instances`, then probes forward through consecutive indices for instances only a WebSocket event has reported. Names can't be probed. Store entries are never removed, so if the rollup includes every name in the store for an app, a removed instance's last status (say, `failed`) keeps the app "degraded" until the tab reloads. An applied config change sends a refetch signal (see Assumed). `liveIndices` also feeds `appNeedsRestart`, which follows whatever rule the rollup does.

**Deciding factor:** a removed instance can't outlive the refetch on a row, with the least store machinery.

| | A: Count only the cached `row.instances`; WS overlays their status | B: Count every store entry for the app; prune entries on refetch | C: Count every store entry for the app; never prune |
|---|---|---|---|
| Added instance, before the refetch | Not in the rollup until the refetch | Counted immediately | Counted immediately |
| Removed instance | Counted until the refetch, then gone | Counted until the refetch | Counted until the tab reloads, possibly "degraded" forever |
| Store shape | Flat, unchanged | Needs app grouping or a prefix scan, plus a prune path | Needs app grouping or a prefix scan |
| Code | Deletes `liveIndices` and its probe | Replaces it, adds pruning | Replaces it |
| Peer behavior | unknown | unknown | unknown |

**Recommendation:** A, because the refetch follows within moments of an add, and the store stays a plain overlay.
**Pick B instead if** a just-added instance must count in the rollup before the refetch lands.
**Pick C instead if** the store should be the sole source of live membership and a stale row until reload is acceptable.
**Reversibility:** easy
**Ratified:** Chose counting only the cached `row.instances` with WebSocket status as an overlay, over counting store entries with or without pruning, with `appNeedsRestart` following the same rule, so a removed instance can't outlive the refetch and `liveIndices` goes, accepting that a just-added instance joins the rollup and its needs-restart count only after the refetch, and that a name which returns without a new event (a rename and rename-back on a disabled or `autostart=false` instance) can show its pre-removal status until reconnect or reload.

### D6: Does an order-only config edit broadcast a refetch?

**Situation:** `AppChangeDetector.detect_changes` compares with `DeepDiff(..., ignore_order=True)`, so a reorder reports no change and sends no refetch signal (see Assumed; spec 143 KI-003). The registry's manifests do update (`refresh_config` runs first), so the next fetch returns the new order. After this change, a stale row has the right name and acts on the right instance, so all that's left is row order, and any fetch fixes that. But `has_any_change`'s docstring promises "whenever the persisted manifest data differs". The issue accepts either a refresh or documenting it.

**Deciding factor:** least code for a rare, cosmetic staleness.

| | A: Document it; correct the docstring | B: Add order changes to `metadata_apps`, broadcasting a refetch |
|---|---|---|
| Row order after a reorder-only edit | Updates on the next fetch | Updates at once |
| Wrong-target risk | None, addressing is by name | None |
| Code | Docstring and a line in `core-concepts/apps/configuration.md` | A per-app ordered-names comparison in `detect_changes`, a test, and the docstring stays true |
| Frequency | A reorder with no other change, with a dashboard open | Same |
| Peer behavior | unknown | unknown |

**Recommendation:** A, because nothing is wrong except row order, and any fetch fixes that.
**Pick B instead if** you'd rather keep `has_any_change` literally true than carry an exception in its docstring.
**Reversibility:** easy
**Ratified:** Chose documenting that an order-only edit refreshes row order on the next fetch and correcting the `has_any_change` docstring, over broadcasting a refetch, to carry no new detector code for a rare cosmetic staleness, accepting that an open dashboard shows the old row order until its next fetch.

### D7: What does a blocking row with no stored name show?

**Situation:** `blocking_events.instance_name` is nullable. Rows recorded before #3095 can hold NULL (spec 142 KI-001) and age out within one retention window. Today the finding builder in `src/hassette/core/telemetry/blocking_findings.py` groups a NULL name by index, and the frontend renders `instance <index>`. With the index gone, those rows have nothing else to distinguish them.

**Deciding factor:** no code for rows that age out by themselves.

**Recommendation:** Keep `BlockingInstanceRef.name` as `str | None`, and give `BlockingHandlerRef` a new `instance_name: str | None` in place of `instance_index`, read from the blocking row's own `instance_name` and nullable only because that column is, merge all NULL rows of a finding into one ref that sorts after the named ones, render it as "unnamed instance", and link it with no `?instance=`.
**Pick "drop those rows from `instances`" instead if** you'd rather have `name: str` required, accepting that an old finding can list no instances until it ages out.
**Reversibility:** easy
**Ratified:** Chose nullable blocking name fields (`BlockingInstanceRef.name` as it is, `BlockingHandlerRef.instance_name` new) and merging a finding's NULL rows into one "unnamed instance" entry, sorted last, that links to the app page with no `?instance=`, over dropping them and requiring a name, to add no code for rows that age out, accepting that those old rows can't be told apart until retention removes them.

### D8: Where does a stale `?instance=` link go?

**Situation:** The URL correction in `frontend/src/pages/app-detail.tsx` (`instanceCorrectionUrl`) writes `instance: 0`, which has no meaning under names. An old numeric bookmark, or a link to a renamed or removed name, reaches it. Correcting to the first configured name would land a stale link on whichever instance is first today, and a reorder would change it.

**Deciding factor:** a corrected URL doesn't depend on config order, and needs no new UI.

| | A: Drop the param | B: Drop the param and show a notice | C: Correct to the first configured name |
|---|---|---|---|
| Stable across a reorder | Yes | Yes | No |
| Single-instance result | Normal app page | Normal app page, with notice | Normal app page |
| Multi-instance result | Parent page; the effect guarded by `showParentOverview` in `app-detail.tsx` moves `handlers` to `overview` | Same, with notice | One instance, chosen by position |
| Tells the user their link was stale | No | Yes | No |
| New code | Removes `instance: 0` | A notice and how long it stays | None |
| Peer behavior | unknown | unknown | unknown |

**Recommendation:** A, because it's stable and removes code, and the page it lands on already lists the instances.
**Pick B instead if** silently landing on the parent page would confuse more than a notice costs. **Pick C instead if** multi-instance links must always land on an instance, accepting that the target changes with config order.
**Reversibility:** easy
**Ratified:** Chose correcting a stale `?instance=` to the same page with no `instance` param, over adding a notice or correcting to the first configured name, so a corrected URL never depends on config order, accepting that the user isn't told their link was stale.

## Assumed

- Parent D11 holds except for its "display order only" wording, which D1 revisits: the name is the sole identity, unique across the config, and renaming starts a new history. Evidence: `design/specs/133-log-identity-axes/design.md` D11.
- Parent D5/D11's charset holds: a name starts with a lowercase letter and contains only lowercase letters, digits and `_`, so it is URL-safe with no encoding and can't be mistaken for a digit string. Evidence: `instance_name_reason` in `src/hassette/config/classes.py`.
- Parent "Applies to all" D6 holds: logger names stay readable labels derived from the instance name. Evidence: parent Breakdown.
- Telemetry queries already filter by `instance_name`, with `None` meaning no filter. Evidence: `core/telemetry/summary_queries.py`, `helpers.py`, spec 142 Summary.
- The lifecycle already takes names: no lifecycle method takes an index, and only outcome fields derive one, through `display_index`. Evidence: `AppLifecycleService.start_instance`, `stop_instance`, `reload_instance` signatures; spec 143 Summary.
- `instance_index` is in no index on `listeners` or `scheduled_jobs` since migration 018, so it can be dropped with `ALTER TABLE ... DROP COLUMN`, as migration 014 does. The newest migration is `019.sql`. A probe applying every migration to a scratch database on SQLite 3.45.1 found no index, view or trigger naming the column on any of the four tables, and all four drops succeeded with the `active_*` views still queryable. `DROP COLUMN` rewrites each table at startup: 3.49 s for 2,000,000 synthetic `log_records` rows (518 MB), not measured on slower storage such as an add-on's SD card. Rolling back means deleting the telemetry database, as with migration 018. Evidence: `src/hassette/migrations_sql/018.sql`, `014.sql`, `012.sql`; the sketch-challenge record (finding 11) in this directory's `review-log.jsonl`.
- Every applied config change broadcasts `APP_LOAD_COMPLETED`, which reaches the frontend as a refetch signal, except a reorder-only edit, where `handle_change_event` returns early. Evidence: `_reconcile_changes` and `handle_change_event` in `src/hassette/core/app_lifecycle_changes.py`.
- `hass-hassette` pins `hassette-client==0.61.0` exactly and calls only app-level actions, so its own instance addressing doesn't change. Its coordinator's one data call is `get_apps()`, so its pinned client fails every poll until it bumps. The schema bump doesn't surface this, because `check_server_version` is a floor: 0.61 passes against schema 5 and then fails at parse. Evidence: `pyproject.toml`, `custom_components/hassette/manifest.json` and `custom_components/hassette/coordinator.py` in that repo; its `tests/conftest.py`; `client/src/hassette_client/version.py`.
- The frontend doesn't read `ExecutionCompletedData.instance_index`: it stores the payload and uses it as a refetch trigger. Evidence: `setExecutionCompleted` in `frontend/src/state/store.ts`, `frontend/src/hooks/use-websocket.ts`; no match for that field outside generated types.
- Nothing in the hautomate corpus reads `self.index` or `instance_index`. Evidence: grep of `~/source/hautomate`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [ ] Ship-time challenge

**Calls made during the build:**
- The CLI's `--instance` check skips when the app list can't be read, for reads as well as actions: a telemetry outage must not block a start, stop or reload, and a read would fail on its own in that outage anyway. The server answers for the name then.
- A `/instances/{name}/...` on an app with no manifest and an untracked name answers `instance_not_found`, and with nothing tracked at all answers `app_not_found`: the first is a real orphaned app with a wrong name, the second is no app.
- `ActionOutcomes` keeps first-targeted order instead of re-sorting: `_targets` sorts names into display order on entry, and a name a config change adds during a reload goes after the existing ones.
- Seed scenarios keep an `instance_ordinal` helper argument, local to the generators, to name a class's nth seeded instance (`Class.N`). It writes only the name.
- `make_app_instance_info` and the e2e fixtures name a default instance `Class.0`, the shape the seed scenarios store, and the e2e manifests' `app_config` lists the same names, so routes accept what the UI sends.
- The released client's `{index}` route templates are in `EXCLUDED` (`tools/client_compat_coverage.py`) until a release ships the `{instance_name}` ones; a stale entry fails that check, so they come out with that release.
- The Handlers page shows `instance_name` as a muted suffix in the app cell, hidden on framework rows, and its handler link carries `?instance=`, since a multi-instance app's handler link without it bounces to the overview.
