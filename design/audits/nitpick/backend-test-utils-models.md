# Nitpick Audit — `src/hassette/test_utils/` and `src/hassette/models/`

Reviewed: `test_utils/` (17 files) and `models/` (~90 files, states/entities/helpers/base modules).

---

## 1. Magic Numbers and Strings

**`harness.py:76`** — Magic float `0.02` as default `interval` in `wait_for()`. Unnamed; should be a named constant such as `WAIT_FOR_INTERVAL`.

**`harness.py:735`** — Magic fallback literal `80` (default port): `self.api_base_url.port or 80`. A named constant `DEFAULT_HTTP_PORT = 80` or just explicit documentation of intent would be clearer.

**`harness.py:746`** — Bare string `"Bearer test_token"` in an inline lambda. The token value is separate from the `TEST_TOKEN` constant defined in `config.py` — same concept, different spellings. If the token ever changes in `config.py`, this lambda silently diverges.

**`web_mocks.py:69`** — Hard-coded URL string `"http://127.0.0.1:8123"` in `create_hassette_stub()`. This is test infrastructure configuration; it belongs as a named constant (compare: `TEST_BASE_URL` in `config.py` already holds the same value and could be imported).

**`web_mocks.py:78`** — Hard-coded string `"0.0.0.0"` for `web_api.host`. No constant, no explanation of why this differs from the loopback address used elsewhere.

**`web_mocks.py:79`** — Hard-coded integer `8126` for `web_api.port`. No named constant.

**`web_mocks.py:82`** — Hard-coded integer `2000` for `log_buffer_size`. No named constant.

**`web_mocks.py:83`** — Hard-coded integer `1000` for `job_history_size`. No named constant.

**`web_mocks.py:93`** — Hard-coded integers `30`, `20`, `10` for lifecycle timeout fields. No named constants.

**`web_mocks.py:170`** — Magic epoch float `1704067200.0` (2024-01-01 UTC) as the default `start_time` argument in `create_mock_runtime_query_service()`. No name, no comment on the choice of date.

**`web_helpers.py:103-106`** — Four bare floats (`2.0`, `1.0`, `5.0`, `2.0`) for `total_duration_ms`, `min_duration_ms`, `max_duration_ms`, `avg_duration_ms` inside `make_listener_metric()`. These are stub values but they are unnamed and appear as inline literals in a factory function other tests depend on for assertions.

**`web_helpers.py:157`** — Magic integer `30` as the default `seconds` value when parsing an `Every` trigger. Used as a hardcoded fallback when `trigger_detail` is absent or unparseable. Should be a named constant such as `DEFAULT_INTERVAL_SECONDS`.

**`web_helpers.py:165`** — String `"2030-01-01T00:00:00"` implicitly embedded via `ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0)` in the `"once"` trigger branch. A far-future sentinel is reasonable here but the year choice is undocumented.

**`app_harness.py:498-499`** — Two identical literal strings `"1970-01-01T00:00:00+00:00"` passed as `last_changed` and `last_updated` in `set_state()`. The docstring explains the epoch sentinel rationale, but these appear as bare string literals in the call rather than a named constant (e.g. `EPOCH_TIMESTAMP_ISO = "1970-01-01T00:00:00+00:00"`).

**`app_harness.py:267`** — Comment says "Set up the full harness in 11 steps" — but the actual step numbering in `_setup()` runs from Step 1 through Step 11, so the count is accurate. However, `"11"` is a magic number in the docstring that will silently lie when steps are added or removed.

**`reset.py:99`** — Bare string `"test"` as the owner ID passed to `remove_listeners_by_owner()`. This couples the reset logic to a convention (test-registered listeners must use `"test"` as their owner) with no named constant and no documentation in this file.

**`web_helpers.py:44`** — String `"http://localhost:3000"` hard-coded as the default `cors_origins` tuple entry in `create_hassette_stub()`. Not a named constant.

---

## 2. Scattered Constants

