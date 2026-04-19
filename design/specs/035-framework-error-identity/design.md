---
feature_number: "035"
feature_slug: "framework-error-identity"
status: "approved"
created: "2026-04-18"
---

# Design: Framework Error Identity and Dashboard Unification

**Status:** archived

## Architecture

### 1. Framework key convention

Replace the single `FRAMEWORK_APP_KEY = "__hassette__"` with a prefix-based scheme:

```
FRAMEWORK_APP_KEY_PREFIX = "__hassette__."
```

Each framework service registers with `__hassette__.<component>`:

| Service | Key | Current `name` parameter |
|---------|-----|-------------------------|
| AppHandler | `__hassette__.app_handler` | `hassette.app_handler.handle_change_event` |
| Hassette (core) | `__hassette__.core` | `hassette.session_manager.on_service_crashed` |
| ServiceWatcher | `__hassette__.service_watcher` | `hassette.service_watcher.restart_service` (and 3 others) |

Keep the old `FRAMEWORK_APP_KEY = "__hassette__"` constant for backward compatibility in tests and documentation, but production code uses component-specific keys.

**Helpers in `types.py`:**

```python
FRAMEWORK_APP_KEY_PREFIX = "__hassette__."

def is_framework_key(app_key: str | None) -> bool:
    """Match both prefixed keys and the bare legacy key."""
    return app_key is not None and (
        app_key.startswith(FRAMEWORK_APP_KEY_PREFIX) or app_key == FRAMEWORK_APP_KEY
    )

def framework_display_name(app_key: str) -> str:
    """'__hassette__.service_watcher' → 'service_watcher'"""
    if app_key == FRAMEWORK_APP_KEY:
        return "framework"
    return app_key.removeprefix(FRAMEWORK_APP_KEY_PREFIX)
```

The existing `FRAMEWORK_APP_KEY = "__hassette__"` constant stays as-is — no deprecation ceremony needed since there are no external consumers. `is_framework_key()` handles it transparently.

The display name is the raw component slug. The UI title-cases it for presentation (`frameworkDisplayLabel()` in TypeScript). No need to store a separate human-readable name — the component names are stable and self-descriptive.

### 2. Registration changes

**`BusService.register_framework_listener()`** — add a `component: str` parameter:

```python
def register_framework_listener(
    self,
    *,
    component: str,  # NEW — e.g., "service_watcher"
    topic: str,
    handler: Callable[..., Awaitable[None]],
    name: str,
    ...
) -> asyncio.Task[None]:
    if not component or not re.match(r'^[a-z][a-z_]*[a-z]$', component):
        raise ValueError(f"Invalid framework component name: {component!r}; must be snake_case")
    app_key = f"{FRAMEWORK_APP_KEY_PREFIX}{component}"
    listener = Listener.create(
        ...
        app_key=app_key,
        ...
    )
```

Callers updated:
- `app_handler.py:80` → `component="app_handler"`
- `core.py:333` → `component="core"`
- `service_watcher.py:217-238` → `component="service_watcher"` (4 calls)

**Registration drain fix** — `core.py:348` calls `await_registrations_complete(FRAMEWORK_APP_KEY)` which will be a no-op after the key change. Add `drain_framework_registrations()` to `BusService` that iterates all keys matching `FRAMEWORK_APP_KEY_PREFIX` in `_pending_registration_tasks`:

```python
async def drain_framework_registrations(self) -> None:
    """Drain all pending framework registration tasks."""
    for key in list(self._pending_registration_tasks):
        if is_framework_key(key):
            await self.await_registrations_complete(key)
```

`core.py` calls `drain_framework_registrations()` instead of the single-key drain.

### 3. Schema and constraint changes

