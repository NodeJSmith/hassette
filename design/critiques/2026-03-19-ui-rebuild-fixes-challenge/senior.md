# Skeptical Senior Engineer Review
## Design: UI Rebuild Post-Critique Fixes (009)

---

## Finding 1: The Batch Query Schema Doesn't Match What the Health Strip Needs

**Problem: `AppHealthSummary` as designed is missing the fields `app_health_strip_partial` actually uses.**

The health strip partial (`partials/app_health_strip.html:7-10`) renders `error_rate`, `avg_duration`, and `init_status`. The `init_status` field comes from `instance.status` — a live runtime field, not a telemetry field. The proposed `AppHealthSummary` model contains `handler_count`, `job_count`, `total_invocations`, `total_errors`, `error_rate`, `avg_duration_ms`, `last_activity_ts`. No `init_status`.

The current `app_health_strip_partial` route (`partials.py:160-178`) calls `runtime.get_all_manifests_snapshot()` to get `instance.status` separately, then also calls two telemetry queries. The design proposes that `compute_app_grid_health()` becomes "a thin wrapper that calls this method once" — but `compute_app_grid_health` feeds the dashboard grid (`partials/dashboard_app_grid.html`), not the health strip. The health strip partial has a separate route and separate context needs.

**What happens when this assumption is wrong:** The health strip route still needs two separate concerns: one from telemetry (error rate, duration) and one from the runtime (init_status). The batch method doesn't merge those. After the change, either (a) the health strip route still does its own two-query call making the batch irrelevant for that path, or (b) someone wires `init_status` into `AppHealthSummary` requiring a cross-service join between `TelemetryQueryService` and `RuntimeQueryService`, which violates the service boundary.

**Evidence:** `partials.py:174-176` — `init_status` is assembled from `instance.status` (runtime), then merged with `health` (telemetry). The batch query only knows about the telemetry side.

**Better approach:** Make `get_all_app_summaries()` return purely telemetry fields. Keep the health strip route calling `compute_health_metrics()` directly as it does now. Only replace the dashboard grid's N+1 with the batch. Don't conflate the two callers.

**Design question:** Which specific route(s) is `get_all_app_summaries()` intended to replace? The dashboard grid partial? The health strip? Both? The design doesn't name the callers explicitly.

---

## Finding 2: The Morph Extension Load Order Is Backwards

**Problem: The design says add `@alpinejs/morph` "before Alpine core, as required" but this requirement isn't what the alpine-morph HTMX extension actually needs.**

The `@alpinejs/morph` plugin is an Alpine plugin — it must be registered _after_ Alpine initializes via `Alpine.plugin(AlpineMorph)` in a `document.addEventListener('alpine:init', ...)` callback, or loaded before `Alpine.start()` is called. The `alpine-morph` htmx extension is a separate package (`https://github.com/imacrayon/alpine-morph`) that wraps the Alpine morph plugin for use with HTMX. It depends on both HTMX and the Alpine morph plugin being available at the time the extension loads.

The current `base.html:22-28` loads scripts in this order:
1. `htmx.org` (synchronous, line 22)
2. `idiomorph-ext.min.js` (synchronous, line 23)
3. `ws-handler.js` (defer, line 24)
4. `live-updates.js` (defer, line 25)
5. `log-table.js` (defer, line 26)
6. Alpine CDN (defer, line 27-28)

The design proposes adding `@alpinejs/morph` "before Alpine core." If both are loaded with `defer`, execution order is determined by document order. But the `alpine-morph` HTMX extension needs to register itself as an HTMX extension _and_ use the Alpine morph plugin. If Alpine is `defer` but the extension script is synchronous, Alpine may not be initialized yet when the extension tries to use it. If both are `defer`, there's no guarantee Alpine has called `Alpine.start()` before the extension tries to call `Alpine.morph()`.

**What happens when this assumption is wrong:** `Uncaught ReferenceError: Alpine is not defined` or `Alpine.morph is not a function` in production on slower connections where defer scripts race. This is a silent failure — the morph silently falls back to replace, destroying Alpine state, which is exactly the bug being fixed.

**Evidence:** `base.html:27-28` — Alpine is already `defer`. Adding another `defer` extension script doesn't guarantee initialization order.

**Better approach:** Use `Alpine.plugin(AlpineMorph)` in a `document.addEventListener('alpine:init')` block in a local script, or switch to the import-map pattern. Alternatively: load `@alpinejs/morph` without defer (blocking), then Alpine without defer — but that blocks rendering. The safest approach is using `type="module"` with proper import ordering or moving to a bundled JS file.