**`config.py:15-19`** — `TEST_TOKEN`, `TEST_BASE_URL`, `TEST_WS_URL`, `SECONDS_PER_DAY`, `TEST_SOURCE_LOCATION` are defined here. `SECONDS_PER_DAY` is defined but never referenced within this file or any file in `test_utils/` based on its usage pattern — it is an orphaned constant.

**`harness.py:746` vs `config.py:15`** — The string `"Bearer test_token"` (harness) differs from `TEST_TOKEN = "test-token"` (config). If the intent is to use the test token, the harness should compose it from `TEST_TOKEN` imported from `config.py`. Two representations of the same conceptual value in two files.

**`web_mocks.py:69` vs `config.py:16`** — `"http://127.0.0.1:8123"` in `create_hassette_stub()` is the same value as `TEST_BASE_URL = "http://test.invalid:8123"` in `config.py`. They are *not* identical — `web_mocks.py` uses `127.0.0.1` and `config.py` uses `test.invalid`. Two different URL strings for the same conceptual "HA base URL for testing" spread across two files without explanation of the divergence.

**`harness.py:199`** — Colors `_white, _gray, _black = 0, 1, 2` are defined as local variables inside `sort_harness_graph()`. They encode a graph coloring protocol. A frozen dataclass or module-level `IntEnum` would give these values stable names and make the DFS algorithm self-documenting.

---

## 3. Ternary Abuse

**`harness.py:83`** — `result = (await predicate()) if is_async else predicate()` is a ternary used as a statement/assignment with a cast comment on the same line. The condition is fine but the `# pyright: ignore` appended inline makes the line push 100+ characters and harder to parse at a glance.

No nested ternaries or ternaries-as-statements without assignment found elsewhere.

---

## 4. CSS and Styling Sins

(CSS and Styling Sins): clean

---

## 5. Dead Code

**`test_server.py:11`** — Commented-out type alias: `# Key = tuple[str, str, str]  # (METHOD, PATH, QUERYSTRING)`. The `Key` dataclass on line 15 replaced this; the comment is vestigial.

**`test_server.py:118`** — Commented-out line inside `dump_all()`: `# expectations = {str(k): v for k, v in self._expectations.items() if v}`. This is a leftover from an earlier implementation that the live line above it replaced.

**`test_server.py:114`** — `dump_all()` has no return type annotation, unlike all other methods in the class. Not dead code, but a consistency failure that makes it look unfinished.

**`config.py:19`** — `TEST_SOURCE_LOCATION = "test.py:1"` is defined but not referenced anywhere in `test_utils/` (the grep over the whole package yields no import or usage). Dead constant.

**`helpers.py:103-134`** — `_create_component_loaded_event()` and `_create_service_registered_event()` carry a `# pyright: ignore[reportUnusedFunction] — imported by simulation.py` comment. The comment is the only clue they are used; their import in `simulation.py` uses `from hassette.test_utils.helpers import _create_component_loaded_event, _create_service_registered_event` (confirmed at `simulation.py:23-25`). The functions are not dead, but the leading `_` prefix signals "do not call" while the reality is they are called from another module — a naming inconsistency flagged here under Dead Code / naming convention rather than a true dead function.

**`fixtures.py:55-61`** — `hassette_with_nothing` fixture is defined in `fixtures.py` but is not re-exported from `_internal/__init__.py` or from the public `test_utils/__init__.py`. It is used in `tests/conftest.py` via pytest fixture injection, so it must be discovered through conftest — not dead, but its absence from the re-export tables is inconsistent with all sibling fixtures.

**`fixtures.py:133-139`** — `hassette_with_state_registry` fixture is defined but absent from `_internal/__init__.py`'s `__all__`. Same pattern as `hassette_with_nothing` above — used in tests but not re-exported.

**`models/states/base.py:72-73`** — Comment `# Note: HA docs mention object_id and name, but I personally haven't seen these in practice.` contains the word "personally" — first-person tone leaked from a note written during authoring. Fine as a rationale but the tone is inconsistent with the rest of the codebase.

