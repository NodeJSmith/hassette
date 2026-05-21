# Nitpick Validation — Backend Reports

**Reports validated:** backend-core, backend-test-utils-models, backend-event-system, backend-api-web, backend-scheduler-resources, backend-support
**Date:** 2026-05-21

---

## Methodology

Each finding category was spot-checked against the actual code. Categories most prone to false positives (magic numbers, scattered constants, dead code, naming) received line-by-line verification. Structural and formatting findings were accepted if the file/method line counts and patterns matched; a sample was verified for each.

---

## Report 1: `backend-core.md`

### Confirmed findings

- **Magic numbers/strings:** All confirmed. The two `stop_after_attempt(5)` in `api_resource.py` and `state_proxy.py` are real (neither is a named constant). The `3600.0` appearing at lines 761 and 787 of `telemetry_query_service.py` is real and inconsistent with `_RETENTION_INTERVAL_SECONDS = 3600` in `database_service.py`. The `session_manager.py` status strings (`'unknown'`, `'running'`, `'success'`, `'failure'`) are confirmed as repeated inline literals. All other magic number findings verified as stated.
- **Scattered/misplaced constants:** The three class-level constants in `command_executor.py` (`_TIMEOUT_WARN_SUPPRESS_SECS`, `_TIMEOUT_WARN_CACHE_MAX`, `_BATCH_DRAIN_CAP`) are confirmed at lines 107–113 while module-level constants live at lines 37–39. The `_LOG_COLUMNS` / `_LOG_INSERT_SQL` placement after the `TelemetryRepository` class body (line 698+) is confirmed.
- **Dead code — 5 unused LOGGER definitions:** Confirmed. All five files define `LOGGER = getLogger(__name__)` and have zero `LOGGER.` usages. Every log call goes through `self.logger`.
- **Dead code — unused TypeVar T:** Confirmed. `T = TypeVar("T", bound=Resource | Service)` at `core.py:51` is the only occurrence of `T` in the file.
- **Naming — `entity_id = cmd.listener.listener_id`:** Confirmed at `command_executor.py:299–302`. The variable is immediately used as a dict key (`self._timeout_warn_timestamps.get(entity_id)`) — clearly an integer listener ID, not an HA entity string.
- **Naming — `lr`, `la`, `jr`, `ja` abbreviations:** Not independently verified (method body length makes this plausible).
- **Naming — `chosen` dict in `bus_service.py`:** Confirmed at line 555 with the inline comment `# listener_id -> (matched_route, listener)`. The name `chosen` conveys nothing without reading the comment.
- **Naming — `status == ResourceStatus.RUNNING.value`:** Confirmed at `runtime_query_service.py:386`. The rest of the codebase compares against the enum directly.
- **Structural messiness:** Four files over 800 lines confirmed (`command_executor.py` 976, `bus_service.py` 947, `telemetry_query_service.py` 903, `telemetry_repository.py` 837). Oversized methods confirmed by report.
- **Import hygiene:** Confirmed. Three files use `import typing` for `TYPE_CHECKING` instead of `from typing import TYPE_CHECKING`.

### False positives

None identified in this report.

---

## Report 2: `backend-test-utils-models.md`

### Confirmed findings

- **Magic numbers/strings:** Mostly confirmed. `harness.py:746` "Bearer test_token" differs from `TEST_TOKEN = "test-token"` in `config.py` (different formatting — confirmed real divergence). `web_mocks.py` hardcoded integers (8126, 2000, 1000, 30, 20, 10) are confirmed as bare literals in stub configuration.
- **Dead code — `test_server.py`:** Commented-out type alias at line 11 and commented-out dict comprehension at line 118 are confirmed.
- **Dead code — `helpers.py` underscore prefix on cross-module functions:** `_create_component_loaded_event` and `_create_service_registered_event` are confirmed to be imported and used by `simulation.py`. The `_` prefix is misleading.
- **Dead code — section dividers in `app_harness.py` and `recording_api.py`:** Confirmed present.
- **Naming — `class TIMEOUTS`:** Confirmed at `harness.py:54`. `ALL_CAPS` for a class name is wrong.
- **Naming — `_CLASS_LOCKS` / `_CLASS_MANIFEST_STATE`:** Confirmed at `app_harness.py:60–65`. These are mutable `WeakKeyDictionary` instances, not constants. `SCREAMING_SNAKE_CASE` is incorrect.
- **Naming — `_HermeticHassetteConfigPair`:** Report actually says `_HermeticHassetteConfigPair` uses `PascalCase` with leading underscore for a module-level variable. Confirmed at `config.py:25`.
- **Structural messiness — `recording_api.py` 1,159 lines:** Confirmed.
- **Structural messiness — duplicated `_stub_execute` inner functions:** Confirmed per report (not independently verified, accepted as stated).
- **Import hygiene:** `fixtures.py` double `typing` import confirmed as a pattern.
- **Formatting — section divider comments:** Confirmed across `harness.py`, `app_harness.py`, `recording_api.py`.

