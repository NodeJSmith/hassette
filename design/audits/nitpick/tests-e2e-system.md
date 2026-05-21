# Nitpick Report: tests/e2e/ and tests/system/

Scope: all `.py` files in `tests/e2e/` and `tests/system/`.

---

## 1. Magic Numbers and Strings

### Repeated timeout literals without constants

`wait_for_timeout(300)` appears 21 times and `wait_for_timeout(500)` appears 15 times across multiple files. Neither value is defined as a named constant anywhere.

- **`test_apps_list.py:34,44,50,70,86`** — `page.wait_for_timeout(300)` repeated 5 times in a single file
- **`test_url_routing.py:126,153,200,285,499,510,524,529`** — `page.wait_for_timeout(300)` repeated 8 times; `wait_for_timeout(500)` repeated 8 times at lines 205, 229, 234, 249, 253, 257, 345, 479
- **`test_navigation.py:208,220,234,250,255`** — `wait_for_timeout(300)` repeated 5 times
- **`test_app_detail.py:97`** — `wait_for_timeout(300)` alongside `wait_for_timeout(500)` at lines 191, 205, 244
- **`test_logs.py:95,181,194,208`** — `wait_for_timeout(500)` 4 times
- **`test_cmd_k.py:143`** — `wait_for_timeout(300)` once

`300` and `500` should be module-level constants (e.g. `FILTER_SETTLE_MS = 300`, `ANIMATION_SETTLE_MS = 500`) in `conftest.py` or a shared constants module.

### Repeated Playwright `timeout=5000` without a constant

Appears 37 times across `test_url_routing.py`, `test_app_detail.py`, `test_responsive.py`, `test_websocket.py`, `test_logs.py`, `test_cmd_k.py`. Zero instances are named constants.

- **`test_url_routing.py:38,49,59,75,83,92,96,363,392,402,410,416,438`** (representative) — `timeout=5000`
- **`test_websocket.py:80,102,106,126,127`** — mixes `timeout=5000` and `timeout=10000`

`5000` should be `EXPECT_TIMEOUT_MS = 5000`; `10000` should be `WS_CONNECT_TIMEOUT_MS = 10000`.

### Hardcoded viewport dict repeated inline

`{"width": 375, "height": 812}` (MOBILE_VIEWPORT) is defined in `conftest.py:46` but used again as a raw literal:

- **`test_logs.py:275`** — `page.set_viewport_size({"width": 375, "height": 812})` — ignores the constant already exported from `conftest.py`

`{"width": 800, "height": 600}` appears in 3 places with no constant:

- **`test_logs.py:178,191`** — `page.set_viewport_size({"width": 800, "height": 600})`
- **`test_responsive.py:186`** — `page.set_viewport_size({"width": 800, "height": 600})`

`{"width": 2400, "height": 600}` appears once:

- **`test_logs.py:207`** — `page.set_viewport_size({"width": 2400, "height": 600})`

All three ad-hoc sizes should be named constants alongside `MOBILE_VIEWPORT` and `DESKTOP_VIEWPORT` in `conftest.py`.

### `"2024-01-01T00:00:00"` repeated 11 times in seed data

- **`conftest.py:59,60,65,66,71,72,77,78,84,85,89,90`** — every entity's `last_changed` / `last_updated` is the same literal timestamp. This should be a single constant (e.g. `_SEED_TIMESTAMP = "2024-01-01T00:00:00"`).

---

## 2. Scattered Constants

### `_ENTITY` and `_DOMAIN` defined identically in 5 separate system test files

`_ENTITY = "light.kitchen_lights"` and `_DOMAIN = "light"` are copy-pasted verbatim into:

- **`test_api.py:15-16`**
- **`test_app_lifecycle.py:16-17`**
- **`test_bus.py:14-15`**
- **`test_reconnection.py:14`** (`_ENTITY` only — `_DOMAIN` absent but used inline at line 17 as `"light"`)
- **`test_state_proxy.py:11-12`**
- **`test_web_api.py:18-19`**

These should be defined once in `conftest.py` (or a `tests/system/constants.py`) and imported. If they are intentionally per-file to avoid cross-file coupling, the duplication across 6 files at minimum warrants a comment explaining why.

### `"light.kitchen_lights"` also appears hard-coded inline in fixture apps

- **`apps/bus_handler_app.py:15`** — `self.bus.on_state_change("light.kitchen_lights", ...)` — not using `_ENTITY` from the test module because it's a fixture app. Acceptable, but the string is the same fixture entity used everywhere.