---

## 6. Naming Inconsistencies

**`harness.py:54`** — `class TIMEOUTS` uses `ALL_CAPS` for a class name, which is the Python convention for module-level constants, not for classes. Every other class in the codebase uses `PascalCase`. `TIMEOUTS` is a namespace for constants (no `__init__`, no instances), so it reads as a class but looks like a constant. A module-level `dataclass(frozen=True)` or a plain namespace with PascalCase (`class Timeouts`) would be consistent.

**`app_harness.py:60-65`** — `_CLASS_LOCKS` and `_CLASS_MANIFEST_STATE` use `SCREAMING_SNAKE_CASE` for module-level variables that are mutable (`WeakKeyDictionary`). Python convention reserves `SCREAMING_SNAKE_CASE` for constants. These are not constants — they are mutable module-level state. `_class_locks` and `_class_manifest_state` would be more accurate.

**`config.py:25`** — `_HermeticHassetteConfigPair` uses `PascalCase` with a leading underscore for a module-level variable. The leading `_` correctly signals private, but `PascalCase` is the class naming convention — this looks like a class name, not a variable. `_hermetic_hassette_config_pair` would be consistent with Python variable conventions.

**`harness.py:302`** — `self._previous_task_factory: typing.Any` and `self._hassette_ctx_token: typing.Any` — both annotated as `typing.Any` with inline comments about their real types. The real type exists (`contextvars.Token[Hassette]` for the token); using `Any` makes static analysis blind here.

**`web_helpers.py:76-90`** — `make_listener_metric()` returns a `MagicMock` but its return type annotation is `MagicMock`. The individual attribute fields set via `setattr` are typed in the inner dict but not in the mock itself. Callers who call `.listener_id` get an untyped `Any`. The factory name says "metric" but the return type is a mock — inconsistent abstraction.

**`helpers.py:103`** — `_create_component_loaded_event` and `_create_service_registered_event` use the `_` prefix convention (conventionally: "do not call from outside this module"), but they are imported and called from `simulation.py`. The underscore is misleading. Either drop the prefix or move them into the module that uses them. Compare with `create_state_change_event` and `create_call_service_event`, which are public functions in the same file and exported.

**`fixtures.py:152`** — Variable `line` is rebound inside the loop body (`line = line.strip().rstrip(",")`) inside `state_change_events` (and again at line 199 in `other_events`). Rebinding a loop variable to a processed version on the same name is a reading hazard. A new name (`stripped` or `raw_line`) would make the transform visible.

**`simulation.py:155`** — Variable `proxy_state: str = "unknown"` — the name `proxy_state` is slightly misleading; it's the *state value string* from the proxy, not a proxy object. `state_value` or `current_state_str` would be more precise.

**`web_mocks.py:151-152`** — Private variables `_cursor` defined at module level inside a function body (inside `create_hassette_stub()`). The leading `_` on a local variable is unusual Python — it implies "unused by the linter" but these variables *are* used. The underscore prefix on locals has no standard Python meaning and just adds noise.

---

## 7. Structural Messiness

**`recording_api.py`** — 1,159 lines. Exceeds the 800-line hard ceiling. The `ApiProtocol` (lines 142–311, ~170 lines), the 32 per-domain CRUD delegation methods (lines 779–968, ~190 lines), and the assertion helpers (lines 1001–1159, ~159 lines) are three structurally distinct sections that could each live in their own module. The per-domain methods are thin delegations with zero logic; their size is pure boilerplate that obscures the actual implementation.

**`harness.py`** — 768 lines. Over the 400-line typical ceiling and approaching the 800 hard ceiling. The `HassetteHarness` class body alone is ~490 lines. The `sort_harness_graph()` function (57 lines), the `_DEPENDENCIES`/`_STARTUP_ORDER`/`_COMPONENT_CLASS_MAP` constants, and the `_starters` dispatch table are all independent of each other and could be extracted into a `_harness_graph.py` module.

