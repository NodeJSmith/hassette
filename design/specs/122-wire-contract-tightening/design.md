# Design: Tighten the hassette-wire contract

**Date:** 2026-10-04
**Status:** abandoned
**Mode:** sketch

## Summary

Issue #2448. Once #2386 ships `hassette-client`, the `hassette_wire` package root (`wire/src/hassette_wire/__init__.py`) becomes the import surface that the client and the HA companion integration pin against. Before that happens, this change cleans up four things.

- **(a)** Response fields that carry a server-defined vocabulary but are typed `str` get a real type:
  - `JobSummary.schedule_status` and `schedule_status_reason` (`telemetry.py`)
  - `ServiceInfoResponse.role` (`health.py`)
  - `ServiceStatusData.role` (`ws.py`)
  - `ActionResponse.action` (`apps.py`)
  - the `AppManifestListResponse.status_counts` keys (`apps.py`)
  - `LogLevelResponse.effective_level` (`logs.py`)

  D3–D6 cover these, and D6 covers `LogLevelRequest.level`.
- **(b)** Public wire class names follow one mechanical rule (D1, D2, D15), and the app resource gets one wire vocabulary (D16).
- **(c)** `DashboardAppGridEntry` (`telemetry.py`) re-declares `AppManifestResponse`'s fields (`apps.py`), and `manifest_response_fields()` in `src/hassette/web/mappers.py` exists only to keep the two lists in step. The fix goes to the cause: the Apps grid endpoint's shape, path and window semantics (D7, D10, D11, D12).
- **(d)** Every class docstring and field description emitted into `frontend/openapi.json` or `frontend/ws-schema.json` is written for a contract consumer (D8). Two groups need work:
  - **Missing class docstrings.** D8 counts them, and its `D101` check finds them.
  - **Server-internal or history prose** to rewrite:
    - `Execution` ("Replaces the split `HandlerInvocation` / `JobExecution` models")
    - `JobSummary` ("returned by `get_job_summary()`")
    - `SessionRequest` (references `design.md` and `client.ts`)
    - `SessionResponse` (references `mint_session_cookie()`)
    - `ExecutionStatus` (references the `executions.status` CHECK constraint)
    - `AppStatusChangedData` and `ServiceStatusData` ("Mirrors `events.hassette.…`")
    - every class in `wire/src/hassette_wire/blocking.py` and `problems.py`

Fixing (c) at its cause also changes how app health is computed. The per-instance health endpoint and the grid get one shared health model, with one rule for removed registrations (D13, D14). That touches the telemetry queries in `src/hassette/core/telemetry/`.

The generated artifacts are regenerated with `uv run python scripts/export_schemas.py --types`, which writes `openapi.json`, `ws-schema.json`, and the generated TS under `frontend/src/api/`. Frontend code that names a renamed schema (`components["schemas"]["X"]`, `ws-types.ts`, test factories and handlers) is updated to match.

**Calibration:** hassette is greenfield with about three known users, and no consumer is known to depend on these models, the HTTP shapes, or the CLI JSON. Decisions optimize for the correct model, not for minimizing breakage. Breaks are still listed in the D9 footer.