---

## 3. Ternary Abuse

**(3. Ternary Abuse): clean**

---

## 4. CSS

*(Skipped per scope.)*

---

## 5. Dead Code

### Empty section header block in `test_logs.py`

- **`test_logs.py:240-243`** — A `# App filter` section header with no tests beneath it. The section immediately gives way to the `# Error toast (#556)` section. Then a second `# App filter` header appears at line 268. The first one (lines 240-243) is a leftover placeholder with zero content — it should be removed.

### `PAGES` constant defined but never used

- **`test_navigation.py:13-17`** — `PAGES` is a list of 3-tuples defined at module level. It is never iterated, parametrized, or referenced elsewhere in the file. `SIDEBAR_LINKS` (line 42) and `SIDEBAR_ACTIVE` (line 72) serve similar purposes and are actually used. `PAGES` is dead code.

### Duplicate tests — `test_hot_reload.py` vs `test_navigation.py`

Two tests in `test_hot_reload.py` are exact (or near-exact) duplicates of tests in `test_navigation.py`:

- **`test_hot_reload.py:28`** `test_spa_navigates_without_full_reload` — identical to **`test_navigation.py:278`** with the same name. The `test_navigation.py` version is a strict superset (adds a nav-apps click and second marker check). The `test_hot_reload.py` version does nothing the navigation version does not.
- **`test_hot_reload.py:50`** `test_spa_handles_direct_deep_link` — near-identical to **`test_navigation.py:290`** with the same name. The navigation version adds one extra assertion (`[data-testid='overview-tab']`). The hot_reload version is a strict subset.

Having both means pytest collects the same test name from two modules, which will silently run it twice. The `test_hot_reload.py` versions should be removed.

---

## 6. Naming Inconsistencies

### Underscore-prefixed module-level helpers in test files (project rule: no underscores)

These are plain helper functions, not pytest fixtures and not framework-required names:

- **`test_apps_list.py:11`** — `def _open_status_filter(page)` — called by 3 tests; should be `open_status_filter`
- **`test_cmd_k.py:11`** — `def _open_palette(page)` — called by 8 tests; should be `open_palette`
- **`test_logs.py:46`** — `def _wait_for_log_entries(page)` — called by 10 tests; should be `wait_for_log_entries`
- **`test_theme.py:13`** — `def _clear_theme_pref(page)` — called by 6 tests; should be `clear_theme_pref`

### Underscore-prefixed pytest fixtures in `conftest.py`

Pytest fixtures use the function name as their identifier in test signatures — there is no "private" meaning here. The underscore-prefix convention is misleading:

- **`conftest.py:130`** — `def _log_handler()` — session fixture, referenced by name `_log_handler` in `_fastapi_app`'s signature; the leading underscore signals nothing useful and the name appears in a test function signature
- **`conftest.py:172`** — `def _ensure_spa_built()` — session fixture, listed in `_fastapi_app`'s args
- **`conftest.py:227`** — `def _fastapi_app(...)` — session fixture, used as a dependency of `live_server` and `live_server_ws`
- **`conftest.py:291`** — `def _set_time_preset_to_1h(...)` — autouse fixture; the leading underscore is particularly odd here since it's globally active

### Underscore-prefixed module-level helpers in `conftest.py`

- **`conftest.py:245`** — `def _get_free_port()` — private helper by project convention: should be `get_free_port`
- **`conftest.py:187`** — `def _make_log_records_from_buffer(...)` — should be `make_log_records_from_buffer`

### Underscore-prefixed module-level functions in `system/conftest.py`

- **`system/conftest.py:116`** — `def _session_ready(hassette)` — called by `startup_context`; should be `session_ready`
- **`system/conftest.py:334`** — `def _ws_probe(ws_url, hold_seconds)` — called by `wait_for_ha_ready`; should be `ws_probe`

### Underscore-prefixed helpers in `test_app_lifecycle.py`

- **`test_app_lifecycle.py:20`** — `def _enable_autodetect(config, app_dir)` — module-level function called directly in tests; should be `enable_autodetect`
- **`test_app_lifecycle.py:28`** — `def _find_app(hassette, class_name)` — called in every lifecycle test; should be `find_app`

### Underscore-prefixed class in `system/conftest.py`

