# Design: Key telemetry rows by instance name

**Date:** 2026-11-01
**Status:** built
**Mode:** sketch
**Issues:** #3098
**Parent:** design/specs/133-log-identity-axes/design.md
**Prior art:** design/research/2026-11-01-rekey-history-by-instance-name/prior-art.md

## Summary

`listeners` and `scheduled_jobs` are keyed by `(app_key, instance_index, ...)`. The index is positional, so reordering or inserting a config entry moves history to a different instance. This change makes the natural keys `(app_key, instance_name, name, topic)` and `(app_key, instance_name, job_name)`, and moves reconcile scoping and telemetry filters to the name. Routes, wire models, client, CLI and frontend keep addressing instances by index until #3100, and the registry stays index-keyed until #3099.

Where each piece lives:

- **Schema:** new `src/hassette/migrations_sql/018.sql` adds the column and retires pre-migration app rows (D2), and swaps the natural-key indexes `idx_listeners_natural`, `idx_scheduled_jobs_natural` and the lookup indexes `idx_listeners_app`, `idx_scheduled_jobs_app` to the name.
- **Write path:** `instance_name` on `ListenerRegistration` and `ScheduledJobRegistration` (`src/hassette/core/registration.py`), filled by `bus_service.py` and `scheduler_service.py`, written through `core/telemetry/insert_params.py`. One function there, shared by both tables' inserts, is the only code that knows the reserved framework name (D2): framework tier stores `__hassette__`, app tier stores its name, and an app-tier `None` or `""` raises. `Resource.instance_name` stays `None` for framework resources, so framework log and blocking rows keep their NULL. Both `ON CONFLICT` targets in `core/telemetry/repository.py` change to match the new indexes exactly. Both upserts also set `instance_index = excluded.instance_index`, so a reorder refreshes the display value on the surviving row.
- **Reconcile:** `instance_index_clause` in `core/telemetry/reconcile_sql.py` becomes a name clause, and the parameter threads through `reconcile_registrations` (`repository.py`), `CommandExecutor.reconcile_registrations`, `reconcile_app_registrations` (`core/app_lifecycle_registrations.py`) and `initialize_instances` (`core/app_lifecycle_instances.py`).
- **Retiring unconfigured names:** `build_retire_removed_apps_query` in `reconcile_sql.py` and a new live-pairs builder beside `live_app_keys` in `core/database_retention.py` (D1). The manifest prune keeps using `live_app_keys`.
- **Fixtures and doubles:** `scripts/seed_scenarios/` sets `instance_name` on seeded registrations with `make_instance_name`. `tests/e2e/mock_fixtures/` and `tools/client_compat_live_state.py` wire `registry.instance_name` to those same names, so the Posture's `client_compat` claim holds without responses going empty. `tests/integration/telemetry/helpers.py` takes `instance_name` as a required parameter, and hand-written `INSERT INTO listeners` and `INSERT INTO scheduled_jobs` statements in tests name the column.
- **`instance_index` afterward:** stays on all four tables as a display value (D3). Registrations and log identity keep writing it, and #3100 removes it.
- **Queries:** the per-instance filters in `core/telemetry/summary_queries.py`, `helpers.py` (`log_record_filter_clauses` and the union fragment), `registration_queries.py`, `execution_queries.py` and `blocking_queries.py` take `instance_name: str | None` instead of `instance_index`. `None` means no instance filter, which is also what the all-apps listener list (`web/routes/bus.py`, no `app_key`) passes. `LISTENER_SUMMARY_SOURCE.tombstone_columns` in `registration_queries.py` gains `retired_at` (D4).
- **Index-to-name lookup, until #3100:** one helper in `src/hassette/web/dependencies.py`, used by `TelemetryFilters` and by the optional-index parameters in `web/routes/logs.py` and `web/routes/telemetry.py`. It returns `None` for a framework app key, because a framework key has exactly one instance, so those queries skip the name filter on all four tables and never compare against the reserved name. Otherwise it returns `AppRegistry.instance_name`. That method returns a display label for an index with no configured name, and the label can't pass name validation, so it matches no stored row and the query returns empty.
- **In-memory natural key:** the canonical tuple in `src/hassette/bus/bus.py` and `bus/wait_for_cancellations.py`, plus the natural-key wording in the `bus.py`, `bus/sync.py`, `bus/sync_events.py` and `bus/options.py` docstrings.
- **Docs:** `docs/pages/core-concepts/apps/configuration.md#instance-names` states that renaming starts a new history, that renaming back restores it as long as retention hasn't deleted the old rows, and that upgrading resets per-instance views. Parent D11 requires the rename statement.

