# Context: Break the Clean-Win Import Cycles (issue #1079, partial)

## Problem & Motivation
`src/hassette` has runtime import cycles between subpackages, held together by `# lazy-import:` annotations and `TYPE_CHECKING` guards. Because the package graph is not a DAG, `tools/check_module_boundaries.py` can enforce only one rule (no production import of `hassette.test_utils`). Three of these cycles are placement problems, not design problems: a leaf utility and several pure data types physically live in `core` (the top layer) while lower layers reach up to them. This work relocates that misplaced code so three cycles disappear, then adds three boundary RULES so they cannot reappear. It is the "clean wins" subset of #1079 — the hard `core` logic edges are explicitly deferred.

## Visual Artifacts
None.

## Key Decisions
1. **Move `core/await_guard.py` → `utils/await_guard.py`.** It is a pure leaf (imports only `exceptions` + `types.enums`). This retires `api → core` fully. It does NOT retire `bus → core` (bus still imports `core.commands.InvokeHandler`) or `scheduler → core` (SchedulerService) — those are out of scope. Destination is `utils/` (decided over a new `runtime/` package: fewer subpackages, lower reader-load).
2. **Extract web-facing data types from `core` into a NEW `hassette.schemas` package.** Chosen over `models/` (which holds HA entity-state models) to keep response/serialization schemas separate. `schemas` is a pure-data leaf: it may import only `types`, `const`, and `utils`.
3. **Relocate `is_event_type` from `utils/type_utils.py` into `events/`.** Its only `Event` consumer in `utils`; moving it removes `utils → events`, leaving the correct one-directional `events → utils`.
4. **Add exactly three boundary RULES** (`api → core`, `web → core`, `utils → events`). Do NOT add a `bus → core` RULE — that cycle persists this PR and a rule would break the build.
5. **The schemas extraction must preserve serialized output byte-for-byte** (OpenAPI + generated TS types). It is a move, not a redesign.

## Constraints & Anti-Patterns
- **No `from __future__ import annotations`** (project ban — breaks Pydantic/pyright runtime introspection).
- **No lazy function-body imports** except under `TYPE_CHECKING`. Do not paper over a move with a new lazy import — move the symbol to the correct layer instead. This PR removes ZERO existing `# lazy-import:` annotations (all 11 serve out-of-scope cycles); it must add none.
- **`schemas` must import only `types`, `const`, `utils`.** If an extracted type needs anything higher (e.g. a `core` class), the extraction is wrong — surface it, do not add a lazy import.
- **Do not change any serialized shape** during the schemas extraction — field names, types, defaults, Pydantic config preserved exactly (FR#9).
- **Do not touch** `bus → core`, `scheduler → core`, `state_manager → core`, `resources ↔ task_bucket`, `conversion ↔ models` — all out of scope (deferred to a separate ADR).
- **`core/` is touched**, so per CLAUDE.md the final verification must include `uv run nox -s system` and `uv run nox -s e2e`, not just unit/integration.
- **Never run `pytest -n auto`** on this machine (it has frozen the box on the e2e suite). Run heavy suites via the `nox` sessions; let CI handle parallelism.
- **Frontend in worktree:** run `cd frontend && npm install` once before any type generation (worktrees don't share `node_modules/`).

## Design Doc References
- `## Architecture` — the three changes in detail, plus the revised L0–L9 layer DAG and the `Rule(name, applies, forbids, reason)` framework.
- `## Edge Cases` — mixed `app_registry.py` (split snapshots from `AppRegistry`), data types needed by `core` itself, constants embedded in service modules.
- `## Key Constraints` — the hard prohibitions above.
- `## Impact → Changed Files` — file inventory (with a gap-check comment listing consumers beyond the explicit list).
- `## Test Strategy` — existing tests to adapt (import-path updates) and the FR#9/AC#5 schema-diff gate.

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

`applies` receives the bare layer name from `layer_of()` (e.g. `"api"`, `"web"`, `"utils"`) — NOT the dotted `hassette.api`. `forbids` receives the imported module's dotted name.

### Pure leaf utility (the shape `await_guard.py` keeps after moving)

**Source:** `src/hassette/core/await_guard.py` (moving to `utils/`)

```python
from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.types.enums import ForgottenAwaitBehavior
# imports only exceptions + types.enums — nothing that would re-introduce a cycle
```

**DON'T** convert a removed cycle's break into a `TYPE_CHECKING` guard if the symbol is used at runtime — that just relocates the smell. Move the symbol to the correct layer instead.
