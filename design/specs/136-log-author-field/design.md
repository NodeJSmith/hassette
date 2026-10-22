# Design: Log author field and one default log filter

**Date:** 2026-10-22
**Status:** built
**Mode:** sketch
**Issues:** #3096

## Summary

Log records carry `source_tier`, which since #3173 (`f9f8df5d`) holds the writing logger's author (`LogIdentityFilter` in `src/hassette/logging_.py` stamps `record.source_tier = author`) while every other telemetry row uses `source_tier` for the owner tier. The parent ledger `design/specs/133-log-identity-axes/design.md` ratified the replacement: a log-only `author` field (D8), and one default in the log API, app-authored lines plus framework lines at ERROR and above, with one opt-in that's the same everywhere (D9). This change builds both. The hidden-lines indicator (#3188) and the "where do my app's logs go" page (#3189) are out of scope.

Where each piece lives:

- **Author on the record:** `LogIdentityFilter` stamps `record.author`; `_RECORD_FIELDS`, `LogRecordEntry` and `_extract_correlation_attrs` in `src/hassette/logging_.py` carry `author` instead of `source_tier`.
- **`LogAuthor` literal:** moves from `src/hassette/logging_.py` to `wire/src/hassette_wire/literals.py`, next to `SourceTier`, so the wire model, the API, the CLI and the client share one definition, typed as D5 states. `logging_.py` imports it from there. A `QueryAuthor` literal (`"app" | "framework" | "all"`) sits beside it for the query parameter and is exported from `hassette_wire` (`wire/tests/test_import.py` requires each submodule name to be exported or listed in `NOT_EXPORTED_NAMES`).
- **Level ordering:** `LOG_LEVELS` moves out of `src/hassette/web/dependencies.py` to `src/hassette/types/types.py` (D6), and the names at or above ERROR are derived from it there by numeric value, not hand-written. `web/dependencies.py`, `web/routes/logs.py` and `tests/unit/test_wire_vocabulary_typing.py` import from the new home.
- **Storage:** a new migration `src/hassette/migrations_sql/015.sql` on `log_records` (D1); `LOG_RECORD_COLUMNS` in `src/hassette/core/database_service.py`; the log queries in `src/hassette/core/telemetry/summary_queries.py` (`LOG_RECORD_SELECT` is `lr.*`, so `author` flows through it unchanged).
- **The one default:** an author-clause helper in `src/hassette/core/telemetry/helpers.py` next to `log_record_filter_clauses`, used by both `get_log_records` and `get_log_records_by_execution`. No author argument applies D9's default; `all`, `app` and `framework` behave as D9 states. Filtering moves from the client to this helper, ahead of each query's row `LIMIT`.
- **Wire and API:** `LogEntry` in `wire/src/hassette_wire/logs.py` and `src/hassette/schemas/log_models.py`; an `author` query parameter on `GET /api/logs/recent` (`src/hassette/web/routes/logs.py`) and `GET /api/executions/{execution_id}` (`src/hassette/web/routes/executions.py`), annotated once in `src/hassette/web/dependencies.py`. Regenerated `frontend/openapi.json` and generated frontend types.
- **Client:** `get_recent_logs` and `get_execution_logs` in `client/src/hassette_client/client.py` take `author`; `client/tests/test_openapi_coverage.py`'s `CALLS` table passes it; the client schema floor moves per `.claude/rules/client-schema-floor.md`; `tools/client_compat_ignore.txt` gets an entry only for each failure `uv run nox -s client_compat` prints (the released client's `source_tier` is optional, and stale entries fail the check). The `logs-recent` fixture request in `tools/client_compat_requests.py` (`ALL_TIERS`, sent as `source_tier=all`) moves to `author=all`; otherwise the server would apply the default and the fixture would silently stop returning the framework rows `scripts/seed_scenarios/adversarial.py` seeds for it.
- **CLI:** `hassette log` replaces `--source-tier` with `--author` (an `AuthorArg` in `src/hassette/cli/types.py`); `hassette execution` gains `--author` (`src/hassette/cli/commands/log.py`). Both show the marker (D4).
- **Web:** the shared log table in `frontend/src/components/shared/log-table/`. `use-log-filters.ts` stops filtering by tier client-side and loses `defaultTier` and the `?tier=` URL parameter; the author control (D2) is stored per viewer through `frontend/src/utils/local-storage.ts` and passed by `use-log-data.ts` into `getRecentLogs` (`frontend/src/api/endpoints.ts`), with the author state joining `queryKeys.recentLogs` so toggling refetches instead of serving the cached view; the control moves out of the `filters.app` block in `use-log-table.tsx`, which is skipped for per-app views and the execution panel, so it appears on every log view; `log-table-view.tsx` renders the marker (D3).
- **Fixtures and docs:** `scripts/seed_scenarios/` writes `author`; the e2e double for `get_log_records` in `tests/e2e/conftest.py` stamps `author` instead of `source_tier` and applies D9's default and `author` values the way the real query does, so e2e views hide what the real API hides; `docs/pages/operating/log-levels.md`, `docs/pages/cli/commands.md`, `docs/pages/core-concepts/database-telemetry.md`, `docs/pages/web-ui/python-client.md` and `docs/pages/web-ui/logs.md` drop the tier wording for logs, and `docs/pages/getting-started/snippets/run_output.txt` shows `author=` in the console tail (fed by `_RECORD_FIELDS`); screenshots of changed log views are regenerated.