**Design question:** Has anyone tested the `alpine-morph` HTMX extension with a CDN-deferred Alpine setup, or is this assumption based on the extension's own README which may assume a different loading model?

---

## Finding 3: Deleting the Polling Div Assumes Alpine-Morph Reliably Keeps Rows Expanded

**Problem: The design deletes the stats polling as "redundant dead code" because alpine-morph will preserve expanded row state. But the `app_handlers.html` partial has no Alpine `x-data` on individual rows — the expanded state lives in the parent page scope, which survives a page transition but may not survive an HTMX inner swap.**

The current `app_handlers.html` partial (`partials/app_handlers.html:1-10`) is a flat list of `handler_row()` macro calls inside a `div.ht-item-list`. The handler rows themselves contain Alpine state for expand/collapse (the traceback display at `app_detail.html:72-78` uses `x-data="{ tbOpen: false }"`). When the `#app-handlers` div is morphed, alpine-morph needs to match old DOM nodes to new DOM nodes by identity.

Idiomorph and alpine-morph both use element matching heuristics. If a handler row doesn't have a stable `id` attribute, the morph may not match it to the same node — it may create a new node, which means a fresh `x-data`, which means `tbOpen` resets to `false`, collapsing any open tracebacks.

**What happens when this assumption is wrong:** A user opens a traceback to investigate an error. Thirty seconds later an `app_status_changed` event fires (because a different app restarted), triggers a morph of `#app-handlers`, and the open traceback collapses. This is exactly the "morph destroying investigation state" problem that was critique finding #2 — it's not fixed, it's shifted from "always destroys state" to "destroys state when handler rows lack stable IDs."

**Evidence:** `app_handlers.html:3-7` — the `handler_row` macro is called but the rendered rows have no `id` attribute shown in the partial. If the macro doesn't emit `id="handler-{{ listener.listener_id }}"` (or similar), morph matching is positional, not identity-based.

**Better approach:** Ensure every handler row and job row has a stable `id` attribute keyed by `listener_id` / `job_id`. Both are primary keys available in the template context. This is required for morph to preserve node identity. Document it as a constraint in the template guide.

**Design question:** Does the `handler_row` macro in `macros/ui.html` emit a stable `id` on the row container? If not, what's the morph matching strategy?

---

## Finding 4: The `live-updates.js` Swap Strategy Detection Is Undefined

**Problem: The design says "update `live-updates.js` to detect which morph extension an element uses and set the correct swap strategy" — but the current code hard-codes `swap: "morph:innerHTML"` for all swaps, and the detection mechanism is completely unspecified.**

The current `live-updates.js:91` does:
```javascript
htmx.ajax("GET", refreshUrl, { target: target, swap: "morph:innerHTML" });
```

This always uses idiomorph (`morph:` prefix). The design intends that for elements with `hx-ext="alpine-morph"`, the swap should instead use the alpine-morph strategy. But `hx-ext` on an element affects HTMX-triggered requests from that element — it does not affect programmatic `htmx.ajax()` calls from external JS.

When `live-updates.js` calls `htmx.ajax()` targeting an element that has `hx-ext="alpine-morph"`, HTMX processes the swap using whatever is configured in the `htmx.ajax` call's `swap` parameter. The `hx-ext` attribute on the target element is not consulted for the swap strategy — extensions register themselves on the triggering element context, not on the target.

**What happens when this assumption is wrong:** All `data-live-on-app` swaps continue to use idiomorph regardless of `hx-ext="alpine-morph"` on the target. Alpine state is still destroyed on every live update. Finding #2 from the original critique is not fixed.

**Evidence:** `live-updates.js:89-93` — the `htmx.ajax` call is a programmatic invocation from outside HTMX's normal event pipeline. `hx-ext` only applies to HTMX's own request lifecycle triggered by user interaction or `hx-trigger`.

**Better approach:** Either (a) use `htmx.ajax()` with `swap: "alpine-morph"` (if the alpine-morph extension registers a named swap strategy, which needs verification), or (b) instead of calling `htmx.ajax()`, synthesize an HTMX trigger event (`htmx.trigger(el, 'refresh')`) on elements that already have `hx-get` and `hx-trigger` configured, letting HTMX process the swap through its normal extension pipeline. Option (b) requires adding `hx-get` and `hx-trigger="refresh"` to the live containers, which is a template change.

**Design question:** Has anyone verified that `htmx.ajax({ swap: "alpine-morph" })` is a valid swap value that alpine-morph intercepts? What is the exact swap string the alpine-morph extension registers?

---

