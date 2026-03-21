# Architect Review: Design 009 — UI Rebuild Post-Critique Fixes

**Reviewer:** Systems Architect
**Date:** 2026-03-19
**Design doc:** `design/specs/009-ui-rebuild-fixes/design.md`

---

## Summary

The design fixes real problems. The N+1 elimination is overdue, the morph strategy problem is correctly diagnosed, and the dead polling deletion is clean. But three structural issues deserve attention before implementation begins: a batch query whose shape is already misaligned with its consumer, a partial typed-model migration that leaves the codebase in mixed state, and a morph detection mechanism that buries routing logic in the wrong layer.

---

## Finding 1 — `AppHealthSummary` shape diverges from what `compute_app_grid_health()` actually computes

**Problem: Tight coupling between query result shape and presentation-layer aggregation logic.**

The design proposes a new `AppHealthSummary` model with fields including `error_rate` and `avg_duration_ms` (`design.md:37`). But the existing `compute_app_grid_health()` (`context.py:112–148`) does not just expose raw DB fields — it *derives* presentation-layer quantities: `success_rate = 100.0 - health["error_rate"]` (`context.py:137`), and it builds `last_activity_ts` by merging listener and job timestamps (`context.py:74–76` via `compute_health_metrics`).

If `AppHealthSummary` is populated entirely inside `get_all_app_summaries()` in the service layer, then `error_rate` has to be computed there (it's derived: `failed / total_invocations * 100`). That forces a division-by-zero guard and a percentage calculation into SQL or into the service. Then `compute_app_grid_health()` becomes a thin wrapper — but it still needs to derive `success_rate`, which isn't in the model, so the caller *still* has to post-process the model's data. Now you have derivation logic split between the service and the context helper.

Worse: if the design adds `avg_duration_ms` to `AppHealthSummary` (as listed), it inherits the flaw in `compute_health_metrics` — that function computes a *mean of averages* (`context.py:72–73`), which is statistically wrong for unequal bucket sizes. Promoting that bug into the canonical Pydantic model makes it harder to fix later.

**Evidence:**
- `context.py:136–137`: `success_rate` derived from `error_rate` post-query
- `context.py:72–73`: mean-of-averages bug in `compute_health_metrics`
- `design.md:37`: `AppHealthSummary` includes `error_rate` and `avg_duration_ms` as model fields

**Better approach:** Keep `AppHealthSummary` as a raw-metrics DTO (counts only: `handler_count`, `job_count`, `total_invocations`, `total_errors`, `total_duration_ms`, `last_listener_ts`, `last_job_ts`). Let the context helper derive `error_rate`, `success_rate`, and `last_activity_ts` from those primitives. The service layer stays free of presentation logic; the derivations are in one place and testable in isolation.

**Design question:** If the thresholds in `classify_error_rate()` change (e.g., the team decides 3% is "warn"), should the service layer's SQL-backed aggregation care? If not, raw counts in the DTO are the right boundary.

---

## Finding 2 — Typed model migration is half-done; `get_global_summary()` stays a `dict`

**Problem: After the fix, the codebase is in a worse mixed state than before.**

`telemetry_models.py` already has `GlobalSummary` (line 103) and `SessionSummary` (line 110). The design correctly identifies they're unused (finding #4). But look at what the fix actually changes:

- `get_global_summary()` currently returns `dict | None` (`telemetry_query_service.py:150`). The design says "wire `GlobalSummary`" — but the template at `dashboard.html:19` calls `global_summary.listeners.get("total_invocations", 0)`. Dict `.get()` with a default is the access pattern. If the return type becomes `GlobalSummary`, templates must switch to `global_summary.listeners.total_invocations` — but the design only mentions this for `dashboard.html` (`design.md:65`).

- `get_current_session_summary()` returns `dict | None` (`telemetry_query_service.py:377`). `dashboard.html:94` accesses `session_summary.total_invocations` — *already* using attribute access, not `.get()`. That means either the template was written expecting a Pydantic model that was never wired, or it accidentally works because dicts don't support attribute access and this is a latent bug nobody has exercised in a template render.

- After the fix: `get_all_app_summaries()` returns `dict[str, AppHealthSummary]` (typed). `get_global_summary()` returns `GlobalSummary | None` (typed). `get_current_session_summary()` returns `SessionSummary | None` (typed). `get_recent_errors()` still returns `list[dict]` (`telemetry_query_service.py:255`). `get_session_list()` still returns `list[dict]` (`telemetry_query_service.py:358`). The "typed models" finding is fixed for three methods and explicitly not addressed for two others.

When requirements change — someone wants to add a field to error records, or rename a column — they still face the silent-failure mode for the un-migrated methods. The fix reduces the problem but doesn't establish a pattern that holds.

**Evidence:**
- `dashboard.html:94`: `session_summary.total_invocations` — attribute access on a `dict` return; latent runtime error if `session_summary` is not `None` and the template actually renders this path
- `telemetry_query_service.py:255, 358`: two query methods still return raw dicts after the migration
- `telemetry_models.py:103, 110`: models exist but are imported nowhere in the current service file (confirmed by absence of `GlobalSummary` in the `from hassette.core.telemetry_models import` statement at `telemetry_query_service.py:7–12`)

**Better approach:** Either complete the migration for all query methods in this PR (add `ErrorRecord` and `SessionRecord` models), or explicitly scope this finding to "typed models for dashboard-critical paths only" and track the remaining methods as follow-up. What you cannot do is leave `dashboard.html:94` as attribute access against a `dict` — that's a bug the typed model migration was supposed to prevent, and it's being introduced here.

**Design question:** Is `session_summary.total_invocations` in `dashboard.html:94` tested by any E2E test that would catch a `AttributeError` on a plain dict? If not, how will the team know this path is broken in the current code?

---

## Finding 3 — Threshold functions in `context.py` are the wrong home

**Problem: Presentation constants live in web infrastructure code, creating an implicit coupling between the query layer and the view layer.**

`context.py` is described in the design as the home for `classify_error_rate()` and `classify_health_bar()` (`design.md:69–93`). The file already contains `compute_app_grid_health()`, `compute_health_metrics()`, `format_handler_summary()`, `alert_context()`, and `base_context()` — a mix of query orchestration helpers, string formatting, and context assembly. Adding threshold classification functions here makes the file a general-purpose utility bag.

The specific risk: `context.py` is imported by both `router.py` and `partials.py` (`router.py:8–15`, `partials.py:8–14`). When requirements change — "make the threshold configurable per-user", "make it configurable in the HA config", "use a different scale for the health bar on mobile" — the change surface includes both routes and every template that calls these functions as Jinja2 globals. The functions encode policy (5% is "warn", 10% is "bad") in web infrastructure code. If those numbers come from user config in the future, `context.py` is the wrong place to discover them from.

The design also proposes passing these functions "via template context or as Jinja2 globals" (`design.md:93`). If they become Jinja2 globals, they are invisible in the context dict — undiscoverable from `router.py`. If passed via context, every route handler must explicitly include them, which will be forgotten.

**Evidence:**
- `context.py:22–110`: already mixes four different concerns (context assembly, query orchestration, string formatting, structural helpers)
- `design.md:69–93`: threshold functions encode `5` and `10` as magic numbers with no configuration path
- `router.py:8–15` and `partials.py:8–14`: both import from `context.py`; both would need to pass through threshold functions to templates

**Better approach:** Define a `thresholds.py` module (or a `HealthThresholds` dataclass in `telemetry_models.py`) that owns all classification constants. Templates receive a single `thresholds` object in context. If thresholds later become configurable, one injection point changes — not every route handler. The Jinja2 global approach is acceptable only if thresholds are truly universal constants; if there's any chance they become configurable, the global registration hides a future injection point.

**Design question:** What's the intended path for making thresholds configurable — say, if an operator with a Pi wants to relax the "warn" threshold to 15% because their hardware is slow and they accept higher error rates? Is `context.py` the place that would need to change, and does that feel right?

---

## Finding 4 — Hybrid morph detection belongs in the template, not in `live-updates.js`

**Problem: The JS layer is being asked to make routing decisions that are already encoded in the HTML.**

The design states: "Update `live-updates.js` to detect which morph extension an element uses and set the correct swap strategy" (`design.md:51–52`). This means `live-updates.js` will inspect each `data-live-on-app` container for the presence of `hx-ext="alpine-morph"` and then choose a different `hx-swap` value accordingly.

This creates a hidden contract: the template must set `hx-ext` correctly, and `live-updates.js` must know to check for it and translate it into a swap strategy. If someone adds a new container with Alpine state and forgets `hx-ext="alpine-morph"`, the morph destroys the state — silently, with no error. The detection logic is non-local: the signal is in the HTML attribute, but the consequence is computed in JS.

The deeper issue is that this design creates *two* code paths in `live-updates.js` for what is conceptually one operation: "refresh this container". The old path does `morph:innerHTML`. The new path does... something else (the design doesn't name the swap value for alpine-morph). When requirements change — e.g., a third container type needs yet another swap strategy — the detection switch in `live-updates.js` grows a third branch.

**Evidence:**
- `design.md:51–52`: "detect which morph extension an element uses and set the correct swap strategy"
- The existing `data-live-on-app` pattern in `dashboard.html:67–68` and the HTMX morph pattern described in `CLAUDE.md` ("All swaps use idiomorph `morph:innerHTML`")

**Better approach:** Make the swap strategy explicit in the HTML attribute rather than derived from `hx-ext`. A `data-live-swap="morph"` or `data-live-swap="alpine-morph"` attribute on each container lets `live-updates.js` read the strategy directly — no inference required. Defaults to `morph:innerHTML` when absent. The template author declares intent; the JS honors it. When a new swap strategy is needed, you add an attribute value and a case in `live-updates.js` — both changes are local and explicit.

**Design question:** Does alpine-morph expose a different HTMX swap value, or does it hook into HTMX's extension mechanism to intercept the existing swap? If the swap value is the same (`morph:innerHTML`) and alpine-morph only changes *how* the morph runs, then the JS detection logic may be unnecessary — the extension does the work transparently.

---

## Finding 5 — `manifest_list.html` dual-use contract is unenforceable

**Problem: The partial-as-include dual-use pattern creates a fragile implicit contract.**

Finding #7 proposes that `manifest_list.html` be written so it works both as `{% include %}` inside the page and as a standalone HTMX partial response (`design.md:97–99`). The mechanism: the partial emits rows with `x-show="activeTab === '{{ manifest.status }}'"`, relying on `activeTab` being defined in the *parent* Alpine scope when included, and in the *page's surviving Alpine scope* when swapped via HTMX.

The contract is: "the receiving `<tbody>` already has Alpine scope from the page's `x-data`." This is true only if the HTMX swap target is a descendant of the `x-data` element — not the `x-data` element itself. If the swap target *is* the `x-data` container, Alpine morph must handle scope preservation. The design asserts this works ("Alpine morph preserves parent scope"), but the correctness depends on the exact DOM nesting and which morph extension is active at that point — exactly the hybrid complexity introduced by finding #2.

When requirements change — say, a new "paused" status is added to the filter tabs — the template author must update: the page's tab list, the partial's `x-show` expression, and the route filter logic. There's no single place to find all three. The `x-show` expression in the partial references a variable (`activeTab`) that is defined nowhere in the partial itself, making the partial's standalone testability zero.

**Evidence:**
- `design.md:97–99`: dual-use contract described
- `partials.py:34–44`: `manifest_list_partial` already does server-side status filtering via `?status=` query param — the Alpine `x-show` approach is a *client-side* duplication of that logic

**Better approach:** Choose one filtering strategy. If server-side: the partial receives pre-filtered data; the page's tab switcher triggers an HTMX request with `?status=<tab>`. No Alpine `x-show` needed in the partial. If client-side: Alpine `x-show` in the page, no HTMX refresh for tab switching. Mixing both creates duplicate filter logic with no canonical source of truth. The server-side approach is already partially implemented (`partials.py:40–43`) and is the cleaner path given that the page needs HTMX for live updates anyway.

**Design question:** Does the filter tab need to switch instantly (client-side, no network round trip) or is a fast HTMX request acceptable? The answer determines which filtering strategy to commit to — and committing to one eliminates the dual-use complexity entirely.

---

## Cross-Cutting Observation: `compute_app_grid_health()` straddles two query granularities

The existing function in `context.py:112–148` calls `get_listener_summary()` and `get_job_summary()` per app — which are per-app-instance queries returning full listener/job detail. The new `get_all_app_summaries()` will return aggregate-only data across all apps. After the migration, `compute_app_grid_health()` becomes a "thin wrapper" — but `app_health_strip_partial` in `partials.py:160–178` will still call the per-app methods directly to render the health strip on the app detail page.

This means the dashboard uses the batch path and the detail page uses the N+1 path — but both go through the same conceptual function family. When a third consumer appears (e.g., an API endpoint for monitoring), it is not obvious which path to use. The architectural distinction between "aggregate health for grid display" and "detailed health for per-app strip" should be explicit in the service interface, not implicit in which method the caller happens to choose.
