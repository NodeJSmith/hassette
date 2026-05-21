# Nitpick Audit: Backend Event System

**Scope:** `src/hassette/bus/`, `src/hassette/event_handling/`, `src/hassette/events/`
**Date:** 2026-05-21

---

## 1. Magic Numbers and Strings

**`injection.py:121`** — `callable_short_name(conv, 2)` — the literal `2` is an unexplained depth argument with no named constant or inline comment explaining what it means.

**`rate_limiter.py:128`** — `name="handler:debounce"` — magic task-name string literal defined inline at the call site. Same issue at `duration_timer.py:149` with `name="bus:duration_timer"`. Neither is a constant, and neither appears elsewhere, but the pattern (inline string as a task identity label) is inconsistent: one lives in `rate_limiter.py`, the other in `duration_timer.py`, with no shared registry of task name strings.

**`events/hassette.py:102`** — `event_type="empty"` — bare magic string.

**`events/hassette.py:114`** — `event_type="file_changed"` — bare magic string.

**`events/hassette.py:214`** — `event_type="invocation_completed"` — bare magic string.

**`events/hassette.py:237`** — `event_type="execution_completed"` — bare magic string.

**`events/base.py:30`** — `origin: str = field(default="UNKNOWN", kw_only=True)` — magic origin string `"UNKNOWN"` defined inline. Compare to `events/base.py:110` where `"HASSETTE"` is also defined inline. Neither is a constant.

**`bus/listeners.py:429`** — `source_tier="framework"` — magic string literal. The sibling value `"app"` appears as a default at `listeners.py:58` and `invocation_record.py:32`. All three are repeated string literals for the same logical type (`SourceTier`), with no shared constant.

**`bus/bus.py:322`** — `assert source_tier in ("app", "framework")` — the same two string literals repeated inline in a validation assert, duplicating the values already scattered across `listeners.py` and `invocation_record.py`.

---

## 2. Scattered Constants

**`event_handling/conditions.py:64–65`** — `ARROW = "→"` and `ELLIPSIS_CHAR = "…"` are display-only Unicode characters living in `conditions.py`. `ARROW` is imported and used by `predicates.py`; `ELLIPSIS_CHAR` is only used within `conditions.py`. These are display constants that arguably belong in a shared display/formatting module rather than a conditions module.

**`event_handling/accessors.py:60`** — `DEFAULT_EXCLUDE = ("last_reported", "last_updated", "last_changed", "context")` — a domain-meaningful constant (the HA fields that change on every state update) defined at module level in `accessors.py`, which is reasonable, but it is not exported anywhere and has no visibility beyond the module. If other code ever needs to know which fields are excluded from change detection, there is no canonical place to find this.

**`bus/invocation_record.py:7`** — `SYNTHETIC_ORIGIN = "HASSETTE_SYNTHETIC"` — named constant, good. But the related origin values `"HASSETTE"` (`events/base.py:110`), `"UNKNOWN"` (`events/base.py:30`), `"LOCAL"`, and `"REMOTE"` (typed as `Literal` in `events/base.py:53` and `events/hass/raw.py`) are scattered across three files with no single place that enumerates all valid origin strings.

---

## 3. Ternary Abuse

**(Ternary Abuse): clean**

---

## 4. CSS and Styling Sins

**(CSS and Styling Sins): skipped — Python backend code**

---

## 5. Dead Code

**`event_handling/conditions.py:423`** — `# self.threshold = threshold` — commented-out code on a single line inside `Comparison.__init__`. One line, so technically below the "2+ consecutive lines" threshold, but it is clearly a leftover from a rename (`threshold` → `compare_to`) and communicates nothing useful.

**`event_handling/predicates.py:498`** — `from hassette.types import ChangeType` — lazy import inside `ServiceDataWhere.__post_init__`. `ChangeType` is already imported at the top of the file at line 55 (`from hassette.types import ChangeType, ComparisonCondition, EventT`) and again inside the `TYPE_CHECKING` block at line 76. The inline import in `__post_init__` is redundant dead weight — it re-imports a name that is already available at module scope.

**`bus/listeners.py:298`** — `Total: 10 fields (AC#2).` — internal audit-tracking note left in a production docstring. `AC#2` is a meaningless reference to an external artifact (an audit checklist item). This is not a ticket reference visible to any reader of the codebase.

