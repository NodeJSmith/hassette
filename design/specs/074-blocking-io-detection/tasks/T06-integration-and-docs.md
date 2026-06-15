---
task_id: "T06"
title: "End-to-end integration tests and documentation"
status: "planned"
depends_on: ["T05"]
implements: ["AC#4", "AC#6", "FR#8"]
---

## Summary
Close the loop with full-stack verification and user-facing docs. Add an integration test that proves the executor-offload invariant end to end — a sync handler doing blocking I/O produces no warning AND no `blocking_events` row — which is only verifiable once both tiers and persistence exist. Then write the concept page and config reference, and run the doc reviews the repo requires.

## Prompt
Finish the feature with integration coverage and documentation, per `design/specs/074-blocking-io-detection/design.md`, `## Documentation Updates` and the design-completeness rule.

1. **End-to-end executor-offload test** — with both tiers enabled and persistence wired, a sync handler (run via the framework executor, off the loop thread) that performs blocking I/O must produce zero blocking warnings and write zero `blocking_events` rows. This is the integration form of FR#8 / AC#4 — it requires the full stack (T03 watchdog + T04 guard + T05 persistence), which is why it lives here. Add it to `tests/integration/`.
2. **Per-app `ignore` end-to-end** — confirm that with `blocking_io_behavior='ignore'` on an app, a genuine block in that app produces no warning and no row (the total-suppression property; complements the T01 resolver unit test).
3. **Concept page** — create `docs/pages/core-concepts/blocking-io-detection.md`. Explain: what loop blocking is and why it matters on a shared loop; the two tiers (watchdog warn-after vs monkeypatch intercept+raise); the warn-vs-raise model; the dev-default / prod-opt-in posture (`allow_deep_detection_in_prod`); and the honest boundary that Tier 2 catches known primitives while Tier 1 catches C-extension blocking as lag. Follow `.claude/rules/voice-guide.md` (system-as-subject for concept pages) and `.claude/rules/doc-rules.md`. All code examples must be tested snippets (co-located `snippets/` dir, `--8<--` includes), not inline blocks. Register the new page in the docs nav and in `tools/docs/gen_ref_pages.py` `PUBLIC_MODULES` if any new public module needs reference docs.
4. **Config reference** — document `blocking_io.*` and `AppConfig.blocking_io_behavior` wherever `forgotten_await_behavior` and `asyncio_debug_mode` are documented.
5. **Docstrings** — ensure the new config fields, `BlockingIOBehavior`, `HassetteBlockingIOWarning`, and the guard module's public functions have clear docstrings (the API reference is generated from these).
6. **Run the doc reviews** — per `.claude/rules/doc-rules.md` (Verify with Persona and Accuracy Reviews), run `doc-persona-review` and `doc-accuracy-review` scoped to the new `core-concepts/blocking-io-detection` page. A `lost`/`stuck-at-step-N` persona verdict or a confirmed `WRONG`/`OUTDATED_API` accuracy finding on the new content is a blocker — fix before done.

## Focus
- This task spans `src/` tests and `docs/` — both are disjoint from other tasks' write targets, but it depends on T05 so the full stack exists.
- Frontend worktrees don't share `node_modules` — if docs build/snippet checks need it, see `.claude/rules/frontend-worktree.md`. The concept-page snippets are Pyright-checked in CI.
- `.claude/rules/design-completeness.md`: docs ship in the same PR as the feature — this task is that obligation. UI surfacing is explicitly a Non-Goal; do NOT add a monitoring-UI view for blocking events.
- Voice: concept pages use system-as-subject ("the watchdog detects...", not "you get..."). The `await_guard` / forgotten-await docs are the closest tone reference.
- Capture full test output to a tmp file; do NOT run `pytest -n auto`. Core-infra changes warrant the system/e2e nox sessions per `CLAUDE.md` "Pre-Ship Verification for Core Changes" — note that for the ship step.

## Verify
- [ ] AC#4: An integration test confirms a sync handler doing blocking I/O via the executor produces no blocking warning and no `blocking_events` row.
- [ ] AC#6: An end-to-end test confirms that an app with `blocking_io_behavior='ignore'` produces neither a warning nor a `blocking_events` row when it genuinely blocks (the row-suppression half of AC#6; the resolver half is unit-tested in T01).
- [ ] FR#8: The same integration test asserts executor-offloaded blocking is never flagged by either tier end to end.