- **`system/conftest.py:38`** — `class _SystemTestConfig(HassetteConfig)` — used directly in `make_system_config` and `make_web_system_config`; the leading underscore is arbitrary. Should be `SystemTestConfig`.

### Underscore-prefixed instance attribute in fixture app

- **`apps/config_app.py:20`** — `self._greeting = self.app_config.greeting` — stores to an underscore-prefixed attribute with no reason; it is not unsafe to read, not a framework hook, not a published API. Should be `self.greeting`.

### Underscore-prefixed inner capture closures in `test_bus.py` (10 occurrences)

All inner closures in `test_bus.py` are named `_capture` or `_capture_a` / `_capture_b`:

- **`test_bus.py:37,79,110,150,182,214,255,258,284,316`** — `async def _capture(...)` or variants

These are local function names inside `async with` blocks, so the underscore has no access-control meaning. Should be `capture` / `capture_a` / `capture_b`.

Similarly in `test_scheduler.py`:

- **`test_scheduler.py:22,36,50,67,85,107,133`** — `async def _callback()` — all local closures inside tests; should be `callback`

And in `test_scheduler.py:115` — `async def _row_exists()` — should be `row_exists`.

---

## 7. Structural Messiness

### Repeated state-proxy readiness wait_for in `test_state_proxy.py`

The same lambda appears in 4 out of 5 tests in the file:

- **`test_state_proxy.py:21,35,49,64`** — `lambda: state_proxy.is_ready() and len(state_proxy.states) > 0`

This is also repeated in:

- **`test_reconnection.py:134`** — same lambda, same `timeout=15.0`, same `desc`

The pattern should be a shared helper `wait_for_state_proxy_ready(state_proxy)` in `conftest.py`.

### `test_config.py` — 7 near-identical tests that each navigate to `/config` and check `page.locator("body")`

- **`test_config.py:9,15,21,30,39,49,57,65,73`** — every test calls `page.goto(base_url + "/config")` and then calls `expect(body).to_contain_text(...)` or `expect(page).to_...`. Seven of the eight tests could be collapsed into a single parametrized test or a single test with multiple expects. The current shape — one `page.goto` per assertion — inflates test count without adding isolation value.

### `test_app_detail.py` — `test_config_tab_renders` and `test_config_tab_shows_filename` are redundant splits

- **`test_app_detail.py:215`** `test_config_tab_renders` — navigates to `/apps/my_app`, clicks Config tab, asserts `config-values-table` is visible
- **`test_app_detail.py:225`** `test_config_tab_shows_filename` — navigates to `/apps/my_app` again, clicks Config tab again, asserts `my_app.py` is in content

These two tests exercise the same page state (config tab on `my_app`). They should be one test.

### Repeated `page.wait_for_load_state("networkidle")` + navigation pattern — no shared helper

`page.goto(...) + page.wait_for_load_state("networkidle")` appears as a two-line block throughout `test_url_routing.py`, `test_navigation.py`, and `test_app_detail.py`. No helper or fixture wraps this. Count in `test_url_routing.py` alone: 30+ occurrences.

### `test_app_lifecycle.py:182` — `test_multiple_apps_isolation` is 53 lines

Includes inline app source code strings, two app definitions, and a 15-second wait. Borderline but worth noting — the inline app code and setup could be extracted to `apps/isolation_app_*.py` fixture files (same pattern as `bus_handler_app.py`) to reduce the test body length.

---

## 8. Import Hygiene

### `import re` unused in `test_apps_list.py`

- **`test_apps_list.py:3`** — `import re` is present; `re.compile(...)` is used once at line 58. Usage confirmed — not unused, but worth noting the file's single use of `re` is for a simple string pattern that could use a plain string equality check instead (`expect(page).to_have_url(re.compile(r"/apps/my_app"))`). Not a hard violation but unusual.

### Imports inside inline app code strings in `test_app_lifecycle.py`

- **`test_app_lifecycle.py:53,101,134,160,188,189,201`** — `from hassette import App` and related imports appear inside multi-line strings written to temporary `.py` files. These are intentional (the string is the app source), not lazy imports in the test module itself. Style is consistent within the pattern.

### `datetime` import in `test_api.py` uses stdlib `datetime`, violating project rule

- **`test_api.py:3`** — `from datetime import UTC, datetime, timedelta` — the project rule (`python.md`) requires `whenever` for all date/time operations. The only usage is at line 94: `(datetime.now(tz=UTC) - timedelta(seconds=120)).isoformat()`. This should be `Instant.now().subtract(seconds=120).format_rfc3339()` or equivalent `whenever` API.