**`event_handling/dependencies.py:77`** — `from hassette import RawStateChangeEvent  # noqa: F401` — import suppressed by a `noqa` comment inside a `TYPE_CHECKING` block. The `# noqa: F401` on a `TYPE_CHECKING`-guarded import is suspicious: linters do not flag unused imports inside `TYPE_CHECKING` blocks by default. The `noqa` suppression is either unnecessary or masking something that should be investigated.

---

## 6. Naming Inconsistencies

**`bus/injection.py:97`** — `_extract_and_convert_parameter` has a leading underscore, making it a "private" method. The project rule (per `coding-style.md`) is to avoid underscore prefixes unless the method is genuinely unsafe to call out of sequence. `_extract_and_convert_parameter` is called once from `inject_parameters` and is straightforwardly testable in isolation. No invariant requires it to be private.

**`bus/metrics.py:53`** — `_record_timing` has a leading underscore while the other three recording methods (`record_success`, `record_error`, `record_di_failure`, `record_cancelled`) do not. The project rule is no underscore prefixes. `_record_timing` is not unsafe — it is simply an internal helper — but the inconsistency within the same class is the compounding problem: four public `record_*` methods and one private `_record_timing`.

**`bus/rate_limiter.py:63`** — `_clear_debounce_ref` has a leading underscore. It is a done-callback passed to `task.add_done_callback` and is externally callable. No invariant requires it to be private.

**`bus/rate_limiter.py:97` and `132`** — `_debounced_call` and `_throttled_call` have leading underscores while `call` does not. Within the same class, three methods are underscore-prefixed and one (`call`) is not. The underscore-prefixed methods are called only from `call`, but they are not unsafe to call directly.

**`bus/listeners.py:113–114`** — Fields `_async_handler` and `_injector` have leading underscores in a `@dataclass(slots=True)`. The docstrings on both explicitly say "Private — not part of the public API." The project rule prohibits this justification. `_app_error_handler_resolver` at line 125 has the same pattern.

**`event_handling/extraction.py:11`** — function `extract_from_annotated` returns `None | tuple[...]`. Parameter name `annotation` is fine but the local variable `result` at line 15 is generic; `type_and_details` would be more precise. Same issue at line 98 where another variable named `result` refers to a `(type, AnnotationDetails)` pair.

**`event_handling/accessors.py:118`, `129`, `154`, `165`, `190`, `199`** — local variable named `data` inside six different inner functions. The name `data` is used to refer to `event.payload.data` (a `RawStateChangePayload`). Given the surrounding type, `payload_data` or `state_data` would communicate more.

**`event_handling/conditions.py:412–413`** — parameter `value` in `Comparison.__init__` refers to the comparison target (what you compare against), but the stored field is `compare_to`. The parameter name `value` is generic and conflicts with the `value` parameter name used in `__call__` methods throughout the file (where it means "the extracted event value being tested"). Two different concepts sharing the same name in the same class.

---

## 7. Structural Messiness

**`bus/bus.py`** — 1122 lines. Exceeds the 800-line hard ceiling. The file contains the `Bus` class (lines 129–1058) plus two module-level builder functions (`build_state_preds`, `build_attr_preds`). The `Bus` class itself is ~930 lines. Even discounting docstrings, the class is substantially oversized.

**`bus/bus.py:181–207` and `bus/bus.py:370–382`** — identical collision-detection block duplicated verbatim. The code at lines 197–206 and lines 372–381 is character-for-character the same: the `once` guard, the `_listener_natural_key` call, the `key_str` fallback, the `ValueError` message, and the `_registered_keys.add`. A comment at line 370 even acknowledges it: "same guard as add_listener." This should be extracted into a private method.

**`event_handling/predicates.py`** — 638 lines. Exceeds the 800-line soft ceiling and approaches it uncomfortably. The file contains predicate classes, combinator helpers, `compare_value`, `ensure_tuple`, `is_predicate_collection`, `normalize_where`, and `summarize_top_level` — several distinct responsibilities.

