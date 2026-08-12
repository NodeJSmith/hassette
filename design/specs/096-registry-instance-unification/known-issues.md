# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: No integration test drives a degraded scenario through the full HTTP-response chain

Status: resolved — fixed during known issues walkthrough
Run: 81
Source: impl-review
Reason not fixed now: out-of-scope
Observed in: impl-review (post-execution, after T05)
Affected files:
- tests/integration/web_api/test_endpoints.py (or a new test file covering `/api/apps` end-to-end)

Issue:
Unit and mapper-level tests cover the `"degraded"` status derivation, snapshot collapse, and
`status_counts` field individually, but no test exercises the full chain — registering a mixed
running/failed app_key on a real `AppRegistry`, then hitting the actual `/api/apps` HTTP endpoint
and asserting the response body shows `status: "degraded"` end-to-end.

Why deferred:
This run's design.md scoped test requirements to unit + integration coverage of the individual
FR/AC items (all of which are met and independently verified by per-task reviewers and the
implementation review). An additional full-stack HTTP-chain test is a valuable but incremental
enhancement beyond what any task's Verify section required, not a gap in the shipped behavior.

Recommended follow-up:
Add an integration test in `tests/integration/web_api/test_endpoints.py` that registers a running
+ failed instance pair for one app_key, calls the `/api/apps` endpoint, and asserts the JSON
response's manifest entry has `status: "degraded"`.

Acceptance criteria:
- A new test exists exercising the full registry → snapshot → mapper → HTTP-response chain for a
  degraded app, and it passes.

## KI-002: `AppManifestInfo.status` stays `str` instead of `ManifestStatus`

Status: resolved — fixed during known issues walkthrough
Run: 81
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review (post-execution, after T05)
Affected files:
- src/hassette/schemas/app_snapshots.py
- src/hassette/core/app_registry.py
- src/hassette/web/mappers.py
- src/hassette/test_utils/web_manifest_helpers.py

Issue:
`AppManifestInfo.status` is typed `str` with a hand-maintained comment enumerating the legal
values (`# "running", "failed", "stopped", "disabled", "blocked", "degraded"`), even though this
PR introduces a real `ManifestStatus` `StrEnum` and uses it correctly everywhere else it touches
(`AppManifestResponse.status: ManifestStatus`, `DashboardAppGridEntry.status: ManifestStatus`,
and `AppRegistry.build_manifest_info()` assigns `ManifestStatus.*` members into this exact
field). `web/mappers.py` still needs a `cast("ManifestStatus", manifest.status)` to bridge the gap.

Why deferred:
This is a deliberate, already-approved design decision, not an oversight — design.md's
Replacement Targets table explicitly scopes the change for this field to "Update comment to
include `degraded`," not a type change. Widening the type to `ManifestStatus` would require
updating every `AppManifestInfo(status=...)` / `make_manifest(status=...)` call site that
currently passes a raw string (`tests/unit/web/test_mappers.py` alone has ~10), plus
`overlay_runtime_state()`'s `status="stopped"` fallback — a moderate-blast-radius change that
exceeds "unambiguous, single-file" scope for a clean-code pass and revisits a decision the
approved design already made deliberately.

Recommended follow-up:
If a future change wants the stronger type guarantee, widen `AppManifestInfo.status` to
`ManifestStatus`, update `overlay_runtime_state()`'s literal-string fallback, drop the now-needless
cast in `web/mappers.py`, and migrate the raw-string call sites in tests to `ManifestStatus.X`.

Acceptance criteria:
- `AppManifestInfo.status` is typed `ManifestStatus`, all call sites construct it with enum
  members, `prek -a && prek pyright -a --stage pre-push` passes with no new suppressions.

## KI-003: App status vocabulary is re-enumerated across 5 separate maps/lists with no single source of truth

Status: filed (#1601)
Run: 81
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review (post-execution, after T05)
Affected files:
- frontend/src/utils/status.ts
- frontend/src/utils/status-priority.ts
- frontend/src/pages/apps.tsx

Issue:
The manifest/app status vocabulary (`running`, `failed`, `degraded`, `stopped`, `disabled`,
`blocked`, plus transitional statuses) is independently hand-maintained in `APP_STATUS_MAP` and
`STATUS_KIND_MAP` (`status.ts`), `STATUS_PRIORITY` (`status-priority.ts`), and
`FILTER_OPTIONS`/`FILTER_TONES` (`apps.tsx`). This PR added `"degraded"` to all of them by hand.
A future status addition risks a partially-updated set (e.g. a status that sorts and filters but
never gets a badge color, or vice versa).

Why deferred:
This is a pre-existing, established convention that predates this PR — design.md's own
"Convention Examples" section documents this exact multi-site-update pattern as how the codebase
already adds a status value, and its "Frontend" section explicitly enumerates the same five
update sites as this PR's required changes, not something it introduced. Consolidating five maps
with genuinely different value types (`StatusVariant`, `StatusKind`, sort priority `number`,
filter membership) and different domains (`STATUS_KIND_MAP` covers transitional statuses like
`starting`/`stopping` that aren't manifest-level filters at all; `APP_STATUS_MAP` additionally
covers non-app service-health values `success`/`failure`/`unknown`) into one source of truth is a
frontend status-architecture redesign, not a mechanical clean-code fix, and is out of scope for a
registry-unification PR. (The narrower, same-file, type-unlinked instance of this — the
`statusCounts` initializer in `apps.tsx`'s `buildAppsCells` — was fixed in this pass by deriving
it from `FILTER_OPTIONS` instead of hand-listing it a third time.)

Recommended follow-up:
Design a single `STATUS_METADATA` registry keyed by status value (variant, kind, priority, and
filter/sort membership per entry) that `APP_STATUS_MAP`, `STATUS_KIND_MAP`, `STATUS_PRIORITY`,
and `apps.tsx`'s filter list all derive from, scoped as its own frontend-architecture change.

Acceptance criteria:
- Adding a new status value requires editing exactly one place, and existing consumers
  (`statusToVariant`, `statusToKind`, `statusPriority`, the apps-page filter) all pick it up
  automatically.
