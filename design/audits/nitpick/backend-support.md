# Nitpick Audit — Backend Support Modules

**Scope:** `src/hassette/utils/`, `src/hassette/config/`, `src/hassette/conversion/`,
`src/hassette/types/`, `src/hassette/const/`, `src/hassette/migrations/`

---

## 1. Magic Numbers and Strings

**`config/config.py:152`** — `100 * 1024 * 1024` inline in a Field default. The expression is self-documenting, but the result (100 MiB) is used nowhere else and the docstring already names it — the constant itself should be named (`DEFAULT_CACHE_SIZE_BYTES`) and placed at module top.

**`config/config.py:232`** — `8` and `12` are bare magic numbers in `truncated_token`. No named constants. What do they mean semantically? Boundary for "show prefix only" vs "show prefix and suffix" is not obvious from the numbers alone.

**`config/config.py:235`** — `6` appears twice in the same expression (`self.token[:6]`, `self.token[-6:]`). Should be a named constant (`TOKEN_DISPLAY_CHARS = 6`).

**`config/config.py:231`** — `3` also magic: `self.token[:3]`. Three separate numeric literals in `truncated_token` with no names.

**`config/helpers.py:137`** — `"INFO"` appears as a hard-coded default string in three places: `get_log_level()` line 148, `coerce_log_level()` line 151, and `log_level_default_factory()` line 189. It's a repeated literal that should be a module-level constant (`DEFAULT_LOG_LEVEL = "INFO"`).

**`config/models.py:22`** — `"INFO"` as the `fallback` literal in `LOG_ANNOTATION = Annotated[..., BeforeValidator(partial(coerce_log_level, fallback="INFO"))]`. Same literal repeated across helpers.py and models.py.

**`config/models.py:210`** — `lambda data: data.get("app_shutdown_timeout_seconds", 10)` — bare `10` as fallback in a `Field(default_factory=...)`. What does 10 mean? "10 seconds" — but the value is not tied to any constant.

**`utils/hass_utils.py:8`** — `MAX_EXPECTED_ENTITY_IDS = 16384` is defined here but is really an lru_cache size. The magic value 16384 (2^14) has no comment explaining the choice.

**`utils/hass_utils.py:24`** — `@functools.lru_cache(64)` — bare `64` with no named constant or comment explaining the choice.

**`utils/hass_utils.py:32`** — `@functools.lru_cache(512)` — bare `512` with no named constant or comment. Different from line 24 with no explanation.

**`utils/hass_utils.py:43`** — `@functools.lru_cache(512)` — same bare `512` repeated. Three different cache sizes across this short file with no rationale.

**`utils/execution.py:107`** — `"\n... [truncated]"` — a magic string suffix for truncated tracebacks. The constant `MAX_TRACEBACK_SIZE` is named, but the truncation suffix is not.

**`utils/source_capture.py:17`** — `lru_cache(maxsize=256)` — bare `256`. No named constant; the comment above says "maxsize=256" which just restates the literal.

**`utils/type_utils.py:32`** — `lru_cache(maxsize=256)` — bare `256` again, same value as `source_capture.py` but no shared constant.

**`utils/app_utils.py:511`** — `sys.path.insert(0, str(p))` — bare `0` as the insertion index. Technically self-evident but could be named `SYS_PATH_PREPEND_INDEX = 0`.

**`conversion/state_registry.py:170`** — `truncated_data = truncated_data[:200] + "...[truncated]"` — bare `200` and a magic truncation suffix string. No named constant for the truncation limit.

**`utils/func_utils.py:140`** — `index = -1 * abs(num_parts)` — the `-1 * abs(...)` pattern is a sign-forcing idiom that could be just `-abs(num_parts)`. Not a magic number but an unnecessarily verbose expression.

---

## 2. Scattered Constants

**`config/defaults.py:9`** — `AUTODETECT_EXCLUDE_DIRS_DEFAULT` is defined here but its semantic home is arguably `config/models.py` where `AppsConfig` uses it, or a dedicated `const/` module. It currently sits in `defaults.py` alongside TOML file path constants, which is a mixed-concern bag.

**`config/defaults.py:6-8`** — `DEV_FILE`, `PROD_FILE`, and `FILE_LOCATION` are internal constants only used by `get_defaults_from_toml`. They are fine as module-level constants but have no doc comments explaining what `"hassette.config"` is (a resource package path).

**`utils/app_utils.py:33`** — `EXCLUDED_PATH_PARTS = ("site-packages", "importlib")` is defined at module level, which is correct, but it's a constant used only by the nested function `_find_user_frame` inside `run_apps_pre_check`. It belongs either as a local constant inside the outer function, or elevated with a clearer name like `NOISY_TRACEBACK_PATH_FRAGMENTS`.