**`simulation.py`** — 676 lines. Exceeds the 400-line typical ceiling. The `_drain_task_bucket` method (lines 504–631) is 127 lines by itself, of which ~60 are inline comments. `_raise_drain_timeout` (lines 633–676) could reasonably be a module-level function.

**`harness.py:610-698`** — `_start_bus()` and `_start_scheduler()` each contain a near-identical `_stub_execute` inner function (~35 lines each). The comment on both says "NOTE: mirrors the other — keep both in sync." This is textbook duplication: the identical logic should be extracted into a shared helper, and the warning comment is the smell.

**`harness.py:651`** and **`harness.py:701`** — `_listener_id_counter` and `_job_id_counter` are local `itertools.count()` objects defined inside `_start_bus()` and `_start_scheduler()` respectively. Each is captured by a nested closure. The counter is re-created every time the starter runs — if `start()` is ever called twice on the same harness (e.g., stop + restart), counter state is lost. The variable naming and scope make this non-obvious.

**`app_harness.py:280`** — `_setup()` is 95 lines. Exceeds the 50-line function limit. The 11 numbered steps could each be extracted into named methods (e.g., `_create_harness()`, `_start_harness()`, `_configure_manifest()`, `_start_app()`).

**`app_harness.py:426`** — `__aexit__` is a one-liner delegating to `_exit_stack`. Fine in isolation, but `__aenter__` calls `_setup()` which is 95 lines. The asymmetry between a trivial exit and a complex entry is itself a structural smell — the complexity is buried one level deep.

**`helpers.py:170-249`** — `make_light_state_dict`, `make_sensor_state_dict`, and `make_switch_state_dict` share identical boilerplate in their bodies: extract `state_kwargs`, update `attributes`. The pattern is the same across all three; a shared private helper would eliminate the repetition.

**`web_mocks.py:20-36`** — `_wire_telemetry_stubs()` is a 17-line private function that assigns 12 individual `AsyncMock` attributes to one object. The function exists purely for length management inside `create_hassette_stub()` but there are no other callers; it reads as extracted for extraction's sake rather than for reuse or testability.

**`models/states/media_player.py`** — 249 lines; the `MediaPlayerAttributes` class has 25 `supports_*` property methods, one per feature flag. Each is a single-line body. This is a legitimate generated pattern across the entire models directory (all entity-feature files follow it). Flagging once: the `supports_*` property pattern is consistently applied but generates significant line-count inflation. It is intentional and consistent, but any future addition of feature flags compounds the file length linearly.

---

## 8. Import Hygiene

**`fixtures.py:1-8`** — Imports `contextlib`, `json`, `logging`, `os`, `random`, `typing` from stdlib, then `Path` from `pathlib`, then `TYPE_CHECKING` from `typing`. The `typing` module is imported twice: once as `import typing` (line 6) and once as `from typing import TYPE_CHECKING` (line 8). These should be consolidated into a single `from typing import TYPE_CHECKING` (and any `typing.X` usages replaced with direct imports).

**`harness.py:41`** — `if typing.TYPE_CHECKING:` uses the module reference form despite `typing` being imported as `import typing` rather than `from typing import TYPE_CHECKING`. The rest of the codebase prefers `from typing import TYPE_CHECKING`. Minor inconsistency.

**`helpers.py:5-6`** — `from logging import Logger, getLogger` and then at line 341, `getLogger(__name__).debug(...)` is called directly on the module. The `Logger` type is imported only for the `create_listener()` function's `logger` parameter annotation. This import is used, but the two uses (type annotation vs. module-level logger) are structurally different and could be clearer if `Logger` were annotated only in `TYPE_CHECKING`.

**`app_harness.py:29-31`** — `if TYPE_CHECKING:` block imports `from hassette import Hassette` and `from hassette.events import HassStateDict`. Then at line 39, `from hassette import context` is a runtime import. The separation is correct, but `Hassette` appears both in the `TYPE_CHECKING` block (line 32) and as a bare string annotation (e.g., `cast("Hassette", ...)` at line 329). Using string annotations for some occurrences and the TYPE_CHECKING import for others creates an inconsistent pattern within the same file.