## Posture

- **Failure handling:** loud and minimal, as in the parent ledger. `LogIdentityFilter` stamps an author on every record it sees, so new rows need no fallback.
- **Compatibility:** break freely (pre-v1). The rename of the log field and query parameter ships with a `BREAKING CHANGE:` footer and the client changes the Summary lists. Migrations do no backfill and retention ages old rows out, except where D1 says otherwise.
- **Scope:** narrowed #3096 only. The hidden-lines indicator (#3188) and the new docs page (#3189) are out. Existing docs, seed scenarios and test doubles that the rename breaks are in.
- **Rollout:** one PR, shipped outright. The rename can't be staged: renaming the field breaks the frontend's client-side tier filter and the CLI's `--source-tier` as soon as it lands.
- **Hardening:** project defaults.
- **Altitude:** `build`. One session builds it right after ratification.

## Decisions

### D1: What happens to log rows written before the migration?

Existing `log_records` rows have `source_tier` but no author. Rows written by released versions (≤ v0.59.0) hold the old owner-tier value, which labels an app's framework children (its Bus, Scheduler, Api loggers) as `app`. Only rows written since #3173 hold the true author. Logs are kept for `logging.log_retention_days` (default 30, `src/hassette/config/models.py:203`).

An app's own logger name ends in its instance name in every version: `hassette.apps.<instance_name>` since #3146 (`APP_LOGGER_PREFIX`, `src/hassette/app/app.py:28,182-185`), and `hassette.…<ClassName>.<instance_name>` before it (`430130ea`). Its framework children nest one level deeper and end in a class name (`Resource._get_logger_name`, `src/hassette/resources/base.py:180-186`; `….Lifecycle`, `src/hassette/app/app.py:192`). Each row stores `instance_name`, so the row itself can tell an app's own line from its children's.

**Deciding factor:** no legacy state carried into code or the wire, under the no-backfill posture.

D's rule: `app` when `logger_name` is outside the `hassette` namespace (the user's own module loggers, as `namespace_author` decides today) or ends in `.<instance_name>` for the row's `instance_name`; `framework` otherwise. Both tests are exact and case-sensitive: the suffix compares `substr(logger_name, -(length(instance_name)+1)) = '.' || instance_name`, and the namespace test is `logger_name = 'hassette' OR substr(logger_name, 1, 9) = 'hassette.'`, never `LIKE` or `GLOB` (case-insensitive, and `_`/`%` are wildcards: `LIKE` matches child `hassette.apps.api.Api` for instance `api`). Migration 015's header says the rule is a one-time legacy derivation, not a reusable author rule.