**`utils/source_capture.py:9`** — `_INTERNAL_PATH_FRAGMENTS = ("hassette/bus/", "hassette/scheduler/", "hassette/core/")` uses an underscore prefix. Per project rules, no underscore prefixes on application code. Should be `INTERNAL_PATH_FRAGMENTS`.

**`conversion/type_registry.py:280`** — the comment `## Value Converters ##` is a section divider. The project style guide explicitly bans decorated comment blocks between methods. This one uses double-hash + spaces but is still a section divider comment. (See also: Structural Messiness.)

**`config/config.py:119`** — `"http://127.0.0.1:8123"` is a hard-coded default URL embedded directly in the `Field(default=...)` call. It belongs in `config/defaults.py` alongside the other location defaults, or at minimum as a named constant at the top of `config.py`.

---

## 3. Ternary Abuse

**`utils/type_utils.py:52`** — `if tp is Any or tp is Any:` — this is a tautological condition. The `or tp is Any` is completely redundant. Likely a copy-paste error from before.

**`utils/app_utils.py:169`** — `config = config if isinstance(config, list) else [config]` — this is fine as a single ternary and passes the length threshold, but the pattern reads oddly: `config = [config]` when it's not a list. The variable `config` is immediately shadowed by the result. This is clean enough but worth a quick look.

No multi-level nested ternaries found.

---

## 4. CSS and Styling Sins

(Skipped — Python backend code.)

---

## 5. Dead Code

**`config/helpers.py:8`** — `cast` is imported from `typing` but only used in one place (`coerce_log_level`, line 174). Not dead, but the import `get_args` is also used (line 18) — however `cast` is used correctly. This is clean.

**`config/classes.py:88`** — `pass  # caller explicitly requested specific fields — respect that` — this is a bare `pass` inside an `if` branch in `model_dump`. The logic is: detect the special case, do nothing. This is intentional but a `pass` with a comment inside a conditional block is the same pattern as a silenced code path. It reads like dead code. Consider early-returning or restructuring so the `if extra_keys` / `elif extra_keys` pair doesn't have an empty branch.

**`utils/type_utils.py:278`** — `if isinstance(t, UnionType) or (get_origin(t) is None and isinstance(t, UnionType)):` — the second condition `get_origin(t) is None and isinstance(t, UnionType)` is unreachable: if `isinstance(t, UnionType)` is already true in the second clause, the first clause `isinstance(t, UnionType)` would already be true and short-circuit. The second half of the `or` is dead.

**`utils/type_utils.py:296-298`** — Inside `_make_union`, the block:
```python
if str(o).endswith("typing.Union"):
    really_flat.update(get_args(t))
```
This is a fragile string-comparison hack for detecting `typing.Union`. The `get_origin` check on line 293 (`o is UnionType`) already handles PEP 604 unions. The `str(o).endswith("typing.Union")` path is a dead-code safety valve that may never execute in modern Python. No TODO or comment justifies keeping it.

**`migrations/versions/__init__.py`** — empty file (verified: 1 line, the file exists but is empty). Not dead code per se, but an empty `__init__.py` with no comment is worth noting.

**`conversion/type_registry.py:281`** — `## Value Converters ##` section divider comment (see also Scattered Constants above). Project style bans these.

---

## 6. Naming Inconsistencies

**`config/config.py:376-380`** — `_NESTED_GROUPS` is defined at module level with an underscore prefix. Project rules prohibit underscore prefixes on non-framework-boundary names in application code. This is module-level, not a method, so the convention applies.

**`utils/service_utils.py:10`** — `class _Color(Enum)` — underscore-prefixed class name at module level. Same objection as above; this is an internal DFS color enum that has no unsafe-call semantics.

**`utils/source_capture.py:9,12,17,35,57`** — All module-level names in this file use underscore prefixes (`_INTERNAL_PATH_FRAGMENTS`, `_is_internal_frame`, `_get_source_and_ast`, `_find_call_source`) despite being the primary functions of the module, not implementation details of a class. Project rules say no underscore prefixes unless genuinely unsafe to call out of sequence.

**`config/classes.py:65`** — `_get_extra_keys` and `_merge_exclude` (lines 65 and 69) use underscore prefixes on methods in `ExcludeExtrasMixin`. These are internal helpers, but per project rules, underscore prefixes are inappropriate unless there's a real unsafe-call concern.

