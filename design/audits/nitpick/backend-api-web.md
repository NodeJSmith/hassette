# Nitpick Report: API Layer and Web Backend

**Scope:** `src/hassette/api/` and `src/hassette/web/` (21 files)
**Date:** 2026-05-21

---

## 1. Magic Numbers and Strings

**`api/api.py:640`** — Magic literal `404` repeated across two nearly-identical methods (`get_entity_or_none` and `get_state_or_none`). Also duplicated at `api.py:669`. No named constant.

**`api/api.py:966`** — Magic literal `204` in `delete_entity`. No named constant for the expected success status code.

**`api/api.py:588`** — URL fragment `"states/{entity_id}"` is a bare string constructed inline. This same pattern appears at lines 603, 860, 962 — four sites, no constant for the `"states/"` prefix.

**`api/api.py:903`** — URL `"calendars"` inline at call site.

**`api/api.py:925`** — URL `"calendars/{calendar_id}/events"` inline at call site.

**`api/api.py:943`** — URL `"template"` inline at call site.

**`web/routes/logs.py:23`** — `86400` (seconds per day) is named `_SECONDS_PER_DAY` — good. But the inline `86400` in `telemetry.py:212` is a separate occurrence of the same value with no constant, see below.

**`web/routes/telemetry.py:212`** — `86400` bare literal in `effective_since = since if since is not None else time.time() - 86400`. A different file defines `_SECONDS_PER_DAY = 86400` for the same concept; this should reuse it.

**`web/routes/telemetry.py:329`** — `num_buckets=12` passed inline; `_NUM_SPARKLINE_BUCKETS = 12` is defined at line 300 and should be used here.

**`web/app.py:49`** — `"Hassette Web API"` title string is a bare literal. Minor, but also appears conceptually in `openapi_url="/api/openapi.json"` and `docs_url="/api/docs"` — the `"/api"` prefix is repeated 11 times across `app.py` lines 63–72 as individual string arguments; none are centralized.

**`web/app.py:58–59`** — Method list `["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]` and header list `["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"]` are bare literals buried in business logic.

**`web/routes/ws.py:16`** — `_LOG_LEVELS` maps level names to integer values (`10`, `20`, `30`, `40`, `50`). These are `logging.DEBUG`, `logging.INFO`, etc. — use the stdlib constants rather than bare ints. The fallback `0` at line 73 is also bare.

**`web/routes/ws.py:51`** — String `"INFO"` appears as a default level in three distinct places within the same function: lines 51, 53, 54, and again as the initial state at line 90. No named constant.

---

## 2. Scattered Constants

**`web/routes/logs.py:21–23`** — `_VALID_LEVELS` and `_VALID_SOURCE_TIERS` are defined in `logs.py` but the same concept of valid levels is independently derived in `ws.py` via `_LOG_LEVELS`. These two files have parallel but disconnected representations of the same domain knowledge.

**`web/routes/ws.py:16`** — `_LOG_LEVELS` duplicates the stdlib `logging` module's level constants. The dict serves as a private reimplementation. Using `logging.getLevelName` / `logging._nameToLevel` or `logging.DEBUG` etc. would centralize the source of truth.

**`web/app.py:26–27`** — `_STATIC_DIR` and `_SPA_DIR` are fine. But the sub-path strings `"assets"`, `"fonts"`, `"index.html"` (lines 76–78, 96) are scattered inline rather than named.

**`web/telemetry_helpers.py:63–68`** — The thresholds `5`, `10` in `classify_error_rate` and `95`, `90`, `100` in `classify_health_bar` (lines 77–83) are magic numbers defining health classification tiers — they should be module-level named constants. These thresholds are the kind of value that will be tweaked, and currently they live in opaque conditionals.

**`web/routes/apps.py:22–23`** — The regex patterns `_VALID_APP_KEY` and `_SECRET_KEYS` are at module level (good), but `"***REDACTED***"` on line 33 is a bare string in the transform function — should be a named constant.

---

## 3. Ternary Abuse

**`web/routes/ws.py:53`** — `level = raw_level.upper() if isinstance(raw_level, str) else "INFO"` — acceptable single-level ternary, but immediately followed by `ws_state["min_log_level"] = level if level in _LOG_LEVELS else "INFO"` on line 54. Two consecutive conditional assignments with the same default make the intent murky; an early-return guard or a helper would be cleaner.

