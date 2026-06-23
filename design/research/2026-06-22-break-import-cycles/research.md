---
proposal: "Break the remaining runtime import cycles between src/hassette subpackages (core↔scheduler, core↔state_manager) so check_module_boundaries.py can enforce a full layer DAG and the cycle-breaking lazy imports can retire."
date: 2026-06-22
status: Draft
flexibility: Decided
motivation: "Make the intended layering mechanically checkable (enables #633 DAG enforcement) and retire the # lazy-import: workarounds that paper over cycles."
constraints: "hassette repo (async Python 3.11+, Pydantic, pyright strict). No `from __future__ import annotations`. Runtime function-body imports banned except as annotated cycle-breaks; TYPE_CHECKING imports allowed."
non-goals: "Adopting pytest-archon; rewriting unrelated coupling; changing public app-author API."
depth: deep
---

# Research Brief: Break Remaining Subpackage Import Cycles to Enable a Module-Boundary DAG (#1079)

**Initiated by**: GitHub issue #1079 — break the runtime import cycles between `src/hassette` subpackages so `tools/check_module_boundaries.py` can grow from per-edge rules to a full architectural layer DAG (the enforcement work tracked in #633), and so the `# lazy-import:` annotations that mark cycle-breaks can be removed.

## Context

### What prompted this

