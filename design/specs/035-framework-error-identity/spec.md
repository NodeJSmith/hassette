---
feature_number: "035"
feature_slug: "framework-error-identity"
status: "draft"
created: "2026-04-18"
---

# Spec: Framework Error Identity and Dashboard Unification

## Problem Statement

Spec 026 (telemetry source tier) established the split between app and framework telemetry. Framework listeners and jobs now persist to the same tables as app records, with a `source_tier` column distinguishing them. However, three usability gaps remain:

1. **Anonymous framework errors.** All framework services register under a single identity (`__hassette__`). When StateProxy, ServiceWatcher, and AppHandler all error, the dashboard shows three errors from "__hassette__" with no indication of which component failed. Operators cannot triage without reading logs.

2. **No tracebacks in the error feed.** The dashboard error feed (`get_recent_errors`) selects `error_type` and `error_message` but not `error_traceback`. The data exists in the database — `track_execution()` stores full tracebacks for unexpected exceptions — but it's never surfaced in the feed. Users must SSH in and grep logs to see stack traces.

3. **Split error sections create false confidence.** The dashboard shows "Recent Errors" (app-only) and "System Health" (framework-only) as separate sections. When 2 framework errors exist but 0 app errors, the primary error section says "No recent errors. All systems healthy." — technically true for apps, but misleading when the framework is actively failing.

4. **Traceback suppression hides framework bugs.** `track_execution()` suppresses tracebacks for `HassetteError` and `DependencyError` via the `known_errors` parameter. This makes sense for app-tier errors (user sees a clean message), but framework-tier errors from known types still indicate framework bugs where the traceback is diagnostic.

## Goals

1. Each framework service registers with a unique, human-readable identity derived from its component name.
2. The dashboard error feed includes tracebacks with an expand/collapse toggle.
3. The dashboard presents a single unified error timeline covering both app and framework errors, with clear visual distinction between tiers.
4. Framework-tier errors preserve tracebacks regardless of exception type.

## Non-Goals

1. Framework service detail pages (like app detail pages) — framework services don't have the same lifecycle or configuration surface.
2. Filtering the error feed by source tier or component — a unified view is the goal; tier filtering is a follow-up.
3. Changes to how app-tier tracebacks are suppressed for known errors — the current behavior is correct for user-facing errors.
4. Framework job registration — no production framework jobs exist today; this spec covers listeners only.

## Acceptance Criteria

### Framework service identity

- [ ] `is_framework_key(app_key)` helper exists in `types.py` and returns `True` for any key starting with `FRAMEWORK_APP_KEY_PREFIX` OR equal to the bare `FRAMEWORK_APP_KEY` (backward compat for existing DB rows and test harness).
- [ ] `framework_display_name(app_key)` helper extracts the raw component slug from a framework key (e.g., `"__hassette__.service_watcher"` → `"service_watcher"`). Title-casing for display is the UI's responsibility.
- [ ] Each framework service registers with its own key: `__hassette__.app_handler`, `__hassette__.core`, `__hassette__.service_watcher`.
- [ ] `register_framework_listener()` validates the `component` parameter (non-empty, snake_case).
- [ ] The CHECK constraint on `listeners` and `scheduled_jobs` tables accepts any `app_key` starting with `__hassette__` for `source_tier = 'framework'`. Constraint uses `GLOB` (not `LIKE`) since `_` is literal in GLOB patterns.
- [ ] CHECK constraint is updated in a new migration 004 (not by editing migration 001), since migrations 002 and 003 also embed the old constraint.
- [ ] `_validate_source_tier()` in `TelemetryRepository` accepts prefix-matched framework keys.
- [ ] User app key validation in `app_config.py` and `config.py` rejects keys starting with `FRAMEWORK_APP_KEY_PREFIX` (not just exact `FRAMEWORK_APP_KEY`).
- [ ] Queries that previously filtered on exact `FRAMEWORK_APP_KEY` match now filter on prefix or use `is_framework_key()`.
- [ ] `get_all_app_summaries()` excludes all framework keys, not just the single `FRAMEWORK_APP_KEY`.
- [ ] `await_registrations_complete()` in `core.py` drains all framework component keys (not just the bare key).

### Traceback in error feed

- [ ] `get_recent_errors()` SQL query selects `error_traceback` from both `handler_invocations` and `job_executions`.
- [ ] `HandlerErrorRecord` and `JobErrorRecord` include `error_traceback: str | None`.
- [ ] `HandlerErrorEntry` and `JobErrorEntry` response models include `error_traceback: str | None`.
- [ ] The `ErrorFeed` component renders a "Traceback" toggle button when `error_traceback` is present.
- [ ] Expanded tracebacks render in a `<pre class="ht-traceback">` element consistent with the app detail page.
- [ ] `track_execution()` caps stored tracebacks at 8 KB to prevent unbounded DB growth during error storms.

### Dashboard unification

- [ ] The dashboard has a single "Recent Errors" section that includes both app and framework errors (breaking default change from `source_tier='app'` to `'all'`).
- [ ] The `dashboard_kpis` endpoint default also changes to `'all'` to match, preventing count mismatches between KPI strip and error feed.
- [ ] Framework errors display a "Framework" badge and the component name instead of linking to an app page. Framework keys must NOT render as `<a href>` links.
- [ ] App errors continue to link to their app detail page.
- [ ] The `FrameworkHealth` component becomes a summary-only indicator (error count badge) without its own error feed. The `FrameworkSummaryResponse.errors` list field is removed; only counts are returned.
- [ ] "No recent errors" text only appears when there are genuinely no errors of any tier.

### Traceback suppression fix

- [ ] Framework-tier executions in `CommandExecutor._execute()` do not pass `known_errors`, so tracebacks are preserved for all exception types.
- [ ] App-tier executions continue to suppress tracebacks for `DependencyError` and `HassetteError`.
- [ ] The source_tier branching uses an explicit match/case with an assertion on unexpected values.

## Technical Considerations

- The DB CHECK constraint exists in migrations 001, 002, and 003. A new migration 004 is required; editing old migrations is insufficient for existing databases.
- SQLite `LIKE` treats `_` as a single-character wildcard. Use `GLOB` for prefix matching in CHECK constraints — `_` is literal in GLOB patterns.
- The `register_framework_listener()` method signature needs a new `component` parameter with validation (non-empty, snake_case).
- The dashboard errors and KPIs endpoint defaults change from `source_tier='app'` to `'all'`. Tests asserting app-only behavior must be updated.
- `is_framework_key()` must also match the bare `FRAMEWORK_APP_KEY` for backward compatibility with existing DB rows and the test harness.
- The `FrameworkSummaryResponse` model is slimmed to counts only — the `errors` list field is removed since the unified feed replaces it.
- The `FrameworkHealth` badge count should use the same 24-hour time window as the unified feed, not the all-time aggregate.
