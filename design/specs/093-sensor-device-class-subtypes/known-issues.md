# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: StateReader.num_domain_states and __contains__ are now orphaned on StateProxy

Status: resolved — fixed during known issues walkthrough
Run: 58
Source: T06
Reason not fixed now: needs-decision
Observed in: T06 (3 review iterations — code review PASS, integration review WARN all 3 times on this finding)
Affected files:
- src/hassette/types/types.py:280 (`StateReader.num_domain_states`)
- src/hassette/types/types.py:284 (`StateReader.__contains__`)
- src/hassette/core/state_proxy.py:317 (`StateProxy.num_domain_states`)
- src/hassette/core/state_proxy.py:421 (`StateProxy.__contains__`)

Issue:
T06 changed `DomainStates.__len__` and `DomainStates.__contains__` in
`src/hassette/state_manager/state_manager.py` to compute membership by iterating
`yield_domain_states()`/`get_state()` and checking `_validate_if_member` (predicate AND
convertibility), instead of delegating to `StateProxy.num_domain_states()` /
`StateProxy.__contains__()`. That delegation was the only production call site for those two
`StateReader` Protocol members. Verified directly (not just via prior review passes): grepping
`num_domain_states` and `StateReader.__contains__`-style usage across `src/` and `tests/` turns up
zero non-test callers of `StateProxy.num_domain_states` or `entity_id in state_proxy`/`__contains__`
on `StateProxy` outside its own definition. `state_manager.py`'s only remaining proxy calls are
`yield_domain_states()` and `get_state()`. The two Protocol methods and their `StateProxy`
implementations are dead code in production as of this change.

Why deferred:
Fixing this requires an architectural decision that isn't T06's (or spec 093's) to make: whether to
keep `num_domain_states`/`__contains__` on the `StateReader` Protocol and `StateProxy` for
potential future or external `StateReader` implementers (the Protocol's own docstring says it
"describes the four members state-manager consumers call on the state proxy" — that description
is now stale either way), or remove both Protocol members and their `StateProxy` implementations
as dead code. Both files are outside T06's declared scope (design.md bounds T06 to
`state_manager.py` + `exceptions.py`) and outside T07's and T08's `modify:` scope as well — neither
task claims `types/types.py` or `core/state_proxy.py` for write access, only `read:`. This is
purely dead internal framework code with zero callers; it does not affect any running behavior, so
it does not trip the known-issues Severity Gate (no user-visible breakage, no data loss, no
security exposure, no blocked workflow).

Recommended follow-up:
Decide keep-vs-remove for `StateReader.num_domain_states`/`__contains__` and the corresponding
`StateProxy` methods:
- If keeping (e.g., for a documented external-implementer use case): update the `StateReader`
  docstring to stop claiming these are called by state-manager consumers, and add a test or comment
  explaining who is expected to call them.
- If removing: delete both Protocol members from `StateReader` in `src/hassette/types/types.py`,
  delete `StateProxy.num_domain_states` and `StateProxy.__contains__` in
  `src/hassette/core/state_proxy.py`, and update `tests/unit/types/test_service_protocols.py` (which
  asserts `StateProxy` has every `StateReader` member) and
  `tests/unit/state_manager/test_domain_states_statereader.py` /
  `test_domain_states_membership.py` (whose fake `StateReader` implementations currently include
  these two methods) accordingly.

Acceptance criteria:
- A decision is recorded (ADR, issue comment, or code comment) on whether `StateReader.num_domain_states`/`__contains__` are kept or removed.
- If removed: no references to `StateProxy.num_domain_states` or `StateProxy.__contains__` remain in `src/` or `tests/`, and the `StateReader` Protocol no longer declares them.
- If kept: `StateReader`'s docstring and any relevant tests reflect the actual (non-state-manager) caller this is being kept for.

## KI-002: Three new sensor-shape exception classes duplicate `__init__` boilerplate

Status: filed (#1545)
Run: 58
Source: clean-code
Reason not fixed now: behavior-change
Observed in: clean-code review at this branch's HEAD
Affected files:
- src/hassette/exceptions.py:379-447 (`UnableToConvertAnnotatedStateError`, `SensorShapeMismatchError`, `EntityNotInViewError`)

Issue:
The three new exception classes added for FR#12/FR#14/FR#15 share an identical `__init__(entity_id,
device_class, state_class)` shape — the same three-parameter signature and the same three attribute
assignments (`self.entity_id`, `self.device_class`, `self.state_class`), differing only in the
f-string message. A shared base class (e.g. an `EntityShapeError` carrying the boilerplate and a
message-template hook) would collapse the repeated constructor to one definition.

Why deferred:
This is exactly the "restructuring an error hierarchy" case this orchestration run's clean-code
pass is instructed to leave for architectural judgment rather than auto-fix. Design.md's own
"Convention Examples" section (`## Conversion error carrying entity context`) shows
`UnableToConvertStateError`'s per-class `__init__` — full message plus structured attributes,
repeated per class — as the *intended* pattern to follow, not incidental debt; introducing a shared
base now would diverge from a documented design decision without a design review. It also risks
subtle behavior changes for external code doing `isinstance`/`except` on `StateRegistryError`
subclasses if the new base's MRO or attribute-setting order differs from what these three classes
currently do independently. No user-visible breakage, data loss, security exposure, or blocked
workflow — does not trip the known-issues Severity Gate.