**`bus/injection.py:43–45`** — `validate_di_signature(signature)` is called explicitly at line 44, then `extract_from_signature(signature)` is called at line 45 — which itself calls `validate_di_signature` internally (extraction.py:87). The signature is validated twice on every `ParameterInjector` construction. The double-call is silent and causes no bug, but it is structurally redundant and the duplication is invisible from the call site.

**`bus/rate_limiter.py:113–120`** — inner function `delayed_call` has no return type annotation (`async def delayed_call():`), while `delayed_fire` in `duration_timer.py:131` does (`async def delayed_fire() -> None:`). Inconsistent annotation practice across the two parallel implementations.

**`events/hass/hass.py:214–288`** — `create_event_from_hass` is 74 lines. Exceeds the 50-line function limit. The body is a `match` statement with 10 arms, each constructing a typed event object. It does one logical thing, but the sheer size puts it over the limit.

---

## 8. Import Hygiene

**`event_handling/predicates.py:498`** — lazy import `from hassette.types import ChangeType` inside `ServiceDataWhere.__post_init__`. The name is already imported at module scope (line 55). This violates the no-lazy-imports rule. (Also flagged under Dead Code for being redundant.)

**`event_handling/accessors.py:52–53`** — `MISSING_VALUE` is imported from `hassette.const` while `FalseySentinel` is imported from `hassette.const.misc` on the very next line. These two symbols come from the same sub-module; importing them from different paths on adjacent lines is inconsistent.

**`event_handling/dependencies.py:68`** — imports `MISSING_VALUE` and `FalseySentinel` from `hassette.const.misc` directly, while `predicates.py` and `conditions.py` import `MISSING_VALUE` from `hassette.const` (the re-export). Three files in the same package import the same symbol via three different paths.

**`events/hass/hass.py:217`** — `from hassette.events import Event` inside `create_event_from_hass` body, with the comment "avoid circular import." This is a lazy import. If it is genuinely required to break a circular import, the correct pattern is a `TYPE_CHECKING` guard or restructuring the import graph — not an inline import inside a function body that runs at call time.

**`bus/extraction.py:1–2`** — `import inspect` and `from inspect import Signature` both appear in the import block. `Signature` is imported directly from `inspect`, making `import inspect` on line 1 redundant for any code that would use `inspect.Signature` — but the module still uses `inspect.Parameter` directly (lines 49, 53, 64, 68, 74), so `import inspect` must stay. The double-import from the same stdlib module on consecutive lines (`import inspect` / `from inspect import Signature`) is a minor inconsistency, but the right pattern is to pick one form and be consistent.

---

## 9. Hard-Coded Environment Values

**(Hard-Coded Environment Values): clean**

---

## 10. Formatting Inconsistencies

**`event_handling/accessors.py:79–81` and `215–217` and `314–316`** — section divider comments use short dashes (`# --------------------------`).

**`event_handling/dependencies.py:133–135`, `154–156`, `224–226`** — section divider comments use long equals signs (`# ======================================================================================`).

Both styles appear in the same package (`event_handling/`) in adjacent files. `conditions.py` and `predicates.py` have no section dividers at all. The inconsistency within a single package is a formatting sin.

**`events/hass/hass.py:27`** — `service_data: dict[str, Any] = field(default_factory=dict)` and `service_call_id: str | None = None  # have never seen this but the docs say it exists` — a casual conversational comment (`# have never seen this but the docs say it exists`) in production code. The linked URL comment on line 85 (`# https://www.home-assistant.io/docs/configuration/events/#automation_triggered`) is a different style: a raw URL with no explanatory text. Inconsistent comment styles within the same file.

---

## Summary

| Category | Findings |
|---|---|
| Magic Numbers and Strings | 9 |
| Scattered Constants | 3 |
| Ternary Abuse | 0 |
| CSS and Styling Sins | 0 (skipped) |
| Dead Code | 4 |
| Naming Inconsistencies | 9 |
| Structural Messiness | 6 |
| Import Hygiene | 5 |
| Hard-Coded Environment Values | 0 |
| Formatting Inconsistencies | 3 |
| **Total** | **39** |

Highest-impact cleanup: **Naming Inconsistencies** — nine findings across five files, all driven by the same root cause (underscore-prefixed "private" methods and fields on dataclasses and service classes), directly contradict the project's own coding-style rule and will proliferate as contributors copy the pattern.