### False positives

**`config.py:19` — `TEST_SOURCE_LOCATION` flagged as dead constant.**
FALSE POSITIVE. `TEST_SOURCE_LOCATION` is imported and used in at least five test files: `test_telemetry_models.py`, `test_telemetry_repository.py` (three times), `test_command_executor.py`, and `test_scheduler_error_handler.py`.

**`config.py:18` — `SECONDS_PER_DAY` flagged as orphaned constant.**
FALSE POSITIVE. `SECONDS_PER_DAY` is imported and used in `test_log_records_retention.py` and `test_telemetry_query_service_aggregates.py`. It is not orphaned.

**`web_mocks.py:78–79` — `"0.0.0.0"` and `8126` flagged as bare magic literals with no explanation of why they differ from loopback.**
PARTIALLY FALSE POSITIVE. These values exactly match the Pydantic field defaults in `config/models.py:259,262` (`host: str = Field(default="0.0.0.0")`, `port: int = Field(default=8126)`). The test stub is simply re-assigning the same default values. The real finding is that these assignments are redundant (they could be removed entirely), not that they are mysterious magic numbers. The report's framing ("no named constant") is misleading — these aren't magic numbers needing names, they're redundant assignments that should be deleted.

---

## Report 3: `backend-event-system.md`

### Confirmed findings

- **Magic strings — `event_type` inline literals in `events/hassette.py`:** Confirmed at lines 102, 114, 214, 237. These are bare strings passed as `event_type=` arguments.
- **Magic strings — `origin` defaults `"UNKNOWN"` and `"HASSETTE"` in `events/base.py`:** Confirmed as inline literals.
- **Magic strings — `source_tier="framework"` / `"app"` scattered across `listeners.py`, `invocation_record.py`, `bus.py`:** Confirmed. `bus.py:322` has `assert source_tier in ("app", "framework")` as a pure inline literal guard.
- **Scattered constants — `ARROW` / `ELLIPSIS_CHAR` in `conditions.py`:** Confirmed as display constants in a non-display module.
- **Dead code — commented-out line in `Comparison.__init__`:** Confirmed (`# self.threshold = threshold`).
- **Dead code — lazy import in `predicates.py:498`:** Confirmed. `from hassette.types import ChangeType` at line 498 inside `__post_init__` is redundant — `ChangeType` is already imported at module scope at line 55 AND in the `TYPE_CHECKING` block at line 76.
- **Dead code — audit tracking note in `listeners.py` docstring:** Confirmed. `Total: 10 fields (AC#2).` is a stale internal audit artifact in a production docstring.
- **Naming — underscore-prefixed methods in `bus/`:** Confirmed. `_extract_and_convert_parameter`, `_record_timing`, `_clear_debounce_ref`, `_debounced_call`, `_throttled_call` all have underscore prefixes without the required justification.
- **Naming — underscore-prefixed dataclass fields in `bus/listeners.py`:** Confirmed. `_async_handler`, `_injector`, `_app_error_handler_resolver` have `_` prefixes in a `@dataclass(slots=True)` with the only justification being "Private — not part of the public API" — which the project rules explicitly reject as insufficient.
- **Structural — `bus/bus.py` 1,122 lines:** Confirmed.
- **Structural — duplicated collision-detection block:** Confirmed. Lines 198–206 and 373–381 are identical logic.
- **Structural — double `validate_di_signature` call:** Confirmed. `injection.py:44` calls `validate_di_signature(signature)` explicitly, then `injection.py:45` calls `extract_from_signature(signature)`, which itself calls `validate_di_signature` internally at `extraction.py:87`.
- **Import hygiene — lazy import in `events/hass/hass.py`:** Confirmed. `from hassette.events import Event` inside the function body with a circular-import comment — violates no-lazy-imports rule.
- **Import hygiene — lazy import in `predicates.py:498`:** Confirmed (same as dead code finding above).
- **Import hygiene — `MISSING_VALUE` imported via three different paths:** Confirmed across `accessors.py`, `conditions.py`, `predicates.py`, `dependencies.py`.
- **Formatting — section dividers in `event_handling/`:** Confirmed.