`tools/check_module_boundaries.py` is an AST-based CI guard that forbids upward/peer imports between hassette subpackages, exempting `TYPE_CHECKING`-guarded imports. The full layer DAG (#633) cannot be enforced while the runtime subpackage graph contains cycles. #1079 is the refactoring that removes those cycles; #633 is the enforcement it unblocks.

**Critical reframing — the issue is mostly already done.** Issue #1079 was filed against an older codebase state. Since then, two refactors have landed that resolved most of the cycles it enumerates:

- **PR #1097** ("break three import cycles and enforce module boundaries") — moved `await_guard` down to `hassette.utils.await_guard` (verified: `scheduler/scheduler.py:78` now imports `from hassette.utils.await_guard import guard_await`), extracted web-facing data types into a new `hassette.schemas` package, and straightened `utils ↔ events`. Landed the `api-no-core`, `utils-no-events`, and `web-no-core` rules.
- **PR #1103** ("break the bus→core→bus runtime import cycle", spec 080) — moved `InvokeHandler`/`ExecuteJob` to a root-level leaf `hassette/commands.py` and demoted the `bus`/`scheduler`/`events` field-type imports to `TYPE_CHECKING`. Landed the `bus-no-core` rule. Verified: `scheduler_service.py:13` now imports `from hassette.commands import ExecuteJob`.

I ran both checkers against the current tree: **both pass clean.** `check_module_boundaries.py` reports "no module-boundary violations across 5 import rule(s)"; `check_lazy_imports.py` reports "no un-annotated lazy imports". (Confidence: **Direct** — fresh tool output.)

This means the brief's job is narrower and sharper than the issue text implies: enumerate what *actually remains*, and make the ADR-ready call on the two hard edges. There is already a prior research brief at `design/research/2026-06-19-break-import-cycles/research.md` and two archived specs (`078-break-import-cycles-clean-wins`, `080-break-bus-core-import-cycle`); this brief supersedes the prior brief's "what's left" section with the post-#1097/#1103 reality.

### Current state — the actual remaining cycles

I rebuilt the runtime cross-subpackage import graph by hand (top-level imports only, excluding `TYPE_CHECKING` blocks and function bodies). **Exactly two runtime cycles remain**, and they are the two the prior work explicitly deferred to an ADR:

| Cycle | Up-edge (the "wrong direction") | Down-edge (legitimate) | Status |
|---|---|---|---|
| `core ↔ scheduler` | `scheduler/scheduler.py:74` imports `SchedulerService` from `core.scheduler_service` | `core/core.py:19` imports `Scheduler`; `core/state_proxy.py:11,16` import `SchedulerService`/`Scheduler` | **Active runtime cycle** |
| `core ↔ state_manager` | `state_manager/state_manager.py:10` imports `StateProxy` from `core.state_proxy` | `core/core.py:20` imports `StateManager` | **Active runtime cycle** |

Verified clean (no longer cycles): `bus → core`, `api → core`, `web → core` (all report zero runtime core imports). (Confidence: **Direct** — grep + manual trace of every edge to file:line.)

#### The remaining lazy imports (recount: 11 total, but most are NOT the two cycles)

The issue's "~11 lazy-import breakpoints" figure is correct as a raw count but misleading as a measure of remaining cycle debt. Here is every current `# lazy-import:` site and which cycle (if any) it breaks:

| Site | Breaks which cycle | Removable by #1079? |
|---|---|---|
| `resources/base.py:145` (`TaskBucket`) | `resources ↔ task_bucket` | **Yes** — separate small cycle (see Phase 1) |
| `conversion/annotation_converter.py:38,40` (`TYPE_MATCHER`, `BaseState`) | `conversion ↔ models` (#892) | **Yes** — separate small cycle (see Phase 2) |
| `conversion/state_registry.py:89` (`BaseState`) | `conversion ↔ models` (#892) | **Yes** — same as above |
| `utils/app_utils.py:199,354` (`App`, `AppSync`) | long `app → … → utils` chain | **Partial/No** — depends on whether `app` stays reachable; likely persists |
| `app/utils.py:8,31,95` (`App`) | annotation-only uses | Likely convertible to `TYPE_CHECKING` (not a runtime cycle) |
| `__main__.py:9` (`cli`) | not a subpackage cycle — CLI startup deferral | **No** — keep; orthogonal to #1079 |
| `conversion/validation.py:77` | not a cycle — load-order safety note | **No** — not a cycle break |

So of the 11 annotations: **the two hard edges (`SchedulerService`, `StateProxy`) are not even held by lazy imports today** — they are live top-level runtime imports that resolve only because neither module references the other's names at import-evaluation time (one module-level expression away from `ImportError`). The genuinely removable lazy imports belong to two *additional* small cycles (`resources ↔ task_bucket`, `conversion ↔ models`) that the issue lists but that are independent of the two core cycles. (Confidence: **Direct** — every site read at file:line.)

### Key constraints

- **No `from __future__ import annotations`** (project ban — breaks Pydantic/pyright runtime introspection). Rules out stringized-annotation-everywhere as a global fix.
- **`TYPE_CHECKING`-guarded imports are the sanctioned cycle-break for annotation-only needs** and the boundary checker already exempts them (`type_checking_ranges`, lines 150-167). Runtime lazy function-body imports are the debt being paid down.
- **The two hard edges need real symbols at runtime, not just annotations**, so `TYPE_CHECKING` demotion alone cannot fix them — they need a structural move or a protocol.

## Feasibility Analysis

### The decisive structural fact (shapes the whole recommendation)

I checked what `SchedulerService` and `StateProxy` import *back* from their consumer packages:

- **`SchedulerService` (in `core/scheduler_service.py`) imports NOTHING from `scheduler/` at runtime** — its only `scheduler`-package reference is `from hassette.scheduler.classes import ScheduledJob` under `TYPE_CHECKING` (line 28). Its runtime deps are all `core` siblings (`database_service`, `registration`, `sync_executor_service`) plus `commands`, `execution_mode`, `resources`, `types`, `utils`.
- **`StateProxy` (in `core/state_proxy.py`) imports NOTHING from `state_manager/`** (grep returns zero). Its runtime deps are `bus`, `events`, four `core` sibling services (`api_resource`, `bus_service`, `scheduler_service`, `websocket_service`), `resources`, `types`, `utils`.

This means the cycle is *not* a true mutual-logic entanglement. The service-layer classes (`Scheduler`, `StateManager`) reach up to fetch the core singleton; the singletons do not reach back into the service-layer packages. The back-edge in each cycle is a single import line in one file. (Confidence: **Direct**.)

### Consumer surface (how small the coupling actually is)

The methods the consumers actually call on the core singletons are a small, stable set — which makes a Protocol cheap if that's the chosen route:

- `Scheduler` calls on `scheduler_service`: `add_job`, `dequeue_job`, `register_removal_callback`, `deregister_removal_callback`, `mark_job_cancelled`, `remove_jobs_by_owner`, and the `.task_bucket` attribute (7 members).
- `StateManager`/`DomainStates` call on `_state_proxy`: `get_state`, `num_domain_states`, `yield_domain_states`, and `__contains__` (4 members — the read-only `StateReader` surface the 2026-03-25 coupling audit already sketched).

### What would need to change

| Cycle | Fix technique (recommended) | Files touched (direct) | Cascade | Effort | Risk |
|---|---|---|---|---|---|
| `resources ↔ task_bucket` | Convert lazy break to structural: `TaskBucket` reference in `Resource.__init__` stays, but extract a tiny `TaskBucketProtocol`/factory so `resources` need not import `task_bucket` at runtime; or accept `task_bucket` injected as a param | `resources/base.py` | `task_bucket` | Small-Med | Med |
| `conversion ↔ models` (#892) | Relocate the registry seam so `models.states.base` imports a lower layer, not `conversion`, OR keep `BaseState`-as-annotation under `TYPE_CHECKING` and move the runtime `issubclass`/registry call below | `conversion/`, `models/states/base.py` | Med | Med | Med |
| `core ↔ scheduler` (`SchedulerService`) | **Relocate `SchedulerService` out of `core` into the `scheduler` package** so `Scheduler` imports a sibling, not core | `scheduler_service.py` move + ~3 import updates + core wiring | core, scheduler | **Medium** | Med (see below) |
| `core ↔ state_manager` (`StateProxy`) | **Relocate `StateProxy` out of `core` into the `state_manager` package** so `StateManager` imports a sibling | `state_proxy.py` move + import updates + core wiring | core, state_manager | **Medium** | Med-High (4 core-sibling deps) |

### What already supports this

- **The back-edges are single lines.** Each hard cycle is broken by relocating one class so the consumer imports a sibling instead of reaching up to `core`.
- **The relocated classes don't import their consumer packages**, so moving them creates no new reverse edge into `scheduler`/`state_manager` (the trap that usually makes relocation fail).
- **Core wires through public accessors already.** `core.py` constructs both via `add_child(...)` and exposes them through `state_proxy`/`scheduler_service` properties (lines 196-218, 395-422). After relocation, `core.py` simply imports them from the new location — a downward `core → scheduler`/`core → state_manager` import, which is the *legitimate* direction (core sits above the service layer).
- **The boundary checker and lazy-import checker are mature, hand-written AST tools** (`lint_helpers.iter_py_files`/`run_check` reusable). Adding a graph cycle detector is additive, zero-dependency, and consistent with the existing `tools/check_*.py` family.
- The revised L0-L9 layer map is already written down (`design/specs/078-break-import-cycles-clean-wins/issue-633-layer-map.md`) and validated against the post-#1097 reality.

### What works against this

- **Relocating `SchedulerService`/`StateProxy` pulls their core-sibling dependencies with them as new edges.** `StateProxy` imports `api_resource`, `bus_service`, `scheduler_service`, `websocket_service` from core; `SchedulerService` imports `database_service`, `registration`, `sync_executor_service` from core. If these classes move into `scheduler`/`state_manager` (L5), those become **L5 → core (L6) upward edges** — trading two named cycles for several new upward violations. **This is the crux of the relocate-vs-invert decision** and is analyzed per-cycle below. (Confidence: **Direct** — sibling imports verified.)
- **`core` is the hub** (imports ~17 subpackages). Its outgoing edges are intended; the problem is purely the incoming upward edges from `scheduler`/`state_manager`, which the relocation removes.
- The `from __future__` ban removes the cheapest escape hatch; every fix is a real move or a `TYPE_CHECKING` guard for annotation-only use.

### Target layer DAG (from the validated #633 revision)

```
L0  const, types                         leaves; no hassette imports
L1  models                               -> types, const
L2  config                               -> types, const, models
L3  utils, events, conversion,           -> L0-L2  (utils -> events now one-directional)
    event_handling, schemas
L4  resources                            -> L0-L3; shared base, BELOW the service group
L5  api, bus, scheduler, state_manager,  -> L0-L4, may use resources; not each other, not core
    task_bucket
L6  core                                 -> all below
L7  app                                  -> all below + core
L8  web, cli                             -> all below; core -> web one-directional
L9  test_utils                           may import anything; production must not
```

The two remaining cycles are the only edges that violate this DAG today (`scheduler`/`state_manager` at L5 importing `core` at L6). Note the SchedulerService/StateProxy core-sibling deps issue above: those classes currently *live* at L6, so their deps are fine; moving the classes to L5 is what would create the new violations.

## Options Evaluated — the hard service-layer edges (ADR-ready)

Per the scoping decision, this section evaluates **relocate vs. protocol-inversion** against the real code, with a per-cycle recommendation. The two cycles look structurally similar but differ in one decisive respect (sibling-dependency count), so they get different recommendations.

### The two candidate styles

- **Relocate**: move `SchedulerService` into `scheduler/`, `StateProxy` into `state_manager/`. The consumer imports a sibling; `core` imports them downward from L5. Cost: the relocated class's own core-sibling deps become L5→L6 upward edges that must each be resolved (relocated further down, or also inverted).
- **Protocol inversion**: define a `Protocol` (or ABC) in a lower layer (L4 `resources` or L0 `types`) describing the small consumer surface. `Scheduler`/`StateManager` depend on the protocol; `SchedulerService`/`StateProxy` stay in `core` and structurally satisfy it (no `implements` needed for `typing.Protocol`). Cost: one new abstraction per cycle that a reader must trace (`reader-load.md`).

### Cycle 1: `core ↔ scheduler` (`SchedulerService`)

**Recommendation: Protocol inversion.** Define `SchedulerServiceProtocol` in L0 `types` (alongside the existing `TriggerProtocol`, which already proves the pattern — `types/types.py` defines protocols). `Scheduler` depends on the protocol; `SchedulerService` stays in `core` and satisfies it structurally.

**Why not relocate here:** `SchedulerService` runtime-imports three `core` siblings (`database_service`, `registration`, `sync_executor_service`). `database_service` and `sync_executor_service` are genuine core services that cannot move to L5. Relocating `SchedulerService` into `scheduler/` would therefore create `scheduler → core` edges for *those* — converting one clean cycle into three new upward violations. Relocation trades the problem sideways.

**Tradeoffs:**
- *Reader load*: +1 protocol to trace. Mitigated by precedent — `Bus` already uses `TYPE_CHECKING` + string annotation for `BusService`, and `TriggerProtocol` shows the house pattern. The 7-member surface is small.
- *Churn*: ~1 new protocol definition + change `scheduler/scheduler.py:74` from concrete import to protocol import (TYPE_CHECKING for the annotation, runtime fetch still via `self.hassette.scheduler_service`). Call sites unchanged (~7 attribute accesses keep working — Protocol is structural).
- *Testability*: improves — `Scheduler` becomes testable against a fake satisfying the protocol, no core import needed.
- *Behavior*: zero change; `SchedulerService` instance still constructed by `core.py`.

### Cycle 2: `core ↔ state_manager` (`StateProxy`)

**Recommendation: Protocol inversion** (a read-only `StateReader` protocol), for the same reason and with stronger justification.

**Why not relocate here:** `StateProxy` runtime-imports *four* core siblings (`api_resource`, `bus_service`, `scheduler_service`, `websocket_service`) and is itself a WebSocket-reconnection/polling service — it is real core logic, not a data holder. Relocating it to `state_manager/` would drag four upward edges and put a stateful core service in a package meant to be a thin typed-access facade. The 2026-03-25 coupling audit independently reached the same conclusion: "Define a read-only Protocol (`StateReader`) with methods `get_state`, `yield_domain_states`, `num_domain_states`, `__contains__`. `StateManager` and `DomainStates` would depend on this Protocol rather than the concrete `StateProxy`." (Confidence: **Supported** — audit recommendation + verified 4-member call surface + verified sibling deps.)

**Tradeoffs:**
- *Reader load*: +1 protocol (`StateReader`, 4 members). `DomainStates.__init__` and `StateManager._state_proxy` change their type annotation from `StateProxy` to `StateReader`.
- *Churn*: 1 protocol + ~2 annotation sites + 1 import line. Runtime fetch stays `self.hassette.state_proxy`. The 4 call sites are unchanged.
- *Testability*: notably improves — `DomainStates` currently takes a concrete `StateProxy`, leaking reconnection internals into the public state-access API. A `StateReader` protocol lets tests inject a trivial dict-backed reader.
- *Risk*: Med-High only because `StateProxy` is the most-touched read path; the protocol must exactly match the live call surface. Mitigated by the small, verified surface.

### Where the protocol lives

Put both protocols in **L0 `types`** (`SchedulerServiceProtocol`, `StateReader`). `types` is the existing home for `TriggerProtocol`, has no hassette runtime imports, and is below everything — so neither the protocol nor its consumers create new edges. Defining them in `resources` (L4) also works but `types` is the cleaner leaf and matches precedent.

## Phased Resolution Plan

Sequenced simplest-first so later phases land on an increasingly-clean base (`subtract-first.md`, `sequence-verifiable-units.md`). Each phase is independently landable and ends with: both checkers green, the relevant `# lazy-import:` annotation(s) removed (where applicable), and tests green.

**Phase 0 — Reconfirm baseline (no code change).** Run both checkers + the unit/integration suite + pyright on `main` to capture the green baseline. Predicate: both checkers pass, suite green. (This brief already confirmed the checkers pass.)

**Phase 1 — `resources ↔ task_bucket`.** Remove the `resources/base.py:145` lazy `TaskBucket` import by injecting `TaskBucket` (or a tiny protocol/factory) rather than importing it inside `Resource.__init__`. Predicate: `resources/base.py` has no `task_bucket` import; `# lazy-import:` line deleted; `check_lazy_imports.py` green; `import hassette` works; suite green.

**Phase 2 — `conversion ↔ models` (#892).** Remove the three `conversion` lazy imports (`annotation_converter.py:38,40`, `state_registry.py:89`) by relocating the registry seam so `models.states.base` no longer imports `conversion` at runtime (or by demoting `BaseState` to `TYPE_CHECKING` where it is annotation-only and moving the runtime `issubclass`/registry call below the boundary). Predicate: three `# lazy-import:` lines deleted; checkers green; suite green.

**Phase 3 — Write the ADR.** Capture the protocol-inversion decision for both core cycles (this brief's Options section is the input). File under `design/adrs/000N-invert-service-layer-core-dependencies.md`. Predicate: ADR merged; decision recorded.

**Phase 4 — `core ↔ scheduler` via `SchedulerServiceProtocol`.** Define the protocol in `types`; change `scheduler/scheduler.py` to depend on it (TYPE_CHECKING annotation + runtime fetch via accessor); remove the runtime `from hassette.core.scheduler_service import SchedulerService`. Add a `scheduler-no-core` rule to `check_module_boundaries.py`. Predicate: no runtime `scheduler → core` import; new rule self-proves (reverting the fix fails the guard); checkers green; pyright clean; suite green.

**Phase 5 — `core ↔ state_manager` via `StateReader`.** Define `StateReader` in `types`; retype `DomainStates`/`StateManager` against it; remove the runtime `from hassette.core.state_proxy import StateProxy`. Add a `state_manager-no-core` rule. Predicate: same shape as Phase 4 for `state_manager`.

**Phase 6 — Flip on full DAG + cycle enforcement (#633).** With the graph acyclic, expand `check_module_boundaries.py` `RULES` to encode the full L0-L9 map and add a hand-written graph cycle detector (~250-350 lines, AST-only, zero deps — consistent with the existing tool family). Predicate: cycle detector reports zero cycles; full layer-map rules pass; suite green. Decide here whether the DAG is over *runtime-top-level edges only* (matches today's checker philosophy; lets the remaining annotated lazy/TYPE_CHECKING breaks stand) or *all edges* (forces removing every lazy break) — see Open Questions.

**Phase 7 — Retire remaining removable annotations + reconcile the count.** After Phases 1-2, the `resources`/`conversion` annotations are gone. Re-examine `app/utils.py` (likely `TYPE_CHECKING`-convertible) and document that `__main__.py:9` and `conversion/validation.py:77` are *not* cycle-related and stay. Predicate: annotation count reflects only genuine remaining breaks, each justified.

## Recommendation

**Proceed, in two waves.** (Confidence: **Supported** — grounded in the verified two-cycle reduction, the single-line back-edges, and the zero reverse-dependency of the relocated classes; the relocate-vs-invert call is **Inferred** but strongly evidenced by the sibling-dependency counts.)

The issue's framing ("~11 lazy imports, ~210 files") is stale: #1097 and #1103 already broke `bus/api/web ↔ core` and moved `await_guard`/`commands`. Only **two runtime cycles remain**, and they are precisely the ones every prior artifact deferred to an ADR. The good news the deeper read surfaces: these two are *not* mutual-logic entanglements — `SchedulerService` and `StateProxy` import nothing from their consumer packages, so each back-edge is a single import line.

**Wave 1 (low-risk, ship independently):** Phases 1-2 — break `resources ↔ task_bucket` and `conversion ↔ models`, deleting ~5-6 of the 11 lazy annotations. These are small, mechanical, and unblock a cleaner base.

**Wave 2 (the ADR-gated core work):** Phases 3-6 — invert both core cycles via Protocols. **Recommend protocol inversion over relocation for both**, because relocating `SchedulerService`/`StateProxy` out of `core` would drag their 3-4 core-sibling service dependencies upward, converting two clean cycles into several new upward violations. Protocol inversion costs two small protocols (`SchedulerServiceProtocol` 7 members, `StateReader` 4 members) in L0 `types` — a precedented pattern (`TriggerProtocol` already lives there) with a small, verified call surface and a testability upside (especially `DomainStates`, which today leaks `StateProxy` reconnection internals into the public state API).

Be honest about scope: #1079 does not zero the lazy imports. `__main__.py:9` (CLI startup deferral) and `conversion/validation.py:77` (load-order note) are not cycles and stay; `app/utils.py` may stay or convert to `TYPE_CHECKING`. The refactor retires the cycle-related annotations and makes the DAG enforceable — which is the real prize (#633).

Do **not** adopt `pytest-archon` (obscure). If a library is wanted for Phase 6, `import-linter` is the mature choice; but the house pattern is hand-written `tools/check_*.py` AST checks, so a hand-written cycle detector is the more consistent option and worth defaulting to.

### Should this split into sub-issues?

**Yes.** Sequence:
- **Sub-issue A** (`resources ↔ task_bucket`) and **Sub-issue B** (`conversion ↔ models`) — independent, parallelizable, no ADR needed. Each its own PR.
- **ADR** (Phase 3) — must land before C and D; serializes them.
- **Sub-issue C** (`core ↔ scheduler`) and **Sub-issue D** (`core ↔ state_manager`) — independent of each other once the ADR exists; can parallelize, but each touches `core.py` wiring so coordinate the `core.py` edits (or land C then D to avoid a merge conflict on `core/core.py`).
- **Sub-issue E** (Phase 6, #633 enforcement) — strictly last; depends on C and D being done so the cycle detector passes. This is #633's headline check; #1079 is its blocker, not the reverse.

### Suggested next steps
1. **Write the ADR** (`/mine-define`) recording protocol-inversion for both core cycles, citing the sibling-dependency evidence that rules out relocation. This is the one decision code-reading alone shouldn't finalize.
2. **Land Wave 1 first** as two independent PRs (`resources↔task_bucket`, `conversion↔models`) — proves the lazy-annotation cleanup and gives an acyclic-er base.
3. **Split #1079 into sub-issues A-E** per the sequencing above; update #1079's body to reflect that #1097/#1103 already resolved the other cycles (the issue text is stale).
4. **Implement C then D** behind the ADR; add `scheduler-no-core` and `state_manager-no-core` rules so each break self-proves and can't re-accrete.
5. **Run `/mine-challenge` on the ADR** — relocate-vs-invert is exactly the fragility/coherence call the critics catch.
6. **Defer Phase 6 enforcement to #633** once the graph is acyclic.

## Open Questions

- [ ] **DAG scope (Phase 6):** enforce over **runtime-top-level edges only** (matches today's checker; lets annotated lazy/TYPE_CHECKING breaks stand) or **all edges** (forces removing every lazy break)? This single choice changes whether `app/utils.py`/`__main__.py` annotations must also go. Recommend runtime-top-level-only, consistent with the existing tool.
- [ ] **Protocol home:** `types` (L0, recommended, matches `TriggerProtocol`) vs `resources` (L4). Either avoids new edges; confirm in the ADR.
- [ ] **`conversion ↔ models` exact seam (Phase 2):** does the `BaseState` runtime need in `state_registry.py:89`/`annotation_converter.py:40` reduce to an annotation (TYPE_CHECKING-convertible) or a true runtime `issubclass`/`model_validate` call that must relocate? Needs a close read of the registry registration order before committing to a technique.
- [ ] **Hand-written cycle detector vs `import-linter` (Phase 6):** house style leans hand-written; confirm whether a dev dependency is acceptable for #633.
- [ ] Unknown: whether `tests/unit/tools/test_check_module_boundaries.py`'s "not yet governed" stand-in (which spec 080 re-pointed to `state_manager → core`) needs another stand-in once C/D land — searched the spec, which notes the assertion flips per new rule, but the post-C/D replacement target isn't pre-chosen.

## Sources

- [Fixing Circular Imports in Python with Protocol — PythonTest](https://pythontest.com/fix-circular-import-python-typing-protocol/)
- [The Circular Import Problem: Breaking Dependency Cycles — DEV Community](https://dev.to/aaron_rose_0787cc8b4775a0/the-circular-import-problem-breaking-dependency-cycles-4i56)
- [Circular Imports in Python: The Architecture Killer — DEV Community](https://dev.to/vivekjami/circular-imports-in-python-the-architecture-killer-that-breaks-production-539j)
- Prior internal artifacts: `design/research/2026-06-19-break-import-cycles/research.md`; `design/specs/078-break-import-cycles-clean-wins/` (issue-633-layer-map.md); `design/specs/080-break-bus-core-import-cycle/design.md`; `design/audits/2026-03-25-comprehensive-audit/coupling.md`