## Finding 5: The `manifest_list.html` Alpine Scope Assumption Will Break on HTMX Swap

**Problem: The design says the partial's `x-show="activeTab === '{{ manifest.status }}'"` will work because "the receiving `<tbody>` already has Alpine scope from the page's `x-data`." This is wrong for how Alpine processes dynamically-swapped content.**

When HTMX swaps in new HTML, Alpine does not automatically initialize Alpine directives on the new nodes unless `Alpine.initTree(el)` is called on the swapped element. HTMX has an `htmx:afterSwap` event, and Alpine's HTMX integration typically requires the `hx-on:htmx:after-swap="$nextTick(() => Alpine.initTree($el))"` pattern or similar, unless the global `MutationObserver` in Alpine catches it.

Alpine does register a `MutationObserver` on `document.body` by default, so new nodes _are_ initialized automatically. However, the `x-show` on partial rows references `activeTab` — which must be found by Alpine by walking up the DOM to find a parent with `x-data` that defines `activeTab`. If the `<tbody>` is swapped via HTMX into a `<table>` that is inside the `x-data="{ activeTab: 'all', expanded: {} }"` div (line 22 of `apps.html`), and the `<tbody>` itself is the swap target, Alpine can walk up through `<table>` to find `activeTab` in the parent scope.

But here's the catch: when the partial is served as a standalone HTMX response (not as `{% include %}`), it is a bare fragment of `<tr>` elements. If the swap target is `<tbody id="manifest-list">` and the swap strategy is `innerHTML` (replacing only inner content), the `<tbody>` element itself remains in the DOM as a descendant of the `x-data` parent. Alpine can resolve `activeTab` from the parent scope. This actually works.

**However**, the current `manifest_list.html` partial (lines 3-5) does not have `x-show` on the rows — the page (`apps.html:54`) has `x-show` on each row, but the partial does not. The design proposes adding `x-show` to the partial, but the page currently renders rows _inline_ (not via `{% include manifest_list.html %}`). If the design also changes the page to `{% include %}` the partial, then tab counts in the filter tabs (which are server-rendered from `manifest_snapshot.total`, `.running`, etc.) become stale after an HTMX swap because only the `<tbody>` is updated, not the filter tab counts.

**What happens when this assumption is wrong:** After an HTMX live update swaps new rows into the `<tbody>`, tab "Running (3)" still shows `3` even if an app just stopped. The tab counter is a Jinja expression rendered at page load time and never updated. Filtering works (Alpine hides/shows rows), but the counts are wrong.

**Evidence:** `apps.html:26-33` — filter tab counts (`manifest_snapshot.running`, etc.) are server-rendered into `<a>` text at page-load time. The `data-live-on-app="/ui/partials/manifest-list"` attribute on `<tbody>` at `apps.html:48` only refreshes the rows, not the tab header.

**Better approach:** Either (a) wrap the entire apps card (tabs + table) in a single live-refreshable container with a single partial that re-renders both, or (b) accept that tab counts are stale and document it as a known limitation. Option (a) requires a new partial. Don't ship tab count staleness without acknowledging it — users will file it as a bug.

**Design question:** Should tab counts update after live refreshes, or is stale count acceptable? The design is silent on this.

---

## Finding 6: `get_global_summary()` Returns `None` Paths That `GlobalSummary` Can't Model

**Problem: The design says wire `get_global_summary()` to return `GlobalSummary | None`. But `GlobalSummary` requires `listeners: ListenerGlobalStats` — a model with non-optional integer fields. If the query returns no rows, the code constructs `GlobalSummary` from empty dicts, which will fail Pydantic validation.**

Current code (`telemetry_query_service.py:205-211`):
```python
listener_data = _row_to_dict(listener_row) if listener_row else {}
job_data = _row_to_dict(job_row) if job_row else {}
return {"listeners": listener_data, "jobs": job_data}
```

If `listener_row` is `None`, `listener_data` is `{}`. `ListenerGlobalStats` requires `total_listeners: int`, `invoked_listeners: int`, etc. — all non-optional. Constructing `GlobalSummary(listeners={}, jobs={})` raises a Pydantic `ValidationError`.

The design proposes returning `GlobalSummary | None` but doesn't specify the logic for when to return `None` vs construct the model. The current return-`None` condition is implicit: the query always returns exactly one row (it's an aggregate without `WHERE`, so it always produces a row with NULLs or zeros, not zero rows). So `listener_row` is never actually `None` in practice — but `fetchone()` can return `None` if the database is brand new with zero rows, and several aggregate functions like `AVG()` return NULL which becomes `None` in Python and fails `float | None` coercion on `avg_duration_ms: float | None` ... except `ListenerGlobalStats.avg_duration_ms` is declared as `float | None`, so that's fine. But `total_listeners: int` will be 0 not None.