### False positives

**`event_handling/dependencies.py:77` — `from hassette import RawStateChangeEvent  # noqa: F401` flagged as suspicious.**
PARTIALLY FALSE POSITIVE. The `noqa: F401` is inside a `TYPE_CHECKING` block, which is the correct pattern. However, the report's concern is valid in a different way: ruff/pyright do not flag unused imports inside `TYPE_CHECKING` blocks, so the `noqa` is indeed unnecessary noise. The import itself is not dead — it is used in the module's type annotations and docstrings (lines 9, 30, etc.). The finding should be: remove the `# noqa: F401` comment, not the import.

**`events/hassette.py` magic event_type strings — flagged as needing named constants.**
These warrant a nuance: the strings `"empty"`, `"file_changed"`, `"invocation_completed"`, `"execution_completed"` are not used in multiple places that need to match — they appear as the defining arguments when constructing event dataclasses. If the event class already encodes its type, these could be removed entirely rather than named. The finding is valid but the fix direction (named constants vs. computed class attribute) is worth considering. Confirmed as real.

**`backend-event-system.md` structural finding — `predicates.py` "Exceeds the 800-line soft ceiling".**
INACCURATE CHARACTERIZATION. The file is 638 lines, which is under the 800-line hard maximum. The project rule states 200–400 lines typical, 800 max — there is no "800-line soft ceiling." The finding that the file is oversized relative to the 400-line typical limit is real, but calling it "exceeds the 800-line soft ceiling" is wrong. The finding stands, the framing does not.

---

## Report 4: `backend-api-web.md`

### Confirmed findings

- **Magic numbers — `404` in `api/api.py`:** Confirmed at lines 640 and 669 (two methods with same inline literal).
- **Magic numbers — `num_buckets=12` inline vs `_NUM_SPARKLINE_BUCKETS = 12` at line 300:** Confirmed. The constant is defined at line 300 but not used at line 329 where `num_buckets=12` is passed directly.
- **Magic numbers — `86400` in `telemetry.py:212`:** Confirmed. `_SECONDS_PER_DAY = 86400` is defined in `logs.py:23` but a bare `86400` is used in `telemetry.py:212` without importing or reusing the constant.
- **Magic numbers — `_LOG_LEVELS` dict with bare int values 10/20/30/40/50 in `ws.py:16`:** Confirmed. stdlib `logging.DEBUG`, `logging.INFO`, etc. should be used.
- **Magic numbers — health classification thresholds in `telemetry_helpers.py`:** Confirmed as inline numbers in conditionals.
- **Dead code — `nonlocal raw_states` in `api.py:398–419`:** Confirmed. The inner `yield_states()` declares `nonlocal raw_states` but never reassigns `raw_states` — it only reads it. The `nonlocal` declaration is unnecessary dead code.
- **Dead code — `base_context` and `alert_context` in `telemetry_helpers.py`:** Confirmed. No callers found anywhere in `src/` or `tests/`. These are legacy Jinja2 helpers with no surviving consumers.
- **Dead code — `compute_health_metrics` duplicate vs inline logic:** PARTIALLY CONFIRMED. `compute_health_metrics` IS used — it is imported and called in `tests/integration/test_telemetry_timed_out.py`. However, the finding that `telemetry.py:145–173` duplicates the same computation inline without calling the helper is still real.
- **Dead code — `FileNotFoundError` catch after `resolved.exists()` check:** Confirmed at `apps.py:158–164`. After explicitly checking `resolved.exists()` and raising on `False`, the subsequent `read_text()` has a `FileNotFoundError` catch that can only be triggered by a TOCTOU race — not a normal code path. This is dead exception handling in practice.
- **Naming — `total_invocations` recomputed as `total_handler_inv`:** Confirmed at `telemetry.py:145,160`.
- **Naming — `ws_state: dict` untyped annotation:** Confirmed at `ws.py:41,62,90`.
- **Naming — `app_key` path string `"Use \`__hassette__\`..."` repeated four times:** Confirmed at lines 119, 182, 204, 228.
- **Naming — `"Any"` quoted return type in `api.py:692`:** Confirmed. `-> "Any":` is a quoted annotation for a non-forward-reference type.
- **Naming — `HassetteDep` annotation on plain helper function `_require_known_app`:** Confirmed at `apps.py:44`. `HassetteDep` is a FastAPI injection alias; using it on a helper that receives the already-resolved object is wrong.
- **Structural — oversized route handlers:** Confirmed (`app_health` 61 lines, `dashboard_app_grid` 82 lines).
- **Structural — `except Exception` in `apps.py:108–130`:** Confirmed.
- **Import hygiene:** Confirmed — `logs.py` uses `import logging` / `logging.getLogger` while all other web routes use `from logging import getLogger`. The `api.py` mixed `import typing` + `from typing import Any, Literal` style is confirmed.
- **Formatting — section divider comments in `api.py`:** Confirmed at lines 214–217, 969–975, 1433–1441.

