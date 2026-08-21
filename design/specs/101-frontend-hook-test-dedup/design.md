# Design: Deduplicate Frontend Hook Test Setup

**Date:** 2026-08-20
**Status:** archived
**Mode:** sketch

## Problem

`tools/check_duplicate_code.py` (PMD CPD-based, wired into CI as `duplicate-code`, `continue-on-error: true`) flags copy-pasted blocks that appear 3+ times across the repo. GitHub issue #1560 scopes cleanup of the flagged clusters within 17 named frontend hook test files — repeated `QueryClient`/`renderHook` setup, `vi.mock`/`vi.fn()` scaffolding, and similar boilerplate that should be extracted into shared helpers (following the existing `frontend/src/test/query-test-utils.tsx` precedent) or annotated as intentional.

## Goals

- None of the 17 target files appear in a `check_duplicate_code.py` cluster after this work.
- New shared helpers follow the existing `frontend/src/test/` naming/organization convention (`createTestQueryClient()`, `renderHookWithProviders()` in `query-test-utils.tsx`).
- Zero behavior change — this is a pure test-code refactor. Every touched test file still passes with identical assertions.
- Unblock the checker itself: `mise.toml`'s `java` tool version is missing its vendor prefix, so `mise install java` currently fails and the checker can't run locally at all.

## Functional Requirements

- **FR#1** `mise.toml`'s `java` tool entry uses the vendor-prefixed version string (`temurin-21.0.12+8.0.LTS`) so `mise install java` succeeds.
- **FR#2** Every occurrence of a flagged duplicate block within one of the 17 target files is either extracted into a named helper in `frontend/src/test/`, or wrapped in a `// dup-ignore-start: <reason>` / `// dup-ignore-end` pair with a specific, non-generic reason — never left as unaddressed literal duplication.
- **FR#3** Extracted helpers are named for what they set up (e.g. `renderInvalidatorHook`, `renderWebSocketHook`), not for the fact that they reduce duplication, and are placed in `frontend/src/test/` alongside existing helpers of the same kind (query/hook rendering helpers extend `query-test-utils.tsx`; hook-specific mock scaffolding that has no other consumer gets its own small file, e.g. `websocket-test-utils.ts`).
- **FR#4** For duplication clusters that span a target file and a non-target file (e.g. `frontend/src/utils/format.test.ts`, `frontend/src/state/store.test.ts`), only the target file's occurrence is required to change. Extracting a shared helper the non-target file could also adopt is fine, but rewriting the non-target file is out of scope.

## Acceptance Criteria

- **AC#1** `mise install java` succeeds; `uv run python tools/check_duplicate_code.py` runs to completion (verifies FR#1).
- **AC#2** Re-running `uv run python tools/check_duplicate_code.py` after all tasks land shows none of the 17 target files listed in any flagged cluster (verifies FR#2, FR#3, FR#4).
- **AC#3** `cd frontend && npm run test -- <touched files>` (or the full `npm run test`) passes with the same test count and no assertion changes for every touched file — confirms the refactor is behavior-preserving.
- **AC#4** `cd frontend && npm run typecheck && npm run lint` pass — confirms new helpers and their call sites are correctly typed and lint-clean.

## Approach