**Migration:** Add a new migration 004 (do NOT edit migrations 001/002/003 — all three embed the old CHECK constraint, and existing databases have migration 003's version as the live constraint). Use the table-rebuild pattern:

```sql
-- New CHECK constraint (uses GLOB, not LIKE — _ is literal in GLOB patterns):
CHECK (app_key NOT GLOB '__hassette__*' OR source_tier = 'framework')
```

`GLOB` treats `_` as a literal character (unlike `LIKE` where `_` is a single-char wildcard). The `*` wildcard matches zero or more characters, so this covers both the bare `__hassette__` and all prefixed keys like `__hassette__.service_watcher`.

Applied to both `listeners` and `scheduled_jobs` tables via table-rebuild in migration 004.

**`_validate_source_tier()`** — change exact match to use the helper:

```python
def _validate_source_tier(self, app_key: str, source_tier: SourceTier) -> None:
    if source_tier == "framework" and not is_framework_key(app_key):
        raise ValueError(...)
```

**`reconcile_registrations()`** — the existing guard skips `FRAMEWORK_APP_KEY` by exact match. Change to prefix match:

```python
# Old:
if app_key == FRAMEWORK_APP_KEY:
    return

# New:
if is_framework_key(app_key):
    return
```

**`get_all_app_summaries()`** — the `all_keys.discard(FRAMEWORK_APP_KEY)` call becomes a prefix filter (catches both bare and prefixed keys):

```python
all_keys = {k for k in all_keys if not is_framework_key(k)}
```

**User app key validation** — update `app_config.py` and `config.py` to reject the full prefix, not just the exact key:

```python
# Old:
if v == FRAMEWORK_APP_KEY:
    raise ValueError(...)

# New:
if is_framework_key(v):
    raise ValueError(...)
```

### 4. Traceback in error feed

**SQL change** in `get_recent_errors()` — add `error_traceback` to both SELECT branches:

```sql
SELECT
    'handler' AS kind,
    hi.listener_id AS record_id,
    l.app_key,
    l.handler_method,
    l.topic,
    NULL AS job_name,
    hi.execution_start_ts,
    hi.duration_ms,
    hi.source_tier,
    hi.error_type,
    hi.error_message,
    hi.error_traceback          -- NEW
FROM handler_invocations hi
...
```

Same for the job branch.

**Model changes:**

- `HandlerErrorRecord` — add `error_traceback: str | None = None`
- `JobErrorRecord` — add `error_traceback: str | None = None`
- `HandlerErrorEntry` — add `error_traceback: str | None = None`
- `JobErrorEntry` — add `error_traceback: str | None = None`

**Endpoint changes** in `telemetry.py` — pass `error_traceback` through in both `dashboard_errors` and `dashboard_framework_summary` response construction.

### 5. Dashboard unification

**Dashboard errors endpoint** — change the default `source_tier` from `"app"` to `"all"` (breaking behavioral change — no schema change, so invisible to static analysis):

```python
# Old:
effective_tier = source_tier if source_tier is not None else "app"

# New:
effective_tier = source_tier if source_tier is not None else "all"
```

**Dashboard KPIs endpoint** — also change default to `"all"` to match, preventing count mismatches between KPI strip and error feed.

**`FrameworkSummaryResponse`** — slim to counts only. Remove the `errors` list field; only `total_errors` and `total_job_errors` remain. The endpoint skips the `get_recent_errors()` call entirely.

**`dashboard.tsx`** — remove the separate `FrameworkHealth` error feed. Keep the `FrameworkHealth` component as a collapsed summary badge (error count + "System Health" label) but it no longer expands to show its own error list. The unified "Recent Errors" section shows everything.

**`error-feed.tsx`** — add framework-aware rendering:

```tsx
const isFramework = isFrameworkKey(err.app_key);
const displayName = isFramework
  ? frameworkDisplayLabel(err.app_key)
  : err.app_key;

// CRITICAL: framework keys must NOT render as <a href> links
{!isFramework && err.app_key ? (
  <a href={`/apps/${err.app_key}`} class="ht-text-sm">{displayName}</a>
) : (
  <span class="ht-text-sm ht-text-muted">{displayName}</span>
)}
```

Add the same `ErrorCell`-style expand/collapse for tracebacks that already exists on the app detail page. Reuse the `ErrorCell` component from `app-detail/error-cell.tsx`.

**Frontend helpers** — add `isFrameworkKey()`, `frameworkDisplayName()`, and `frameworkDisplayLabel()` to a shared utils file, mirroring the Python helpers:

```typescript
const FRAMEWORK_KEY_PREFIX = "__hassette__.";
const FRAMEWORK_KEY_BARE = "__hassette__";

export function isFrameworkKey(appKey: string | null): boolean {
  return appKey !== null && (
    appKey.startsWith(FRAMEWORK_KEY_PREFIX) || appKey === FRAMEWORK_KEY_BARE
  );
}

export function frameworkDisplayName(appKey: string): string {
  if (appKey === FRAMEWORK_KEY_BARE) return "framework";
  return appKey.replace(FRAMEWORK_KEY_PREFIX, "");
}

export function frameworkDisplayLabel(appKey: string): string {
  const slug = frameworkDisplayName(appKey);
  return slug.split("_").map(w => w[0].toUpperCase() + w.slice(1)).join(" ");
}
```

### 6. Traceback suppression fix

**`CommandExecutor._execute()`** — branch `known_errors` based on `cmd.source_tier` using explicit match/case:

```python
match cmd.source_tier:
    case "app":
        known = (DependencyError, HassetteError)
    case "framework":
        known = ()
    case _:
        raise AssertionError(f"Unexpected source_tier: {cmd.source_tier!r}")

async with track_execution(known_errors=known) as result:
    await fn()
```

This preserves the current behavior for app-tier executions while ensuring framework-tier errors always include full tracebacks. The assertion guard prevents silent behavior changes from unexpected values.

**Traceback size cap** — add truncation in `track_execution()`:

```python
MAX_TRACEBACK_SIZE = 8192  # 8 KB — sufficient for 10-20 async frames

tb = traceback.format_exc()
if len(tb) > MAX_TRACEBACK_SIZE:
    tb = tb[:MAX_TRACEBACK_SIZE] + "\n... [truncated]"
result.error_traceback = tb
```

## Affected Files

### Python (backend)

| File | Change |
|------|--------|
| `src/hassette/types/types.py` | Add `FRAMEWORK_APP_KEY_PREFIX`, `is_framework_key()`, `framework_display_name()`; deprecation comment on `FRAMEWORK_APP_KEY` |
| `src/hassette/core/bus_service.py` | Add `component` param with validation to `register_framework_listener()`; add `drain_framework_registrations()` |
| `src/hassette/core/app_handler.py` | Pass `component="app_handler"` |
| `src/hassette/core/core.py` | Pass `component="core"`; replace `await_registrations_complete(FRAMEWORK_APP_KEY)` with `drain_framework_registrations()` |
| `src/hassette/core/service_watcher.py` | Pass `component="service_watcher"` |
| `src/hassette/core/telemetry_repository.py` | Update `_validate_source_tier()` and `reconcile_registrations()` to prefix match; update SQL comments |
| `src/hassette/core/telemetry_query_service.py` | Add `error_traceback` to `get_recent_errors()` SQL; update `get_all_app_summaries()` filter |
| `src/hassette/core/telemetry_models.py` | Add `error_traceback` to `HandlerErrorRecord`, `JobErrorRecord` |
| `src/hassette/core/command_executor.py` | Branch `known_errors` on `cmd.source_tier` with match/case + assertion |
| `src/hassette/utils/execution.py` | Add traceback size cap (8 KB) |
| `src/hassette/web/models.py` | Add `error_traceback` to `HandlerErrorEntry`, `JobErrorEntry`; slim `FrameworkSummaryResponse` to counts only |
| `src/hassette/web/routes/telemetry.py` | Pass `error_traceback` in response; change default tier to `"all"` for both errors and KPIs; remove errors fetch from framework-summary |
| `src/hassette/app/app_config.py` | Update reserved key check from exact match to `is_framework_key()` |
| `src/hassette/config/config.py` | Update reserved key check from exact match to `is_framework_key()` |
| `src/hassette/migrations/versions/004_framework_key_prefix.py` | New migration: table-rebuild with updated CHECK constraint using GLOB |
| `src/hassette/test_utils/harness.py` | Add `component` param to `_register_framework_listener()` wrapper (line 505 calls `register_framework_listener()` directly); keep bare key for `_register_framework_job()` |

### Frontend (Preact)

| File | Change |
|------|--------|
| `frontend/src/utils/framework-keys.ts` | New — `isFrameworkKey()`, `frameworkDisplayName()`, `frameworkDisplayLabel()` |
| `frontend/src/components/dashboard/error-feed.tsx` | Framework-aware rendering (no `<a>` for framework keys), traceback toggle using `ErrorCell` in flex context |
| `frontend/src/components/dashboard/framework-health.tsx` | Remove error feed expansion, keep summary badge with 24h-scoped count |
| `frontend/src/pages/dashboard.tsx` | Remove split error sections; single "Recent Errors" with `source_tier='all'` |
| `frontend/src/api/generated-types.ts` | Regenerated — `error_traceback` on `HandlerErrorEntry` and `JobErrorEntry` |
| `frontend/src/global.css` | Add `ht-traceback-toggle` and `ht-traceback` styles for flex context in error-feed (existing styles are table-specific from app-detail) |

### Tests

| File | Change |
|------|--------|
| `tests/unit/test_types.py` | Test `is_framework_key()`, `framework_display_name()` for both bare and prefixed keys |
| `tests/unit/test_telemetry_repository.py` | Update constraint tests for prefix keys; test GLOB-based CHECK constraint |
| `tests/unit/test_command_executor.py` | Test traceback suppression branching (app vs framework); test assertion on unexpected source_tier |
| `tests/unit/test_execution.py` | Test traceback 8 KB cap in `track_execution()` |
| `tests/integration/test_web_api.py` | Update framework summary assertions (counts-only response); test unified error feed includes both tiers |
| `tests/integration/test_framework_telemetry.py` | Update `"__hassette__"` assertions to accept component-specific keys |
| `tests/integration/test_dispatch_unification.py` | Update `"__hassette__"` assertions to accept component-specific keys |
| `tests/system/test_telemetry_lifecycle.py` | Update hardcoded `app_key = '__hassette__'` SQL assertions |
| `frontend/src/components/dashboard/error-feed.test.tsx` | Framework key rendering (no link), traceback toggle, unified feed with both tiers |
| `frontend/src/components/dashboard/framework-health.test.tsx` | New — test summary-only badge (no error list), count alignment |
| `frontend/src/utils/framework-keys.test.ts` | New — helper function tests for `isFrameworkKey()`, `frameworkDisplayName()`, `frameworkDisplayLabel()` |
| `tests/e2e/test_dashboard.py` | Update panel heading assertions (lines 150-152); update `framework-health` tests (lines 201-224); update `dashboard-errors` assertions; update `ht-tag--framework` assertions for unified feed |
| `tests/e2e/conftest.py` | Update `framework_tier_errors` fixture seeds (lines 634-647) — use component-specific keys instead of bare `"__hassette__"` |

### Documentation

| File | Change |
|------|--------|
| `docs/pages/web-ui/dashboard.md` | Update "System Health" section (now summary badge, no expandable error list); update "Recent Errors" section (now includes framework errors with tier badges and tracebacks); update KPI strip description (counts now include framework) |
| `docs/pages/core-concepts/database-telemetry.md` | Update source-tier note — framework identity is now per-component (`__hassette__.<component>`) rather than a single sentinel |

## Alternatives Considered

**Option A: `source_label` column** — a free-text column on `listeners`/`scheduled_jobs` for display names. Rejected: adds a migration, a new column to maintain, and decouples identity from display. The `app_key` already serves as identity — extending its convention is more natural.

**Option B: Keep split error sections** — keep app and framework errors in separate UI sections but fix the "No recent errors" text. Rejected: two error lists with different visibility creates a cognitive split. Users check one place for errors, not two.

### `FrameworkHealth` badge count alignment

The `FrameworkHealth` badge count should match the scope of the unified feed (last 24 hours, same as the feed's `since_ts`), not the all-time aggregate. Change the `FrameworkSummaryResponse` to use the same time window. This prevents the badge showing "11" while the feed shows 10 — both now draw from the same source.

## Open Questions

None.