The rule is pinned for both logger-name formats it meets, since almost every row it rewrites was written by v0.59.0 (no release contains #3173 or #3146):
- v0.59.0: `hassette.<Class>.<instance>`, `hassette.<instance>` when the instance name starts with the class name, and children `….<instance>.<Child>` → app, app, framework (`v0.59.0:src/hassette/app/app.py:169-173`, `v0.59.0:src/hassette/resources/base.py:203-241`)
- current: `hassette.apps.<instance>` → app; `….Lifecycle` and other children → framework
- a lowercase instance whose child ends in the capitalized class (`api` / `hassette.apps.api.Api`) → framework, and an underscore instance (`my_app` against `hassette.MyApp.myXapp`) → framework
- a module logger outside the namespace → app; `py.warnings` → app; an in-namespace row with NULL `instance_name` → framework

| | A: Delete existing log rows | B: Keep rows; `author` NULL on old rows | C: Rename the column; old values become `author` | D: Keep rows; derive `author` from `logger_name` and `instance_name` |
|---|---|---|---|---|
| Legacy state in code | None: `author` is always set | `author: LogAuthor \| None` on the wire and in the DB; every filter and marker handles NULL | None | None outside the migration |
| Correctness of what's shown | Every row's author is true | True for new rows; old rows have no author | Old released rows mislabel framework lines about an app as `app` | True for app, child and framework loggers. Misses: captured warnings (`py.warnings`) all read `app`; a user's `self.logger.getChild(...)` logger reads `framework`; an instance named like a child class (`Bus`) reads that child as `app`; an instance named like the last part of a framework module logger (`scheduler` against `hassette.scheduler.scheduler`) reads that module's lines written in the app's context as `app`; an old app line stored without `instance_name` reads `framework` |
| What the user sees after upgrading | Log history starts at the upgrade | Old lines below ERROR show only with the opt-in, for up to 30 days | Old history shows by default, partly mislabelled | Old history shows by default, rare misses age out within 30 days |
| Fit with "no backfill" | Fits: nothing is backfilled | Fits | Keeps old values under a new meaning | A computed backfill: a posture exception |
| Migration | `DELETE`, `DROP COLUMN source_tier`, add `author` NOT NULL | `ADD COLUMN author`, `DROP COLUMN source_tier` | `RENAME COLUMN` | In place: `ADD COLUMN author TEXT NOT NULL DEFAULT 'framework' CHECK (author IN ('app','framework'))`, `UPDATE` by the rule, `DROP COLUMN source_tier`; no index changes |

**Recommendation:** D, because it keeps the log history and labels it correctly for every logger Hassette names, with no nullable field and no code outside the migration. Its misses are rare and age out with retention.
**Pick A instead if** losing up to 30 days of log history is fine and you want no backfill SQL at all. **Pick B instead if** history matters but no derived label should ever be shown. **Pick C instead if** a partly wrong label on old rows is acceptable in exchange for the simplest migration.
**Reversibility:** hard (the migration rewrites stored rows)
**Ratified:** Chose deriving `author` for existing rows from `logger_name` and the row's `instance_name` by the exact, case-sensitive rule above, in an in-place migration (`author` NOT NULL with an unused `'framework'` default and a CHECK), over deleting rows, NULL authors or renaming the column, to keep log history with true labels for every Hassette-named logger in both naming eras, accepting a posture exception for this one backfill (it supersedes the parent ledger's no-backfill line for `log_records` only); rare mislabels that age out with retention (captured warnings, user `getChild` loggers, v0.59.0 instances named like a child class or like the last part of a framework module logger, old app lines logged outside bound context reading `framework`); rows from unreleased builds since #3173 getting the derived author instead of their stamped one; a one-way migration (rolling back past 015 means deleting the telemetry DB); and that a very large log table on slow storage may time out the first start after upgrading, with the next start completing.

### D2: What does the author control in the web log views offer?

Today the shared log table has a three-way tier toggle (All / Apps / Framework; `TIER_OPTIONS` in `frontend/src/components/shared/log-table/constants.ts`), omitted on the execution panel (`use-log-table.tsx:175-179`). D9 replaces it with one opt-in, the same on every log view including the execution panel, remembered per viewer. The API accepts four states (default, `all`, `app`, `framework`).