**`utils/type_utils.py:273`** — `_make_union` and `_type_sort_key` (lines 273, 315) use underscore prefixes on module-level functions. Not methods, not framework boundaries, no unsafe-call concern.

**`utils/app_utils.py:49,62,96`** — Three nested helper functions (`_root_cause`, `_find_user_frame`, `_log_compact_load_error`) inside `run_apps_pre_check` use underscore prefixes. Nested functions by definition have limited scope; the prefix adds nothing. No naming rule requires it.

**`config/models.py:22`** — `LOG_ANNOTATION` is an annotated type alias used as a field type. It's more of a type than a constant, but it's named in `SCREAMING_SNAKE_CASE` like a constant rather than `PascalCase` like a type alias. Inconsistent with how Python type aliases are typically named.

**`utils/type_utils.py:91`** — `V` and `V_contra` type variables are defined in `types/types.py` (lines 91-92). Then separately in `utils/type_utils.py` there is no `V` but there are local conventions. The `V` / `V_contra` pair is duplicated; `V` in `types/types.py` is a value TypeVar while there are separate `R = TypeVar("R")` and `T = TypeVar("T")` in `conversion/type_registry.py`. Generic single-letter TypeVars scattered across three files.

**`conversion/type_registry.py:15-16`** — `R = TypeVar("R")` and `T = TypeVar("T")` at module level. `T` is a very generic name for the input type; `R` for return. These are identical in meaning to the `T`/`R` concept but not shared with `types/types.py`.

**`config/models.py:22`** — `LOG_ANNOTATION` (constant-style name) vs `ChangeType` in `types/types.py` (type-style name) — two type aliases with inconsistent naming conventions.

**`utils/execution.py:27`** — `status: str = "pending"` — `"pending"` is a magic string for the initial status. The status strings `"success"`, `"error"`, `"cancelled"`, `"timed_out"`, and `"pending"` all appear as literals throughout `execution.py`. None are defined as named constants or an enum. The status field is a `str` type rather than `Literal[...]` or an enum.

**`utils/glob_utils.py:34`** — `split_exact_and_glob` duplicates the `any(ch in value for ch in GLOB_CHARS)` check that `is_glob` (line 8) already performs, rather than calling `is_glob`. Inconsistent use of the extracted helper within the same file.

---

## 7. Structural Messiness

**`utils/app_utils.py:36-148`** — `run_apps_pre_check` is 113 lines. Three nested helper functions (`_root_cause`, `_find_user_frame`, `_log_compact_load_error`) are defined inside it. The function does more than one thing: defines helpers, iterates manifests, and handles multiple exception types. The nested helper functions could be promoted to module-level helpers.

**`utils/app_utils.py:62-90`** — `_find_user_frame` is 29 lines and has three labeled phases in comments ("1) prefer...", "2) otherwise...", "3) fallback"). Each phase is a separate concern and warrants extraction.

**`utils/type_utils.py`** — The file is 416 lines, over the 400-line soft limit. It contains at least 15 distinct functions covering isinstance normalization, union building, annotation formatting, and event-type checking — multiple coherent responsibilities that could be split.

**`utils/app_utils.py`** — The file is 517 lines, significantly over the 400-line limit. It combines: pre-check orchestration, app cleaning, auto-detection, class loading, module importing, sys.path management, and namespace package manipulation. These are at least four separable concerns.

**`config/config.py:268-320`** — `model_post_init` is 53 lines, over the 50-line function limit. It applies root-level defaults, then nested group defaults, then checks for legacy key migration. Three distinct phases, each could be a separate method.

**`conversion/state_registry.py:60-120`** — `try_convert_state` is 61 lines. It validates the entity_id, resolves the state class, iterates a fallback chain, and delegates to `_conversion_with_error_handling`. The method does multiple things and is at the edge of the line limit.

**`utils/service_utils.py:166-229`** — `wait_for_ready` is 64 lines with an embedded async inner function `_wait_all`. The inner function + the two-branch outer structure (with/without shutdown_event) makes this harder to read than necessary.

**`utils/type_utils.py:273-312`** — `_make_union` is 40 lines with two separate flattening passes (`flat` then `really_flat`) and a `str(o).endswith(...)` hack. Comment density is high, indicating the function is explaining its own complexity rather than being simple.

**`config/models.py:320-347`** — `extract_app_definitions` model validator at 28 lines does multiple passes: identify known fields, identify reserved fields, extract app defs, merge with existing. Three concerns.

**`config/classes.py:183-207`** — `validate_model_extra` at 25 lines has an `if/elif/else` structure where the `else` branch contains a nested `if/elif`. Nesting reaches 3+ levels within the else.