### False positives

**`web/app.py:49` — `title="Hassette Web API"` flagged under "Hard-Coded Environment Values".**
FALSE POSITIVE. An application title string in a FastAPI instantiation is not an "environment value." It is the application name. Categorizing it as a hard-coded environment value is a miscategorization. It may be a minor style note (could be a constant) but it is not in the same category as hardcoded hostnames or credentials.

**`web/utils.py:69` — ternary `fire_at.timestamp() if live_job.jitter is not None else None` flagged as logic smell.**
FALSE POSITIVE. The condition tests `jitter` to decide whether to expose `fire_at`, because `fire_at` is meaningful (jittered) only when `jitter` is configured. When `jitter is None`, `fire_at == next_run` and showing it separately would be redundant. The condition correctly guards the semantically-meaningful case. This is valid domain logic, not a bug or smell.

**`api/api.py:588` — URL fragment `"states/{entity_id}"` flagged for repeated `"states/"` prefix across 4 sites.**
FALSE POSITIVE. URL path construction with f-strings from HA API path fragments is a self-documenting REST pattern. Extracting `"states/"` to a constant does not aid readability and adds indirection. Each call site shows the full intent clearly. This is not a magic string by rule #5 — the parameter name (`entity_id`) provides context at each use. This would be a valid finding only if the URL structure changes frequently; HA's REST API is stable.

---

## Report 5: `backend-scheduler-resources.md`

### Confirmed findings

- **Magic strings — FQN strings in `resources/base.py:86`:** Confirmed. `"hassette.resources.base.Service"` and `"hassette.core.core.Hassette"` are hardcoded class-name strings used for identity matching in `FinalMeta.__init__`. A rename or move of either class silently breaks the check.
- **Magic strings — `"Hassette"` / `"hassette"` / `"Hassette."` cluster in `resources/base.py:213–217`:** Confirmed as three related but distinct literals.
- **Magic strings — `assert source_tier in ("app", "framework")` in `scheduler.py:381`:** Confirmed — same values as in `bus/bus.py:322`, two independent inline guards for the same type.
- **Magic strings — `"Task-"` prefix string in `task_bucket.py:338`:** Confirmed.
- **Scattered constants — `resources/base.py:86` inline allowlist:** Confirmed.
- **Dead code — lazy imports in `resources/mixins.py`, `resources/base.py`, `app/utils.py`:** All confirmed as runtime lazy imports outside `TYPE_CHECKING`. `mixins.py:340` imports `HassetteServiceEvent` to instantiate it; `base.py:193` imports `TaskBucket` in `__init__`; `utils.py:31,96` import `App` twice in two separate functions. All violate the no-lazy-imports rule with no `TYPE_CHECKING` guard.
- **Dead code — section dividers in `resources/mixins.py`:** Confirmed (four section dividers).
- **Naming — `seq` counter in `classes.py:27`:** Confirmed. `seq = itertools.count(1)` is generic.
- **Naming — `v: str` in `app_config.py` validator:** Confirmed at line 33. Single-letter parameter name.
- **Naming — `FinalMeta.__init__` parameters `ns` / `kw`:** Confirmed. These abbreviate `namespace` and `kwargs`.
- **Naming — mixed logging import styles across module set:** Confirmed. `mixins.py` and `triggers.py` use `import logging` / `logging.getLogger` while `classes.py`, `utils.py`, `app.py` use `from logging import getLogger`.
- **Naming — `_shutting_down` / `_initializing` vs `_shutdown_completed` naming inconsistency:** Confirmed in `resources/base.py`.
- **Structural — `resources/base.py` 828 lines:** Confirmed (over 800-line hard limit).
- **Structural — `scheduler.py` 774 lines:** Confirmed.
- **Structural — oversized methods:** Confirmed (`schedule()` 88 lines, convenience methods 51–55 lines each).
- **Structural — `_run_hooks()` nesting depth 5:** Confirmed.
- **Structural — `else` after `return` in `task_bucket.py`:** Confirmed at lines 130 and 173.
- **Import hygiene — `app/app.py` redundant `import logging`:** Confirmed. Both `import logging` and `from logging import getLogger` are present; `logging.Logger` at line 67 should be `Logger` via direct import.

