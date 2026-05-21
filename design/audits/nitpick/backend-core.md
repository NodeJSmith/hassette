# Nitpick: `src/hassette/core/`

Scope: 27 files in `src/hassette/core/`. Mandate: style, organization, and hygiene only — no correctness or security review.

---

## 1. Magic Numbers / Magic Strings

| File | Line | Value | Context |
|------|------|-------|---------|
| `api_resource.py` | 89 | `0.25` | Sleep delay when SSL verify is enabled — unnamed float |
| `api_resource.py` | 127 | `5` | `stop_after_attempt(5)` — unnamed retry count |
| `api_resource.py` | 163 | `404` | `if e.status == 404` — inline HTTP status code |
| `app_lifecycle_service.py` | 157 | `5` | `get_short_traceback(5)` — unnamed depth |
| `bus_service.py` | (implicit) | named | Uses `_DISPATCH_STABILITY_SLEEP`, `_DISPATCH_IDLE_DEFAULT_TIMEOUT`, etc. — well done |
| `command_executor.py` | (docstring) | `"100"` | Docstring at `_drain_and_persist` hardcodes `"100"` while the code uses `_BATCH_DRAIN_CAP` |
| `database_service.py` | 146, 477 | `5000` | `"PRAGMA busy_timeout = 5000"` — appears in two places without a named constant |
| `database_service.py` | 244 | `5.0` | `thread.join, 5.0` — unnamed thread join timeout |
| `database_service.py` | 333 | `100` | `qsize % 100 == 0` — unnamed log-every-N-items interval |
| `database_service.py` | 363 | `3` | `len(head) < 3` — unnamed minimum header length |
| `database_service.py` | 534 | `86400` | Seconds-per-day as bare literal |
| `registration_tracker.py` | 66 | `1.0` | `asyncio.wait(still_pending, timeout=1.0)` — unnamed cancel-wait timeout |
| `runtime_query_service.py` | 354 | `50` | `limit: int = 50` default in `get_recent_events` |
| `runtime_query_service.py` | 450 | `256` | `asyncio.Queue(maxsize=256)` — unnamed WS client queue capacity |
| `runtime_query_service.py` | 478 | `10.0` | WS drop rate-limit interval — unnamed float |
| `scheduler_service.py` | 431 | `1` | `add(seconds=1)` — unnamed 1-second advancement after jitter |
| `service_watcher.py` | 506 | `30.0` | Fallback startup timeout when `spec` is `None` |
| `session_manager.py` | 155, 164, 232, 247 | `'unknown'`, `'running'`, `'success'`, `'failure'` | Session status strings repeated as inline literals throughout SQL and Python logic |
| `state_proxy.py` | 126, 172, 203 | `5` | `stop_after_attempt(5)` — same unnamed retry count as `api_resource.py` |
| `telemetry_query_service.py` | 629 | `12` | `num_buckets: int = 12` — unnamed default bucket count |
| `telemetry_query_service.py` | 761, 787 | `3600.0` | `time.time() - 3600.0` — duplicated in two separate methods; inconsistent with `_RETENTION_INTERVAL_SECONDS = 3600` in `database_service.py` |
| `web_api_service.py` | 68 | `3` | `timeout_graceful_shutdown=3` — unnamed shutdown timeout |

**Notable pattern**: `stop_after_attempt(5)` appears independently in both `api_resource.py` and `state_proxy.py` with no shared constant. If the retry budget ever changes, both must be found and updated.

---

## 2. Scattered / Misplaced Constants

### `command_executor.py` — class-level vs module-level inconsistency

Three constants are defined as class-level attributes on `CommandExecutor` while other constants for the same class live at module level:

```
Module level (correct): _MAX_RETRY_COUNT, _CAPACITY_WARN_THRESHOLD, _CAPACITY_WARN_RATE_LIMIT_SECS
Class level (inconsistent): _TIMEOUT_WARN_SUPPRESS_SECS, _TIMEOUT_WARN_CACHE_MAX, _BATCH_DRAIN_CAP
```

