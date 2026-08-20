---
task_id: "T02"
title: "Deduplicate setup boilerplate in use-websocket.test.ts"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#3", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- modify: `frontend/src/hooks/use-websocket.test.ts`
- create or modify: `frontend/src/test/websocket-test-utils.ts` (new — hook-specific helper file; only this hook's tests should import it)

## Prompt

`frontend/src/hooks/use-websocket.test.ts` is the largest source of flagged duplication in GitHub issue #1560 (~25 clusters). Get the authoritative current list first:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
mise install java   # one-time, may already be done — safe to re-run
uv run python tools/check_duplicate_code.py 2>&1 | grep -B1 -A1 "use-websocket.test.ts"
```

(Or just run the full checker and read the sections mentioning this file — line numbers will differ from any prior scan.)

**What you'll find**: the dominant repeated pattern is

```ts
const queryClient = createTestQueryClient();
renderHookWithProviders(() => useWebSocket(), { queryClient });
const ws = MockWebSocket.instances[0];
```

appearing near-verbatim at the start of most `it()` blocks, sometimes followed by a repeated `act(() => { ws.simulateOpen(); ws.simulateMessage({...}); })` sequence with a "connected" message payload, and sometimes preceded by `vi.useFakeTimers()`.

**Fix**: add a helper to `frontend/src/test/websocket-test-utils.ts`:

```ts
export function renderWebSocketHook(options?: { queryClient?: QueryClient }) {
  const queryClient = options?.queryClient ?? createTestQueryClient();
  const result = renderHookWithProviders(() => useWebSocket(), { queryClient });
  const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
  return { ...result, queryClient, ws };
}
```

(Adjust the exact shape to whatever the tests actually need — read the file first. `MockWebSocket` is currently defined inline in the test file; keep it there or move it into this helper file if every consumer needs it — it's currently only used by this one test file, so moving it is fine either way, use judgment based on what reads cleaner.)

For the repeated "simulate connected" sequence (open + connected message with a given `uptime_seconds`/`entity_count`/`app_count`), add a second helper, e.g. `simulateConnected(ws, overrides?)`, if 3+ tests share that exact shape.

Replace every occurrence of the flagged blocks with calls to the new helper(s). Do not change any assertions, test names, or `describe`/`it` structure — only the setup portion.

For any occurrence that turns out to be a meaningfully distinct test body that only *looks* like duplication (rare, but check before forcing an abstraction), wrap it with `// dup-ignore-start: <specific reason>` / `// dup-ignore-end` instead.

Separately, this file also appears in a plain 5-line `import`-statement cluster shared with `use-relative-time.test.ts`, `use-scoped-query.test.ts`, and `use-telemetry-health.test.ts` (see design.md's "A separate cross-cutting cluster"). Import lines can't be extracted into a helper — resolve this file's occurrence with `// dup-ignore-start: <reason>` / `// dup-ignore-end` around the shared import block.

After editing, re-run the checker scoped to this file to confirm no more clusters mention it:

```bash
uv run python tools/check_duplicate_code.py 2>&1 | grep "use-websocket.test.ts"
```

(No output for this file = clear. The overall command may still exit non-zero due to other files — that's expected and not this task's concern.)

## Verify

- [ ] FR#2/FR#3: Every previously-flagged block in this file is either extracted to a helper or `dup-ignore`d with a specific reason.
- [x] AC#2: `uv run python tools/check_duplicate_code.py` output contains no line referencing `use-websocket.test.ts` **for this file's own self-contained clusters** — accepted as met. This file's fragment of the cross-cutting 5-line import-prologue cluster (shared with T04/T05/T09's files) is `dup-ignore`d, but the checker only suppresses a cluster once every fragment across all files is ignored, so the cluster line persists until T04/T05/T09 land. This is the documented inter-task dependency from design.md's "A separate cross-cutting cluster" section, not an unresolved issue in this file.
- [ ] AC#3: `cd frontend && npm run test -- src/hooks/use-websocket.test.ts` passes with the same number of tests as before the change.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` pass with no new errors.
