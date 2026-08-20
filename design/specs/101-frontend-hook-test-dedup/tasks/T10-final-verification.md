---
task_id: "T10"
title: "Final verification: confirm all 17 target files are clear of flagged duplication"
status: "planned"
depends_on: ["T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09"]
implements: ["AC#1", "AC#2", "AC#3", "AC#4"]
---

## Target Files

- (none expected — this is a verification pass. If verification finds a small leftover gap in one of T02-T09's target files, e.g. a cluster missed or a new one introduced, fix it directly in that file rather than reopening the owning task.)

## Prompt

All per-file dedup tasks (T02-T09) have landed. Run a full consolidated verification pass:

```bash
cd /home/jessica/source/hassette/.claude/worktrees/1560
uv run python tools/check_duplicate_code.py 2>&1 | tee /tmp/dup-check-final.txt
```

Check that **none** of the 17 target files appear anywhere in the output:

```bash
grep -E "frontend/src/hooks/use-(websocket|document-title|query-params|scoped-query|telemetry-health|relative-time|async-action|manifests|roving-tab-index|correct-url|media-query|query-invalidator)\.test\.ts|frontend/src/hooks/use-breadcrumbs\.test\.tsx|frontend/src/components/shared/log-table/use-(column-visibility|log-table|log-data|log-filters)\.test\.ts" /tmp/dup-check-final.txt
```

This grep should produce **no output**. If it does, identify which file(s) still have flagged clusters and whether that's a leftover from an incomplete earlier task or a new cluster introduced by this work — fix it directly if it's small and clearly in scope, or report it clearly if it needs a design decision.

Then run the full frontend suite and quality gates:

```bash
cd frontend
npm run test
npm run typecheck
npm run lint
```

All three must pass. `npm run test` should show the same total test count as before this spec's changes began (no tests were added, removed, or changed in behavior — only setup code moved).

## Verify

- [ ] AC#1: `mise install java` and `uv run python tools/check_duplicate_code.py` both still work (confirms T01's fix is durable).
- [ ] AC#2: The grep above for all 17 target files against a fresh `check_duplicate_code.py` run produces no output.
- [ ] AC#3: `cd frontend && npm run test` passes in full, with the same test count as the pre-spec baseline.
- [ ] AC#4: `cd frontend && npm run typecheck && npm run lint` both pass with zero errors.