**Deciding factor:** D9's "one opt-in", with the fewest controls a user has to understand.

| | A: Binary toggle (default ↔ `all`) | B: Four-way select (Default / All / Apps only / Framework only) | C: Three-way (Default / All / Framework only) |
|---|---|---|---|
| Matches D9's single opt-in | Yes | Exposes more than the opt-in | Partly |
| "Is it Hassette?" diagnosis | Turn it on; the marker shows which lines are framework | Framework only isolates them | Framework only isolates them |
| Controls to learn | One switch | Four states | Three states |
| Parity with CLI `--author` | CLI also offers `app`/`framework` for scripting | Full parity | Partial |
| Persisted state | A boolean | One of four values | One of three values |

**Recommendation:** A, because D9 settled on one opt-in, and with the marker on, the opt-in already answers "is it Hassette?". `app` and `framework` stay available in the API and CLI for scripting.
**Pick B instead if** you want the web UI to expose everything the API can do. **Pick C instead if** "show me only Hassette's lines" is a common enough web task to earn a control.
**Reversibility:** easy
**Ratified:** Chose a binary toggle between the D9 default (app lines plus framework ERROR+) and `author=all`, worded as showing framework lines below ERROR (not "apps only", since the default already includes framework errors), over a four- or three-way select, to keep D9's single opt-in with one switch, accepting that `app`-only and `framework`-only views exist only in the API and CLI.

### D3: How does the web log table mark framework-authored lines?

The table has a column picker (`use-column-visibility.ts`), so users can hide columns. Status badges use the shadcn `Badge` component (`.claude/rules/frontend-css.md`).

**Deciding factor:** the mark can't be hidden by accident, and app lines stay uncluttered.

| | A: Small badge at the start of the message cell, framework lines only | B: An "Author" column in the column picker | C: Row styling (muted text or tint) on framework lines |
|---|---|---|---|
| Can the user hide it by accident | No | Yes, by hiding the column | No |
| Noise on app lines | None | A cell on every row | None |
| Readable without colour | Yes (text label) | Yes | No |
| Mobile (message cell carries inline source today, `log-table-view.tsx:105-116`) | Fits inline | Column usually hidden at narrow widths | Fits |
| Sortable or filterable by author | No (D2's toggle reveals framework lines; it doesn't filter to them) | Sortable | No |

**Recommendation:** A, because the mark is the point of the change and a column can be hidden away. The label reads "Framework", matching the API value and the current toggle's wording.
**Pick B instead if** sorting by author in the table matters. **Pick C instead if** a text badge proves too loud next to the level badge.
**Reversibility:** easy
**Ratified:** Chose a "Framework" badge at the start of the message cell on framework-authored lines only over an Author column or row styling, so the mark can't be hidden and app lines stay clean, accepting that the table can't sort by author.

### D4: How does `hassette log` mark framework-authored lines?

`LOG_COLUMNS` and `EXECUTION_LOG_COLUMNS` (`src/hassette/cli/commands/log.py:15-30`) render tables through `render_table`; `--json` emits each wire field, so `author` appears there with no extra work.

**Deciding factor:** the same at-a-glance reading as the web badge, without widening every row.

**Recommendation:** an "Author" column in both tables showing `framework` on framework lines and blank on app lines. It's the same table mechanics as every other column.
**Pick a message prefix (`[framework] ...`) instead if** the table is already too wide on typical terminals.
**Reversibility:** easy
**Ratified:** Chose an "Author" column in the `hassette log` and `hassette execution` tables (`framework` on framework lines, blank on app lines) over a message prefix, to mark lines with the same table mechanics as every other field, accepting one more column of width.

### D5: Is `LogEntry.author` a closed or open vocabulary on the wire?

`wire/tests/test_lenient.py::test_every_response_vocabulary_field_is_open` fails any response field typed with a multi-valued `Literal` unless it's an `Open<…>` alias or listed in `CLOSED_VOCABULARIES` (today `SourceTier`, `LogLevel`). `wire/src/hassette_wire/__init__.py` requires a field added after the first published release to be optional with a default.

**Deciding factor:** match how the existing two-valued `SourceTier` is treated; author is binary by definition.