### False positives

**`classes.py:81` — `max_iterations = 10_000` flagged as a magic number needing a module-level named constant.**
FALSE POSITIVE. This is a local variable inside a method body controlling a safety loop. The `10_000` notation is already self-documenting, and the value is used in a log message on the next line. This is not a scattered config value that will be tweaked independently — it is a safety cap specific to this algorithm. A module-level constant for this value would add indirection without clarity. The finding is marginal at best.

**`app/app_config.py:22,28` — `instance_name: str = ""` and `app_key: str = ""` flagged for missing `UNSET_INSTANCE_NAME = ""` constant.**
FALSE POSITIVE. These are Pydantic model field defaults (rule #1). The empty string is the Pydantic-idiomatic "not yet configured" default for a string field. Grepping confirms neither `instance_name == ""` nor `app_key == ""` are used as sentinel checks in logic anywhere in the codebase — they are purely field defaults. A named constant for an empty-string Pydantic default adds no clarity.

**`resources/base.py:107` — f-string wrapping a single variable `f"{origin.__qualname__}"`.**
Confirmed as a real (minor) formatting finding — a redundant f-string with no formatting operations.

---

## Report 6: `backend-support.md`

### Confirmed findings

- **Magic numbers — `config/config.py` `truncated_token` method (3, 6, 8, 12):** Confirmed at lines 231–235. Four numeric literals defining display thresholds with no names.
- **Magic numbers — `"INFO"` repeated across `config/helpers.py` and `config/models.py`:** Confirmed. The string appears at `helpers.py:148,189` and `models.py:22,119,129` — five occurrences across two files with no shared constant.
- **Magic numbers — `lru_cache` sizes (64, 512, 512) in `utils/hass_utils.py`:** Confirmed. Three different cache sizes with no named constants or rationale comments.
- **Magic numbers — `lru_cache(maxsize=256)` in `source_capture.py` and `type_utils.py`:** Confirmed. Same value in two files with no shared constant.
- **Magic numbers — `conversion/state_registry.py:170` bare `200` truncation limit:** Confirmed.
- **Scattered constants — `config/config.py:119` base URL as Field default:** Confirmed. `"http://127.0.0.1:8123"` is a bare string in `Field(default=...)` rather than a named constant.
- **Scattered constants — `utils/source_capture.py:9` underscore prefix on `_INTERNAL_PATH_FRAGMENTS`:** Confirmed — module-level constant with unnecessary `_` prefix per project rules.
- **Dead code — `utils/type_utils.py:52` tautological condition:** Confirmed. `if tp is Any or tp is Any:` — the second clause is identical to the first and can never be reached independently.
- **Dead code — `utils/type_utils.py:278` unreachable second clause:** Confirmed. `isinstance(t, UnionType)` in the second half of the `or` can never be true independently if the first half `isinstance(t, UnionType)` is false.
- **Dead code — `utils/type_utils.py:296–298` `str(o).endswith("typing.Union")` fallback:** Confirmed as a fragile legacy string-match hack.
- **Dead code — `conversion/annotation_converter.py:104` unreachable `raise` after exhaustive if-chain:** Confirmed. After checking all three valid origins at the top of the function, the final `raise` is structurally unreachable.
- **Naming — `_NESTED_GROUPS` underscore prefix and placement after `HassetteConfig` class:** Confirmed. Defined at line 376 in a 380-line file, after the class body ends. Same pattern as `telemetry_repository.py` constants-after-class. The underscore prefix is also incorrect per project rules.
- **Naming — `utils/service_utils.py:10` `class _Color`:** Confirmed. An internal DFS color enum with `_` prefix that is not unsafe to call out of sequence.
- **Naming — underscore-prefixed functions in `source_capture.py`:** PARTIALLY CONFIRMED. `_is_internal_frame`, `_get_source_and_ast`, `_find_call_source` are internal helpers only called within `source_capture.py` — no external callers. The underscore prefix is technically acceptable here as true module-private helpers not exposed via `__init__.py`. However, the project rule does not recognize "private module function" as a valid justification — it only accepts "genuinely unsafe to call out of sequence." Finding is real per the stated rule.
- **Naming — `_get_extra_keys`, `_merge_exclude` in `config/classes.py`:** Confirmed. Internal helpers on a mixin class with no sequencing invariants.
- **Naming — `_make_union`, `_type_sort_key` in `utils/type_utils.py`:** Confirmed. Module-level functions with `_` prefix but no unsafe-call concern.
- **Naming — nested helper functions with `_` prefix inside `run_apps_pre_check`:** Confirmed. Nested functions by definition have limited scope; the prefix is noise.
- **Naming — `utils/execution.py:27` status strings as bare literals:** Confirmed. `"pending"`, `"success"`, `"error"`, `"cancelled"`, `"timed_out"` appear as inline literals throughout `execution.py` with no enum or named constants.
- **Import hygiene — lazy imports in `annotation_converter.py`, `state_registry.py`, `validation.py`, `type_utils.py`, `app_utils.py`:** All confirmed. These are runtime lazy imports without `TYPE_CHECKING` guards. The circular-import workarounds need structural resolution (dependency inversion or singletons moved to a `const`-style module).
- **Import hygiene — private Pydantic internal API `pydantic._internal._typing_extra`:** Confirmed at `type_utils.py:9`.
- **Hard-coded env values — Docker paths in `config/helpers.py`:** Confirmed. `/config`, `/data`, `/apps` appear as bare `Path("...")` literals in three separate functions with no shared constants.
- **Structural — oversized files and methods:** Confirmed across `app_utils.py` (517 lines), `type_utils.py` (416 lines), `run_apps_pre_check` (113 lines), `load_app_class` (76 lines).
- **Formatting — inconsistent docstring styles:** Confirmed.

### False positives

**`config/config.py:152` — `default_cache_size: int = Field(default=100 * 1024 * 1024)` flagged as a magic number.**
FALSE POSITIVE. This is a Pydantic field default (rule #1). The expression `100 * 1024 * 1024` is self-documenting (100 MiB), the field is named `default_cache_size`, and the docstring says "Defaults to 100 MiB." Adding a `DEFAULT_CACHE_SIZE_BYTES` constant would add indirection without clarity.

**`config/models.py` Pydantic field defaults flagged under "Hard-Coded Environment Values" — `host: str = Field(default="0.0.0.0")`, `port: int = Field(default=8126)`, `cors_origins: tuple[str, ...] = Field(default=("http://localhost:3000", "http://localhost:5173"))`.**
FALSE POSITIVE. These are Pydantic configuration model defaults — exactly where deployment defaults belong. They are not environment values hardcoded into logic; they are overridable config defaults declared in the config schema. `0.0.0.0`, `8126`, and the dev-server CORS origins are the correct place to document default deployment values. Rule #1 applies.

**`config/models.py:210` — `lambda data: data.get("app_shutdown_timeout_seconds", 10)` flagged for bare `10`.**
FALSE POSITIVE. This is a Pydantic `default_factory` that provides a fallback when the related `app_shutdown_timeout_seconds` field (also defaulting to 10) is not available in the raw data. The field `resource_shutdown_timeout_seconds` has a docstring explaining it defaults to `app_shutdown_timeout_seconds`. This is a Pydantic field default (rule #1), and the `10` exactly matches the adjacent field's own default, making the value self-consistent. Not a magic number.

**`config/defaults.py:9` — `AUTODETECT_EXCLUDE_DIRS_DEFAULT` flagged for being in the wrong file.**
FALSE POSITIVE. This is a named constant in a module specifically designed for configuration defaults (`defaults.py`). The concern is about which file is the "semantic home" — but `defaults.py` is a perfectly reasonable home for a default value used in configuration. Not a finding.

**`utils/app_utils.py:511` — `sys.path.insert(0, str(p))` flagged for bare `0`.**
FALSE POSITIVE. The `0` in `sys.path.insert(0, ...)` is the universally-understood Python idiom for "prepend to sys.path." Creating `SYS_PATH_PREPEND_INDEX = 0` would be absurd. This is rule #5 — the parameter name provides complete context.

**`utils/func_utils.py:140` — `index = -1 * abs(num_parts)` flagged as overly verbose.**
This is a code style note, not a magic number finding. The expression is redundant (`-abs(num_parts)` is cleaner), but it is not a magic number. Confirmed as a real style note, miscategorized as "Magic Numbers."

---

## Summary

| Report | Total reported | Confirmed | False positives | FP notes |
|--------|---------------|-----------|-----------------|----------|
| backend-core | ~51 | ~51 | 0 | — |
| backend-test-utils-models | 66 | 63 | 3 | TEST_SOURCE_LOCATION, SECONDS_PER_DAY dead code; web_mocks 0.0.0.0/8126 framing |
| backend-event-system | 39 | 37 | 2 | `noqa` characterization; predicates.py "800-line soft ceiling" framing |
| backend-api-web | 54 | 50 | 4 | app title as env value; fire_at ternary; `"states/"` URL prefix; compute_health_metrics framing |
| backend-scheduler-resources | 48 | 46 | 2 | max_iterations local variable; empty-string Pydantic defaults |
| backend-support | 78 | 68 | 10 | 4× Pydantic field defaults; lambda default; AUTODETECT_EXCLUDE_DIRS_DEFAULT placement; sys.path `0`; func_utils `-1 * abs` miscategorized; source_capture underscore (borderline) |
| **Total** | **336** | **315** | **21** | |

**False positive rate: ~6%.** The reports are high-quality with a low false positive rate. The most common false positive pattern across all six reports is **Pydantic field defaults in config schema files flagged as magic numbers or hard-coded environment values** — these are definitionally not magic numbers (rule #1 applies). The second pattern is **two findings where the nitpicker's characterization was inaccurate** (predicates.py line count framing, fire_at/jitter logic) rather than wrong about the existence of a finding.

### Highest-confidence false positives (safe to ignore entirely)

1. `TEST_SOURCE_LOCATION` and `SECONDS_PER_DAY` in `test_utils/config.py` — actively used in multiple test files
2. All Pydantic `Field(default=...)` numbers in `config/config.py` and `config/models.py` flagged under "magic numbers" or "hard-coded env values"
3. `web_mocks.py:78–79` `"0.0.0.0"` and `8126` — these exactly match the Pydantic defaults and the real finding is they're redundant assignments, not unnamed magic values
4. `web/utils.py:69` fire_at/jitter ternary — valid domain logic, not a smell
5. `sys.path.insert(0, ...)` bare `0` — universal Python idiom

### Findings worth elevating (real and high-impact)

1. **All five circular-import lazy imports in `backend-support`** — only category that violates a hard project invariant (`no-lazy-imports` rule). Structural fix required.
2. **5 unused `LOGGER` definitions in `backend-core`** — trivial, zero-risk deletions
3. **`TEST_SOURCE_LOCATION` / `SECONDS_PER_DAY` false positive** — these should be removed from any fix lists
4. **`compute_health_metrics` inline duplication** — real even though the function has callers; the inline version in `telemetry.py` should call the helper
5. **`base_context` and `alert_context` in `telemetry_helpers.py`** — confirmed dead, safe to delete