**`utils/app_utils.py:331-406`** — `load_app_class` is 76 lines. Well over the 50-line limit. Contains: cache lookup, two cache-miss paths (force-reload and cold), module import, attribute extraction, subclass check, import-exception check, and validation. Seven distinct operations.

**`else` after `return` findings:**

**`utils/type_utils.py:196-211`** — `normalize_annotation`: the final `return normalize_constructible(tp) if constructible else tp` follows an early-return pattern throughout, which is fine, but line 205 has `return tp` after a series of `continue`-equivalent early returns via the `while True` loop. Clean enough.

**`conversion/annotation_converter.py:104`** — `convert_homogeneous_iterable`: after `if origin is list: return [...]` and `if origin is set: return {...}` and `if origin is frozenset: return frozenset(...)`, there is a final `raise UnableToConvertValueError(...)`. Given that the guard at line 104 already checks `if origin not in (list, set, frozenset)`, the final raise is unreachable. It's a defensive guard, but structurally it's dead code after an exhaustive if-chain (see also Dead Code).

---

## 8. Import Hygiene

**`config/config.py:1-33`** — Imports are grouped correctly (stdlib → third-party → local). Clean.

**`utils/type_utils.py:9`** — `from pydantic._internal._typing_extra import try_eval_type` — this is a private internal Pydantic API import (`_internal`). Importing private internals is a hygiene concern: it may break across Pydantic minor versions without warning.

**`conversion/annotation_converter.py:38-39`** — Two lazy imports inside the `convert` method:
```python
from hassette.conversion import TYPE_MATCHER, TYPE_REGISTRY
from hassette.models.states import BaseState
```
These are explicitly lazy to avoid circular imports. The circular import pattern is a structural smell: if `annotation_converter.py` needs `TYPE_MATCHER` and `TYPE_REGISTRY` from its own package's `__init__.py`, that init file should not import from `annotation_converter` — or the singletons should live in a separate module. As it stands, this is a noted exception (`TYPE_CHECKING` is not used here, and these are runtime imports — the project rules say the only acceptable exception is `TYPE_CHECKING` guards). This violates the "no lazy imports" rule.

**`conversion/state_registry.py:86`** — Lazy import inside `try_convert_state`:
```python
from hassette.models.states.base import BaseState
```
Same circular-import workaround. Not guarded by `TYPE_CHECKING`. Violates the no-lazy-imports rule.

**`conversion/validation.py:83-92`** — `_get_base_state_class()` wraps a lazy import in a function to avoid circular imports. This is a deliberate workaround documented in a docstring, but still violates the rule. The function exists solely to defer the import.

**`utils/type_utils.py:261-263`** — Lazy import inside `is_event_type`:
```python
from hassette.events import Event
```
Same pattern. No `TYPE_CHECKING` guard. Violates no-lazy-imports rule.

**`utils/app_utils.py:195`** — Lazy import inside `autodetect_apps`:
```python
from hassette.app import App, AppSync
```
Violates no-lazy-imports rule.

**`utils/app_utils.py:350`** — Lazy import inside `load_app_class`:
```python
from hassette.app import App, AppSync
```
Same import, same violation. The same `from hassette.app import App, AppSync` appears twice in the same file at lines 195 and 350, both lazy. If the circular import concern applies, a single lazy import at the top of the file into a local name would at least consolidate it.

**`config/config.py:33-34`** — `from hassette.utils.app_utils import autodetect_apps, clean_app` — these are utilities for a config-processing step. Their presence in a config module creates a dependency on the utils layer, which is fine directionally, but the import of `autodetect_apps` specifically pulls in `inspect`, `json`, `sys`, `traceback`, and `importlib` indirectly. The config module transitively pulls in a lot of machinery.

**`utils/service_utils.py:1-8`** — `import logging` (stdlib) and `import asyncio` are correctly at the top. But `from enum import Enum, auto` is used only for the private `_Color` enum. This is a tiny concern but `_Color` is used only internally — if it were inlined as a module-level tuple of constants it would avoid the import.

---

## 9. Hard-Coded Environment Values

**`config/config.py:119`** — `base_url: str = Field(default="http://127.0.0.1:8123")` — a hard-coded localhost URL for Home Assistant. This is a default value, which is intentional, but the literal `"http://127.0.0.1:8123"` is buried in the field declaration rather than named as a constant (`DEFAULT_HA_BASE_URL`).

**`config/models.py:259`** — `host: str = Field(default="0.0.0.0")` — a hard-coded bind address in `WebApiConfig`. Same concern: intentional default but unnamed.