**Recommendation:** closed: add `LogAuthor` to `CLOSED_VOCABULARIES` (and the closed list in the `__init__` docstring), and type the field `author: LogAuthor | None = None`, optional on the wire even though the DB column is NOT NULL.
**Pick open (`OpenLogAuthor | None = None`) instead if** a third author value is plausible, so older clients should parse unknown values.
**Reversibility:** hard (closing or opening a released vocabulary is a wire change)
**Ratified:** Chose a closed `LogAuthor` vocabulary (in `CLOSED_VOCABULARIES`, field `author: LogAuthor | None = None`) over an open alias, to mirror `SourceTier` and keep author binary, accepting that adding a third author value later is a breaking wire change.

### D6: Where does the ordered level map `LOG_LEVELS` live?

The ERROR floor needs the names at or above ERROR in core telemetry. `LOG_LEVELS` is defined in the web layer (`src/hassette/web/dependencies.py:21-28`), and core telemetry imports nothing from web (`src/hassette/core/telemetry/helpers.py:7-16`), but it does import `APP_SOURCE_TIER` from `src/hassette/types/types.py`. `hassette_wire` is a released package of response models and their vocabulary.

**Deciding factor:** a home core and web both already import, without widening the public wire surface.

**Recommendation:** `src/hassette/types/types.py`, beside `APP_SOURCE_TIER`.
**Pick `hassette_wire.literals` instead if** clients need the numeric ordering too, beside `LogLevel`.
**Reversibility:** easy
**Ratified:** Chose `src/hassette/types/types.py` over `hassette_wire.literals` for `LOG_LEVELS` and the derived ERROR-and-above names, so core and web share one definition without adding a server-only constant to the public wire package, accepting that clients can't import the numeric ordering.

## Assumed

