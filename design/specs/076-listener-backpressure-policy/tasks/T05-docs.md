---
task_id: "T05"
title: "Document the backpressure policy on the bus concept page"
status: "done"
depends_on: ["T01", "T02", "T03", "T04"]
implements: ["FR#1", "FR#2"]
---

## Summary
Document the new `backpressure` parameter and its non-obvious properties on the bus concept page, with a
Pyright-checked snippet, and write the `BackpressurePolicy` docstrings. The docs must distinguish
dispatch-gate backpressure (global saturation) from per-listener `throttle`/`debounce` (rate), and name
the surprising behaviors: starvation under sustained load, fan-out-order sensitivity, the loud-vs-quiet
signal trade, and live-only drop counts.

## Target Files
- modify: `docs/pages/core-concepts/bus/index.md` (or the appropriate bus concept page)
- create: a snippet under `docs/pages/core-concepts/bus/snippets/` (e.g. `backpressure_drop.py`)
- modify: `src/hassette/types/enums.py` (docstrings, if not already complete from T01)
- read: `design/specs/076-listener-backpressure-policy/design.md`
- read: `design/specs/076-listener-backpressure-policy/tasks/context.md`
- read: `.claude/rules/voice-guide.md`
- read: `.claude/rules/doc-rules.md`

## Prompt
Implement the documentation per the design doc's `## Documentation Updates`.

1. **Concept page** (`docs/pages/core-concepts/bus/`): add a "Backpressure policy" section. Lead with
   what `DROP_NEWEST` does, show a minimal subscription with `backpressure="drop_newest"`, then state
   the non-obvious properties (each is in the design's Documentation Updates list):
   - **Global, not per-listener**: drops when the *whole bus* is saturated, unlike `throttle`/`debounce`
     (per-listener rate).
   - **Starvation**: a `DROP_NEWEST` listener may not run at all while the bus stays saturated; use
     `BLOCK` for must-run handlers.
   - **Fan-out order**: within one event, which `DROP_NEWEST` listeners drop depends on dispatch order.
   - **Loud vs quiet signal**: `BLOCK` propagates overload as latency; `DROP_NEWEST` converts it to
     silent loss visible only as the drop count. Use it only where loss is acceptable.
   - **Drop counts are live-only**: they reset on app reload/restart; the configured policy persists, the
     counts do not.
   Follow `.claude/rules/voice-guide.md` (system-as-subject on concept pages — no "you").

2. **Snippet**: write a runnable `.py` snippet under the page's `snippets/` directory that registers a
   listener with `backpressure="drop_newest"`, and include it via `--8<--`. It is Pyright-checked in CI,
   so it must type-check.

3. **Docstrings** (`src/hassette/types/enums.py`): ensure `BackpressurePolicy` and its members have
   docstrings whose first sentence carries the global-vs-per-listener distinction (T01 may have written
   these — verify and strengthen if needed). If `BackpressurePolicy` needs surfacing in the API
   reference, check the `PUBLIC_MODULES` allowlist in `tools/docs/gen_ref_pages.py`.

4. **Reviews**: per `.claude/rules/doc-rules.md`, run `doc-persona-review` and `doc-accuracy-review`
   scoped to the changed bus page slug before the work is considered done. A `lost`/`stuck` persona
   verdict or a confirmed `WRONG`/`OUTDATED_API` accuracy finding on the new lines is a blocker.

## Focus
- Snippets live in a `snippets/` subdir co-located with the page and are included via `--8<--`; they are
  type-checked in CI (see `.claude/rules/doc-rules.md`). Use real entity names (`sensor.power_meter`),
  keep lines under 80 chars.
- The voice on concept pages is system-as-subject ("the bus drops the event") — not "you". See
  `voice-guide.md` rule 10 and its before/after examples.
- This task documents shipped behavior, so it depends on T01-T04 being complete (the API and behavior
  must exist to document accurately).
- Do NOT manually edit `CHANGELOG.md` (release-please owns it). The PR title (`feat:`) becomes the entry.

## Verify
- [ ] FR#1: The concept page documents the `backpressure` parameter on subscriptions with a working,
  Pyright-checked snippet using `backpressure="drop_newest"`.
- [ ] FR#2: The page/docstring states that `BLOCK` is the default and that omitting `backpressure`
  preserves today's behavior.
