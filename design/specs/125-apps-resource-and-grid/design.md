# Design: Reshape the apps resource and Apps grid

**Date:** 2026-10-04
**Status:** ratified
**Mode:** sketch

## Summary

Issue #2509. `DashboardAppGridEntry` re-declares `AppManifestResponse`'s fields, and `manifest_response_fields()` in `src/hassette/web/mappers.py` exists only to keep the two lists in step (#2448 item (c)). This ledger reshapes the grid row and the apps resource to remove that duplication. The decisions below hold the shapes and names; the remaining wire renames are spec 126's.

The generated artifacts are regenerated with `uv run python scripts/export_schemas.py --types` (writes `frontend/openapi.json`, `frontend/ws-schema.json` and the generated TS under `frontend/src/api/`), and frontend code naming a changed schema is updated to match.

**Calibration:** hassette is greenfield with about three known users, and no consumer is known to depend on these models, the HTTP shapes, or the CLI JSON. Decisions optimize for the correct model, not for minimizing breakage. Breaks are still listed in this ledger's D9 footer.

**Origin:** split from spec 122 (`design/specs/122-wire-contract-tightening/design.md`), where every decision below was ratified, challenged and combed together. Decision numbers keep their spec-122 ids. Order of the four ledgers: 123 (vocabulary) and 124 (health) are independent; 125 (apps resource and grid) builds on 124; 126 (naming and docs) goes last. All four land before #2386.

Builds on spec 124: `AppActivity` carries `health: AppHealth` (spec 124 D13).

Related: #1825 (show app health in the CLI app table) becomes straightforward once `hassette app list` reads the grid (D10). #1894 (manifest cache invalidation across query paths) touches the event D16 renames.

Out of scope: surfacing D12's marker in the web UI; minimum-server-version policy for `hassette-client` (#2386).

## Decisions

### D7: How does the contract express the app + activity join behind the Apps grid?

**What the classes serve.** `AppManifestResponse` (renamed `AppSummary` by D15) is what an app *is*: its config identity, lifecycle status and instances. It's served by `GET /api/apps/manifests` (in a list) and `GET /api/apps/{app_key}/manifest`, and read by the sidebar, the app shell, the logs app picker, app detail, and `hassette app list`. `DashboardAppGridEntry` is served by `GET /api/telemetry/dashboard/app-grid` and read by the Apps page (`frontend/src/pages/apps.tsx` via `toAppRow()` in `frontend/src/utils/app-data.ts`) and `hassette dashboard` (`src/hassette/cli/commands/status.py`). It copies the 14 manifest fields and adds how the app is *doing* over a time window.

**Cause.** The grid endpoint joins two concepts (the app and its activity), and the contract expresses that join by copying fields. `manifest_response_fields()` exists to keep the copies in step. The join itself is deliberate: #1464 (`7cb36c58`) replaced a client-side two-source merge (`mergeManifestsAndGrid()`) with this single endpoint, because the split version could show inconsistent state during the hot-reload race window.

**Deciding factor:** the contract states what the data is before #2386 pins it, without bringing back the race #1464 fixed.

| | A: Shared base model, flat JSON | B: Composition: grid entry = `{app: AppSummary, activity: AppActivity}` | C: Separate endpoints, client joins |
|---|---|---|---|
| Cause or symptom | Symptom: the join stays implicit | Cause: the join is named in the contract | Cause, but moved to the client |
| #1464 race | Not affected | Not affected (still one server-side join) | Reintroduced |
| JSON | Unchanged | Breaking for the grid endpoint | Breaking |
| Churn | Generated types | `toAppRow()` (already the single flattening point), test factories/handlers, CLI columns (`Column` in `src/hassette/cli/output.py` supports dot paths), the path-removed compat-ignore entries (D11); the new path's shape has no compat baseline until the next release tag | The Apps page goes back to two queries |
| Client author's view | Two flat models that happen to share 14 fields | A row is an app plus its activity, so `AppSummary` code is reused directly | Two calls to coordinate |