- The default, `all`, `app` and `framework` semantics, and that the UI and CLI pass the parameter instead of filtering, are settled by the parent ledger's D9. Evidence: `design/specs/133-log-identity-axes/design.md` D9.
- `author` replaces `source_tier` on log records only. Listener, job, execution and blocking-event rows keep `source_tier` as owner tier, and `QuerySourceTier`, `SourceTierQuery` and `APP_SOURCE_TIER` stay for those routes. Evidence: parent ledger D8; `src/hassette/web/dependencies.py:113-132`.
- D9's "execution log query" is `get_log_records_by_execution`, behind `GET /api/executions/{execution_id}`, which `hassette execution` and `HassetteClient.get_execution_logs` call. It has no tier filter today, so it gains both the default and the `author` parameter. The web execution panel reads `/api/logs/recent?execution_id=` instead (`use-log-data.ts:69`), so it gets the default through the general query. Evidence: `src/hassette/web/routes/executions.py:85`, `src/hassette/cli/commands/log.py:58-74`, `client/src/hassette_client/client.py:220`.
- The ERROR floor compares the stored level name, since `log_records.level` is TEXT holding names (`src/hassette/migrations_sql/001.sql:122-137`). `VALID_LOG_LEVEL_NAMES` is `frozenset(LOG_LEVELS)`, every name, so it isn't the floor set itself. Evidence: `src/hassette/web/dependencies.py:21-28`.
- Live updates need no separate filter: the WebSocket sends `log_hint` pings and the table refetches through the API. Evidence: `src/hassette/web/routes/ws.py:72`, `frontend/src/components/shared/log-table/use-log-data.ts:40-77`.
- No index is added for the default predicate: `get_log_records` walks `idx_lr_time` and filters until the `LIMIT` fills, which can slow down on very large tables dominated by framework DEBUG lines. Measuring that and adding an index if needed is #3192. Evidence: `src/hassette/migrations_sql/001.sql:139-141`, `src/hassette/core/telemetry/summary_queries.py:203-221`.
- `get_log_records` applies its `LIMIT` after its `WHERE`, so once the author clause is in the `WHERE`, framework lines no longer use up the fetch cap of a default view. Evidence: `src/hassette/core/telemetry/summary_queries.py:203-221`.
- Author and app (subject) are independent axes. The app dropdown no longer hides when the author control changes, and changing the author control no longer clears the app filter (both happen today: `use-log-table.tsx:201`, `use-log-filters.ts:305`). Evidence: parent ledger D1–D3.
- Nothing in the app links with `?tier=`, so dropping it needs no redirect. Evidence: `grep "tier="` in `frontend/src` finds only tests.
- `log_records` has no index on `source_tier`, so dropping the column in place needs no index change (`src/hassette/migrations_sql/001.sql:139-141`). SQLite adds a NOT NULL column when it has a non-NULL DEFAULT, as migrations `003`, `004`, `006` and `008` do, and drops one in place, as `014` does. The `'framework'` default is never reached by production writes, because the log insert names `:author` and raises when it's missing (`_LOG_INSERT_SQL`, `src/hassette/core/database_service.py:84-87`). Only raw-SQL fixtures that leave out `author` get it. The migration runner applies each migration as one `BEGIN IMMEDIATE … COMMIT` script before any writer starts (`src/hassette/core/migration_runner.py:95-114`). Evidence: `src/hassette/migrations_sql/001.sql:139-141`.
- Migration 015 must come before #3098's log-table migration, which drops `instance_index` and is chained after this one. Evidence: parent ledger Breakdown item 6.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- The D2 opt-in is `showAllFrameworkLogs` in the zustand store (`frontend/src/state/store.ts`), persisted through `utils/local-storage.ts` like the theme and sidebar state: one value every mounted log view shares, so toggling on one view changes them all.
- The control is `FrameworkLinesToggle`, a checkbox labelled "all framework lines" (tooltip: Hassette's errors always show), placed in each log view's table footer: the Logs page, the execution panel, the app logs panel and the app overview tab. The footer is the one slot every log view already renders.
- The Logs page's app filter now renders only when there are app keys; it used to host the tier toggle, so it rendered even with no apps.
- `tools/client_compat_requests.py`: the `execution-logs` fixture also sends `author=all`, not only `logs-recent`, so it keeps the framework rows the adversarial scenario seeds.
- `API_SCHEMA_VERSION` 2→3 (`wire/src/hassette_wire/health.py`) and `MIN_API_SCHEMA_VERSION` 3 (`client/src/hassette_client/version.py`): v0.59.0 reports 2, so this is the one bump for the next release.
- `get_log_records_by_execution` builds its `WHERE` through `log_record_filter_clauses`, the same path as `get_log_records`, so the author clause precedes its `LIMIT limit+1` and `truncated` counts only lines the view shows.
- `hassette.schemas.log_models.LogRecord.author` is required (`LogAuthor`), since the column is NOT NULL; the wire `LogEntry.author` stays optional per D5.
- The CLI marker formatter is `fmt_log_author` in `src/hassette/cli/formatters.py`; `AuthorArg` is typed with `hassette_wire.QueryAuthor`.
- `LogAuthor` is imported from `hassette_wire` in `logging_.py`, `app/app.py` and `resources/base.py`; `logging_` doesn't re-export it.
- A request carrying the old `source_tier` on the log routes gets the default view (FastAPI ignores unknown query parameters); `test_get_logs_recent_ignores_source_tier` pins that, since it is what a released client sees.
- Ship-time challenge F6: `LogRecordEntry.author` is required and `_extract_correlation_attrs` reads `record.author` directly; `LogPersistenceHandler.emit` routes a record that fails `record_to_dict` to `handleError`. It runs on the queue listener thread, where an escaping exception would stop persistence, so a record that skipped `LogIdentityFilter` now fails alone instead of failing its whole batch on the NOT NULL column.
- Ship-time challenge F7: chosen as "re-read `user_version` under the lock", built as a process-level `_RUN_LOCK` around `run_migrations` (`src/hassette/core/migration_runner.py`). The re-read releases the lock before `executescript()` takes it again (it commits any open transaction, even in autocommit mode on Python 3.14), and two overlapping runs could both pass the check; a code-review stress run reproduced that double-apply. The abandoned run and the next one share a process, so serializing whole runs makes the next run wait and then read the version the first one left, which is what D1's "the next start completes" relies on.
