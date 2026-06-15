---
task_id: "T07"
title: "Document scheduler execution modes"
status: "planned"
depends_on: ["T02"]
implements: ["FR#6", "FR#7"]
---

## Summary

Document the new scheduler overlap modes on the scheduler concept page: the four modes by behavior,
the tier-aware default, the dispatch-time-reschedule consequence for overrunning jobs, the `queued`
cap, DEBUG suppression logging, the stall WARNING, and live-only counts. Add tested snippets and run
the doc reviews. This makes the `mode` parameter (FR#6) and its tier-aware default (FR#7)
discoverable — docs are how users find a user-facing parameter.

## Prompt

Implement design.md "Documentation Updates". This ships in the same PR as the feature
(design-completeness rule).

1. **Scheduler concept page** (`docs/pages/` — the scheduler concept page; see Focus to locate):
   add an "Execution modes" section covering:
   - The four modes by behavior (`single` skips overruns; `queued` serializes, bounded, newest
     dropped at cap; `restart` cancels-and-replaces; `parallel` runs concurrently).
   - The tier-aware default (app→`single`, framework→`parallel`).
   - That recurring jobs now reschedule at dispatch time, so an overrunning job fires on its grid
     and the mode governs the overlap; a within-interval job is unaffected.
   - DEBUG suppression/drop logging, the 60s stall WARNING, and that suppressed/dropped counts are
     live-only (reset on restart).
   - That `mode` is accepted on one-shot schedules but has no effect.
   Voice: system-as-subject per `.claude/rules/voice-guide.md` (concept pages, not "you").

2. **Tested snippets**: all code examples live in `.py` snippet files under the page's `snippets/`
   subdirectory and are included via `--8<--` (see `.claude/rules/doc-rules.md` "Snippets and drift
   prevention"). CI type-checks snippets via Pyright. Use real entity/job names, lines < 80 chars.

3. **Docstrings**: confirm the `schedule()`/convenience-method docstrings updated in T01 read well
   for the rendered API reference (the `mode` parameter, four values, tier default, one-shot no-op).
   `ScheduledJob`'s `mode`/`guard` fields have brief docstrings.

4. **Doc reviews** (ship blockers per `.claude/rules/doc-rules.md`): run `doc-persona-review` and
   `doc-accuracy-review` scoped to the changed page slug(s). A `lost`/`stuck-at-step-N` persona
   verdict or a confirmed `WRONG`/`OUTDATED_API` accuracy finding on touched lines blocks shipping —
   fix before done.

Do NOT touch `CHANGELOG.md` (release-please owns it). Do NOT document non-goals (no `max_instances`,
no config-level default override).

## Focus

- Locate the scheduler concept page: grep `docs/pages/` for `scheduler`, `run_every`, `Scheduler` —
  likely under `docs/pages/core-concepts/scheduler/` or similar. The bus's execution-modes section
  (added by #543) is the structural model — find it under the bus concept page and mirror its shape
  for the scheduler.
- Snippet mechanics, voice, admonition rules, and the persona/accuracy review requirement are all in
  `.claude/rules/doc-rules.md` and `.claude/rules/voice-guide.md`. Concept pages use system-as-subject.
- Behavior to document must match the FINAL implementation from T02 (Option B ordering: current fire
  always runs; trigger errors stop only future fires). This task depends on T02 for that reason.
- `mkdocs serve` to preview locally (`uv run mkdocs serve`).

## Verify

- [ ] FR#6: the scheduler concept page documents the `mode` parameter and the four modes by behavior.
- [ ] FR#7: the page documents the tier-aware default (app→single, framework→parallel); doc-persona-review and doc-accuracy-review pass on the touched lines (no `lost`/`stuck` or confirmed `WRONG`/`OUTDATED_API`).