**`web/utils.py:69`** — `"fire_at": live_job.fire_at.timestamp() if live_job.jitter is not None else None` — condition tests `jitter` but accesses `fire_at`. The condition name doesn't match what's being guarded. This is a logic smell masquerading as a style smell: the test predicate (`live_job.jitter is not None`) doesn't obviously justify accessing a different field (`live_job.fire_at`). At minimum, a comment is required; ideally the condition tests `live_job.fire_at is not None`.

No multi-level nested ternaries found.

---

## 4. CSS and Styling Sins

(skipped — Python backend code)

---

## 5. Dead Code

**`api/api.py:398–419`** — `get_states_iterator` defines an inner function `yield_states()` with a `nonlocal raw_states` declaration but `raw_states` is never reassigned inside the function — the `nonlocal` is unnecessary noise.

**`web/telemetry_helpers.py:86–91`** — `base_context` returns a dict with `"current_page"` and `"hassette_version"`. This function exists to support "legacy Jinja2 partials" per the module docstring, but no Jinja2 templates exist in the reviewed scope. Verify whether any caller remains; if the Jinja2 migration is complete, this is dead code.

**`web/telemetry_helpers.py:94–106`** — `alert_context` similarly builds a Jinja2-style context dict. Same concern: if the legacy UI has been fully replaced, this function is dead.

**`web/telemetry_helpers.py:125–156`** — `compute_health_metrics` returns a plain `dict`. The identical computation is performed inline in `web/routes/telemetry.py:145–173` without calling this helper. Either the helper is unused (dead code), or the inline version is a duplicate that should call the helper. Either way, one of them should be removed.

**`web/routes/apps.py:116`** — `app_instance = hassette.app_handler.registry.get(app_key)` — the variable `app_instance` is used only to extract its type on line 119 (`type(app_instance).app_config_cls`). No issue per se, but the name `app_instance` is misleading — it's used to get the class, not to invoke the instance.

No commented-out code blocks found. No TODO/FIXME/HACK comments without tickets found.

---

## 6. Naming Inconsistencies

**`web/routes/telemetry.py:145, 160`** — `total_invocations` is computed at line 145 and then recomputed into `total_handler_inv` at line 160. These are the same value (`sum(ls.total_invocations for ls in listeners)`). The rename from `total_invocations` to `total_handler_inv` six lines later breaks naming continuity and the duplicate computation is waste.

**`web/routes/telemetry.py:155–156`** — Variables named `total` and `errors` here (local to `app_health`) shadow/parallel `total_invocations` and `handler_errors` which were already computed above. Four names for two concepts in 20 lines.

**`web/routes/ws.py:41, 62`** — Parameter `ws_state: dict` — `dict` is an untyped annotation. The dict has a known shape (`{"subscribe_logs": bool, "min_log_level": str}`); it should be `TypedDict` or at minimum `dict[str, Any]`.

**`web/routes/ws.py:90`** — `ws_state: dict = {...}` — same issue; the annotation is bare `dict`.

**`web/routes/bus.py:25`** — Variable `effective_tier` — used identically in `telemetry.py` at lines 125, 188, 211, 243 and in `scheduler.py` at line 37. It's a consistent pattern but defined four separate times with identical logic (`source_tier if source_tier is not None else "app"`). This one-liner pattern should be a shared helper or default should be set at the `Query()` level.

**`web/routes/bus.py:22`** — `instance_index: Annotated[int, Query()] = 0` — default `0` here; in `telemetry.py` the same parameter uses `int = 0` (bare type, no `Annotated`). Inconsistent annotation style for the same parameter across routes.

**`web/routes/telemetry.py:119, 182, 204, 228`** — The `app_key` path parameter has an inline `Path(description=...)` with the identical string `"Use \`__hassette__\` to query framework-internal actor telemetry."` repeated four times. This string should be a module-level constant.

**`api/api.py:692`** — Return type annotation `"Any"` is a quoted string for no reason — it's not a forward reference and `Any` is already imported on line 163. The annotation on `get_state_value_typed` reads `-> "Any":` while all other methods use `-> Any:` unquoted.

**`api/api.py:863`** — Variable `curr_attributes` is initialized to `{}` then conditionally reassigned; `new_attributes` is then computed from it. Two variable names for what is effectively one value going through a transform. `curr_attributes = {}` followed by the conditional assignment is a mutable-init pattern that could be a single conditional expression.