Under B:
- `AppActivity` is the activity fields spec 124 left flat on the grid row: `handler_count`, `job_count`, the `total_*` counts, `activity_buckets`, `blocking_event_count`, the `last_error_*` fields, and `health: AppHealth` (spec 124 D13).
- `manifest_response_fields()` is deleted.
- The route builds the nested `app` with `app_manifest_response_from()`, minus its `recent_invocations_1h` argument (D10).
- The mappers of types this ledger renames or creates are renamed after the wire type they build: `app_manifest_response_from`, `app_manifest_list_response_from`, and the grid-row construction. The build picks the target names and records them as build-time calls. Mappers of types spec 126 renames are that ledger's.
- Pointers to the old names are updated where this ledger changes them: `src/hassette/web/REVIEW.md`, and the example in `.claude/rules/web-api.md`'s Enrichment bullet, which cites the `recent_invocations_1h` enrichment that D10 deletes.

**Recommendation:** B. The concrete gains over a flat subclass:
- `activity` is one object whose parts D12's degradation marker can name, and whose window D12's `since` echo describes.
- `AppSummary` stays free of activity fields (see D10).
- Nothing added to the app summary later leaks into grid rows by inheritance.

Under the Summary's calibration, the JSON break is not a cost worth trading these for.

**Pick A instead if** you want #2448 to change no JSON, and accept the duplication as a known symptom. C is listed to rule it out.
**Reversibility:** hard after #2386 (the JSON shape is pinned); easy before.
**Ratified:** Chose composition (B) over a shared base (A) and split endpoints (C), to name the app + activity join in the contract while keeping #1464's single server-side join, accepting a breaking grid-JSON change and its frontend/CLI churn.

### D10: Where does `recent_invocations_1h` go?

**Deciding factor:** `AppSummary` describes the app only. The field is activity data on the app summary, read only by `hassette app list`'s "Invoc/1h" column (`src/hassette/cli/commands/app.py:47`); the frontend never reads it. Nested inside a D7 grid row, it would read 0.

| | A: Remove it from `AppSummary`; `hassette app list` reads the grid with `since` = now − 1h and shows `activity.total_invocations` | B: Keep it on `AppSummary`; the grid computes it too | C: Move it to the list envelope as `recent_invocations_1h: dict[str, int]` |
|---|---|---|---|
| `AppSummary` is pure | Yes | No | Yes |
| Activity appears once per grid row | Yes | No (also inside `app`) | Yes |
| `app list --json` | Each row goes flat → `{app, activity}` | Unchanged | Unchanged |
| Who sets "now" for the window | The CLI's clock, as the Apps page already does | Server | Server |
| Query | Swapped for the grid query, so the equivalence is pinned first and the old query deleted | Kept, and the grid needs it too | Kept, moved to the envelope |

**Recommendation:** A. It removes the smell instead of moving it, and `app list` becomes the same apps-with-activity view the Apps page uses. C is a client-side join, the shape #1464 removed.
**Pick B instead if** you want `hassette app list` left untouched until #2387 moves the CLI. **Pick C instead if** you want `app list` on the app list endpoint (D16: `GET /api/apps`).
**Reversibility:** easy before #2386.

Under A:
- With `since` set, the grid's `activity.total_invocations` counts app-tier handler invocations in the window.
- The old query (`get_recent_invocations_1h_all_apps` in `src/hassette/core/telemetry/execution_queries.py`) builds its joins and filters differently. For the same seeded DB, its count equals `activity.total_invocations` with `since = now - 3600`. That equivalence is pinned before the switch.
- Afterwards, `get_recent_invocations_1h_all_apps` and its enrichment blocks in `get_app_manifests`/`get_app_manifest` (`src/hassette/web/routes/apps.py`) are deleted.
- `hassette app list --json` prints a bare array today (`cmd_app` dumps the manifest list); after the switch it dumps the grid rows, so each element becomes `{app, activity}`.
- The command runs the heavier grid query (buckets, last errors, blocking counts).