**Out of scope:** backfilling names, rename or merge tooling, and a surrogate identity (no peer ships these; see the prior-art brief). The registry and lifecycle keys (#3099). Name-addressed routes, wire models, client, CLI and frontend (#3100). Two framework visibility gaps belong to the Diagnostic Evidence milestone (#20): routine framework executions aren't stored (`framework_record_sample_rate` defaults to `0.0`), and the web UI has no surface for framework rows.

## Posture

- **Failure handling:** loud and minimal, as in the parent. A failed migration fails startup. An index with no name returns an empty result and never falls back to another instance.
- **Compatibility:** break freely for stored history (pre-v1, accepted by parent D11). No API or wire change, since those belong to #3100, so `client_compat` needs no ignore entries. One deliberate exception: `GET /logs/recent` with `instance_index` and no `app_key` now answers `validation_failed` (see Build).
- **Scope:** minimal. Schema, write path, reconcile, telemetry queries, the temporary route lookup, tests, and the rename docs. No backfill, rename tooling or surrogate ID.
- **Rollout:** one PR with one migration, shipped outright. No flag.
- **Hardening:** project defaults. The issue's required challenge runs against the schema and startup reconciliation at the sketch-time challenge.
- **Altitude:** `build`. One session builds it next, and this ledger cites files.

## Decisions

### D1: How do rows under a name that's no longer configured get retired?

**Situation:** A live reload that changes one instance runs `_create_instance_unlocked` (`src/hassette/core/app_lifecycle_start_stop.py`), which reconciles only that instance. Renaming a config entry takes this path. Today that's safe, because a renamed instance keeps its index and its old rows stay in scope. Once scoping moves to the name, reconcile sees only the new name, so the old name's rows stay active. They drop out of the instance's own views, but old jobs still appear in the global jobs list (`get_job_summary` in `web/routes/scheduler.py`). Changing the instance count reloads the whole app and reconciles by `app_key`, so renames are the only affected path. A separate sweep already exists: the retention cycle retires rows of apps no longer in config or running (`build_retire_removed_apps_query`, called from `_run_parent_guard_deletes`), but it only compares `app_key`.

**Deciding factor:** one owner for "this registration is no longer configured", with the fewest new moving parts.

| | S: Extend the retention sweep to instance names | R: Reconcile also retires unconfigured names | A: Accept until the next full app start |
|---|---|---|---|
| Mechanism | The sweep compares `(app_key, instance_name)` against every configured name plus every running instance's name, instead of `app_key` alone. It returns and logs the pair, in wording that fits a rename. Must pin a rename mid-reload and an `autostart=false` section staying live | Instance-scoped reconcile gains one more statement covering names not configured for the app, and needs the manifest's names passed down | None, plus a docs line |
| Old rows leave the global jobs list | Within one retention cycle (default 1 hour) | At the reload | At the next Hassette restart or full app start |
| Rename frequency it pays for | Rare; same sweep also handles removed apps | Rare; adds a second retire path for it | Rare; costs nothing |
| New code | A live-pairs builder, one query, and the retirement log line | New statement plus threading through three layers | None |
| Peer behavior | Airflow retires absent registrations on its periodic parse, and its users filed a bug when a renamed DAG stayed listed (#11901) | Same outcome as Airflow, sooner | Matches that bug |

**Recommendation:** S, because it extends the one place that already owns this question, and a delay of up to an hour on a rare config edit costs little.
**Pick R instead if** old names lingering in the global jobs list for up to an hour would mislead you during debugging. **Pick A instead if** you'd rather carry no new code and rarely rename while Hassette keeps running.
**Reversibility:** easy
**Ratified:** Chose extending the retention sweep to compare `(app_key, instance_name)` against every configured name plus every running instance's name, over a new reconcile statement or accepting the delay, so one mechanism owns retiring anything no longer configured, accepting that a renamed instance's old rows can stay active for up to one retention cycle.

### D2: What does `instance_name` hold on framework rows and pre-migration rows?

**Situation:** Framework resources register rows too, under `__hassette__.*` app keys, and `Resource.instance_name` is `None` for them. SQLite treats NULLs as distinct in unique indexes, so a NULL name means `ON CONFLICT` never fires and every restart inserts a duplicate (confirmed with a probe on SQLite 3.45.1). Reconcile skips framework keys, so nothing would clean those up. Separately, pre-migration app rows have no name and must be retired per parent D11. Sibling instances can share a listener name and topic, so legacy rows can't all take one value under the new unique index. Framework identity isn't changing, so in both options framework rows are named in place and keep their history. Migration 015 shows a `NOT NULL DEFAULT` column can be added without a rebuild.

**Deciding factor:** the duplicate-row bug can't come back through a later code path.

| | A: `NOT NULL`, reserved framework name, legacy placeholders | B: Nullable, reserved framework name, legacy NULL |
|---|---|---|
| Framework rows | `__hassette__` (`FRAMEWORK_APP_KEY`), which D11's charset makes impossible for users | Same |
| Pre-migration app rows | Retired, named `__legacy__.<index>` so siblings stay distinct; also impossible for users | Retired, left NULL |
| A future write with no name | An explicit NULL is refused, so that registration fails loudly. The one write-side function (see Summary) raises first on an app-tier `None`. Omitting the column entirely would take the default, but the inserts always name it | Silently brings the duplicate rows back |
| Migration | `ADD COLUMN ... NOT NULL DEFAULT '__unset__'`, a value `instance_name_reason` rejects. Then `source_tier = 'framework'` sets `__hassette__`, and `source_tier = 'app'` sets `'__legacy__.' \|\| instance_index` and retires the row, then index swap. No rebuild (probed). Must pin that no row holds `__unset__` afterward | `ADD COLUMN`, one UPDATE, index swap. No rebuild |
| Oddity left in the schema | A default that real inserts never reach (015 has the same) and placeholder strings until retention removes them | NULL means "pre-migration" until retention removes the rows |
| Query code | Never handles NULL | Never handles NULL, since filters compare to a real name |
| Peer behavior | No peer evidence; SQLite sources call this the simplest form | No peer evidence; SQLite sources warn NULL needs workarounds in keys |

**Recommendation:** A, because the database then refuses the NULL that causes the bug, for the cost of one odd placeholder value that ages out.
**Pick B instead if** placeholder strings in a stored name column bother you more than relying on registration code to never write NULL.
**Reversibility:** hard (stored values in a shipped migration)
**Ratified:** Chose a `NOT NULL` `instance_name` on `listeners` and `scheduled_jobs` with `DEFAULT '__unset__'`, `__hassette__` on framework-tier rows (named in place, keeping their history) and `__legacy__.<index>` on retired app-tier rows, over a nullable column with legacy NULLs, so the database refuses the NULL that would cause duplicate registrations, accepting placeholder values until retention removes them and that a write with an explicit NULL fails registration loudly.

### D3: When does `instance_index` leave the log and blocking tables?

**Situation:** Parent issue 6 and #3098's acceptance criteria drop `instance_index` from `log_records` and `blocking_events` in this change. But the API still returns it until #3100: `LogEntry.instance_index`, and the required ints `BlockingInstanceRef.index` and `BlockingHandlerRef.instance_index`. The frontend uses them for instance links and labels (`frontend/src/utils/app-routes.ts`, `components/app-detail/blocking-findings.tsx`). Live log entries also carry it from logger identity (`LogIdentityFilter` in `src/hassette/logging_.py`). No peer has a comparable positional field, so there's no peer evidence.

**Deciding factor:** no temporary code that the next PR in the same milestone deletes.

| | K: Keep the columns until #3100; filters move to the name now | D: Drop now, derive the index from the registry for responses | W: Drop now, change the wire now |
|---|---|---|---|
| Reordering stops moving history | Yes, filters use the name | Yes | Yes |
| New temporary code | Only the index-to-name route lookup every option up to #3100 needs | That lookup, plus a name-to-index lookup at each response path, both deleted by #3100 | None, but it pulls #3100's work in |
| Rows for a name no longer configured | Keep their stored index | No index to return, but the blocking fields require an int, so a wire change anyway | Named directly |
| Links on old rows after a reorder | Point at the stored index, which can be stale (same as today) | Correct for configured names | Correct, once routes take names |
| Wire and `client_compat` | Unchanged | Changed for blocking | Breaking, frontend regenerated |
| Parent and issue | Supersedes parent issue 6's drop; #3098's criterion and #3100's scope need editing | Follows them | Merges two issues |

No release ships between #3098 and #3100, so K's in-between state reaches only `main` and its bleeding-edge image, and both migrations run in one upgrade for release users. `client_compat` still runs per PR, so wire breaks take ignore entries in whichever PR makes them. Running #3100 before #3098 also removes this conflict, but only swaps the route lookup's direction, puts the frontend work first, and leaves history moving in the meantime.

**Recommendation:** K, because the drop and the wire removal depend on each other, so they belong in one PR. The stored index meanwhile becomes the display-only value D11 calls for.
**Pick D instead if** the tables must stop storing the index in this PR regardless of temporary code. **Pick W instead if** you'd rather merge #3098 and #3100 into one PR.
**Reversibility:** easy (a later migration drops the columns either way)
**Ratified:** Chose K, keeping `instance_index` on `log_records` and `blocking_events` and moving its drop into #3100 with the wire fields, over dropping now with a registry lookup or merging the two PRs, superseding parent D3's "until issue 6 drops it" and the drop in parent Breakdown issue 6 while keeping parent D11's "display order only", so no temporary response-path code exists and the wire stays unchanged here, accepting that links on old rows can point at a stale index until #3100, that a tab, bookmark or CLI call holding an index from before a reorder shows the instance now at that index until #3100, and that the #3098 and #3100 issue bodies need editing.

### D4: Do retired listeners stay in listener summaries?

**Situation:** Listener summaries deliberately include retired rows (`LISTENER_SUMMARY_SOURCE.tombstone_columns` is only `removed_at`), while job summaries exclude them. The Handlers page reads the all-apps list from `GET /api/bus/listeners`. Once the migration retires every app listener and the next startup registers fresh rows, each handler with history appears twice on that page and in `hassette listener`, a `__legacy__.<index>` row and a live row, for up to the retention window (30 days by default). A renamed instance's old listeners stay listed the same way after D1 retires them. The list route also has no instance to resolve when `app_key` is `None`, so the lookup returns `None` there.

**Deciding factor:** no duplicate handlers after upgrade, with the fewest rules about when retired rows count.

| | F: Exclude retired listeners, as jobs do | G: Exclude them from the all-apps list only | H: Accept the duplicates |
|---|---|---|---|
| Handlers page after upgrade | One row per handler | One row per handler | Two rows per handler with history, for up to 30 days |
| App page for a handler removed from code | Handler leaves the table; its runs still count in health and activity | Handler stays listed | Handler stays listed |
| Rule to remember | One, shared with jobs | Listeners differ from jobs, and the all-apps list differs from the app page | Unchanged |
| Code | Add `retired_at` to one tuple; update `test_listener_summary_includes_retired` | A conditional in `build_registration_summary_query` | None |
| Peer behavior | Airflow marks absent DAGs deactivated and keeps their history; its default listing wasn't checked | Unknown | Same symptom as Airflow #11901 |

**Recommendation:** F, because it removes an inconsistency between listeners and jobs instead of adding a condition around it, and the runs stay reachable.
**Pick G instead if** the app page must keep listing handlers removed from code. **Pick H instead if** a month of duplicates after one upgrade doesn't matter to you.
**Reversibility:** easy
**Ratified:** Chose excluding retired listeners from listener summaries everywhere, matching job summaries, over excluding them only from the all-apps list or accepting duplicates, so each handler appears once after upgrade and listeners and jobs follow one rule, accepting that a handler removed from code leaves its app's table while its runs still count in health and activity.

## Assumed

- The instance name is the identity, and renaming starts a new history. Evidence: parent D11.
- Pre-migration rows get no backfill, so upgrading resets per-instance views for every instance, and those rows stay queryable by id until retention. Evidence: parent Posture and D11; peer brief, Pattern 1.
- Names are unique across the config, in a charset that excludes `_` as a first character and uppercase. Evidence: parent D5 and D11, shipped in #3095 (`430130ea`).
- `executions` keep their FKs because the parent rows are altered in place and never rebuilt. Evidence: `src/hassette/migrations_sql/001.sql`.
- Retired rows are deleted only after their executions age out, and an upsert clears `retired_at`, so a name that returns gets its history back. Evidence: `_run_parent_guard_deletes` in `src/hassette/core/database_retention.py`; `repository.py` upserts.
- Framework resources register at index 0, so naming framework rows in place can't collide under the new unique index. Evidence: `Resource.index` default in `src/hassette/resources/base.py`; no framework row with a non-zero index in the local and demo telemetry databases (2026-11-01); `self.index =` appears only in the app-tier `App` at v0.37.0, v0.40.0, v0.50.0 and v0.59.0. If this were wrong, 018 fails loudly and atomically and the database stays at 017, so a fixed 018 in a later release could still apply; `tests/unit/test_migration_018.py` pins that failure.
- `log_records` and `blocking_events` have no natural key, so a NULL `instance_name` loses nothing there and correctly means "no app subject". They keep it nullable. Evidence: `001.sql`, `005.sql`; framework log and blocking rows with NULL names in those databases.
- `SQLite` requires each `ON CONFLICT` target to match a unique index. Evidence: `repository.py` already relies on this; SQLite upsert documentation.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- `build_retire_removed_apps_query` renamed to `build_retire_unconfigured_instances_query`, and its log line now names removed or renamed instances: it no longer only concerns removed apps.
- `TelemetryFilters.query_kwargs` became a method taking `app_key`, and the dataclass gained a `HassetteDep` field: the lookup needs both, and FastAPI keeps the OpenAPI schema unchanged.
- `GET /logs/recent` with `instance_index` and no `app_key` now answers `validation_failed`. It used to filter on `lr.instance_index` across every app, so this is a deliberate wire change and the one exception to the Posture's "no API or wire change". Keeping that filter would add a path #3100 deletes, for a query no in-repo caller sends and whose meaning (position N in any app) is dubious. `validation_failed` is a global problem code, so the route doesn't declare it.
- `stored_instance_name` also refuses `""`, not only `None`: an App built outside config loading carries `AppConfig`'s empty default, and two under one key would merge rows. A hand-built App must now pass an `instance_name` before it registers anything.
- Blocking finding instance refs key on the name, falling back to the index for a row stored without one: one name at two indexes after a reorder is one instance, even though `instance_index` stays a display value (D3).
- Hand-written `INSERT INTO listeners`/`scheduled_jobs` in tests name `instance_name` only where the test filters by it; the others take the column default, and changing them would add noise to tests that don't exercise identity. This narrows the Summary's "name the column".
- D1's claim that renames are the only path leaving old rows active holds: `app_lifecycle_changes.py` reloads the whole app on a count change and each changed index otherwise, and only the latter reconciles by name.