**Target files and current duplication** (from a local run of `uv run python tools/check_duplicate_code.py` after fixing `mise.toml`, filtered to blocks touching the 17 files named in issue #1560):

| File | Clusters | Notes |
|---|---|---|
| `frontend/src/hooks/use-websocket.test.ts` | ~25 | Dominant pattern: `const queryClient = createTestQueryClient(); renderHookWithProviders(() => useWebSocket(), { queryClient });` repeated near-verbatim across most `it()` blocks, plus a repeated `MockWebSocket` open/message-simulation sequence. |
| `frontend/src/hooks/use-query-invalidator.test.ts` | ~15 | Repeated `const queryClient = createTestQueryClient(); const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries"); const { rerender } = renderHookWithProviders(...)` block, varying only the query key and filter fn. |
| `frontend/src/hooks/use-telemetry-health.test.ts` | ~8 | Repeated hook-render + assertion scaffolding. |
| `frontend/src/hooks/use-scoped-query.test.ts` | ~10 | Repeated hook-render scaffolding. |
| `frontend/src/components/shared/log-table/use-log-data.test.ts` | ~6 | Repeated fixture/render scaffolding. |
| `frontend/src/components/shared/log-table/use-log-filters.test.ts` | 3 (+1 mixed) | Repeated filter-state scaffolding; one 5-line block also duplicated in `use-correct-url.test.ts` and `use-query-params.test.ts`. |
| `frontend/src/hooks/use-media-query.test.ts` | 1 | Small — 3 near-identical `matchMedia` mock setups. |
| `frontend/src/hooks/use-roving-tab-index.test.ts` | 2 | Small — repeated DOM/ref setup. |
| `frontend/src/hooks/use-query-params.test.ts` | 2 (+1 mixed) | Small — repeated `renderHook` + location-mock setup. |
| `frontend/src/hooks/use-correct-url.test.ts` | 0 own (+1 mixed) | Only appears in the mixed 3-file cluster shared with `use-log-filters.test.ts`/`use-query-params.test.ts`. |
| `frontend/src/hooks/use-relative-time.test.ts` | 0 own (+2 mixed) | Only appears in clusters mixed with `frontend/src/utils/format.test.ts`, `frontend/src/utils/time-window.test.ts`, `use-query-invalidator.test.ts`, `use-scoped-query.test.ts` — looks like a repeated fake-timer setup block. |

**Files with zero flagged clusters — no changes needed**: `use-document-title.test.ts`, `use-async-action.test.ts`, `use-manifests.test.ts`, `use-breadcrumbs.test.tsx`, `use-column-visibility.test.ts`, `use-log-table.test.tsx` (6 of the 17).

**A separate cross-cutting cluster**: a live checker run also flags a plain 5-line `import` block (lines 1-5) shared across four target files owned by four different tasks — `use-relative-time.test.ts` (T09), `use-scoped-query.test.ts` (T05), `use-telemetry-health.test.ts` (T04), and `use-websocket.test.ts` (T02). Import statements can't be "extracted into a helper" — each owning task should resolve its own file's occurrence with `// dup-ignore-start: <reason>` / `// dup-ignore-end` around the shared import lines rather than attempting an abstraction.

**Existing shared helper relevant to T07**: `frontend/src/test/mock-wouter.ts` already exports `createWouterMock()`, imported by all three of T07's target files (`use-correct-url.test.ts`, `use-query-params.test.ts`, `use-log-filters.test.ts`). Their shared flagged cluster is leftover `const mockNavigate = vi.fn(); vi.mock("wouter", () => createWouterMock({ ... }))` boilerplate wrapped around that existing helper, not a wholly new pattern — T07 should extend/wrap `mock-wouter.ts`'s existing infrastructure rather than inventing a new one. Confirm the exact zero-cluster set with a fresh checker run at task start — line numbers and cluster membership shift as earlier tasks land, so each task should re-run the checker scoped to its own file(s) rather than trusting this table's line numbers past the first task.

**Extraction pattern**: `frontend/src/test/query-test-utils.tsx` already exports `createTestQueryClient()` and `renderHookWithProviders()`. For hooks with a dominant repeated setup shape (websocket connection + mock, query-invalidator render + spy), add a small hook-specific helper that composes those two existing primitives and returns whatever the tests need to assert against (e.g. `renderWebSocketHook()` returning `{ queryClient, ws }`; `renderInvalidatorHook(filterFn, queryKey)` returning `{ queryClient, invalidateSpy, rerender }`). Put a new helper in `query-test-utils.tsx` only if it's a generic composition useful beyond one hook's tests; otherwise give it its own file in `frontend/src/test/` named after the hook (e.g. `websocket-test-utils.ts`) to avoid unrelated hooks' tests importing scaffolding they don't need.

**`dup-ignore` usage**: Reserve for cases where the "duplication" is actually meaningfully distinct test bodies that happen to token-match (e.g. near-identical but intentionally parallel test cases covering different enum values). Confirmed syntax from `tools/check_duplicate_code.py`: `// dup-ignore-start: <reason>` / `// dup-ignore-end` for a range, `// dup-ignore-file: <reason>` for a whole file. A reason is mandatory and must be specific (not "duplication is fine").

**MIXED clusters and scope**: PMD CPD's copy-paste detection is a literal/token match. Once a target file's occurrence becomes a single-line helper call instead of the original multi-line block, it stops matching the pattern the other files still contain inline, so it drops out of that cluster's flagged-occurrence list — this holds even if the cluster keeps firing among the remaining non-target files. That is an acceptable outcome per FR#4: the goal is that target files stop appearing in the checker's output, not that all duplication repo-wide disappears.

**Task decomposition**: One task per file or small file-group, ordered from largest cluster count to smallest so the two files responsible for most of the 71 clusters (`use-websocket.test.ts`, `use-query-invalidator.test.ts`) land first and establish the helper patterns smaller files can follow. Each task re-runs `uv run python tools/check_duplicate_code.py` scoped to its own file(s) before/after to get accurate line numbers and confirm clearance. Almost no task depends on another's code changes (each file's duplication is self-contained or, for mixed clusters, resolved by editing only the target file), so ordering is mostly for clarity and pattern-reuse, not correctness — with one exception: T09 (`use-relative-time.test.ts`) declares a real `depends_on` on T03 and T05, since its mixed-cluster block overlaps theirs and it needs to check whether they already extracted a matching helper before adding a duplicate one.