**Ratified:** Chose removing the field and reading the grid (A) over keeping it (B) and the envelope map (C), to model one apps-with-activity resource with activity in one place, accepting nested `app list --json` rows and client-computed windows matching the Apps page. Re-ratified after the challenge corrected the side-effect description.

### D11: Do the stale "Dashboard" names change?

**Deciding factor:** names the client pins should name what they serve. The grid has fed the Apps page since #710 (`fcfc4d6a`), and no dashboard page exists.

| | A: Rename the classes only: `DashboardAppGridEntry`→`AppGridEntry`, `DashboardAppGridResponse`→`AppGridResponse` | B: A, plus the endpoint path `/telemetry/dashboard/app-grid`→`/telemetry/app-grid` | C: Leave as-is |
|---|---|---|---|
| Pinned class names accurate | Yes | Yes | No |
| HTTP path | Unchanged | Breaking (frontend and CLI updated; compat-ignore entries) | Unchanged |
| Scope | Same rename pass as this ledger's other renames | Adds a route change | None |

The `hassette dashboard` command keeps its name because it moves with the CLI in #2387. Under B, only its path constant changes. The route function `dashboard_app_grid` and the frontend's `getDashboardAppGrid` are renamed to match the path.

**Recommendation:** B, because the grid endpoint already breaks under D7, so renaming its path at the same time gives the endpoint one breaking moment instead of two.
**Pick A instead if** you want the path left unbroken. **Pick C instead if** you'd rather keep this PR's renames to spec 126's D1/D2.
**Reversibility:** classes are hard after #2386; the path is a breaking change at any time.
**Ratified:** Chose renaming the classes and the endpoint path (B) over classes only (A) and leaving as-is (C), to take the grid endpoint's one breaking moment together with D7's JSON change, accepting a route change, frontend/CLI path updates, and compat-ignore entries for the old path.

### D12: What shape does the grid's degradation marker and window echo take?

This comes from Finding 2 of the sketch challenge, which chose a response-level marker plus a `since` echo. Today each grid enrichment query (`get_all_app_summaries`, `get_per_app_activity_buckets`, `get_per_app_last_errors`, `get_blocking_event_counts`, in the grid route in `src/hassette/web/routes/telemetry.py`) fails as one all-apps unit and degrades to empty defaults at 200. Zero invocations classifies as healthy (`"excellent"` in `activity.health.health_status` after spec 124). `.claude/rules/web-api.md` ("Enrichment (partial data at 200)") describes this pattern, but no response reports it today.

**Deciding factor:** a client knows exactly which parts of `activity` are missing and what window the counts cover, with the fewest new names.

| | A: `degraded: list[OpenGridEnrichment] = []` plus `since: float \| None = None` on `AppGridResponse`, where `GridEnrichment = Literal["summaries", "activity_buckets", "last_errors", "blocking_counts"]` | B: `degraded: bool = False` plus `since` |
|---|---|---|
| Says which part is missing | Yes | No |
| New public names | `GridEnrichment` plus its `Open` alias | None |
| Grows when an enrichment is added | One `Literal` value (open, so lenient clients tolerate it) | Nothing |

Behavior to pin:
- Each enrichment query that fails appears in `degraded` by its `GridEnrichment` value. A fully successful response has `degraded == []`.
- `since` echoes the request's value. `None` means all-time totals, with empty buckets and no last errors.
- `hassette app list` and `hassette dashboard` print a one-line warning to stderr naming what degraded, so the table output stays clean.

`.claude/rules/web-api.md`'s Enrichment bullet gains a sentence: a route whose response model carries a degradation marker reports each degraded enrichment in it.

