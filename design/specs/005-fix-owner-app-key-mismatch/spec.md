---
feature_number: "005"
feature_slug: "fix-owner-app-key-mismatch"
status: "approved"
created: "2026-03-15T17:33:48Z"
---

# Spec: Fix owner_id/app_key mismatch in job and listener recording

## Problem Statement

Scheduler job and event listener records in the database are stored with incorrect ownership identifiers. The system conflates two distinct concepts: the per-instance resource identifier (owner_id) and the configuration-level application key (app_key). This causes all job and listener filters in the monitoring UI and API to silently return empty results, because the stored value never matches the filter value. Users see no jobs or listeners on app detail pages, even though the data exists.

## Goals

- Job and listener filters in the monitoring UI and API return correct, non-empty results when filtering by application
- The database records contain the correct configuration-level application key alongside the instance identifier
- Field names on in-memory data structures clearly communicate which identifier they hold, preventing future confusion
- Existing telemetry data self-corrects on next application restart without requiring a manual migration

## Non-Goals

- Database migration to fix historical records (rows self-correct via UPSERT on restart)
- Changes to the session lifecycle or session recording
- Changes to the telemetry query layer or report aggregation
- UI redesign of the job or listener views

## User Scenarios

### Scenario 1: Viewing jobs for a specific app

A developer opens the monitoring dashboard and navigates to an app's detail page. They expect to see all scheduled jobs belonging to that app. Currently, the job list is always empty because the filter compares the wrong identifiers. After the fix, the correct jobs appear.

### Scenario 2: Filtering jobs via the API

A developer calls the scheduler jobs API endpoint with an app_key filter parameter. Currently, the response is always an empty list. After the fix, only jobs belonging to the specified application are returned.

### Scenario 3: HTMX partial refreshes

The dashboard uses HTMX partials to refresh job lists dynamically. These partials filter jobs by app_key but compare against the wrong field. After the fix, partial refreshes show the correct filtered job list.

## Functional Requirements

1. **Correct DB recording**: When a listener or job is registered in the database, the `app_key` column must contain the application's configuration key (e.g., `"my_app"`), not the resource's instance identifier (e.g., `"MyApp.MyApp[0]"`).

2. **Propagate app_key to resources**: The application's configuration key must be accessible from the Bus and Scheduler resources so it can be passed during registration.

3. **Fix partial route filters**: The three HTMX partial routes that filter jobs must compare against the correct identifier so they return matching results.

4. **Fix API route filter**: The API endpoint that filters jobs by application must compare against the correct identifier.

5. **Rename fields for clarity**: The `owner` field on Listener and ScheduledJob must be renamed to `owner_id` to clearly indicate it holds the resource instance identifier, not the configuration key.

6. **Correct instance_index recording**: The `instance_index` field in registration must reflect the actual app instance index, not a hardcoded zero.

## Edge Cases

1. **Apps with multiple instances**: Each instance has the same `app_key` but a different `owner_id` and `instance_index`. Filters must correctly distinguish between instances when instance-level filtering is requested.

2. **Core/system resources without an app parent**: Resources owned by the Hassette core (not an app) may not have an `app_key`. Registration must handle this gracefully.

3. **Stale DB rows from before the fix**: Old rows with incorrect `app_key` values will coexist with correct rows until overwritten by the UPSERT on next restart. The UPSERT's conflict key includes `app_key`, so old rows with wrong values will not conflict — they will remain as orphans until retention cleanup removes them.

## Dependencies and Assumptions

- The existing UPSERT mechanism (ON CONFLICT ... DO UPDATE) on the listeners and scheduled_jobs tables will overwrite stale rows when the correct app_key is written on restart.
- The partial fix from PR #334 (pages using `instance.owner_id` for filtering) is already merged and serves as the reference pattern.
- No external systems are affected — this is purely internal telemetry recording and display.

## Acceptance Criteria

1. The `app_key` column in the `listeners` table contains the application's configuration key after registration
2. The `app_key` column in the `scheduled_jobs` table contains the application's configuration key after registration
3. The three HTMX partial routes return non-empty job lists when filtering by a valid app_key
4. The API endpoint for scheduler jobs returns non-empty results when filtering by a valid app_key
5. The owner field on Listener is renamed to owner_id across the codebase
6. The owner field on ScheduledJob is renamed to owner_id across the codebase
7. All existing integration and end-to-end tests pass
8. Type checking passes without new errors