## Dependencies and Assumptions

- Assumes `mise install java` (a first-time JVM/Java Temurin download, ~100-200MB) succeeds in the execution environment. It already succeeded once in this session on this worktree/machine.
- The exact cluster list and line numbers will shift slightly as tasks land in sequence (each task's edits change line numbers for files it doesn't touch only if it changes overall file length elsewhere — in practice each task only edits its own file(s), so cross-file line-number drift is not expected, but same-file line-number drift within a not-yet-fully-fixed file is expected across multiple edits within one task).

## Changed Files

- `mise.toml` — modify: fix `java` tool version to include `temurin-` vendor prefix (FR#1).
- `frontend/src/hooks/use-websocket.test.ts` — modify: replace repeated setup blocks with shared helper calls.
- `frontend/src/hooks/use-query-invalidator.test.ts` — modify: replace repeated setup blocks with shared helper calls.
- `frontend/src/hooks/use-telemetry-health.test.ts` — modify: replace repeated setup blocks with shared helper calls.
- `frontend/src/hooks/use-scoped-query.test.ts` — modify: replace repeated setup blocks with shared helper calls.
- `frontend/src/components/shared/log-table/use-log-data.test.ts` — modify: replace repeated setup blocks with shared helper calls.
- `frontend/src/components/shared/log-table/use-log-filters.test.ts` — modify: replace repeated setup blocks with shared helper calls.
- `frontend/src/hooks/use-query-params.test.ts` — modify: replace repeated setup blocks with shared helper calls.
- `frontend/src/hooks/use-correct-url.test.ts` — modify: resolve its mixed-cluster occurrence.
- `frontend/src/hooks/use-media-query.test.ts` — modify: replace repeated `matchMedia` mock setup.
- `frontend/src/hooks/use-roving-tab-index.test.ts` — modify: replace repeated DOM/ref setup.
- `frontend/src/hooks/use-relative-time.test.ts` — modify: resolve its mixed-cluster occurrences.
- `frontend/src/test/query-test-utils.tsx` — modify: add generically-reusable helpers if warranted.
- `frontend/src/test/websocket-test-utils.ts` (or similarly named, hook-specific) — create: as needed per file.