**Recommendation:** A, because "which part is missing" is what tells a client whether `health` is trustworthy: summaries degraded means it isn't, buckets degraded means it is.
**Pick B instead if** you consider any degradation reason enough to distrust the whole row.
**Reversibility:** hard after #2386, easy before.
**Ratified:** Chose a list of degraded enrichments (A) over a boolean (B), so a client knows whether `health` is trustworthy, accepting the new `GridEnrichment` name and its `Open` alias.

### D15: What happens when a spec 126 D1 rename collides with an existing hassette name?

This comes from the sketch comb. This ledger renames the internal colliders (`ListenerSummaryRow`, `LogRecordEntry` or build-chosen names) so spec 126's wire renames have free names.

| Wire name spec 126's D1/D2 would produce | Already exists | Visibility |
|---|---|---|
| `AppConfig` (would collide if `AppConfigResponse` were a record; listed to document why it keeps its suffix) | `hassette.AppConfig` (`src/hassette/app/app_config.py:10`, the base class app authors subclass) | Public, top-level `hassette.__all__` |
| `AppManifest` | `hassette.config.AppManifest` (`src/hassette/config/classes.py:104`, the type of `App.app_manifest`) | Public, `hassette.config.__all__` |
| `ListenerSummary` | `hassette.schemas.listener_models.ListenerSummary` (the server's per-listener query row) | Internal |
| `LogEntry` | `hassette.logging_.LogEntry` (`src/hassette/logging_.py:63`) | Internal |

**Deciding factor:** a name means one thing across the hassette ecosystem, with no import aliasing.

| | A: Wire names never reuse a public `hassette` name; internal collisions are fixed by renaming the internal class | B: Rename anyway and alias at import sites | C: Colliding names keep their `*Response` suffix |
|---|---|---|---|
| `AppConfig` | `AppConfigResponse` stays: under spec 126's D1 rule it is an aggregate view | `hassette_wire.AppConfig` next to `hassette.AppConfig` | Stays `AppConfigResponse` |
| `AppManifest` | The wire record becomes `AppSummary`, pairing with `JobSummary`/`ListenerSummary` | Two public `AppManifest`s with different shapes | Stays `AppManifestResponse`, an exception to the rule |
| Internal collisions | The internal classes are renamed (e.g. `ListenerSummaryRow`, `LogRecordEntry`; the build picks names that say what they are) | Aliased | n/a |
| Rule stays mechanical | Yes, plus one clause | Yes | No: a hidden exception list |

**Recommendation:** A, because two public types with one name and different shapes is the confusion spec 126's D1 exists to remove, and renaming internal classes is free under the calibration.
**Pick B instead if** you consider `hassette_wire` a namespace app authors never import. **Pick C instead if** you accept a short exception list.
**Reversibility:** hard after #2386.
**Ratified:** Chose no public-name reuse with `AppSummary` for the wire manifest record (A) over aliasing (B) and suffix exceptions (C), to keep one meaning per name across `hassette` and `hassette_wire`, accepting renames of two internal classes.

### D16: Where does the app resource live, and does "manifest" stay on the wire?

This comes from the sketch comb, run 2. After D15, the record is `AppSummary` (its `status_counts` typing came from spec 123), but "manifest" still names its paths (`GET /api/apps/manifests`, `GET /api/apps/{app_key}/manifest`), its WS refetch event (`app_manifests_changed`: `AppManifestsChangedData`/`AppManifestsChangedWsMessage`, emitted from `src/hassette/core/runtime_query_service.py` and consumed by `frontend/src/hooks/use-websocket.ts`), and its status enum (`ManifestStatus`). The list envelope `AppManifestListResponse` becomes `AppListResponse` (this ledger owns the rename). The natural path `GET /api/apps` (`get_apps` in `src/hassette/web/routes/apps.py`) serves `AppStatusResponse`, an in-memory live-instance view. No production code calls it. The frontend, the CLI, the client and the docs don't. Its dependents are tests and generated or exported surface: `tests/system/test_web_api.py`, `tests/integration/web_api/test_endpoints.py`, `test_problem_details.py` and `test_auth.py` (the endpoint), `tests/unit/web/test_mappers.py` (`app_status_response_from`), `tests/unit/core/test_runtime_query_service.py` (`get_app_status_snapshot`), `AppStatusResponse` in `hassette_wire.__all__`, and the generated `frontend/openapi.json` / `generated-types.ts`.

**Deciding factor:** one word for the app resource on the wire, and no orphaned endpoint.

| | A: Keep the "manifest" names; record why | B: Remove the orphan; the app resource lives at `/apps`; "manifest" leaves the wire |
|---|---|---|
| `GET /api/apps` | Keeps serving `AppStatusResponse`, which nothing calls | Deleted, with `AppStatusResponse`, `app_status_response_from` (`src/hassette/web/mappers.py`) and `get_app_status_snapshot` (route-only) |
| App list / one app | `GET /api/apps/manifests` / `GET /api/apps/{app_key}/manifest` | `GET /api/apps` → `AppListResponse` / `GET /api/apps/{app_key}` → `AppSummary`, beside `/apps/{app_key}/config`, `/source`, `/start` |
| List envelope field | `manifests` | `apps` (`AppListResponse.apps: list[AppSummary]`) |
| WS refetch event | `app_manifests_changed` | `apps_changed` (`AppsChangedData`/`AppsChangedWsMessage`); the frontend ships with the server |
| Status enum | `ManifestStatus` | `AppStatus` (unused in `src/`, `wire/` and `client/`; `OpenManifestStatus` → `OpenAppStatus`). The frontend's local `type AppStatus` in `frontend/src/components/app-detail/overview-tab.tsx` is renamed so it doesn't collide (build-time call) |
| Dead code left | An unused endpoint, a model and a mapper | None |

Hardcoded paths to update: `src/hassette/cli/client.py` (`_fetch_instances`, `_try_fetch_instances`), `frontend/src/api/endpoints.ts`, `docs/pages/cli/commands.md`, `tests/TESTING.md`. (`cmd_app`'s endpoint is set by D10 and D11, not here.)

"Manifest" stays as the internal term: the `app_manifests` table, `AppManifestInfo`, the telemetry queries, and `hassette.config.AppManifest`.

**Recommendation:** B, because it removes dead code and the vocabulary mismatch together, and nothing outside the tests notices the deletion.
**Pick A instead if** you want the app paths and the WS protocol left untouched.
**Reversibility:** hard after #2386.
**Ratified:** Chose removing the orphaned `GET /api/apps`, serving apps at `/apps` and `/apps/{app_key}`, renaming the list field `manifests` to `apps`, the WS event to `apps_changed` and `ManifestStatus` to `AppStatus` (B), over keeping the manifest names (A), so the wire uses one word for the app resource with no dead endpoint, accepting moved paths, a WS literal change and an enum rename.

### D9: Is the PR a breaking change (`feat!` with a `BREAKING CHANGE:` footer)?

**Deciding factor:** the changelog tells users what actually breaks. Spec 122's D9 ratified `feat!` with one `BREAKING CHANGE:` footer naming every break; this ledger's list is its share:
- The grid endpoint moves from `/api/telemetry/dashboard/app-grid` to `/api/telemetry/app-grid` (D11), and its rows become `{app, activity}` (D7)
- `hassette app list --json` and `hassette dashboard --json` rows go from flat to `{app, activity}` (D7, D10)
- `recent_invocations_1h` leaves the app summary. oasdiff scores removing an optional response property as `info`, so `tools/check_wire_compat.py` won't flag it; it is listed because the tool can't see it (D10)
- `GET /api/apps` (`AppStatusResponse`) is removed. The app list moves from `GET /api/apps/manifests` to `GET /api/apps`, and one app from `GET /api/apps/{app_key}/manifest` to `GET /api/apps/{app_key}`. The list envelope's `manifests` field becomes `apps`, the WS event `app_manifests_changed` becomes `apps_changed`, and `ManifestStatus` becomes `AppStatus`, and `OpenManifestStatus` becomes `OpenAppStatus` (D16)
- OpenAPI and WS-schema component names change: `AppManifestResponse`→`AppSummary`, `AppManifestListResponse`→`AppListResponse`, `DashboardAppGrid*`→`AppGrid*`, the WS manifests-changed classes, `ManifestStatus`→`AppStatus` (D11, D15, D16)
- `hassette_wire` root exports change: `AppStatusResponse` is removed, and the renamed types above (`AppSummary`, `AppListResponse`, `AppGridEntry`, `AppGridResponse`, `AppsChangedData`/`AppsChangedWsMessage`, `AppStatus`, `OpenAppStatus`) replace their old names; `AppActivity` and `GridEnrichment`/`OpenGridEnrichment` are added
- `AppGridResponse` gains `degraded` and `since` (D12). These are additive, listed for completeness

The PR body also gets a migration note for HTTP consumers (old paths → new paths; flat → `app`/`activity`; `apps_changed`).

Any compat-ignore lines come from `tools/check_wire_compat.py`'s output, and the header of `tools/wire_compat_ignore.txt` pairs them with `!` plus a footer.

**Recommendation:** `feat!` with exactly one `BREAKING CHANGE:` footer at the end of the PR body, naming every item above.
**Reversibility:** easy until merge.
**Ratified:** Chose `feat!` with one footer over `refactor:`, to report the path, JSON, CLI-output, WS and schema-name breaks.

## Assumed

- **Package isolation.** `hassette_wire` cannot import `hassette`, so any vocabulary shared with the server must be defined in wire. Evidence: `wire/src/hassette_wire/REVIEW.md` ("Package Isolation"); `wire/pyproject.toml` depends on `pydantic` only.
- **Open/closed vocabularies.**
  - Response fields typed with an enum or multi-value `Literal` use an `Open<TypeName>` alias (`Annotated[X | UnknownValue, LenientValue("X")]`). `SourceTier` and `LogLevel` are closed and stay strict.
  - This ledger's open vocabularies are `GridEnrichment` and the `AppStatus` (formerly `ManifestStatus`) keys.
  - "Open" means a Python client parsing with `LENIENT_CONTEXT` tolerates unknown values. `openapi.json` and `ws-schema.json` describe what the server emits, so consumers generated from them (the frontend's TS types and `ws-validator.generated.ts`) see closed enums, as spec 121 intends.

  Evidence: `design/specs/121-wire-lenient-unknown-enums/design.md` (D5, D14); spec 116 addendum 2026-10-03.
- **State left by spec 124.** `AppHealth` exists, the grid row carries a flat `health: AppHealth` in place of the loose health fields, and `AppHealthResponse` is gone.
- **State left by spec 123.** The vocabularies live in `hassette_wire`, and `status_counts` is `dict[OpenManifestStatus, int]` (renamed here by D16).
- **Generated TS.** `frontend/src/api/generated-types.ts`, `ws-types.ts` and `ws-validator.generated.ts` are regenerated, not hand-edited. Evidence: `scripts/export_schemas.py` docstring.
- **Required checks.** `tools/check_wire_compat.py` runs against the latest `v*` tag (v0.55.0) in both directions, and deliberate breaks go in `tools/wire_compat_ignore.txt` verbatim from its output. Evidence: the module docstring and the file header.
- **CLI column contract.** `tests/snapshots/cli_columns.json` records every CLI table's columns, and `tools/check_cli_drift.py` fails when it drifts. Evidence: `tests/snapshots/cli_columns.json` ("Invoc/1h" entry).
- **Tests encoding the old behavior.** `frontend/src/test/factories.ts` sets `recent_invocations_1h`; the tests listed in D16 call `GET /api/apps` and the deleted mapper and snapshot method. Evidence: those files.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

## Addendum
