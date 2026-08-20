# Context: Deduplicate Frontend Hook Test Setup

## Problem & Motivation

GitHub issue #1560: the `duplicate-code` CI job (`tools/check_duplicate_code.py`, PMD CPD, `continue-on-error: true` — informational, not a merge blocker) flags copy-pasted blocks (3+ occurrences) within 17 named frontend hook test files. This is scoped test-file-only cleanup — no production code changes.

## Key Decisions

1. Extract repeated setup into named helpers in `frontend/src/test/`, following the existing `createTestQueryClient()` / `renderHookWithProviders()` precedent in `query-test-utils.tsx`. Add generically-reusable helpers there; give hook-specific scaffolding its own small file (e.g. `websocket-test-utils.ts`).
2. Where extraction would be awkward (genuinely distinct test bodies that happen to token-match), use `// dup-ignore-start: <reason>` / `// dup-ignore-end` on every occurrence in the target file instead of forcing an abstraction. A reason is mandatory and must be specific.
3. For clusters that span a target file and a non-target file, only the target file's occurrence needs to change. Once it becomes a helper call, it stops literal-matching the pattern and drops out of the checker's flagged list for that cluster, even if the cluster keeps firing among the remaining non-target files — that's an acceptable outcome, not a partial fix.
4. `mise.toml`'s `java` tool entry was missing its vendor prefix (`temurin-`), which made `mise install java` fail and blocked the checker from running locally at all. This is fixed in its own task (T01) ahead of the dedup work.
5. Each task re-runs `uv run python tools/check_duplicate_code.py` scoped to its own file(s) to get accurate current line numbers — line numbers in the design doc's table are from the original scan and will have shifted.

## Constraints

- Zero behavior change. This is a pure refactor of test setup code — assertions, test names, and coverage must stay identical.
- Do not touch non-target files' internal structure. If a shared helper is useful to a non-target file too, that's a bonus, not a requirement — do not expand a task's scope to "fix" a non-target file.
- Do not invent new abstractions beyond what's needed to clear the flagged clusters in the task's own file(s). No speculative generalization.
- New helpers must be genuinely typed (no `any`), consistent with the rest of `frontend/src/test/`.
- Run `cd frontend && npm run test`, `npm run typecheck`, and `npm run lint` (scoped to touched files where practical) before considering a task done.