**`config/models.py:262`** — `port: int = Field(default=8126)` — a hard-coded port number with no named constant.

**`config/models.py:265`** — `cors_origins: tuple[str, ...] = Field(default=("http://localhost:3000", "http://localhost:5173"))` — two hard-coded CORS origin URLs embedded in the field default. These look like dev server URLs. They should be named constants.

**`config/defaults.py:11`** — `ENV_FILE_LOCATIONS = ["/config/.env", ".env", "./config/.env"]` and `TOML_FILE_LOCATIONS = ["/config/hassette.toml", "hassette.toml", "./config/hassette.toml"]` — the `/config/` prefix is a Docker-specific path convention. It's correct to have these as named constants, but the `/config/` path appears hardcoded in three places across these two lists without a named constant (`DOCKER_CONFIG_PATH = "/config"`).

**`config/helpers.py:72`** — `docker = Path("/config")` — the Docker config path `/config` appears as a literal here and implicitly also in `defaults.py`. No shared constant.

**`config/helpers.py:90`** — `docker = Path("/data")` — the Docker data path `/data` as a literal.

**`config/helpers.py:109`** — `docker = Path("/apps")` — the Docker apps path `/apps` as a literal.

Three Docker-path literals (`/config`, `/data`, `/apps`) each defined as a bare `Path("...")` in a local variable `docker` within their respective functions, with no shared constants module entry. All three should reference named constants like `DOCKER_CONFIG_DIR`, `DOCKER_DATA_DIR`, `DOCKER_APPS_DIR`.

---

## 10. Formatting Inconsistencies

**`utils/type_utils.py:42`** — Docstring uses triple-quoted block without Args/Returns style but with an in-body description, inconsistent with the Google-style docstrings used elsewhere. The `normalize_for_isinstance` function's docstring is formatted as a freeform block starting with `"""` and indented description, while adjacent functions like `flatten_types` (line 14) have no docstring at all. Inconsistent docstring coverage in the same file.

**`utils/type_utils.py:167-183`** — `normalize_constructible` and `unwrap_annotated` (lines 186-189) have no docstrings, while `normalize_annotation` (line 192) has one. Inconsistent docstring coverage within the same file's utility functions.

**`utils/func_utils.py:93`** — `callable_stable_name`'s docstring format (long bulleted list with dashes) is inconsistent with `callable_name`'s docstring (prose paragraphs). Both document the same class of function but in completely different styles.

**`utils/app_utils.py:462`** — The function `import_module` has a docstring with `Returns:` section and an example as plain text with `->` arrows. The `_module_name_for` function (line 468) uses a `Examples:` block with `->` arrows as inline example text. No Sphinx/Google markup — inconsistent with the rest of the codebase.

**`config/models.py`** — Mix of class-level docstrings as single-line (e.g., `DatabaseConfig`, `WebSocketConfig`) and multi-line with inline markup (e.g., `AppsConfig` with `.. code-block:: toml`). Inconsistent docstring style within the same file.

**`utils/service_utils.py:41`** — `_resolve_deps` is a nested function inside `topological_sort` with a single-line docstring. The outer function has a full Google-style docstring. Inconsistent docstring depth between outer and inner functions.

**`conversion/validation.py:78-80`** — Section divider comment `# ---------------------------------------------------------------------------` with dashes appears twice. These are long horizontal rules in a 262-line file — a visual section separator, which is the same pattern as the banned "section divider comments" (though the project style guide specifically calls out "decorated comment blocks between methods"; these are between top-level functions, so borderline).

**`utils/app_utils.py:62`** — `_find_user_frame` has a non-Google-style docstring:
```
"""
Pick the most useful traceback frame:
1) last frame inside the app's directory
...
"""
```
Numbered list format inside a docstring without Args/Returns sections, while most other docstrings use Google style.

---

## Summary

| Category | Findings |
|---|---|
| Magic Numbers and Strings | 16 |
| Scattered Constants | 6 |
| Ternary Abuse | 1 |
| CSS and Styling Sins | 0 |
| Dead Code | 5 |
| Naming Inconsistencies | 14 |
| Structural Messiness | 11 |
| Import Hygiene | 8 |
| Hard-Coded Environment Values | 9 |
| Formatting Inconsistencies | 8 |
| **Total** | **78** |

Highest-impact cleanup: consolidate the five lazy imports (violating the no-lazy-imports rule) into `TYPE_CHECKING`-guarded imports or resolve the circular dependencies that force them — this affects `annotation_converter.py`, `state_registry.py`, `validation.py`, `type_utils.py`, and `app_utils.py`, and is the only category that violates a hard project invariant.