---

## 9. Hard-Coded Environment Values

### `HA_URL` hard-coded in `system/conftest.py`

- **`system/conftest.py:31`** — `HA_URL = "http://localhost:18123"` — this is a constant, not a magic string buried in a function. Acceptable as-is, but the port `18123` is repeated in `docker-compose.yml:8` (`"18123:8123"`). If the port ever changes, there are two places to update. Consider deriving `HA_URL` from the docker-compose port mapping or an env var.

### `"127.0.0.1"` repeated as a literal in `conftest.py`

- **`conftest.py:248`** — `s.bind(("127.0.0.1", 0))` in `_get_free_port`
- **`conftest.py:269,376`** — `socket.create_connection(("127.0.0.1", port), ...)` in both `live_server` and `live_server_ws`
- **`conftest.py:276,383`** — `yield f"http://127.0.0.1:{port}"` in both fixtures

Four separate occurrences of `"127.0.0.1"` with no constant. Should be `_SERVER_HOST = "127.0.0.1"`.

### `base_url="http://localhost:8126"` in mock config

- **`mock_fixtures.py:785`** — `base_url="http://localhost:8126"` hard-coded in `wire_config`. The port 8126 is also used elsewhere in the project as the default web API port. No constant wraps it here.

---

## 10. Formatting Inconsistencies

### Inconsistent section header dividers in `test_logs.py`

- **`test_logs.py:240-243`** — A `# App filter` section header block appears between the truncation tests and the error toast section, with no tests under it. A second `# App filter` section header then appears at line 268 with actual tests under it. The empty one is not just dead code — it also makes the file structure misleading to read. Two section headers with the same name in one file is a formatting error.

### Inconsistent docstring style on `test_navigation.py:27,32`

- **`test_navigation.py:27`** — `def test_logs_page_loads` has no docstring
- **`test_navigation.py:32`** — `def test_config_page_loads` has no docstring

These are the only two test functions in the entire file without docstrings. Every other test function in the file has one.

### Inner closure naming inconsistency within `test_web_api.py`

- **`test_web_api.py:117`** — `def _capture(request)` is named with an underscore (inner function, as noted above), but the capture list it appends to is named `api_requests` (line 115) without an underscore. The outer list and inner closure follow different naming conventions within the same test.

---

## Summary

| Category | Count | Files Affected |
|---|---|---|
| Magic Numbers/Strings | 21× `300ms`, 15× `500ms`, 37× `5000ms`, 4× `10000ms`, inline viewport dicts, 11× timestamp literal | `test_apps_list`, `test_url_routing`, `test_navigation`, `test_app_detail`, `test_logs`, `test_cmd_k`, `test_responsive`, `test_websocket`, `conftest` |
| Scattered Constants | `_ENTITY`/`_DOMAIN` in 5 system files, `"127.0.0.1"` in 4 conftest locations | All system test files, `conftest.py` |
| Dead Code | Empty `# App filter` section, unused `PAGES` constant, 2 duplicate tests in `test_hot_reload.py` | `test_logs`, `test_navigation`, `test_hot_reload` |
| Naming (underscore prefixes) | 4 module helpers in e2e, 4 fixtures in conftest, 2 system conftest helpers, 1 class, 1 app attribute, 10 inner closures in `test_bus`, 8 inner closures in `test_scheduler` | Pervasive |
| Structural Messiness | Repeated 4× wait_for lambda, 7 near-identical config tests, redundant config tab split, 53-line isolation test | `test_state_proxy`, `test_config`, `test_app_detail`, `test_app_lifecycle` |
| Import Hygiene | stdlib `datetime` in `test_api.py` (project rule violation) | `test_api` |
| Hard-Coded Env Values | `"127.0.0.1"` × 4, HA port × 2, `http://localhost:8126` | `conftest.py`, `mock_fixtures.py`, `system/conftest.py` |
| Formatting | Empty section header, 2 missing docstrings, inconsistent inner naming | `test_logs`, `test_navigation`, `test_web_api` |

**Highest-impact cleanup:** rename all underscore-prefixed module-level helpers and fixtures (pervasive across both test suites, ~30 violations), extract `_ENTITY`/`_DOMAIN` to `system/conftest.py`, and delete the two duplicate tests in `test_hot_reload.py`.