Recommended follow-up:
If a fourth entity-shape exception is ever added and the constructor is still identical, revisit
introducing a shared base (e.g. `EntityShapeError(StateRegistryError)` holding `entity_id`,
`device_class`, `state_class`, and a message-template hook per subclass) as a deliberate,
reviewed refactor — not as a byproduct of an unrelated change.

Acceptance criteria:
- A decision is recorded on whether `UnableToConvertAnnotatedStateError`, `SensorShapeMismatchError`,
  and `EntityNotInViewError` should share a common base, and if so, the base is introduced with
  existing behavior (message text, attribute names, exception MRO for external `except` clauses)
  preserved and covered by tests.

## KI-003: `run_pipeline` in codegen is a ~180-line function mixing six responsibilities

Status: filed (#1546)
Run: 58
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review at this branch's HEAD
Affected files:
- codegen/src/hassette_codegen/pipeline.py:64-244 (`run_pipeline`)

Issue:
`run_pipeline` performs domain discovery/rejection, override loading/validation, per-domain state
and entity generation, sensor-constants generation, the FR#17 predicate-freshness drift check,
`__init__.py` generation, and manifest/summary bookkeeping — all in one function, well past the
project's 50-line function guideline (`CLAUDE.md`, File Organization). This predates the current
branch; the branch only inserted a small `sensor_init_py`/`_check_predicate_freshness` block into
the middle of it (~12 lines) and added the new `_check_predicate_freshness` function alongside it.

Why deferred:
The current branch's task is sensor device-class subtypes (spec 093), not a codegen pipeline
refactor. Splitting a 180-line orchestration function with interleaved side effects (ordered
`print()` diagnostics, `generated_files`/`skipped_domains`/`rejections` bookkeeping threaded across
every stage, `check_mode` branching at each step) risks reordering or dropping one of those side
effects — exactly the "could change behavior in subtle ways" class of finding this orchestration
run's clean-code pass is instructed to leave for a dedicated, reviewed pass rather than auto-fix.
No user-visible breakage, data loss, security exposure, or blocked workflow (the pipeline is a dev
tool, not a runtime path) — does not trip the known-issues Severity Gate.

Recommended follow-up:
Decompose `run_pipeline` into named steps (e.g. `_generate_domains(...)`, `_generate_constants(...)`,
`_check_drift_guards(...)`, `_finalize_manifest(...)`) as a standalone refactor, with the existing
codegen test suite (`codegen/tests/`) as the pin proving the split preserves ordering and output.

Acceptance criteria:
- `run_pipeline` is decomposed into functions each under roughly 50 lines, with no change in CLI
  behavior, exit codes, or stderr output ordering verified by the existing `codegen/tests/` suite.

## KI-004: `HA_CORE_PATH` fallback and `sys.path.insert` boilerplate duplicated across 14 codegen test files

Status: filed (#1547)
Run: 58
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review at this branch's HEAD
Affected files:
- codegen/tests/test_constants_and_exports.py:12,23-24
- codegen/tests/test_extractors.py:9,16-17
- codegen/tests/test_ha_source.py, test_integration.py, test_services.py (same `_HA_CORE`/`_HAS_HA_CORE` pattern)
- codegen/tests/test_cli.py, test_desync_docstring.py, test_docstring_builder.py, test_entity_generator.py, test_manifest.py, test_output.py, test_overrides.py, test_pipeline_guards.py, test_rendering.py, test_state_generator.py (same `sys.path.insert` line)

Issue:
`sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))` is copy-pasted verbatim
at the top of all 14 files in `codegen/tests/`, with no comment explaining why the package isn't
importable without it. The two-line `_HA_CORE = Path(os.environ.get("HA_CORE_PATH",
"~/source/core")).expanduser()` / `_HAS_HA_CORE = _HA_CORE.exists()` block (including the
machine-specific `~/source/core` fallback default) is separately duplicated across at least 5 of
those files. Both patterns pre-date this branch — this branch only added new test classes below the
existing boilerplate in `test_constants_and_exports.py` and `test_extractors.py`.

Why deferred:
Only 2-3 of the 14 files with this pattern are touched by the current branch's diff. Deduplicating
just the in-scope files (e.g. into a local `codegen/tests/_ha_core.py` or `conftest.py`) while
leaving the identical pattern in the other 11-12 files would make the touched files diverge from the
established (if debt-laden) convention, which is worse than leaving it consistent — a proper fix
needs to touch all 14 files, which is outside spec 093's scope. No user-visible breakage, data loss,
security exposure, or blocked workflow (test-only, dev-time code) — does not trip the known-issues
Severity Gate.

Recommended follow-up:
As a standalone codegen-test-infra cleanup: add `codegen/tests/conftest.py` (or a small
`codegen/tests/_ha_core.py` module) exporting `HA_CORE`/`HAS_HA_CORE`, migrate all 14 files to
import from it, and evaluate whether a `pythonpath` entry in `codegen/pyproject.toml`'s pytest
config removes the need for the per-file `sys.path.insert` line entirely.

Acceptance criteria:
- `grep -c "sys.path.insert" codegen/tests/*.py` returns 0 (or 1, if consolidated into a
  `conftest.py`) instead of 14.
- `_HA_CORE`/`_HAS_HA_CORE` (or equivalent) is defined once and imported everywhere it's used.