**`web/routes/apps.py:44`** — `_require_known_app` takes `hassette: HassetteDep` as its second parameter. But `HassetteDep` is a `typing.Annotated` type alias — it's the FastAPI injection alias, not appropriate for a plain helper function that receives the already-resolved `Hassette` object. The type annotation here should be `"Hassette"` (the concrete type), not `HassetteDep`.

**Generic name `data`:** `api/api.py:464` — local variable named `data` (a dict built for the WS call) then immediately shadowed on the next assignment `data = {k: v ...}` in `call_service` at line 519. Both `payload` (line 511) and `data` (line 519) exist in scope at the same time with related but distinct content, which is confusing.

**Generic name `val`:** Used as the intermediate for WebSocket responses across the entire api/api.py helper section (lines 985, 1000, 1043, 1057, etc.). Consistent within the file but `val` is a generic filler name where `raw` or `response_data` would signal intent.

**`web/utils.py:58`** — `live_by_db_id` — good name. But local `js` (line 61) for a `JobSummary` is a single-letter-ish abbreviation while the outer parameter is named `db_jobs`. Inconsistent verbosity within the same function.

---

## 7. Structural Messiness

**`web/routes/telemetry.py:115–175`** — `app_health` is 61 lines long (exceeds 50-line limit). It fetches data, computes totals twice (lines 145 and 160 recompute `total_invocations`), derives success rate, recomputes handler and job averages, collects timestamps, and builds the response. This is at least three distinct operations.

**`web/routes/telemetry.py:303–384`** — `dashboard_app_grid` is 82 lines long (exceeds 50-line limit). It handles DB fetch, optional bucket fetch, optional error fetch, builds an `empty` sentinel, iterates manifests, and constructs response objects. Multiple responsibilities.

**`web/routes/apps.py:108–130`** — `get_app_config` contains `except Exception: LOGGER.warning(...)` at line 121 — bare `Exception` catch swallows everything including `KeyboardInterrupt` subclasses. Should catch a narrower type.

**`web/routes/apps.py:133–174`** — `get_app_source` is 42 lines. The path-traversal check (lines 142–156) plus two nested `try/except` blocks (lines 161–167) increase nesting to 3–4 levels. Extractable into a helper.

**`web/routes/apps.py:158–164`** — `else` after implicit return via `raise HTTPException`. The `if not resolved.exists(): raise` at line 158 is followed by a `try` block. No `else` keyword, but structurally the happy path runs after the guard — that part is fine. However the `FileNotFoundError` on line 163 can never be raised in practice since `resolved.exists()` was just checked at line 158 — this is dead exception handling.

**`web/routes/telemetry.py:97–102`** — `_health_status_from_summary` multiplies `((total - failures) / total) * 100` inline without naming the intermediate `success_rate`. Lines 155–157 in `app_health` do the same calculation with a named variable. Same pattern, inconsistent treatment.

**`api/api.py:448–468`** — `fire_event` has an odd double-assignment: `event_data = event_data or {}` on line 462, then `data = {..., "event_data": event_data}` on line 464, then immediately `if not event_data: data.pop("event_data")` on line 465–466. The `or {}` on line 462 guarantees `event_data` is always falsy-safe, but then line 465 pops the key when it's empty. The `or {}` assignment is therefore pointless — if `event_data` was `None`, it becomes `{}`, which is falsy, which causes the pop. Just `event_data = event_data or None` and skip the pop, or keep the original and remove the `or {}`.

**`api/api.py:510–519`** — Two dict comprehensions filtering `None` values (lines 518–519) run back-to-back on `payload` and `data`. The `payload` variable is built on lines 511–517 then immediately reconstructed. This is the mutate-then-reassign pattern.

**`web/routes/telemetry.py:339–351`** — `empty = AppHealthSummary(...)` is constructed inside the route handler as a fallback sentinel. This should be a module-level constant — it's an immutable default value, not handler state.

---

## 8. Import Hygiene

**`web/routes/logs.py:1–15`** — Import `import time` at line 4 is stdlib. Import `from hassette.core import telemetry_repository as _repo` at line 9 is a local import aliased with a leading underscore. Using a leading-underscore alias on a module import (`_repo`) is unusual and applies underscore-prefix convention to an import rather than a definition — the alias name implies "private implementation detail" but imports can't be private. The alias should be `repo` or the module should be imported without an alias.

