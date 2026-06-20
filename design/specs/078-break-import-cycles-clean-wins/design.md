# Design: Break the Clean-Win Import Cycles (issue #1079, partial)

**Date:** 2026-06-19
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-06-19-break-import-cycles/research.md

## Problem

`src/hassette` has runtime import cycles between subpackages. They are held together today by `# lazy-import:` annotations and `TYPE_CHECKING` guards — workarounds that hide real import-order coupling, break `patch()`-based mocking at those sites, and defer import errors to runtime. Because the package graph is not a DAG, `tools/check_module_boundaries.py` can enforce only a single rule (production code must not import `hassette.test_utils`); the intended layering cannot be mechanically checked, so it erodes silently in an AI-authored codebase.

Three of the cycles are not design problems — they are *placement* problems. A leaf utility and several pure data types physically live in `core` (the top layer) while lower layers reach up to them. Fixing those means moving code to where it belongs, which makes the layering match the mental model and adds zero abstraction. This design covers exactly those three clean wins.

The research brief (`design/research/2026-06-19-break-import-cycles/research.md`) traced every claimed cycle to file:line and corrected two points the issue overstated: the edit surface is ~15–30 files, not ~210 (210 is the linter's *scan* scope), and moving `await_guard.py` retires `api→core` fully but **not** `bus→core` (bus imports `core.commands.InvokeHandler` separately).

## Goals

- Remove the `api → core`, `web → core`, and `utils → events` runtime import cycles by relocating misplaced code — no new abstraction layers.
- Add three boundary RULES to `tools/check_module_boundaries.py` that forbid those three now-clean upward edges, so they cannot reappear.
- Keep the moves clean — introduce no new `# lazy-import:` annotations and no `TYPE_CHECKING` guard used to dodge a runtime import. (The three in-scope cycles are held by top-level runtime imports, so **no existing `# lazy-import:` annotations are removed by this PR** — all 11 serve out-of-scope cycles.)
- Record the revised target layer DAG (with `resources` placed below the api/bus/scheduler service group) so it can feed issue #633.

## Non-Goals

- **`bus → core` (InvokeHandler).** `core/commands.py:InvokeHandler` depends on `bus.Listener` and `scheduler.ScheduledJob`, so it cannot move below them. Relocating it is the brief's medium-effort "cycle 4" and is deferred.
- **`scheduler → core` (SchedulerService)** and **`state_manager → core` (StateProxy)** import real `core` logic, not data. These need a relocate-vs-protocol-inversion decision (an ADR weighing reader-load) and are explicitly out of scope.
- **`resources ↔ task_bucket`** and **`conversion ↔ models`** — already broken via lazy imports; converting them to structural breaks is deferred.
- **Full graph-level cycle detection / `import-linter` adoption.** This PR adds three per-edge RULES in the existing hand-written framework only. Whole-graph DAG enforcement is #633's job.

## User Scenarios

The "users" of this change are the framework maintainer and CI. There is no end-user-visible behavior change.

### Maintainer: framework developer
- **Goal:** keep the subpackage layering correct as the codebase grows
- **Context:** editing `src/hassette` and relying on CI to catch architectural drift

#### A new upward edge is introduced by accident

1. **A developer (human or AI) adds `from hassette.core import X` inside `api/` or `web/`.**
   - Sees: the local edit looks fine; pyright passes.
   - Then: `tools/check_module_boundaries.py` fails in CI (`lint.yml`) naming the file, line, and forbidden module.
2. **The developer reads the failure and either moves the symbol down or routes it through the allowed direction.**
   - Sees: a clear boundary-violation message with the offending import.
   - Then: the layering invariant holds without anyone remembering to check it.

### CI: boundary checker

#### The checker runs on every push

1. **`check_module_boundaries.py` walks `src/hassette`, resolving runtime (non-`TYPE_CHECKING`) imports.**
   - Then: it applies each RULE's `applies`/`forbids` predicate and exits non-zero on any violation, exactly as it does today for the `test_utils` rule.

## Functional Requirements

- **FR#1** `guard_await` (and the rest of `await_guard.py`) is importable from its new location under `hassette.utils`, and `bus`, `api`, and `scheduler` import it from there.
- **FR#2** After the move, `api/` contains no runtime (non-`TYPE_CHECKING`) import of any `hassette.core` module.
- **FR#3** The web-facing data types currently in `core` (`domain_models`, `telemetry_models`, the `app_registry` snapshot dataclasses, `bus_service.LiveCounts`, and the telemetry query-limit constants) are importable from a new `hassette.schemas` package.
- **FR#4** After the extraction, `web/` contains no runtime import of any `hassette.core` module (`TYPE_CHECKING` imports of core service classes may remain).
- **FR#5** `is_event_type` is importable from `hassette.events`, and every caller (`bus/extraction.py` in `src/`, plus `tests/integration/test_type_detection.py`) imports it from there.
- **FR#6** After the move, `utils/` contains no import of `hassette.events`.
- **FR#7** `tools/check_module_boundaries.py` forbids, as runtime imports: `api → hassette.core.*`, `web → hassette.core.*`, and `utils → hassette.events.*`.
- **FR#8** The structural moves introduce no new `# lazy-import:` annotation and no `TYPE_CHECKING` guard used to dodge a runtime import; `tools/check_lazy_imports.py` passes.
- **FR#9** The OpenAPI schema and generated frontend types (`openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`) are byte-identical before and after the `schemas` extraction.

## Edge Cases

- **A web data type is needed by `core` itself at runtime.** Several are (e.g. `bus_service.LiveCounts` is produced by `core`). Moving the *type* to `schemas` (a lower layer) lets both `core` and `web` import it downward — no cycle. The type must not carry behavior that depends on `core`.
- **`app_registry.py` is a mixed module** — four snapshot dataclasses plus the `AppRegistry` logic class. Only the snapshot dataclasses move; `AppRegistry` stays in `core`. `core/app_registry.py` then imports the snapshots from `schemas` (downward).
- **A moved data type pulls a `core` import with it.** The snapshot dataclasses currently use `utils.exception_utils.get_traceback_string` (already a low leaf) and `types.enums` — both below `schemas`, so the move is clean. Any field typed against a `core` class would block the move and must be surfaced, not worked around.
- **The telemetry query constants live inside a service module** (`core/telemetry/query_service.py`). Moving only the two constants (`DEFAULT_QUERY_LIMIT`, `DEFAULT_SPARKLINE_BUCKETS`) to `schemas` (or `types`) leaves the service logic in place; `query_service.py` imports them back downward.
- **A new cycle is created by the move itself.** `schemas` must import only `types`, `const`, and `utils`. If any extracted type needs something higher, the extraction is wrong — fail loudly rather than add a lazy import.
- **`bus → core` survives this PR.** No RULE forbidding `bus → core` may be added; doing so would break the build on the still-present `InvokeHandler` import.

## Acceptance Criteria

- **AC#1** `uv run pyright` passes with zero new errors after all moves.
- **AC#2** The full unit + integration suite passes (`uv run nox -s tests`), and — because `core/` and `resources/` boundaries are touched — the system and e2e suites pass (`uv run nox -s system`, `uv run nox -s e2e`).
- **AC#3** `tools/check_module_boundaries.py` exits non-zero when a deliberately-added `from hassette.core import ...` is inserted into an `api/`, `web/`, or (for events) `utils/` file, and exits zero on the clean tree. (Verifiable via a throwaway edit.)
- **AC#4** `tools/check_lazy_imports.py` passes. The `# lazy-import:` annotation count is **unchanged** (the three in-scope cycles are held by top-level runtime imports, not annotations, so this PR removes none — expected delta: zero).
- **AC#5** `uv run python scripts/export_schemas.py --types` produces no diff in `openapi.json`, `ws-schema.json`, `generated-types.ts`, or `ws-types.ts` (maps to FR#9). The pre-push schema-freshness check (`tools/check_schemas_fresh.py`) passes.
- **AC#6** `grep -rn "from hassette.core" src/hassette/api src/hassette/web` returns only `TYPE_CHECKING`-guarded lines (maps to FR#2, FR#4).
- **AC#7** The revised layer DAG is recorded in this design doc and referenced from a comment or note that issue #633 can consume.

## Key Constraints

- **No `from __future__ import annotations`** (project ban — breaks Pydantic/pyright runtime introspection). Cycle breaks must be real structural moves, not stringized annotations.
- **No lazy function-body imports** except under `TYPE_CHECKING`. The goal is to *remove* the lazy imports tied to these cycles, not add new ones.
- **`schemas` must be a pure-data leaf package** — it may import only `types`, `const`, and `utils`. No `core`, no service logic. If a "data type" needs behavior, it does not belong in `schemas`.
- **The `schemas` extraction must not change any serialized shape.** Field names, types, defaults, and Pydantic config must be preserved exactly so the OpenAPI/TS output is identical (FR#9). This is a move, not a redesign.
- **Do not add a `bus → core` RULE** — `bus` legitimately still imports `core` this PR (InvokeHandler).

## Dependencies and Assumptions

- Depends on `scripts/export_schemas.py` and the frontend type-generation pipeline (`scripts/generate-ws-types.cjs`) for verifying FR#9. The worktree needs `cd frontend && npm install` once before running type generation (worktrees don't share `node_modules/`).
- Assumes `tools/check_module_boundaries.py`'s existing `Rule(applies, forbids)` framework, `layer_of`/`package_of` helpers, and `TYPE_CHECKING` exemption (`type_checking_ranges`) are sufficient — confirmed in reconnaissance; no framework changes needed beyond appending RULES.
- Independent of issue #633. #633's DAG/cycle checks are blocked *by* cycle-breaking work like this, not the reverse; the shipped `test_utils` rule proves enforcement can land without cycle-breaking.

## Architecture

### The target layer DAG (revised from #633)

```
L0  const, types                         leaves; no hassette imports
L1  models                               -> types, const
L2  config                               -> types, const, models
L3  utils, events, conversion,           -> L0-L2
    event_handling, schemas              utils -> events removed (is_event_type moves to events)
                                         schemas -> types, const, utils only
L4  resources                            -> L0-L3; shared base, BELOW the service group
L5  api, bus, scheduler, state_manager,  -> L0-L4, may use resources; not each other, not core
    task_bucket
L6  core                                 -> all below
L7  app                                  -> all below + core
L8  web, cli                             -> all below; web is launched by core's WebApiService
L9  test_utils                           may import anything; production must not import it
```

Differences from #633's proposed map, to feed back: `resources` is pulled out into its own L4 below the service group (the code demands it — `api/bus/scheduler/state_manager/task_bucket` all import `resources`); `schemas` is added at L3; `utils ↔ events` is resolved to a one-directional `events → utils` edge.

`web` sits at L8 but is *launched* by `core/web_api_service.py` (a `core → web` edge). That is fine as a DAG: `web` must not import `core` at runtime (the rule this PR adds), and `core`'s launcher imports `web` downward-in-startup-order. No cycle.

### Change 1 — move `await_guard.py` to `utils/` (retires `api → core`)

`src/hassette/core/await_guard.py` is a 194-line pure leaf: it imports only `hassette.exceptions` and `hassette.types.enums`. Three sites reach up into `core` for `guard_await`:
- `bus/bus.py:101`, `api/api.py:173`, `scheduler/scheduler.py:74`.

Move the file to `src/hassette/utils/await_guard.py` and update those three import lines. `utils` (L3) sits below all three importers, so the edges become downward.

Effect on each cycle:
- **`api → core`: fully retired.** `guard_await` was `api`'s only runtime `core` import (`api.py:214`'s `ApiResource` is `TYPE_CHECKING`).
- **`bus → core`: partially retired** — the `guard_await` edge is gone, but `bus/invocation.py:10` still imports `core.commands.InvokeHandler`. Cycle persists (out of scope).
- **`scheduler → core`: partially retired** — `scheduler.py:75` still imports `SchedulerService`. Cycle persists (out of scope).

### Change 2 — extract web data types to a new `schemas/` package (retires `web → core`)

Create `src/hassette/schemas/`. Move the following *data types* out of `core` into it, preserving every field exactly:

| Symbol(s) | From | Notes |
|---|---|---|
| `domain_models` data classes (`SystemStatus`, `AppStatusChangedData`, `ConnectivityData`, `ServiceStatusData`, `StateChangedData`) | `core/domain_models.py` | imports nothing internal — clean move |
| `telemetry_models` (`ListenerSummary`, `JobSummary`, and the rest) | `core/telemetry_models.py` | imports only `types.enums` + `types.types` — clean move |
| `AppInstanceInfo`, `AppStatusSnapshot`, `AppManifestInfo`, `AppFullSnapshot` | `core/app_registry.py` | **split**: snapshot dataclasses move; `AppRegistry` class stays in `core` and imports them downward |
| `LiveCounts` | `core/bus_service.py` | **extract** the dataclass from the service module; `BusService` imports it back downward |
| `DEFAULT_QUERY_LIMIT`, `DEFAULT_SPARKLINE_BUCKETS` | `core/telemetry/query_service.py` | **extract** the two constants; the service imports them back downward |

Update the `web` importers to point at `schemas`:
- `web/mappers.py:18-21`, `web/models.py:7`, `web/routes/scheduler.py:10`, `web/routes/telemetry.py:15-16`, `web/utils.py:6`.

After this, `web`'s only `core` references are the `TYPE_CHECKING` service-class imports (`web/dependencies.py`, `web/routes/executions.py`, `web/telemetry_helpers.py`) — allowed. `core → web` (`web_api_service.py:16`) is untouched and one-directional.

`schemas` imports only `types`, `const`, and `utils` (`AppFullSnapshot` et al. use `utils.exception_utils.get_traceback_string`, a low leaf) — no cycle.

### Change 3 — relocate `is_event_type` to `events/` (retires `utils → events`)

`utils/type_utils.py:10` imports `events.Event` solely for the `issubclass` check inside `is_event_type` (`type_utils.py:240-263`). The `Event` base lives in `events/base.py`. `is_event_type` has one `src/` caller (`bus/extraction.py`) and is exercised directly by `tests/integration/test_type_detection.py` — both must be repointed.

Move `is_event_type` from `utils/type_utils.py` into `events/` (alongside the `Event` base, or a small `events/type_checks.py`). Update `bus/extraction.py:7` and the `test_type_detection.py` import to import it from `events`. Drop the now-unused `from hassette.events import Event` from `type_utils.py`.

Effect: `utils → events` removed. `events → utils` (`events/hassette.py:7` → `get_traceback_string`) remains and is correct (`utils` below `events`).

### Change 4 — add three boundary RULES

`tools/check_module_boundaries.py` already has the machinery: a `Rule(name, applies, forbids, reason)` dataclass, `layer_of`/`package_of` helpers, relative-import resolution, and a `TYPE_CHECKING` exemption (`type_checking_ranges`, lines 81-98). `applies` receives the source file's **layer** (the bare subpackage name from `layer_of()`, e.g. `"api"` — not the dotted `hassette.api`); `forbids` receives the imported module's dotted name. Append three `Rule` entries to `RULES`, each with all four fields:

1. `applies=lambda layer: layer == "api"`; `forbids`: module is `hassette.core` or starts with `hassette.core.`.
2. `applies=lambda layer: layer == "web"`; `forbids`: module is/startswith `hassette.core.`.
3. `applies=lambda layer: layer == "utils"`; `forbids`: module is/startswith `hassette.events.`.

Do **not** add rules for `bus`, `scheduler`, or `state_manager` → `core` — those cycles persist this PR.

## Replacement Targets

**No `# lazy-import:` annotation is removed by this PR.** The three in-scope cycles are held by top-level *runtime* imports, not lazy annotations — all 11 annotated sites (`resources↔task_bucket`, `conversion↔models`, the `app` chains, `__main__`, the `validation` load-order note) serve out-of-scope cycles and stay untouched. The "replacement" here is purely the structural relocation of misplaced symbols (next paragraph); the lazy-import regime is unaffected.

`core/domain_models.py`, `core/telemetry_models.py`, and the snapshot portion of `core/app_registry.py` are replaced by their `hassette.schemas` equivalents — old import paths are migrated, not left as re-export shims (project rule: migrate callers then delete legacy APIs).

## Convention Examples

### Module-boundary Rule (the pattern Change 4 extends)

**Source:** `tools/check_module_boundaries.py`

```python
@dataclass(frozen=True)
class Rule:
    """A forbidden-import boundary.

    ``applies`` decides whether the rule governs a source file's layer; ``forbids``
    decides whether an imported ``hassette.*`` module name violates it.
    """
    name: str
    applies: Callable[[str], bool]
    forbids: Callable[[str], bool]
    reason: str  # required — no default; every new Rule must supply it


RULES: list[Rule] = [
    Rule(
        name="test_utils-isolation",
        applies=lambda layer: layer != "test_utils",
        forbids=lambda module: module == "hassette.test_utils"
        or module.startswith("hassette.test_utils."),
        reason="production code must not import test helpers from hassette.test_utils",
    ),
]
```

### Pure leaf utility (the shape `await_guard.py` keeps after moving)

**Source:** `src/hassette/core/await_guard.py` (moving to `utils/`)

```python
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.types.enums import ForgottenAwaitBehavior
# imports only exceptions + types.enums — nothing that would re-introduce a cycle
```

### Lazy-import annotation (what gets removed where tied to these cycles)

**Source:** `src/hassette/resources/base.py:145` (example of the annotation form — this specific one is OUT of scope; it breaks `resources↔task_bucket`)

```python
# lazy-import: <reason the import is deferred to break a cycle>
```

**DON'T** convert a removed cycle's break into a `TYPE_CHECKING` guard if the symbol is used at runtime — that just relocates the smell. Move the symbol to the correct layer instead.

## Alternatives Considered

- **Do nothing (brief's Option C).** Keep the `# lazy-import:` regime as the boundary mechanism. Rejected: it leaves new *upward peer* edges (`api → bus`, etc.) uncaught — the erosion #633 most wants to prevent — and these three fixes are cheap pure relocations with no abstraction cost, so the do-nothing case is weak *for this subset*. (Option C remains defensible for the hard `core` edges, which is why those are deferred, not done.)
- **Full refactor now (brief's Option A).** Also break `bus→core` (InvokeHandler), `scheduler→core`, `state_manager→core` and turn on whole-graph cycle detection. Rejected for this PR: the last two need an ADR (relocate vs protocol inversion, a reader-load tradeoff), and `import-linter`/graph enforcement is #633's scope. Bundling them would block the clean wins behind a design decision.
- **Put the web data types in `models/` instead of a new `schemas/`.** Rejected by the user during discovery: `models/` holds HA entity-state models; mixing response/serialization schemas there muddies it. A dedicated `schemas` layer keeps the separation clear.
- **Move `await_guard.py` to a new `runtime/` package.** Rejected by the user during discovery in favor of the existing `utils/` — fewer subpackages, lower reader-load; `await_guard` is a leaf helper and `utils` is its natural home.
- **Also move `InvokeHandler` to make `bus→core` clean.** Rejected: `InvokeHandler` depends on `bus.Listener` and `scheduler.ScheduledJob`, so it cannot sit below them — it is not a clean downward move, and forcing it would expand scope into the brief's medium-effort cycle 4.

## Test Strategy

### Existing Tests to Adapt
- Any test importing the moved symbols by their old paths will break and must be updated to the new paths. Likely sites: tests referencing `hassette.core.domain_models`, `hassette.core.telemetry_models`, `hassette.core.app_registry` snapshots, `hassette.core.await_guard`, `LiveCounts`, or `is_event_type`. The implementer greps `tests/` for each moved symbol and updates imports. The forgotten-await tests under the `071-forgotten-await-detection` spec are the most likely `await_guard` consumers — adapt their import paths, not their assertions.
- No assertion logic should change — these are relocations, so behavior is identical.

### New Test Coverage
- **FR#7 / AC#3** — a test (or a documented manual check) that `check_module_boundaries.py` rejects a planted `from hassette.core import ...` in `api/` and `web/`, and a planted `from hassette.events import ...` in `utils/`. If `tools/` has an existing test harness, add cases there; otherwise the AC#3 throwaway-edit check covers it.
- **FR#9 / AC#5** — schema-freshness is the critical new guard: run `scripts/export_schemas.py --types` and assert no diff. This is the highest-risk part of the change (the `web → core` extraction).

### Tests to Remove
No tests to remove — nothing is deleted, only moved.

## Documentation Updates

- **`tools/check_module_boundaries.py` module docstring** (lines 13-19) — update the note that says the full DAG "are NOT enforced here ... tracked in #1079" to reflect that `api→core`, `web→core`, and `utils→events` are now enforced, with the rest still pending.
- **`design/research/2026-06-19-break-import-cycles/research.md`** — no edit needed; this design supersedes its Option B section by reference.
- **Issue #633** — post the revised L0-L9 layer map (the `resources`-below-services and `schemas`-at-L3 corrections) as a comment so the enforcement issue inherits the accurate map (AC#7).
- **No docs-site (`docs/pages/`) changes** — this is internal framework plumbing with no user-facing API surface; the `design-completeness.md` docs trigger does not fire.
- **No `CHANGELOG.md` edit** (release-please owns it). Commit as `refactor:` so it surfaces appropriately, or `chore:` if judged internal-only — `refactor` is recommended since the package layout changes.

## Impact

### Changed Files

<!-- Gap check 2026-06-19: consumers beyond the explicit list, all included in tasks —
  core/runtime_query_service.py (domain_models + snapshots) → T03;
  core/app_handler.py (AppStatusSnapshot) → T03;
  test_utils/web_helpers.py + web_mocks.py (snapshots) → T03;
  4 await_guard/RegistrationHandle tests → T01; ~8 domain_models/app_registry/LiveCounts tests → T03;
  ws payload models feed ws-schema.json → FR#9 gate in T03.
  Correction: DEFAULT_QUERY_LIMIT/DEFAULT_SPARKLINE_BUCKETS are defined in core/telemetry/helpers.py:16,28
  (query_service.py only re-exports them) → extract from helpers.py, not query_service.py. -->

Cross-cutting / higher-risk first:
- **create** `src/hassette/schemas/__init__.py` (+ module files) — new pure-data package for web-facing schemas.
- **modify** `tools/check_module_boundaries.py` — append three RULES; update docstring.
- **modify** `src/hassette/core/bus_service.py` — extract `LiveCounts` to `schemas`, import it back.
- **modify** `src/hassette/core/telemetry/query_service.py` — extract the two query constants to `schemas`, import back.
- **modify** `src/hassette/core/app_registry.py` — move snapshot dataclasses to `schemas`; `AppRegistry` imports them.
- **delete/move** `src/hassette/core/domain_models.py` → `src/hassette/schemas/` (migrate, no shim).
- **delete/move** `src/hassette/core/telemetry_models.py` → `src/hassette/schemas/` (migrate, no shim).
- **move** `src/hassette/core/await_guard.py` → `src/hassette/utils/await_guard.py`.
- **modify** `src/hassette/utils/type_utils.py` — remove `is_event_type` and the `events` import.
- **create/modify** `src/hassette/events/` — add `is_event_type`.
- **modify** importers: `src/hassette/bus/bus.py`, `src/hassette/api/api.py`, `src/hassette/scheduler/scheduler.py` (await_guard path); `src/hassette/bus/extraction.py` (is_event_type path); `src/hassette/web/mappers.py`, `web/models.py`, `web/routes/scheduler.py`, `web/routes/telemetry.py`, `web/utils.py` (schemas paths).
- **modify** affected test files — import-path updates only.

### Behavioral Invariants
- No runtime behavior changes. Every moved symbol keeps identical semantics; serialized output (OpenAPI/TS types) is byte-identical (FR#9).
- `bus → core`, `scheduler → core`, `state_manager → core` continue to work unchanged — they are intentionally not touched.
- `core → web` startup launch (`web_api_service.py`) continues to work.

### Blast Radius
- Internal to `src/hassette`. No public app-author API changes (`schemas` is an internal package; users import from `hassette.models`/`hassette.states`, not these web types).
- The frontend type-generation pipeline is in the blast radius via FR#9 — a botched move would ripple into `generated-types.ts`. AC#5 guards it.

## Open Questions

None. (The three placement decisions — `await_guard`→`utils/`, web types→new `schemas/`, add the three clean RULES — were resolved during discovery. The hard `core` edges are explicitly deferred to a separate ADR, not left open here.)