**`entities/base.py:1`** — `import typing` at the top, then uses `typing.TYPE_CHECKING`, `typing.TypeVar`. The rest of the entities module uses `from typing import ...`. This file uses the module-reference style while siblings use the import-from style — inconsistent within the same package.

---

## 9. Hard-Coded Environment Values

**`web_mocks.py:72`** — `hassette.config.data_dir = "/srv/hassette/data"` — hard-coded absolute path in stub configuration. This is a mock value, but it leaks an assumption about deployment paths into test infrastructure.

**`web_mocks.py:73`** — `hassette.config.config_dir = "/srv/hassette/config"` — same issue as above.

**`web_mocks.py:95`** — `hassette.config.apps.directory = "/srv/hassette/apps"` — same issue.

**`harness.py:746`** — `"Authorization": "Bearer test_token"` — a hard-coded credential string in the API mock headers factory. The token should at minimum be sourced from `TEST_TOKEN` in `config.py` to avoid the two representations diverging.

**`web_mocks.py:44`** — `cors_origins: tuple[str, ...] = ("http://localhost:3000",)` — hard-coded origin URL in a default argument.

---

## 10. Formatting Inconsistencies

**`test_server.py:40`, `56`, `73`, `89`** — Section divider comments use `# ----- label -----` style (dashes as decorators). The project coding style rule explicitly prohibits decorated comment blocks between methods. These four section dividers should be removed.

**`sync_facade.py`** — Generated file, but has a consistent style divergence from hand-written files: every method body is separated from its signature by a blank line (e.g., line 134: empty line between `def get_states():` docstring and `items = list(...)`). This blank line is the generator's output format. It is consistent within this file but inconsistent with the hand-written counterpart `recording_api.py` where no such blank lines appear. Not a violation to fix by hand (it's generated), but worth noting for the generator.

**`helpers.py:349`** — Inline decorator string: `decorator = "@only_app\n" if has_only_app else ""` — this is a ternary building source code via string concatenation. It is functional but mixes code generation into what looks like a utility function. The `\n` newline is a formatting detail embedded in a flag-value mapping.

**`app_harness.py:432-434`** — Section divider comments `# ------------------------------------------------------------------` (66 dashes, repeating across several locations). Same violation as `test_server.py` — decorated comment blocks are prohibited by coding style.

**`recording_api.py:432`, `545`, `629`, `662`, `998`** — Same `# ------------------------------------------------------------------` section divider pattern, five instances.

**`harness.py:46-52`** — Multi-line section header with `# ---------------------------------------------------------------------------` borders. Same decorated comment block pattern.

**`harness.py:174-176`** and **`harness.py:608-609`** — Additional `# ---------------------------------------------------------------------------` borders.

**`simulation.py`** — No section dividers (clean). Notable positive contrast with `harness.py` and `recording_api.py`.

---

## Summary

| Category | Findings |
|---|---|
| Magic Numbers and Strings | 16 |
| Scattered Constants | 4 |
| Ternary Abuse | 1 |
| CSS and Styling Sins | 0 |
| Dead Code | 8 |
| Naming Inconsistencies | 8 |
| Structural Messiness | 11 |
| Import Hygiene | 4 |
| Hard-Coded Environment Values | 5 |
| Formatting Inconsistencies | 9 |
| **Total** | **66** |

Highest-impact cleanup: **Structural Messiness** — `recording_api.py` at 1,159 lines with three distinct structural sections (protocol, 32 delegating CRUD methods, assertion helpers), combined with the duplicated `_stub_execute` functions in `harness.py` and the bloated `_setup()` in `app_harness.py`, represent the largest concentration of accumulated complexity; splitting `recording_api.py` alone would drop the file below the 400-line ceiling and make the protocol definition, implementation, and test helpers independently navigable.
