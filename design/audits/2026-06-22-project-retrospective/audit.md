# Project Retrospective — Evolution & Patterns (2026-06-22)

A from-a-distance read of the whole project: 482 commits over ~10 months (2025-09-01 → 2026-06-22), ~75 releases, ~190 design docs (specs, research briefs, audits, critiques). Built from git history, the `design/` corpus, file churn, and commit-type signals, then the structural findings were validated against the live code (see [§4](#4-validation-pass--blind-spots-checked-against-code)).

This is backward-looking and synthesis-level. It does not re-list individual audit findings — those live in the dated audits it draws on.

## 1. The arc

The repo splits into two eras with a quiet winter between them.

**Era 1 — Scrappy bootstrap (Sept 2025, 89 commits).** Loudest by commit count, smallest by ambition. `v0.1.0` ships Sept 1; most of September is fighting CI/CD into existence — Docker containers for a live HA test instance, the test matrix, `requires_ha` markers. Plumbing for a public release, not features.

**Era 2 — Core framework takes shape (Oct–Nov 2025, ~72 commits).** The foundational abstractions land, each a PR-sized feature: predicate rewrite + Bus (#147), scheduler (#101), resource structure & parentage (#114/#115), state proxy + dynamic class registry (#192/#196), config organization (#180), app autodetection (#158), task factory (#97). The shape described in CLAUDE.md today is all from this window. Python 3.13 was briefly required (#192) then walked back.

**Winter lull (Dec 2025 – Jan 2026, 13 commits total).** Near-dormant; the little activity is packaging and Docker. The seam between the two eras.

**Era 3 — The design-driven rebuild (Feb 2026 → present, ~308 commits).** The `design/` process appears — research briefs, numbered specs, ADRs, audits. The entire 190-doc corpus is from here. Cadence is industrial: 47 commits in Feb, peaking at **114 in May**. Identifiable waves:

- **Telemetry/SQLite foundation** (Feb–Mar) — single-writer DB queue, CommandExecutor, decomposing the `DataSyncService` god object (ADR-0001, ADR-0002).
- **UI big-bang** (Mar) — full frontend rebuild that immediately churns stacks (see §3).
- **API ergonomics** (Apr) — bus filtering layers (predicates/conditions/accessors/DI), scheduler API redesign, execution timeouts, duration-hold + immediate-fire, exception handlers.
- **Codegen + CLI + maturation** (May, peak) — typed entity models generated from HA core, a from-scratch `hassette` query CLI, CSS modules, TanStack Query, logging-as-Resource.
- **Async-safety tooling** (Jun) — the dominant recent theme: mechanical detection of forgotten `await`, blocking I/O on the loop, swallowed `CancelledError`, and breaking import cycles to enforce a layered DAG.

~75 releases is roughly one every four days — small, continuous shipping. Commit mix (83 feat / 55 fix / 42 chore / 35 refactor / 31 docs) is feature-heavy with a healthy refactor and fix tail: a codebase being actively reshaped, not just accreted.

## 2. The dominant pattern: build fast, re-derive the same seam

The clearest signal across churn, specs, research, and the team's own audits is **the same handful of structural problems being re-diagnosed repeatedly** without the root cause closing. The 2026-06-19 audit names it directly: "boundary gaps the build never ratcheted shut."

| Seam | Times re-attacked | Evidence |
|---|---|---|
| Bus/scheduler dispatch duplication ("drifted twins") | 4+ diagnoses, bridged Jun | audits 03-25, 03-20, 06-19; specs 036→073→074→079 |
| Hassette god object + private-attr reach-through (`hassette._bus_service`) | 2 research briefs + 2 audit waves, still open | research 02-26, 05-02; audits 03-25, 06-19 |
| Core→web / bus→core import cycles | Flagged repeatedly, broken only in Jun | audit 03-25 → 06-19; specs 078/079/080 (3 in 3 days) |
| Telemetry SQL quadruplication | 3 audit waves | 03-20, 03-25, 06-19 |
| Test infrastructure | Cleaned up 6+ times | specs 039, 040, 041, 042, 061, 075 |
| Listener/handler stable identity | 3 research briefs | 04-06 (×2), 05-28 |
| Docs | Re-baselined ~5 times | specs 023, 027, 030, 062, 070 |

`harness.py` (test infra) has **56 commits — the second-most-churned file in the repo**, behind only `core.py` (65). That is a file repeatedly rebuilt because earlier passes treated symptoms; specs 040 and 061 explicitly call out duplication left behind by prior cleanups.

**Mechanism:** this is an AI-paced codebase. Spec 078's own design doc says it — "the intended layering erodes silently in an AI-authored codebase." Fast generation means structure decays between waves, so each wave re-discovers the decay. The June pivot to **mechanical linters** (import-cycle DAG enforcement, forgotten-await detection, blocking-IO detection, module-boundary checks) is the correct fix: stop writing instructions, encode the invariant in a check. It is the most encouraging trend in the history — but it arrived after the seams had been re-cut many times.

## 3. The frontend is a genuine cost sink

Stack trajectory: Bulma POC → custom design system → big-bang rebuild (spec 008) → htmx/Alpine/idiomorph → **abandoned** → Preact SPA (011) → 5+ visual-parity rounds (012/013/016/017 + 019/050) → CSS modules (055) → shared components (056) → TanStack Query (063).

Roughly **20 of 85 specs (~23%) are frontend**, and at least three (009, 010, early parity rounds) were rework of work designed days earlier. Two complete design docs were sunk before the framework choice was made right. The visual-parity saga ground from 20 → 14 → 2 open gaps across four screenshot rounds but **never cleared sign-off**; round-1 fixes spawned fresh breakage (15 components wired to CSS classes that did not exist, rendering the fixes invisible). The frontend is ~60% of all audit volume. For a Python automation framework whose stated audience is "non-developers who drop a file in a folder," the monitoring UI has absorbed a disproportionate share of total effort — and it is the area least settled.

## 4. Validation pass — blind spots checked against code

The first synthesis leaned on the design-doc audits, which are point-in-time. Validating each candidate "blind spot" against the **live code** (2026-06-22) collapsed the list: the team had closed most of those findings faster than the docs reflected.

| Candidate gap | Verdict vs. code | Evidence |
|---|---|---|
| **Web security / auth absent** | ✅ **CONFIRMED — worse** | No auth/CSRF/rate-limit on any endpoint incl. `start`/`stop`/`reload` (`web/routes/apps.py:72-107`) and `/source` raw-code disclosure (`apps.py:135-176`); WS accepts with no handshake (`routes/ws.py`); default bind `0.0.0.0` (`config/models.py:312`); CORS `allow_credentials=True` (`app.py:57`). → **issue #1117** |
| **Performance never measured** | ✅ **CONFIRMED** | No benchmark/load/profiling infra; only a stray `perf_counter`. No baseline. → **issue #1119** |
| **Multi-instance / scale** | ⚠️ **MISFRAMED** | "Instance" = multiple instances of one app class, a fully designed feature wired through listeners, jobs, telemetry, queries. The real, narrower truth: single-process / single-loop / single-SQLite **by design** — a defensible choice for the target audience, not a blind spot. Worth an ADR, not a bug. |
| **a11y absent** | ❌ **WRONG** | 252 ARIA usages across ~66 components, skip-nav (`app.tsx:90`), focus trap, `prefers-reduced-motion`, WCAG-AA contrast in `DESIGN_RULES.md`, dedicated a11y audit + remediation PR #442. Only residual: no automated enforcement. → **issue #1118** (CI gate only) |
| **Packaging gaps** | ❌ **WRONG** | `src/hassette/py.typed` present, `uv_build` backend, current 3.11–3.14 classifiers. The audit's "py.typed missing" was stale. |
| **End-user error UX thin** | ❌ **WRONG** | `api/client.ts:26-36` parses error bodies into a typed `ApiError`; backend returns structured `detail`; `ErrorBanner`/`ErrorDisplay`/`ErrorSpotlight` system with friendly 404 special-casing. Well-built. |

**Methodology lesson:** trusting the audit corpus over the code over-reported the gaps by 4×. The audits are reliable as a record of what was *once* true; they are not a current state of the codebase. Future retrospectives should validate any structural claim against live `src/` before reporting it — the same lesson the 2026-06-19 audit reached about its own file:line claims ("unverified structural claims are leads, not facts").

This is, net, a **positive** signal about the project: it closes findings faster than its own documentation reflects. The one durable, serious gap is web security.

## 5. Two process tells

- **Spec-number collisions** (eleven, all mid-project) are the fingerprint of bursty parallel authoring outrunning the sequential numbering scheme. Most are benign (disjoint backend/frontend/docs work). The friction signals are same-area collisions — 042 (two test-infra specs), 057 (two UI-table specs), and the triple-collisions at 063 and 074, where 074's parallel async-safety specs each hand-rolled dispatch glue that 079 later had to reconcile.
- **"Ship-then-fix-the-next-day"** recurs: blocking-IO attribution shipped 66% broken and got a correctness brief the next day; the sync-handler timeout was a silent no-op for an unknown period. And the founding trigger of the whole design process was #329/#330 **passing all tests but crashing on first homelab deploy** — green CI, broken reality. That scar is why startup-races and smoke-tests got so much attention; it is a healthy lesson learned.

## 6. One-sentence version

Hassette is a fast, design-disciplined framework that **builds features faster than it consolidates structure** — so its history is a series of waves that each re-cut the same coupling, duplication, and test-infra seams, with a late and correct pivot toward encoding those invariants as linters; the frontend has quietly consumed a quarter of the effort without converging; and of the production-readiness domains a 1.0 needs most, only **web security** turned out to be a genuine, unaddressed gap once the claims were checked against code.

## Follow-up issues filed

- **#1117** — Add authentication and a safe default bind to the web API (`priority:high`, `release:v1.0.0`)
- **#1118** — Add automated accessibility enforcement (jsx-a11y lint + axe tests)
- **#1119** — Establish a performance baseline and benchmark methodology

Not filed (deliberately): the single-process/single-SQLite constraint is a design decision, better captured as an ADR than a bug if the team wants it on record.