All six are behavioral tuning parameters with no per-instance variation. They should all be at module level together.

### `telemetry_repository.py` — constants after the class definition

`_LOG_COLUMNS` (line 698) and `_LOG_INSERT_SQL` (line 715) are module-level constants defined *after* the class body. Python's constant convention (and this project's own `coding-style.md`) places module-level constants at the top of the file, after imports.

### `telemetry_query_service.py` — `3600.0` duplicated

`time.time() - 3600.0` appears at lines 761 and 787 in two separate methods (`get_recent_errors` and `get_slow_handlers`). A `_ONE_HOUR_SECONDS` constant exists conceptually in `database_service.py` as `_RETENTION_INTERVAL_SECONDS = 3600` but is not shared. Both files should reference a single named constant.

### `session_manager.py` — SQL status literals with no constants

`'unknown'`, `'running'`, `'success'`, `'failure'` appear repeatedly in both SQL strings and Python conditionals. A small `_STATUS_*` constant group or a `SessionStatus` enum would eliminate all repetition.

---

## 3. Ternary Abuse

No egregious ternary chains found. The one slightly compound ternary:

```python
# api_resource.py:89
asyncio.sleep(0.25 if self.hassette.config.verify_ssl else 0)
```

is acceptable in isolation. No category findings here beyond the magic float noted above.

---

## 4. Dead Code

### Unused `LOGGER` definitions

Five files define `LOGGER = getLogger(__name__)` at module level but never reference it — every log call in those files goes through `self.logger` instead:

| File | Line |
|------|------|
| `api_resource.py` | 37 |
| `app_factory.py` | 21 |
| `app_handler.py` | 28 |
| `app_lifecycle_service.py` | 36 |
| `state_proxy.py` | 26 |

All five can be deleted.

### Unused `TypeVar` in `core.py`

```python
# core.py:52
T = TypeVar("T", bound=Resource | Service)
```

`T` is defined but never used anywhere in the file. Dead code.

---

## 5. Naming Inconsistencies

### `command_executor.py` — misleading `entity_id` variable

```python
# command_executor.py:~299
entity_id = cmd.listener.listener_id
```

`entity_id` strongly implies a Home Assistant entity ID (e.g., `"light.kitchen"`). This is an in-memory integer listener ID. The misleading name makes every subsequent use of the variable ambiguous. `listener_id` or `key` would be accurate.

### `telemetry_query_service.py` — abbreviated aliases `lr`, `la`, `jr`, `ja`

In `_build_app_summaries` (lines 91-94), SQL result columns are assigned to two-letter abbreviations:

```python
lr = ...  # listener rows
la = ...  # listener aggregates (?)
jr = ...  # job rows
ja = ...  # job aggregates (?)
```

The expansions are unclear without reading deep into the query. Short names inside a 10-line block are fine; these span a 108-line method and get referenced throughout. `listener_rows`, `listener_agg`, `job_rows`, `job_agg` (or similar) would read clearly.

### `bus_service.py` — `chosen` dict

```python
# bus_service.py:~555
chosen: dict[int, tuple[str, Listener]] = {}
```

`chosen` is generic. The dictionary holds the selected listeners for the current dispatch cycle; `selected_listeners` or `dispatch_targets` would convey purpose.

### `runtime_query_service.py` — `.value` comparison

```python
# runtime_query_service.py:~386
status == ResourceStatus.RUNNING.value
```

The comparison is against the string value of the enum rather than the enum itself. Elsewhere in the codebase comparisons use `ResourceStatus.RUNNING` directly. This is inconsistent and bypasses type checking on the enum member.

---

## 6. Structural Messiness

### Files exceeding 800-line limit

| File | Lines |
|------|-------|
| `command_executor.py` | 976 |
| `bus_service.py` | 947 |
| `telemetry_query_service.py` | 903 |
| `telemetry_repository.py` | 838 |