**`web/routes/logs.py:3`** — `import time` is stdlib but `from logging import getLogger` and `import logging` are both present (lines 3 and 18 after the TYPE_CHECKING block). Wait — line 3 imports `import logging` and line 19 uses `LOGGER = logging.getLogger(__name__)` while elsewhere in the web layer the pattern is `from logging import getLogger` (e.g., `apps.py:4`, `scheduler.py:6`, `services.py:4`). **`logs.py` uses `import logging` / `logging.getLogger` while every other web route uses `from logging import getLogger`.** Inconsistent logging import style across the route files.

**`api/api.py:159`** — `import typing` is followed immediately by `from typing import Any, Literal, overload` at line 163. Using both `import typing` (for `typing.TYPE_CHECKING` and `typing.Literal[False]` on line 488) and `from typing import ...` in the same file is a mixed style. `Literal` is imported explicitly but `typing.Literal` is also used directly at line 488 — one `Literal` via bare name, one via `typing.Literal`.

**`web/routes/telemetry.py:8`** — `import time` is used only at lines 212 and 325 inside route handlers. Fine placement, just noting it is used twice.

**`api/api.py:206–210`** — `TYPE_CHECKING` block imports `HassStateDict` from `hassette.events`, but in `api/sync.py:51` the same type is imported from the more specific `hassette.events.hass.raw`. Inconsistent import path for the same type across closely related files in the same package.

---

## 9. Hard-Coded Environment Values

**`web/app.py:49`** — `title="Hassette Web API"` — application title is a string literal in source code. Minor, but not sourced from config.

No hardcoded hostnames, API keys, credentials, or machine-specific paths found.

---

## 10. Formatting Inconsistencies

**`api/sync.py` (throughout)** — Docstring closing triple-quotes are on the same line as the last sentence (e.g., line 109: `Returns:\n            The response from the API."""`), while `api/api.py` consistently places the closing `"""` on its own line. Every single method in `sync.py` uses the closing-quote-on-last-line style, which conflicts with the style used in `api.py` (the file it mirrors). Since `sync.py` is auto-generated, this may be intentional, but it is visually inconsistent with the rest of the codebase.

**`web/routes/telemetry.py:119, 182, 204, 228`** — `app_key` uses `str = Path(...)` (bare type, no `Annotated`) while `instance_index` at line 120 uses `int = 0` (bare type). Within the same route file, `bus.py` uses `Annotated[int, Query()]` for `instance_index`. Mixed annotation styles for the same parameter types across sibling route files.

**`web/routes/telemetry.py:121, 183, 205`** — `since: float | None = Query(default=None)` carries a `# pyright: ignore[reportCallInDefaultInitializer]` suppression comment. The same suppression appears in `bus.py:22`, `scheduler.py:26`. These are consistent within the pattern, but the need to suppress Pyright on `Query()` calls in default initializers vs the `Annotated` form used elsewhere suggests a convention that has not been applied uniformly.

**`web/routes/health.py:19`** — `if status_data.status != "ok":` uses a bare string `"ok"` while `web/telemetry_helpers.py:104` uses `if m.status == "failed"` — both are comparing against status string literals with no shared constants. The status values `"ok"`, `"failed"`, `"running"`, etc. appear as bare strings throughout the web layer.

**`api/api.py:214–217`** — Section divider comment block (`# ------... Module-level helpers...------`) violates the project's "No Section Divider Comments" rule. A second divider appears at lines 969–975, and a third at lines 1433–1441.

---

## Summary

| Category | Findings |
|---|---|
| Magic Numbers and Strings | 11 |
| Scattered Constants | 6 |
| Ternary Abuse | 2 |
| CSS and Styling Sins | skipped |
| Dead Code | 5 |
| Naming Inconsistencies | 12 |
| Structural Messiness | 8 |
| Import Hygiene | 4 |
| Hard-Coded Environment Values | 1 |
| Formatting Inconsistencies | 5 |
| **Total** | **54** |

Highest-impact cleanup: the `app_health` and `dashboard_app_grid` route handlers in `telemetry.py` both exceed the 50-line limit, duplicate computation (`total_invocations` computed twice in `app_health`), and duplicate the `compute_health_metrics` helper that already exists in `telemetry_helpers.py` — consolidating these would eliminate 3 findings in one pass.
