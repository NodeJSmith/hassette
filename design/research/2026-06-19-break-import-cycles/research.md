---
proposal: "Break runtime import cycles between src/hassette subpackages so check_module_boundaries.py can enforce a full layer DAG instead of only test_utils isolation."
date: 2026-06-19
status: Draft
flexibility: Exploring
motivation: "Make the intended layering mechanically checkable and remove the ~11 # lazy-import: workarounds that paper over cycles."
constraints: "hassette repo (async Python 3.11+, Pydantic, pyright strict). No `from __future__ import annotations`. Lazy function-body imports banned except under TYPE_CHECKING."
non-goals: "Adopting pytest-archon specifically; rewriting unrelated coupling; changing public app-author API."
depth: deep
---

# Research Brief: Break Subpackage Import Cycles to Enable a Module-Boundary DAG

**Initiated by**: GitHub issue #1079 — break the ~10 runtime import cycles between `src/hassette` subpackages so `tools/check_module_boundaries.py` can grow from the current `test_utils`-isolation rule to a full architectural layer DAG.

## Context

### What prompted this

`tools/check_module_boundaries.py` today enforces exactly one rule: production code must not import `hassette.test_utils`. The tool's own docstring (lines 13-19) states the full layer DAG and cycle-freedom "are NOT enforced here — the codebase currently has cross-layer cycles ... that must be refactored before those rules can pass (tracked in #1079)." #633 is the umbrella enforcement issue (it proposes the layer map and would add cycle detection, optionally via `pytest-archon`); #1079 is the refactoring that unblocks it.

The motivation is **architectural enforceability**: make the intended layering mechanically checkable so an all-AI-authored codebase can't silently erode it, and retire the `# lazy-import:` annotations that currently mark cycle-breaking points.

### Current state

`src/hassette` has 271 `.py` files across 20 subpackages. The relevant ones for layering: `const`, `types`, `models`, `config`, `conversion`, `events`, `event_handling`, `utils`, `api`, `bus`, `scheduler`, `state_manager`, `resources`, `task_bucket`, `core`, `app`, `web`, `cli`, `test_utils`, `migrations_sql`.

**Critical reframing — most listed "cycles" are already broken at module load.** Issue #1079's bullet list mixes two different things: runtime *cycles* (a real import-time hazard) and *cross-layer violations* (an upward edge that offends the proposed DAG but does not, by itself, deadlock imports). I traced every claimed edge to its file:line and classified it as runtime-top-level / TYPE_CHECKING-only / lazy function-body. Result:

| Claimed cycle (from #1079) | Actually a runtime cycle today? | How it's currently held together |
|---|---|---|
| `core ↔ bus` | **Yes** | Both directions are top-level runtime imports |
| `core ↔ api` | **Yes** | Both directions top-level runtime |
| `core ↔ scheduler` | **Yes** | Both directions top-level runtime |
| `core ↔ state_manager` | **Yes** | Both directions top-level runtime |
| `core ↔ web` | **Yes** | Both directions top-level runtime (web→core for data types) |
| `resources ↔ task_bucket` | No (broken) | `resources/base.py:145` lazy-imports `TaskBucket` |
| `conversion ↔ models` | No (broken) | `conversion` lazy-imports `models.states` in two methods (#892) |
| `utils ↔ events` | **Yes** | `utils/type_utils.py:10` and `events/hassette.py:7` both top-level |
| `app → scheduler → core → app` | No (broken) | `app/app.py:20` imports `Hassette` under TYPE_CHECKING only |
| `app → scheduler → core → conversion → utils → app` | No (broken) | `utils/app_utils.py:199,354` lazy-import `app` |

So the genuine, unbroken **runtime** cycles are the five `core ↔ {bus,api,scheduler,state_manager,web}` pairs plus `utils ↔ events`. The other four are already broken — but by exactly the lazy/TYPE_CHECKING devices that #1079 wants to retire. A DAG checker that counts lazy and TYPE_CHECKING edges as real (which a graph-level cycle detector would, if it doesn't exempt them) would still flag them. (Confidence: **Supported** — every edge verified at file:line; classification cross-checked between two independent explorations and one direct grep pass.)

#### The runtime cycles, with their load-bearing symbols

The decisive detail is *what symbol* each upward edge needs, because that dictates the fix.

- **`bus → core`, `api → core`, `scheduler → core` all reach up to `core` for the same thing: `guard_await` from `core/await_guard.py`.** That file (194 lines) imports only `hassette.exceptions` and `hassette.types.enums` — it is a pure leaf utility that happens to live in `core`. Specific sites: `bus/bus.py:101`, `api/api.py:173`, `scheduler/scheduler.py:74`.
  - `scheduler → core` has a second, harder edge: `scheduler/scheduler.py:75` imports `SchedulerService` from `core/scheduler_service.py` (real core logic).
  - `bus → core` has a second edge: `bus/invocation.py:10` imports `InvokeHandler` from `core/commands.py` (a dataclass).
- **`state_manager → core`**: `state_manager/state_manager.py:9` imports `StateProxy` from `core/state_proxy.py`. `StateProxy` is non-trivial core logic.
- **`web → core`**: 8 top-level edges, all importing **pure data types and constants** — `domain_models`, `telemetry_models`, `app_registry` snapshots, `bus_service.LiveCounts`, query-limit constants. Examples: `web/mappers.py:18-21`, `web/models.py:7`, `web/routes/telemetry.py:15-16`. These models import only `hassette.types.*` themselves (`telemetry_models.py:18-19`), so they are extractable.
- **`utils ↔ events`**: `utils/type_utils.py:10` imports `events.Event` (used in an `issubclass` check in `is_event_type`); `events/hassette.py:7` imports `utils.get_traceback_string` (a 1-function helper in `utils/exception_utils.py`).

### Key constraints

- **No `from __future__ import annotations`** (project ban — breaks Pydantic/pyright runtime introspection). This rules out the most common Python cycle-break trick (stringized annotations everywhere).
- **Lazy function-body imports are banned except under `TYPE_CHECKING`.** This is the core tension: `TYPE_CHECKING`-guarded imports are a *legitimate* tool here and the boundary checker already exempts them (`check_module_boundaries.py:81-98`). But #1079's stated goal includes removing `# lazy-import:` annotations — and a few cycles are currently held only by genuine runtime lazy imports (resources↔task_bucket, conversion↔models), which can't be converted to TYPE_CHECKING because the symbol is used at runtime, not just in annotations.
- pyright strict; line length 120; async-first.

## Feasibility Analysis

### What would need to change

| Cycle | Fix technique | Files touched (core) | Cascade | Effort | Risk |
|---|---|---|---|---|---|
| `bus/api/scheduler → core` (guard_await) | **Move `core/await_guard.py` to a lower layer** (`utils/` or new `_runtime/`) | 1 move + ~6 import updates | low — symbol is leaf | **Small** | Low |
| `web ↔ core` | **Extract `domain_models`/`telemetry_models`/snapshot types out of `core` into `models/` (or new `web_models`/`schemas` layer)** | ~4 model modules moved | ~15-20 importers (web + core) | **Medium** | Medium — high fan-in, but pure data |
| `bus → core` (InvokeHandler), `core → bus` | Move `InvokeHandler`/command dataclasses to a shared lower module, or invert via protocol | `core/commands.py` split | bus + core | Medium | Medium |
| `state_manager → core` (StateProxy) | Hardest: `StateProxy` is logic, not data. Options: move `StateProxy` into `state_manager`, or invert with a protocol StateManager depends on | `state_proxy.py` move | core + state_manager | **Medium-Large** | Medium-High |
| `scheduler → core` (SchedulerService) | Same shape as state_manager — relocate or invert | `scheduler_service.py` | core + scheduler | Medium-Large | Medium-High |
| `utils ↔ events` | Two clean moves: push `Event` base low enough, or move `is_event_type` / `get_traceback_string` so the edge is one-directional | 1-2 small moves | small | **Small** | Low |
| `resources ↔ task_bucket` (already lazy) | Invert: extract a `ResourceProtocol` task_bucket depends on, or move `TaskBucket` ref out of `Resource.__init__` | `resources/base.py` | task_bucket | Small-Medium | Medium |
| `conversion ↔ models` (already lazy, #892) | Move the registry/`register_state_converter` seam so `models.states.base` imports a lower layer, not `conversion` | `conversion/`, `models/states/base.py` | Medium | Medium | Medium |

Total churn is **not** ~210 files of edits — the issue's "210 files" figure refers to the *guard's scan scope*, not the edit surface. The actual edit surface is the moved modules plus their importers: realistically **30-60 files** across all cycles, concentrated in `core`, `web`, `bus`, `scheduler`, `state_manager`, `conversion`, `models`.

### What already supports this

- **The boundary checker already exempts TYPE_CHECKING** (`type_checking_ranges`, lines 81-98) and resolves relative imports correctly (lines 101-118). The hardest parsing work is done.
- **`guard_await` is a free win**: one file move retires three upward edges (`bus/api/scheduler → core`) at once. This is the highest leverage move in the whole effort.
- **`web → core` is all data types** — no behavior to untangle, just relocation. The coupling audit (`design/audits/2026-03-25-comprehensive-audit/coupling.md`) already documented this reverse dependency.
- The intended layer order is already articulated in #633 and largely matches reality below the `core` line. `const`/`types`/`migrations_sql` are pure leaves today.
- `lint_helpers.py` (`iter_py_files`, `run_check`) is reusable; a graph-based cycle check is additive.

### What works against this

- **`StateProxy` and `SchedulerService` are real logic in `core`** consumed upward. These aren't data-relocation moves — they need either relocation (which may pull more core logic down) or protocol inversion (which adds an abstraction layer, costing reader-load per `reader-load.md`). These two edges are where the effort and risk concentrate.
- **The `from __future__` ban removes the cheapest escape hatch.** Every fix must be a real structural move or a `TYPE_CHECKING` guard that genuinely only needs the symbol for annotations.
- **`core` is a hub** importing 17 subpackages (graph agent confirmed). It's intended to sit high in the DAG, so its *outgoing* edges are mostly fine — the problem is purely the *incoming upward* edges from its peers.
- **#633's proposed map says `api/bus/scheduler/state_manager/resources/task_bucket` are mutually independent.** Reality: `api → resources`, `bus → resources`, `scheduler → resources`, `state_manager → resources`, and `task_bucket → resources` all exist (resources is a shared base). The proposed "peer independence" rule conflicts with the actual code — **`resources` belongs in a layer below the api/bus/scheduler group, not beside it.** This is a map revision #1079 must feed back into #633.

### Target layer DAG (revised from #633)

Reconciling #633's proposed map with the actual runtime graph:

```
L0  const, types                         (leaves; no hassette imports)
L1  models                                (-> types, const)
L2  config                                (-> types, const, models)
L3  utils, events, conversion,            (-> L0-L2; utils<->events cycle to break)
    event_handling
L4  resources                             (-> L0-L3; shared base, BELOW the services)
L5  api, bus, scheduler, state_manager,   (-> L0-L4, may use resources; NOT each other,
    task_bucket                            NOT core)
L6  core                                  (-> all below)
L7  app                                   (-> all below + core)
L8  web, cli                              (leaves at top; nothing imports them)
L9  test_utils                            (may import anything; production must not import it)
```

Differences from #633's map: `resources` pulled out into its own L4 below the service group (the code demands it); `utils ↔ events` flagged as a same-layer cycle that must be made one-directional. Everything else matches.

### Per-cycle breaking plan (recommended sequencing)

Sequence leaf/foundational cycles first so later moves land on an acyclic base (`subtract-first.md`, `sequence-verifiable-units.md`). Each step ends with the test suite green and the new edge gone.

1. **`utils ↔ events`** (Small, Low) — make one-directional. Move `get_traceback_string` so `events` no longer reaches `utils`, or move the `Event`-type check out of `utils`. Foundational; unblocks clean L3.
2. **Move `await_guard.py` down to L3/L4** (Small, Low) — retires `bus → core`, `api → core`, and the `guard_await` half of `scheduler → core` in one move. **Highest leverage; do early.**
3. **`web ↔ core` data extraction** (Medium) — relocate `domain_models`, `telemetry_models`, registry snapshot types from `core` to `models/` (or a new schema layer). Pure data, high fan-in but mechanical.
4. **`bus → core` (InvokeHandler) / `core → bus`** (Medium) — relocate command dataclasses to a shared lower module.
5. **`resources ↔ task_bucket`** and **`conversion ↔ models`** (Medium) — convert the existing *lazy* breaks into real structural breaks (protocol inversion or symbol relocation) so the `# lazy-import:` annotations can be deleted.
6. **`state_manager → core` (StateProxy)** and **`scheduler → core` (SchedulerService)** (Medium-Large, highest risk) — last, because they need design choices (relocate vs. protocol) and touch real core logic. Do after the easy wins prove the approach.
7. **Flip on DAG + cycle enforcement** in `check_module_boundaries.py` once the graph is acyclic.

### Lazy-import payoff

Of the 11 `# lazy-import:` sites, here is which become removable:

| Lazy-import site | Removable after | Notes |
|---|---|---|
| `resources/base.py:145` (TaskBucket) | Cycle 5 (resources↔task_bucket break) | **Yes** |
| `conversion/annotation_converter.py:38,40` (#892) | Cycle 5 (conversion↔models break) | **Yes** |
| `conversion/state_registry.py:89` | Cycle 5 | **Yes** |
| `utils/app_utils.py:199,354` (App/AppSync) | Only if `app → scheduler → core → conversion → utils` chain is fully inverted | **Partial** — these break the long chain; removable only if `utils` stops being reachable from `app`'s transitive deps. May need to stay. |
| `__main__.py:9` (cli import) | Not a subpackage cycle — `cli` is a top leaf | **No** — keep; it defers the heavy app graph for CLI startup, unrelated to #1079 |
| `conversion/validation.py:77` | N/A — comment marks a load-order safety note, not a cycle break | **No** — not a cycle |
| `app/utils.py:8,31,95` (App) | These are TYPE_CHECKING-adjacent / annotation uses | Likely convertible to `TYPE_CHECKING` if only annotations |

So **~5-6 of the 11 annotations become cleanly removable** (the resources/conversion ones), 2-3 are not cycle-related at all (`__main__`, `validation`), and the `app_utils`/`app/utils` ones depend on whether the long `app→...→utils` chain is fully straightened. Honest read: the refactor retires roughly half the annotations; it does not zero them.

## Options Evaluated

### Option A: Full refactor — break all runtime cycles, enforce the complete DAG

**How it works**: Execute steps 1-7 above. Move `await_guard` and the `web`/`bus`/`core` data types to lower layers; invert or relocate `StateProxy` and `SchedulerService`; straighten `utils↔events`; convert the lazy resources/conversion breaks into structural ones. Then revise `check_module_boundaries.py` `RULES` to encode the L0-L9 map as allowed-import predicates and add a graph-level cycle detector (~250-350 lines, AST-only, no new dependency) or adopt `import-linter` (mature, config-driven layers + cycle contracts).

**Pros**:
- The runtime import graph becomes a provable DAG; the architecture is mechanically enforced going forward — the exact harness-engineering goal motivating #633.
- Retires ~half the `# lazy-import:` annotations and the conceptual debt they represent.
- Forces resolution of the genuine logic-coupling in `state_manager`/`scheduler` → `core`, which the coupling audit already flagged as HIGH.

**Cons**:
- The `StateProxy`/`SchedulerService` edges need real design decisions (relocate vs. protocol); protocol inversion adds abstraction layers that raise reader-load, partially trading one maintainability axis for another.
- 30-60 file edit surface; several PRs; touches `core`, the highest-fan-in subpackage.
- Does not zero the lazy imports (`__main__`, `app_utils` may persist), so the "remove all annotations" framing in #1079 is slightly optimistic.

**Effort estimate**: **Large** — but decomposable into ~7 independently-landable PRs (one per cycle), most of which are Small/Medium. Only the last two (state_manager, scheduler) are genuinely hard.

**Dependencies**: Optionally `import-linter` (dev-only) for the enforcement layer; otherwise zero new deps (hand-written AST). `pytest-archon` is referenced in #633 but is essentially undocumented/obscure (web search found nothing) — **recommend `import-linter` over `pytest-archon`** if a library is used at all.

### Option B: Partial — break the cheap, high-value cycles; enforce a partial DAG

**How it works**: Do steps 1-3 only (`utils↔events`, `await_guard` move, `web↔core` data extraction). These are the Small/Medium, low-risk wins. Then expand `check_module_boundaries.py` `RULES` to enforce the boundaries that are now clean (e.g., "`web` must not be imported by anyone but `test_utils`/`cli`"; "`bus`/`api` must not import `core`") while leaving the `state_manager`/`scheduler` → `core` edges as documented, allowlisted exceptions. Do not add full graph cycle detection yet.

**Pros**:
- Captures ~70% of the value (three of five hard cycles gone, including the free `guard_await` win) for ~30% of the effort and risk.
- Each new `RULES` entry is independently testable in the existing per-edge framework — no graph machinery needed.
- Leaves the genuinely hard, design-heavy edges (`StateProxy`, `SchedulerService`) for a later, deliberate decision instead of forcing them now.

**Cons**:
- The graph is still not a DAG, so `import-linter`/cycle detection can't be turned on — enforcement stays per-edge allow/deny, which is weaker.
- Partial enforcement risks a false sense of done; the remaining `core` cycles persist.

**Effort estimate**: **Medium**.

**Dependencies**: None.

### Option C: Do nothing structural — keep lazy-import annotations as the boundary mechanism

**How it works**: Accept that `# lazy-import:` annotations + `check_lazy_imports.py` (which forces every cycle-break to be annotated with a reason) already function as a lightweight, enforced documentation of every cycle-breaking point. Keep `check_module_boundaries.py` at `test_utils` isolation. Optionally add a *read-only* cycle *reporter* (not a blocker) so new cycles are at least visible in CI.

**Pros**:
- Zero churn across `core`/`web`/`state_manager`.
- The existing annotation regime is already a real, enforced mechanism (`encode-lessons-in-structure.md`): every lazy import must carry a reason or CI fails. That's not nothing.
- Avoids adding protocol-inversion abstraction layers whose reader-load cost may exceed the enforcement benefit for a small, single-maintainer-plus-AI codebase.

**Cons**:
- The architecture stays unenforceable as a DAG; #633's headline check can never pass.
- Lazy imports keep their known downsides (break `patch()` mocking, hide import errors to runtime) at the ~11 sites.
- New upward edges between peers (`api → bus` etc.) would still compile silently — the annotation regime only catches *cycles that someone chose to break lazily*, not *new upward dependencies*.

**Effort estimate**: **Small** (just the optional reporter).

**Dependencies**: None.

## Concerns

### Technical risks
- **`StateProxy`/`SchedulerService` relocation may cascade.** Moving them out of `core` could pull other `core` symbols down with them, or the protocol-inversion alternative adds an interface layer. This is the one place where "just move the file" may not work — it needs a design decision, ideally an ADR.
- **`web → core` extraction touches Pydantic response models** with high fan-in (web routes + frontend type generation via `scripts/export_schemas.py`). Moving these modules must keep the OpenAPI/TS-type generation stable — a relocation that changes a model's import path could ripple into `generated-types.ts`. Verify schema freshness after the move.
- **Cycle detector exemption semantics.** If the new graph check counts TYPE_CHECKING and lazy edges as real, it will flag the four "already broken" cycles. The checker must decide deliberately whether the DAG is over *runtime-top-level edges only* (matches the existing `check_module_boundaries.py` philosophy) or *all edges* (which would force removing every lazy break, a larger goal).

### Complexity risks
- Protocol inversion for `state_manager`/`scheduler` introduces ABCs/Protocols that didn't exist — new indirection a reader must trace. Weigh against `reader-load.md`: only invert where relocation is genuinely impossible.

### Maintenance risks
- A full DAG checker (hand-written, ~300 lines) is more code to own. `import-linter` externalizes that but adds a dev dependency and a contract config file to maintain. Either way, the enforcement layer itself becomes a thing to maintain — justified only if the architecture is actually held to the DAG.

## Open Questions

- [ ] Should the enforced DAG be over **runtime-top-level edges only** (lets the 4 already-lazy-broken cycles stay as-is, matching today's checker) or over **all edges** (forces removing every lazy import)? This single decision changes the scope dramatically.
- [ ] For `StateProxy`/`SchedulerService` → `core`: **relocate the symbol down**, or **invert via protocol**? Needs an ADR; can't be settled by code-reading alone.
- [ ] Does the `web → core` model extraction destabilize `scripts/export_schemas.py` output? Needs a prototype move + regen to confirm. (Unknown — not verifiable without running the generator.)
- [ ] **Sequencing vs #633**: confirmed below — they are largely independent.
- [ ] Is `import-linter` acceptable as a dev dependency, or is hand-written AST cycle detection preferred for zero-dependency consistency with the existing `tools/check_*.py` family? (The existing tools are all hand-written AST — house style leans hand-written.)
- [ ] Unknown: the prior-art research brief #633 cites (`design/research/2026-05-03-structural-enforcement/research.md`) **does not exist** at that path. I searched `design/research/`, `design/audits/`, and `design/adrs/` and found the 2026-03-25 coupling audit instead, but no structural-enforcement research brief. Either it was never written or the path drifted.

### Sequencing vs #633

**#1079 does not strictly need #633 done first, and the two can proceed independently.** #633 is the *enforcement* work (the layer-map rules + cycle detection); #1079 is the *refactoring* that makes those rules pass. You can break cycles (this issue) entirely independently of building the checker. The natural order is: break cycles first (#1079), then turn enforcement on (#633) so it doesn't immediately fail. The `test_utils` isolation rule from #633 is already shipped and didn't need any cycle-breaking — proof the two are decoupled. The only hard dependency is the *reverse* of what the issue implies: #633's headline DAG/cycle checks can't pass *until* #1079 lands, so if anything #633 is blocked by #1079, not the other way around.

## Recommendation

**Start with Option B (partial), with Option A as the explicit long-term target.** (Confidence: **Inferred** — grounded in the verified cycle classification and symbol analysis, but the relative value of full enforcement is a judgment call.)

The evidence points strongly to a tiered payoff curve. Three of the five hard cycles are cheap and low-risk: moving `await_guard.py` down a layer retires three upward edges in one stroke, `web → core` is pure data relocation, and `utils ↔ events` is two small moves. These deliver most of the architectural benefit and are independently shippable. The remaining two edges (`state_manager`/`scheduler` → `core`) carry real design weight and should not be rushed — they deserve an ADR deciding relocate-vs-invert.

Be honest about the framing: #1079's "remove ~11 lazy imports across ~210 files" is optimistic on both counts. The edit surface is ~30-60 files, not 210 (210 is the guard's scan scope), and the refactor retires roughly half the annotations, not all. Option C is defensible if the team decides enforcement isn't worth the abstraction cost — the existing `check_lazy_imports.py` annotation regime already forces every cycle-break to justify itself in CI, which is a real, if weaker, mechanism. But Option C leaves new *upward peer* edges uncaught, which is the erosion #633 most wants to prevent.

Do **not** adopt `pytest-archon` (obscure, undocumented). If a library is used for enforcement, use `import-linter` (mature, layer + cycle contracts in ~6 lines of config). Given the house pattern of hand-written `tools/check_*.py` AST checks, a hand-written cycle detector (~300 lines, zero deps) is the more consistent choice and worth comparing against `import-linter` in the design doc.

### Suggested next steps
1. **Write a design doc / ADR** (`/mine-define`) covering: the revised L0-L9 layer map (with `resources` pulled below the service group), the runtime-vs-all-edges enforcement decision, and the relocate-vs-protocol choice for `StateProxy`/`SchedulerService`.
2. **Land the free wins first as separate PRs**: move `await_guard.py` down (retires 3 edges), then `web → core` data extraction, then `utils ↔ events`. Each ends with tests green and one cycle gone.
3. **Prototype the `web → core` model move and re-run `scripts/export_schemas.py`** to confirm frontend type generation stays stable before committing to it.
4. **Split #1079 into per-cycle sub-issues** (the issue itself suggests this) sequenced leaf-first per the plan above.
5. **Defer `state_manager`/`scheduler` → `core`** until the ADR settles the technique; these are the only genuinely hard edges.
6. Consider running `/mine-challenge` on the design doc before committing — the relocate-vs-invert decision is exactly the kind of fragility/coherence call the critics catch.

## Sources

- [How to Fix a Circular Import in Python — Rollbar](https://rollbar.com/blog/how-to-fix-circular-import-in-python/)
- [Fixing Circular Imports in Python with Protocol — PythonTest](https://pythontest.com/fix-circular-import-python-typing-protocol/)
- [Import Linter documentation](https://import-linter.readthedocs.io/)
- [Contract types — Import Linter](https://import-linter.readthedocs.io/en/latest/contract_types.html)
- [Six lines of code to prevent Python spaghetti — David Seddon](https://seddonym.me/2025/11/12/six-lines-of-code/)