All four exceed the project's stated 800-line maximum.

### Methods exceeding 50-line limit

| File | Method | Approx. lines |
|------|--------|---------------|
| `command_executor.py` | `_persist_batch` | ~143 |
| `command_executor.py` | `_drain_and_persist` | ~52 |
| `bus_service.py` | `_immediate_fire_task` | ~74 |
| `bus_service.py` | `await_dispatch_idle` | ~52 |
| `database_service.py` | `_check_size_failsafe` | ~110 |
| `database_service.py` | `_do_run_retention_cleanup` | ~68 |
| `core.py` | `run_forever` | ~87 |
| `core.py` | `wire_services` | ~75 |
| `service_watcher.py` | `restart_service` | ~117 |
| `telemetry_query_service.py` | `get_all_app_summaries` | ~108 |
| `telemetry_query_service.py` | `get_app_recent_activity` | ~93 |

---

## 7. Import Hygiene

### `import typing` used only for `TYPE_CHECKING`

Several files do `import typing` and then use only `typing.TYPE_CHECKING`. The preferred form is `from typing import TYPE_CHECKING`:

| File | Line |
|------|------|
| `app_handler.py` | ~5 |
| `bus_service.py` | ~7 |
| `core.py` | ~9 |

Additionally, `api_resource.py` imports both `import logging` (for `logging.WARNING`) and `from logging import getLogger`. The `getLogger` import is consistent with the rest of the codebase; `import logging` is used only for the `logging.WARNING` constant in the retry decorator. This can be replaced with `from logging import WARNING, getLogger` or just `from logging import getLogger` with `WARNING` referenced as the integer `30` — but the cleaner option is `from logging import WARNING, getLogger`.

---

## 8. Hard-Coded Environment Values

No hard-coded hostnames, tokens, or environment-specific values found in the 27 files. Host and port configuration flows through `hassette.config.*` uniformly. No findings.

---

## 9. Formatting Inconsistencies

### `_LOG_COLUMNS` / `_LOG_INSERT_SQL` after class body in `telemetry_repository.py`

These two module-level constants are placed after the `TelemetryRepository` class definition (lines 698-715) rather than at the top of the file with other constants. This is the only formatting deviation of note across the 27 files.

---

## 10. Summary Table

| Category | Finding count | Severity |
|----------|--------------|---------|
| Magic numbers/strings | 22 | Low–Medium |
| Scattered/misplaced constants | 4 clusters | Low |
| Ternary abuse | 0 | — |
| Dead code | 6 (5 × LOGGER, 1 × TypeVar) | Low |
| Naming inconsistencies | 4 | Low–Medium |
| Structural messiness | 4 files over limit, 11 methods over limit | Medium |
| Import hygiene | 4 files | Low |
| Hard-coded environment values | 0 | — |
| Formatting inconsistencies | 1 | Low |

**Total actionable findings: ~51 across 9 of 10 checklist categories.**

### Highest-leverage fixes

1. **Delete 5 unused `LOGGER` definitions** — trivial, zero-risk, immediately cleaner.
2. **Name the `stop_after_attempt(5)` retry count** — one shared constant shared by `api_resource.py` and `state_proxy.py`; prevents drift.
3. **Fix `entity_id = cmd.listener.listener_id`** — most semantically misleading name in the codebase.
4. **Move `_LOG_COLUMNS` / `_LOG_INSERT_SQL` to the top of `telemetry_repository.py`** — mechanical, no risk.
5. **Promote `_TIMEOUT_WARN_SUPPRESS_SECS`, `_TIMEOUT_WARN_CACHE_MAX`, `_BATCH_DRAIN_CAP` to module level** in `command_executor.py` to match the other constants.
6. **Extract `3600.0` into a shared constant** shared by `telemetry_query_service.py` and `database_service.py`.
7. **Name the `session_manager.py` status strings** — a `SessionStatus` enum or `_STATUS_*` constants would eliminate 8+ literal repetitions.