Out of scope:
- Moving `CliFormat`/`CliFormatStyle` into `hassette-client` (#2386/#2387).
- Any change to which values a vocabulary holds.
- Client transport code.
- Minimum-server-version policy for `hassette-client` (#2386).
- Surfacing D12's degradation marker in the web UI.

## Decisions

### D1: Which naming convention do public wire classes follow?

**Deciding factor:** a rule a new type can be named from without consulting a list.

Today served models mix `*Response` (`AppManifestResponse`, `AppInstanceResponse`, `BootIssueResponse`) with bare nouns (`Execution`, `JobSummary`, `ActivityFeedEntry`, `BlockingFinding`, `StackFrame`). WS payloads are `*Data` except `ConnectedPayload`.

| | A: Role-based: records get bare nouns, everything else served over HTTP gets `*Response`/`*Request`, WS payloads `*Data`, WS envelopes `*WsMessage` | B: Every served HTTP model gets `*Response` | C: Fix only the WS outlier (`ConnectedPayload` → `ConnectedData`) and document the HTTP mix as-is |
|---|---|---|---|
| Predictable from the rule | Yes. A record keeps its name whether it's returned alone, in a list, or nested | Yes, but the suffix stops carrying meaning once everything has it | No. HTTP stays ad hoc |
| Renames | See the rename list below | ~15 (`Execution`, `JobSummary`, `ListenerWithSummary`, `ActivityFeedEntry`, `ActivityBucket`, `DashboardAppGridEntry`, all of `blocking.py`, `ProblemDetail`, ...) | 1 |
| Reads well in client code | `list[AppSummary]`, `AppInstance` | `StackFrameResponse` (also the persisted frame shape), `ProblemDetailResponse` (RFC 9457 name lost) | Unchanged |

Under A, the rule is mechanical:
- **Record (bare noun).** The type describes one domain object (an app, instance, health, activity, source, job, listener, execution, log entry, finding, frame, service, boot issue) wherever it appears. The element type of a list endpoint's rows is also a record (`AppGridEntry`, `ActivityFeedEntry`), even when it composes other records.
- **`*Response` / `*Request`.** Everything else served over HTTP: collections, aggregate views that bundle several things for one endpoint, probes, acknowledgements.
- **WS payloads** are `*Data`; WS envelopes are `*WsMessage`.
- **`ProblemDetail`** keeps its RFC 9457 name.
- **No reuse of public `hassette` names** (D15).

Renames this produces:
- `AppInstanceResponse`→`AppInstance`
- `AppManifestResponse`→`AppSummary` (D15)
- `AppManifestListResponse`→`AppListResponse` (it wraps `AppSummary`)
- `BootIssueResponse`→`BootIssue`
- `ServiceInfoResponse`→`ServiceInfo`
- `LogEntryResponse`→`LogEntry`
- `AppSourceResponse`→`AppSource`
- `AppHealthResponse`→`AppHealth` (D13)
- `ConnectedPayload`→`ConnectedData`
- `AppManifestsChangedData`/`AppManifestsChangedWsMessage`→`AppsChangedData`/`AppsChangedWsMessage`, and `ManifestStatus`→`AppStatus` (D16)
- `AppStatusResponse` is deleted (D16). D2, D7 and D11 add `ListenerSummary`, `AppActivity`, `AppGridEntry` and `AppGridResponse`; D12 adds `GridEnrichment`.

Staying `*Response`:
- `ActionResponse`
- `AppConfigResponse` (an aggregate view: config values, TOML and schema for one endpoint)
- `SystemStatusResponse`
- `LivenessResponse`
- `ReadinessResponse`
- `LogsByExecutionResponse`
- `LogLevelResponse`
- `SessionResponse`
- `ConfigSchemaResponse`
- `AppGridResponse` (new name, D11)
- `TelemetryStatusResponse`
- `JobTriggerResponse`
- `BlockingFindingsResponse`
- `UnattributedBlockingResponse`

The build applies the rule to every exported model and records any type it reclassifies beyond these lists as a build-time call.

The rule goes in the `hassette_wire/__init__.py` module docstring and as a question in `wire/src/hassette_wire/REVIEW.md`.

**Recommendation:** A, because it is the only option a new type can be named from without consulting a list. Under the Summary's calibration, rename count is not a cost.
**Pick B instead if** you want every HTTP body type identifiable by suffix alone. **Pick C instead if** you'd rather not churn names at all before #2386.
**Reversibility:** hard after #2386 ships (the names become the client's import surface); easy before it.
**Ratified:** Chose the mechanical record-vs-envelope rule (A) over uniform `*Response` (B) and WS-only (C), so a new type can be named from the rule alone, accepting the rename list above (re-ratified after challenge Finding 12; names adjusted by D15 and D16).

### D2: Does `ListenerWithSummary` become `ListenerSummary`?

**Deciding factor:** symmetry with its sibling `JobSummary`. Both are the per-registration rows of a list endpoint, and "With" describes how the server once built it, not what it is.

**Recommendation:** rename to `ListenerSummary` in the same pass as D1.
**Pick keep instead if** you want D1's renames kept to suffix fixes only.
**Reversibility:** hard after #2386, easy before.
**Ratified:** Chose renaming to `ListenerSummary` over keeping `ListenerWithSummary`, to match `JobSummary`, accepting one more rename in the same pass.

### D3: Where do the new vocabularies for (a) live?

**Deciding factor:** one definition per vocabulary. `hassette-wire` exists so the server and its consumers share one definition, and the existing precedent agrees: `ResourceStatus`/`ManifestStatus` live in `wire/src/hassette_wire/enums.py` and the server imports them.

The vocabularies: `ResourceRole` (`src/hassette/types/enums.py`), `ScheduleStatus` and `ScheduleStatusReason` (`src/hassette/scheduler/classes.py`), and `AppAction` (a `Literal` in `src/hassette/web/routes/apps.py`).

| | A: Move each existing `StrEnum` into `wire/src/hassette_wire/enums.py`, move `AppAction` into `literals.py`; old homes re-import (same public name from `hassette`); add an `Open<TypeName>` alias for each | B: Leave the server enums where they are; add mirror `Literal`s plus `Open*` aliases in `literals.py`, and a hassette-side test that each `Literal`'s values equal its enum's |
|---|---|---|
| Definitions per vocabulary | 1 | 2, kept in step by a test |
| `hassette` public API | `hassette.types.enums.ResourceRole` and `hassette.scheduler.classes.ScheduleStatus` keep resolving (re-export) | Unchanged |
| Spec 121 compliance ("no `Literal`→`StrEnum` conversion") | Yes. Existing enums move; no `Literal` is converted | Yes |
| Schema shape | Field becomes a `$ref` to a named enum component (`ResourceRole`, ...) | Inline `enum` on the field |
| Lets the CLI drop its hand-synced action copy (`src/hassette/cli/commands/app.py:28-33`) | Yes, `AppAction` becomes importable without the route layer | No |

At the move, class and member docstrings are rewritten for a contract consumer, with no references to `Job`, `Scheduler.register()`, the heap, or `Resource` inheritance. Scheduler-internal detail that app authors need moves to `docs/pages/core-concepts/scheduler/management.md`. Internal-only members (`ResourceRole.CORE`, `ResourceRole.BASE`, `ScheduleStatusReason.LEGACY_UNKNOWN`) get text that tells a consumer what the value means when received. `ResourceRole` uses `auto()`, and its member values must not change across the move.

**Parity with the SQL CHECK constraints.** Once these fields are typed, server-side parsing is strict, so a single row outside the vocabulary fails the whole response. Each SQL CHECK constraint's value list (from the migration that currently defines it under `src/hassette/migrations_sql/`) must equal the values of its wire enum or `Literal`. The columns covered are `schedule_status` and `schedule_status_reason` (`ScheduleStatus`/`ScheduleStatusReason`), plus the existing `status`, `mode` and `source_tier` checks. The CHECK-parity question in `wire/src/hassette_wire/REVIEW.md` gains the two schedule columns and points to that check.

**Recommendation:** A, because it removes the second definition instead of guarding it.
**Pick B instead if** you consider `ScheduleStatus`/`ResourceRole` server-domain types that shouldn't be published as wire vocabulary.
**Reversibility:** easy (moving a type back behind a re-export is mechanical).
**Ratified:** Chose moving the vocabularies into wire (A) over mirrored Literals (B), to keep one definition per vocabulary, accepting consumer-facing docstring rewrites at the move and a CHECK-parity test across all five constrained columns (re-ratified after challenge Findings 10 and 11).

### D4: What does `ServiceInfoResponse.role` hold when no role is known?

**Deciding factor:** narrow the type without inventing a sentinel. Today the field defaults to `""` ("Empty string when not available"). Every construction site passes `child.role.value` (`src/hassette/core/runtime_query_service.py:329-335`), and every `Resource` has a role, so `""` is never actually emitted. `ResourceRole` already has an `UNKNOWN` member.

| | A: `role: OpenResourceRole` (required, no default) | B: `role: OpenResourceRole \| None = None` | C: keep `= ""` by widening the type to allow `""` |
|---|---|---|---|
| Matches what the server emits | Yes | Yes (`None` never emitted) | Yes |
| Wire compat (old client, new server) | A required field that was optional: oasdiff flags it in the reversed direction | Nothing new required; `""` → `null` is a type change only for a value never sent | None |
| Type honesty | Exact | Admits a state that can't happen | Keeps a fake sentinel in the vocabulary |

`ServiceStatusData.role` is already required (`ws.py`), and only its type narrows. Server-side construction without `LENIENT_CONTEXT` rejects an out-of-vocabulary `role`, and the same holds for `schedule_status`.

**Recommendation:** A, because the server always has a role, and `ResourceRole.UNKNOWN` already covers "unclassified". The compat finding is recorded in `tools/wire_compat_ignore.txt`.
**Pick B instead if** you want zero compat-ignore entries from this item.
**Reversibility:** easy before #2386.
**Ratified:** Chose required `OpenResourceRole` (A) over optional (B) and the `""` sentinel (C), to type the field exactly as the server emits it, accepting a compat-ignore entry for optional→required.

### D5: How is `status_counts` typed?

The field lives on `AppManifestListResponse`, which D1 renames `AppListResponse`.

**Deciding factor:** typed keys without a new model. The server always fills every `ManifestStatus` (D16: `AppStatus`) key with a count, zero included (`MANIFEST_STATUS_KEYS` in `src/hassette/schemas/app_snapshots.py:13,101`).

| | A: `dict[OpenAppStatus, int]` (`OpenManifestStatus` before D16) | B: a `ManifestStatusCounts` model with one `int = 0` field per status | C: keep `dict[str, int]` and document the keys |
|---|---|---|---|
| Schema | `propertyNames: $ref` to the status enum component (verified with pydantic 2.12) | Named object, one property per status | Untyped keys |
| New status from a newer server | Lenient: the key parses as `UnknownValue` (verified) | Ignored extra field, so the count is silently dropped | Passes as a string |
| Generated TS | `{ [key: string]: number }` (openapi-typescript ignores `propertyNames`; key typing is Python-only) | Fixed interface | `{ [key: string]: number }` |
| New public names | None | One | None |

A `status_counts` holding an unknown key parses leniently and round-trips unchanged through `model_dump(mode="json")`.

**Recommendation:** A, because it types the keys through the existing open alias and keeps unknown statuses visible.
**Pick B instead if** you want the generated TS to guarantee every key is present. **Pick C instead if** you consider the keys display-only.
**Reversibility:** easy before #2386.
**Ratified:** Chose `dict[OpenAppStatus, int]` (A) over a counts model (B) and untyped keys (C), to type the keys with no new public name, accepting that key typing is Python-only because generated TS ignores `propertyNames` (re-ratified after challenge Finding 13).

### D6: Does `LogLevelRequest.level` narrow to `LogLevel` too?

**Deciding factor:** request validation in the schema versus today's lenient input. Today `level: str` accepts any case and the route upper-cases it, then rejects unknown names with a `VALIDATION_FAILED` problem (`src/hassette/web/routes/logs.py:96-102`). `LogLevelResponse.effective_level` narrows to the closed `LogLevel` regardless: the route sets the target logger to a validated name, so its effective level is always one of the five (`src/hassette/web/dependencies.py:20-27`).

| | A: Keep `level: str`; document the accepted names, case-insensitive, in the field description | B: `level: LogLevel` (strict, uppercase only) |
|---|---|---|
| Behavior change for callers | None | `"debug"` starts failing with a 422 |
| Schema tells a client the valid values | Description only | Yes, as an `enum` |
| Error path | One route-level check (current) | Pydantic 422, and the route check becomes dead code |

**Recommendation:** A, because a request field accepting more than the response emits is fine, and B breaks lowercase callers for no contract gain.
**Pick B instead if** you want the request vocabulary machine-readable and accept case-sensitive input.
**Reversibility:** easy.
**Ratified:** Chose keeping `level: str` with documented case-insensitive values (A) over strict `LogLevel` (B), to avoid breaking lowercase callers, accepting that the schema lists the values only in prose.

### D7: How does the contract express the app + activity join behind the Apps grid?

**What the classes serve.** `AppManifestResponse` (D15: `AppSummary`) is what an app *is*: its config identity, lifecycle status and instances. It's served by `GET /api/apps/manifests` (in a list) and `GET /api/apps/{app_key}/manifest`, and read by the sidebar, the app shell, the logs app picker, app detail, and `hassette app list`. `DashboardAppGridEntry` is served by `GET /api/telemetry/dashboard/app-grid` and read by the Apps page (`frontend/src/pages/apps.tsx` via `toAppRow()` in `frontend/src/utils/app-data.ts`) and `hassette dashboard` (`src/hassette/cli/commands/status.py`). It copies the 14 manifest fields and adds how the app is *doing* over a time window.

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
- `AppActivity` holds the grid's per-app activity, with its fields set by D13.
- `manifest_response_fields()` is deleted.
- The route builds the nested `app` with `app_manifest_response_from()`, minus its `recent_invocations_1h` argument (D10).
- Every surviving mapper in `src/hassette/web/mappers.py` is renamed after the wire type it builds (e.g. `app_manifest_response_from`, `app_manifest_list_response_from`, `instance_response_from`, `to_listener_with_summary`). The build picks the names and records them as build-time calls.
- Pointers to the old names are updated: `src/hassette/web/REVIEW.md`, `.claude/rules/design-completeness.md` (`ListenerWithSummary`), and the example in `.claude/rules/web-api.md`'s Enrichment bullet, which cites the `recent_invocations_1h` enrichment that D10 deletes.

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
- `hassette app list --json` already prints a bare array (`cmd_app` dumps `result.manifests`), and each element becomes `{app, activity}`.
- The command runs the heavier grid query (buckets, last errors, blocking counts).

**Ratified:** Chose removing the field and reading the grid (A) over keeping it (B) and the envelope map (C), to model one apps-with-activity resource with activity in one place, accepting nested `app list --json` rows and client-computed windows matching the Apps page. Re-ratified after the challenge corrected the side-effect description.

### D11: Do the stale "Dashboard" names change?

**Deciding factor:** names the client pins should name what they serve. The grid has fed the Apps page since #710 (`fcfc4d6a`), and no dashboard page exists.

| | A: Rename the classes only: `DashboardAppGridEntry`→`AppGridEntry`, `DashboardAppGridResponse`→`AppGridResponse` | B: A, plus the endpoint path `/telemetry/dashboard/app-grid`→`/telemetry/app-grid` | C: Leave as-is |
|---|---|---|---|
| Pinned class names accurate | Yes | Yes | No |
| HTTP path | Unchanged | Breaking (frontend and CLI updated; compat-ignore entries) | Unchanged |
| Scope | Same rename pass as D1 | Adds a route change | None |

The `hassette dashboard` command keeps its name because it moves with the CLI in #2387. Under B, only its path constant changes. The route function `dashboard_app_grid` and the frontend's `getDashboardAppGrid` are renamed to match the path.

**Recommendation:** B, because the grid endpoint already breaks under D7, so renaming its path at the same time gives the endpoint one breaking moment instead of two.
**Pick A instead if** you want the path left unbroken. **Pick C instead if** you'd rather keep this PR's renames to D1/D2.
**Reversibility:** classes are hard after #2386; the path is a breaking change at any time.
**Ratified:** Chose renaming the classes and the endpoint path (B) over classes only (A) and leaving as-is (C), to take the grid endpoint's one breaking moment together with D7's JSON change, accepting a route change, frontend/CLI path updates, and compat-ignore entries for the old path.

### D12: What shape does the grid's degradation marker and window echo take?

This comes from Finding 2 of the sketch challenge, which chose a response-level marker plus a `since` echo. Today each grid enrichment query (`get_all_app_summaries`, `get_per_app_activity_buckets`, `get_per_app_last_errors`, `get_blocking_event_counts`, in the grid route in `src/hassette/web/routes/telemetry.py`) fails as one all-apps unit and degrades to empty defaults at 200. Zero invocations classifies as `health_status: "excellent"`. `.claude/rules/web-api.md` ("Enrichment (partial data at 200)") describes this pattern, but no response reports it today.

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

### D13: One shared app-health model, computed in one place

This comes from Finding 9 of the sketch challenge, which chose to extract a shared sub-model.

What the two models share today:
- `AppHealthResponse` (`wire/src/hassette_wire/telemetry.py`) is served per instance by `GET /api/telemetry/app/{app_key}/health` (`app_health` in `src/hassette/web/routes/telemetry.py`) and read by `hassette app health`.
- It and the grid's activity fields compute the same concept the same way: `compute_error_rate()` → `classify_error_rate()` / `classify_health_bar()`.
- `last_activity_ts` is the latest handler or job execution in both.

Scope is the only legitimate difference (one instance vs. all instances of an app). Two discrepancies are not explained by scope:
- The grid's `avg_duration_ms` is the handler-only average (`build_app_summaries` in `src/hassette/core/telemetry/helpers.py` takes it from the listener query alone, `COALESCE`d to `0.0`). The per-instance model has `handler_avg_duration`/`job_avg_duration`, and job averages exclude `skipped`.
- The two queries apply different removed-registration rules (D14).

**Deciding factor:** one definition of app health, computed one way, with scope as the only difference.

| | A: Shared `AppHealth` record | B: Keep both shapes, document the scope difference |
|---|---|---|
| `AppHealth` fields | `error_rate`, `error_rate_class`, `health_status`, `last_activity_ts`, `handler_avg_duration_ms: float \| None`, `job_avg_duration_ms: float \| None`. The two averages are renamed from `handler_avg_duration`/`job_avg_duration`, and become `None` when nothing ran | Unchanged |
| Per-instance endpoint | Returns `AppHealth`, replacing `AppHealthResponse` | Unchanged |
| `AppActivity` (grid) | `handler_count`, `job_count`, the `total_*` counts, `activity_buckets`, `blocking_event_count`, the `last_error_*` fields, and `health: AppHealth` | Today's flat activity fields |
| Computation | One server helper builds `AppHealth` from either aggregate (per-instance `AppHealthAggregates`, per-app `AppHealthSummary`), and the per-app summary gains a job average | Two |
| Mislabelled grid average | Replaced by the handler/job split | Documented |
| Debt left | None | Two known inconsistencies in the pinned contract |

Behavior to pin:
- For the same app, instance set and window, the per-instance and per-app health agree when the app has one instance.
- An average with no executions in the window is `None`.
- The job average excludes `skipped` executions in both scopes.

Consumers updated:
- `toAppRow()`/`AppRow` and the Apps page duration cell (`frontend/src/utils/app-data.ts`, `frontend/src/pages/apps-table-row.tsx`)
- the `hassette dashboard` and `hassette app health` columns (`src/hassette/cli/commands/status.py`, `app.py`)

**Recommendation:** A, because B publishes two known inconsistencies into the contract #2386 pins.
**Pick B instead if** you'd rather keep #2448 out of the telemetry queries.
**Reversibility:** hard after #2386.
**Ratified:** Chose a shared `AppHealth` record computed in one place (A) over documenting both shapes (B), to give app health one definition with scope as the only difference, accepting telemetry query changes in this PR (challenge Finding 9).

### D14: Do executions of removed handlers and jobs count toward app health?

Today `get_app_health_aggregates` (`src/hassette/core/telemetry/summary_queries.py`) excludes executions whose listener or job has `removed_at` set. `get_all_app_summaries` counts them, because its activity queries read the raw `listeners`/`scheduled_jobs` tables, while its `handler_count`/`job_count` use the `active_*` views. D13's single computation needs one rule.

**Deciding factor:** a window's health reflects what actually ran in that window.

| | A: Count them in both | B: Exclude them in both |
|---|---|---|
| Matches what ran in the window | Yes | No: errors from a handler removed mid-window vanish |
| Health right after a reload that removed a failing handler | Still shows the window's errors | Looks healthy immediately |
| `handler_count`/`job_count` | Active-only (they describe what is registered) | Active-only |

Behavior to pin: an error execution of a handler removed later in the window counts toward health in both the per-instance and per-app scopes, while `handler_count` excludes the removed handler.

**Recommendation:** A, because health over a window is a statement about executions, and a removed registration's executions still happened.
**Pick B instead if** you want health to describe only the currently registered code.
**Reversibility:** easy.
**Ratified:** Chose counting removed registrations' executions in both queries (A) over excluding them (B), so window health reflects what ran, accepting that health stays affected by a removed handler's errors until they leave the window.

### D15: What happens when a D1 rename collides with an existing hassette name?

This comes from the sketch comb.

| Wire name D1/D2 would produce | Already exists | Visibility |
|---|---|---|
| `AppConfig` (would collide if `AppConfigResponse` were a record; listed to document why it keeps its suffix) | `hassette.AppConfig` (`src/hassette/app/app_config.py:10`, the base class app authors subclass) | Public, top-level `hassette.__all__` |
| `AppManifest` | `hassette.config.AppManifest` (`src/hassette/config/classes.py:104`, the type of `App.app_manifest`) | Public, `hassette.config.__all__` |
| `ListenerSummary` | `hassette.schemas.listener_models.ListenerSummary` (the server's per-listener query row) | Internal |
| `LogEntry` | `hassette.logging_.LogEntry` (`src/hassette/logging_.py:63`) | Internal |

**Deciding factor:** a name means one thing across the hassette ecosystem, with no import aliasing.

| | A: Wire names never reuse a public `hassette` name; internal collisions are fixed by renaming the internal class | B: Rename anyway and alias at import sites | C: Colliding names keep their `*Response` suffix |
|---|---|---|---|
| `AppConfig` | `AppConfigResponse` stays: under D1's rule it is an aggregate view | `hassette_wire.AppConfig` next to `hassette.AppConfig` | Stays `AppConfigResponse` |
| `AppManifest` | The wire record becomes `AppSummary`, pairing with `JobSummary`/`ListenerSummary` | Two public `AppManifest`s with different shapes | Stays `AppManifestResponse`, an exception to the rule |
| Internal collisions | The internal classes are renamed (e.g. `ListenerSummaryRow`, `LogRecordEntry`; the build picks names that say what they are) | Aliased | n/a |
| Rule stays mechanical | Yes, plus one clause | Yes | No: a hidden exception list |

**Recommendation:** A, because two public types with one name and different shapes is the confusion D1 exists to remove, and renaming internal classes is free under the calibration.
**Pick B instead if** you consider `hassette_wire` a namespace app authors never import. **Pick C instead if** you accept a short exception list.
**Reversibility:** hard after #2386.
**Ratified:** Chose no public-name reuse with `AppSummary` for the wire manifest record (A) over aliasing (B) and suffix exceptions (C), to keep one meaning per name across `hassette` and `hassette_wire`, accepting renames of two internal classes.

### D16: Where does the app resource live, and does "manifest" stay on the wire?

This comes from the sketch comb, run 2. After D15, the record is `AppSummary`, but "manifest" still names its paths (`GET /api/apps/manifests`, `GET /api/apps/{app_key}/manifest`), its WS refetch event (`app_manifests_changed`: `AppManifestsChangedData`/`AppManifestsChangedWsMessage`, emitted from `src/hassette/core/runtime_query_service.py` and consumed by `frontend/src/hooks/use-websocket.ts`), and its status enum (`ManifestStatus`). The natural path `GET /api/apps` (`get_apps` in `src/hassette/web/routes/apps.py`) serves `AppStatusResponse`, an in-memory live-instance view. No production code calls it. The frontend, the CLI, the client and the docs don't. Its dependents are tests and generated or exported surface: `tests/system/test_web_api.py`, `tests/integration/web_api/test_endpoints.py`, `test_problem_details.py` and `test_auth.py` (the endpoint), `tests/unit/web/test_mappers.py` (`app_status_response_from`), `tests/unit/core/test_runtime_query_service.py` (`get_app_status_snapshot`), `AppStatusResponse` in `hassette_wire.__all__`, and the generated `frontend/openapi.json` / `generated-types.ts`.

**Deciding factor:** one word for the app resource on the wire, and no orphaned endpoint.

| | A: Keep the "manifest" names; record why | B: Remove the orphan; the app resource lives at `/apps`; "manifest" leaves the wire |
|---|---|---|
| `GET /api/apps` | Keeps serving `AppStatusResponse`, which nothing calls | Deleted, with `AppStatusResponse`, `app_status_response_from` (`src/hassette/web/mappers.py`) and `get_app_status_snapshot` (route-only) |
| App list / one app | `GET /api/apps/manifests` / `GET /api/apps/{app_key}/manifest` | `GET /api/apps` → `AppListResponse` / `GET /api/apps/{app_key}` → `AppSummary`, beside `/apps/{app_key}/config`, `/source`, `/start` |
| List envelope field | `manifests` | `apps` (`AppListResponse.apps: list[AppSummary]`) |
| WS refetch event | `app_manifests_changed` | `apps_changed` (`AppsChangedData`/`AppsChangedWsMessage`); the frontend ships with the server |
| Status enum | `ManifestStatus` | `AppStatus` (unused in `src/`, `wire/` and `client/`; `OpenManifestStatus` → `OpenAppStatus`). The frontend's local `type AppStatus` in `frontend/src/components/app-detail/overview-tab.tsx` is renamed so it doesn't collide (build-time call) |
| Dead code left | An unused endpoint, a model and a mapper | None |

Hardcoded paths to update: `src/hassette/cli/client.py` (`_fetch_instances`, `_try_fetch_instances`), `src/hassette/cli/commands/app.py` (`cmd_app`), `frontend/src/api/endpoints.ts`, `docs/pages/cli/commands.md`, `tests/TESTING.md`.

"Manifest" stays as the internal term: the `app_manifests` table, `AppManifestInfo`, the telemetry queries, and `hassette.config.AppManifest`.

**Recommendation:** B, because it removes dead code and the vocabulary mismatch together, and nothing outside the tests notices the deletion.
**Pick A instead if** you want the app paths and the WS protocol left untouched.
**Reversibility:** hard after #2386.
**Ratified:** Chose removing the orphaned `GET /api/apps`, serving apps at `/apps` and `/apps/{app_key}`, renaming the list field `manifests` to `apps`, the WS event to `apps_changed` and `ManifestStatus` to `AppStatus` (B), over keeping the manifest names (A), so the wire uses one word for the app resource with no dead endpoint, accepting moved paths, a WS literal change and an enum rename.

### D8: How is the docstring rule from (d) kept from regressing?

**Deciding factor:** catch what can be checked mechanically, at the lowest cost. `wire/src/hassette_wire/REVIEW.md` already has a "Schema-Emitted Text" question, but the current offenders predate it, so review hasn't actually been tested against them yet.

| | A: A custom wire test: missing docstrings plus a server-pointer pattern list | B: Review only (the existing REVIEW.md question) | C: Ruff `D101` scoped to `wire/src` for missing docstrings; prose stays with review |
|---|---|---|---|
| Catches a missing class docstring | Always | When a reviewer notices | Always, at lint time via `prek` |
| Catches server-history prose | The listed patterns only | When a reviewer notices | When a reviewer notices |
| New code to maintain | A test plus a pattern list and an allowlist | None | A config change only |

Under C, `D101` comes out of the global `ignore` in `ruff.toml` and goes into `[lint.per-file-ignores]` as `"!wire/src/**" = ["D101"]`. That pattern was verified on ruff 0.14.9. Today it flags 14 undocumented classes in `wire/src` (apps, health, logs, and the `ws.py` envelopes and `ConnectedPayload`), with 0 hits in `src`, `client` or `tests`. Every hit, plus every class this change adds or renames, gets a consumer-facing docstring.

**Recommendation:** C, because it enforces the mechanical half with config instead of a custom test, and leaves the judgment half with review.
**Pick A instead if** server-pointer prose regresses after this PR despite the REVIEW.md question.
**Reversibility:** easy.
**Ratified:** Chose ruff `D101` scoped to `wire/src` plus review (C) over a custom test (A) and review alone (B), to enforce missing docstrings by config while keeping prose with review, accepting that server-pointer prose is caught only by review.

### D9: Is the PR a breaking change (`feat!` with a `BREAKING CHANGE:` footer)?

**Deciding factor:** the changelog tells users what actually breaks. The `hassette-wire` released at v0.55.0 was an empty stub, so no released Python consumer imports these class names. The HTTP API and CLI output still break. The list uses current names for existing components, with D1/D15 renames noted where they apply.
- The grid endpoint's path changes (D11), its rows become `{app, activity}` (D7), and activity health moves under `activity.health` (D13).
- `ServiceInfoResponse.role` (now `ServiceInfo.role`) becomes required (D4).
- The OpenAPI and WS-schema component names change (D1, D2, D11, D13, D15, D16).
- `hassette app list --json` and `hassette dashboard --json` rows go from flat to `{app, activity}` (D7, D10).
- The `hassette app health` and `hassette dashboard` duration columns change to the handler/job averages (D13).
- `recent_invocations_1h` leaves `GET /api/apps/manifests` and `GET /api/apps/{app_key}/manifest` (D10). oasdiff scores removing an optional response property as `info`, so `tools/check_wire_compat.py` won't flag it. It is listed here because the tool can't see it.
- On `GET /api/telemetry/app/{app_key}/health`, `handler_avg_duration`/`job_avg_duration` become `handler_avg_duration_ms`/`job_avg_duration_ms` and are `null` when nothing ran (D13). The grid's handler-only `avg_duration_ms` is replaced by both averages (D13).
- Per-instance health starts counting executions of removed handlers and jobs (D14).
- `GET /api/apps` (`AppStatusResponse`) is removed. The app list moves from `GET /api/apps/manifests` to `GET /api/apps`, and one app from `GET /api/apps/{app_key}/manifest` to `GET /api/apps/{app_key}`. The list envelope's `manifests` field becomes `apps`, the WS event `app_manifests_changed` becomes `apps_changed`, and `ManifestStatus` becomes `AppStatus` (D16).
- `AppGridResponse` gains `degraded` and `since` (D12). These are additive, listed for completeness.

The diff carries compat-ignore lines, and the header of `tools/wire_compat_ignore.txt` pairs those with `!` plus a footer. Every removed or moved path (D7, D11, D16) gets its lines from the check's output. Existing lines for paths that no longer exist (the #2382 entries for `GET /api/apps/{app_key}/manifest`) are left to the file's own clear-after-release rule.

**Recommendation:** `feat!` with exactly one `BREAKING CHANGE:` footer at the end of the PR body, naming every item above. The PR body also gets a migration note for HTTP consumers (old paths → new paths; flat → `app`/`activity`; renamed health fields; `apps_changed`).
**Pick `refactor:` instead if** none of the above lands. That's no longer possible after D4, D7, D11, D13 and D16.
**Reversibility:** easy until merge.
**Ratified:** Chose `feat!` with one `BREAKING CHANGE:` footer naming every item above over `refactor:`, to report the HTTP, CLI-output and health-semantics breaks honestly, accepting a breaking changelog entry.

## Assumed

- **Package isolation.** `hassette_wire` cannot import `hassette`, so any vocabulary shared with the server must be defined in wire. Evidence: `wire/src/hassette_wire/REVIEW.md` ("Package Isolation"); `wire/pyproject.toml` depends on `pydantic` only.
- **Open/closed vocabularies.**
  - Response fields typed with an enum or multi-value `Literal` use an `Open<TypeName>` alias (`Annotated[X | UnknownValue, LenientValue("X")]`). `SourceTier` and `LogLevel` are closed and stay strict.
  - Every new vocabulary in this change is open: `ResourceRole`, `ScheduleStatus`, `ScheduleStatusReason`, `AppAction`, the `AppStatus` (formerly `ManifestStatus`) keys, and `GridEnrichment`.
  - "Open" means a Python client parsing with `LENIENT_CONTEXT` tolerates unknown values. `openapi.json` and `ws-schema.json` describe what the server emits, so consumers generated from them (the frontend's TS types and `ws-validator.generated.ts`) see closed enums, as spec 121 intends.
  - Narrowing WS `ServiceStatusData.role` therefore tightens the frontend's WS validator. WS has no compat check (the `hassette_wire/__init__.py` docstring).

  Evidence: `design/specs/121-wire-lenient-unknown-enums/design.md` (D5, D14); spec 116 addendum 2026-10-03.
- **`effective_level` is always a `LogLevel`.** The route only sets `VALID_LOG_LEVEL_NAMES` (the five `LOG_LEVELS` keys) on the target logger. Evidence: `src/hassette/web/routes/logs.py:96-112`, `src/hassette/web/dependencies.py:20-27`.
- **Role values.** `ServiceStatusData.role` comes from `ServiceStatusPayload.role: ResourceRole`. Evidence: `src/hassette/events/hassette.py:35`.
- **Request side stays strict.** Only response fields get `Open*` aliases. Evidence: spec 121.
- **No released consumer imports `hassette_wire` names.** Evidence: v0.55.0 wire `__init__.py` is a stub; models moved in by #2449 after that tag. `client/src` does not import `hassette_wire` yet.
- **Generated TS.** `frontend/src/api/generated-types.ts`, `ws-types.ts` and `ws-validator.generated.ts` are regenerated, not hand-edited. Evidence: `scripts/export_schemas.py` docstring.
- **Required checks.** `tools/check_wire_compat.py` runs against the latest `v*` tag (v0.55.0) in both directions, and deliberate breaks go in `tools/wire_compat_ignore.txt` verbatim from its output. Evidence: the module docstring and the file header.
- **CLI column contract.** `tests/snapshots/cli_columns.json` records every CLI table's columns, and `tools/check_cli_drift.py` fails when it drifts. Evidence: `tests/snapshots/cli_columns.json` ("Invoc/1h" entry).
- **Tests encoding the old behavior.** Each of these needs updating:
  - `tests/integration/telemetry/test_global_jobs_and_service_info.py` asserts `role == ""` and builds `role="Service"`, which is not a `ResourceRole` value (`auto()` values are lowercase).
  - `tests/unit/test_model_types.py` builds `ServiceInfoResponse` without `role`.
  - `frontend/src/test/factories.ts` sets `recent_invocations_1h`.

  Evidence: those files; `src/hassette/types/enums.py:176-195`.

## Build

- [ ] Implementation and tests committed
- [ ] Docs
- [ ] Ship-time challenge

**Calls made during the build:**

## Addendum

### 2026-10-04: split into specs 123–126 before build

This ledger was ratified decision by decision, challenged and combed, then split before build because it was too large for one PR. Every decision moved, unchanged apart from cross-references, into one of four ledgers, which are built in this order:
- `design/specs/123-wire-vocabulary-typing/` (D3–D6), under #2448
- `design/specs/124-app-health-unification/` (D13, D14), under #2508
- `design/specs/125-apps-resource-and-grid/` (D7, D10–D12, D15, D16), under #2509
- `design/specs/126-wire-naming-and-docs/` (D1, D2, D8), under #2448

Each ledger has its own D9. D14 supersedes #1022's exclusion rule.