The real risk: on a fresh install with no handler invocations, `COUNT(hi.rowid)` returns `0` and `AVG(hi.duration_ms)` returns `NULL`. The current dict-based code silently passes these through as `None` in `avg_duration_ms`. Converting to `GlobalSummary` with `avg_duration_ms: float | None` works. But if `get_global_summary()` is changed to return `GlobalSummary | None` and the caller switches from `.get()` to attribute access, a `None` return crashes the template.

**What happens when this assumption is wrong:** On a fresh Hassette install with no recorded invocations, the dashboard crashes with `AttributeError: 'NoneType' object has no attribute 'listeners'` or a Pydantic `ValidationError` on the very first page load.

**Evidence:** `telemetry_query_service.py:205-206` — the empty-dict fallback is a landmine. `telemetry_models.py:83-107` — `GlobalSummary` requires non-optional nested models.

**Better approach:** Provide zero-value defaults in `ListenerGlobalStats` and `JobGlobalStats` using `model_fields` defaults, then always return `GlobalSummary` (never `None`). The dashboard should never crash due to no data — it should render zeros. Change the return type to `GlobalSummary` (non-optional) and handle the zero case inside the query method with `COALESCE`.

**Design question:** Under what conditions should `get_global_summary()` return `None`? If the database is unreachable, an exception is raised anyway. If there's no data, zeros are correct. What is the actual `None` case?

---

## Finding 7: `classify_error_rate()` Disagrees With the Existing Health Strip Threshold

**Problem: The new `classify_error_rate()` function uses `< 5` as the "good" threshold. The existing `app_health_strip.html` uses `> 5` as the "bad" threshold. These are different cutpoints.**

Design proposes:
```python
if rate == 0: return "good"
if rate < 5:  return "good"   # 0–4.99% → good
if rate < 10: return "warn"   # 5–9.99% → warn
return "bad"                  # ≥10% → bad
```

Current `app_health_strip.html:8-9`:
```jinja
status_class="good" if error_rate == 0 else ("bad" if error_rate > 5 else "warn")
```

The current template classifies: 0% → good, 0.01–5% → warn, >5% → bad.

The new function classifies: 0–4.99% → good, 5–9.99% → warn, ≥10% → bad.

So a 3% error rate shows "warn" in the current health strip but will show "good" after centralization. An 8% error rate shows "bad" currently but "warn" after. This is a silent semantic change disguised as a refactor.

**What happens when this assumption is wrong:** Users who tuned their attention to health strip colors will see everything look "better" after the update without any actual improvement. An app at 7% error rate will flip from red (bad) to yellow (warn). This erodes trust in the monitoring UI.

**Evidence:** `app_health_strip.html:8-9` — current threshold is `> 5` for bad. Design spec proposes `< 5` for good / `< 10` for warn, which is materially different.

**Better approach:** Before centralizing, explicitly decide which threshold is correct and document it as a product decision, not a refactoring side-effect. If the new thresholds are intentional, call it out in the commit message and changelog.

**Design question:** Is the threshold change intentional (product decision) or an oversight? Who owns the decision on what constitutes "warn" vs "bad" error rates?

---

## Summary

| # | Risk | Severity | Will It Fail Silently? |
|---|------|----------|----------------------|
| 1 | Batch query missing `init_status` for health strip route | HIGH | Yes — health strip continues its own N+1 |
| 2 | Alpine morph CDN load order race | HIGH | Yes — morph silently falls back to replace |
| 3 | Handler rows need stable `id` for morph matching | HIGH | Yes — traceback collapses, user doesn't know why |
| 4 | `htmx.ajax()` ignores `hx-ext` on target element | CRITICAL | Yes — alpine-morph never fires from live-updates.js |
| 5 | Tab counts stale after live refresh | MEDIUM | No — visible wrong count |
| 6 | `GlobalSummary` construction crashes on fresh install | HIGH | No — Pydantic raises on first dashboard load |
| 7 | Threshold change disguised as refactor | MEDIUM | Yes — colors change silently |

**The most dangerous finding is #4.** If `htmx.ajax()` with a programmatic target ignores `hx-ext` on that target, the entire hybrid morph strategy for live updates doesn't work. The alpine-morph extension only activates through HTMX's normal request pipeline. Before committing to this architecture, verify with a minimal testcase that `htmx.ajax({ swap: "..." })` actually invokes the alpine-morph swap hook.
