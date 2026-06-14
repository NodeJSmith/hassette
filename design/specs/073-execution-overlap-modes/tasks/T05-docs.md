---
task_id: "T05"
title: "Document execution modes on the bus concept page and docstrings"
status: "planned"
depends_on: ["T02"]
implements: ["FR#2", "FR#3", "FR#5", "FR#15", "FR#20", "FR#21", "FR#22"]
---

## Summary

Document the new `mode` parameter so users can discover and use it. Add an "Execution modes" section to the bus concept page, write docstrings on the changed registration methods and `ListenerOptions`, and run the beginner persona review on the new page. Per `design-completeness.md`, docs ship with the feature, not as a follow-up. The scheduler concept-page update ships separately with #1027.

## Prompt

1. **Bus concept page** — add an "Execution modes" section to the bus docs under `docs/pages/core-concepts/bus/` (find the existing page that covers handler registration; check whether a sibling depth page like `handlers.md` or `filtering.md` is the better home, following the page-structure rules in `.claude/rules/doc-rules.md`). Cover, system-as-subject per `.claude/rules/voice-guide.md`:
   - the four modes by behavior (`single` drops re-fires while running; `restart` cancels the running invocation and starts fresh; `queued` serializes in order; `parallel` runs concurrently) (FR#2)
   - the tier-aware default — app handlers default to `single`, framework-internal listeners to `parallel` — and that an explicit `mode=` always wins (FR#3)
   - that suppressed and dropped events log at DEBUG, not WARNING (FR#5)
   - the `queued` bounded depth (newest-dropped beyond the cap)
   - that suppressed/dropped counts are live-only diagnostics (in-memory, reset on restart), visible in the monitoring UI (FR#15)
   - composition: `mode` with `debounce`/`throttle` (rate limiting governs whether an invocation starts; mode governs overlap of started invocations) (FR#20), with `once=True` (fires at most once regardless of mode) (FR#21), and with duration-hold (the guard applies at hold-expiry dispatch) (FR#22)

   All code examples must be tested snippets under the page's `snippets/` directory (CI type-checks them) — follow the `--8<--` include pattern in `.claude/rules/doc-rules.md`. Keep lines under 80 chars. Use real entity names (`binary_sensor.front_door`, etc.).

2. **Docstrings** — add `mode` parameter documentation to: the four async bus methods (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`) and their `bus/sync.py` facades, and the `ListenerOptions` class (`src/hassette/bus/listeners.py`). Note the tier default and the composition rules. If `ExecutionMode`/`ExecutionModeGuard` should appear in the generated API reference, add them to `PUBLIC_MODULES` in `tools/docs/gen_ref_pages.py`.

3. **Persona review** — run the `doc-persona-review` skill on the new/edited page(s), scoped to the page slug(s) you changed. A `lost` or `stuck-at-step-N` verdict on the new content is a blocker — fix before finishing. `followable`/`followable-with-effort` pass.

Do NOT manually edit `CHANGELOG.md` (release-please owns it). The `feat!` + `BREAKING CHANGE:` framing for the default flip lands in the PR title/body, not here.

## Focus

- Voice: concept pages use system-as-subject ("the bus drops the re-fire"), not "you" — see `.claude/rules/voice-guide.md`. Lead with what each mode does, not what it is.
- The doc must introduce `mode` as a behavior, mirror HA's terminology (users know `single`/`restart`/`queued`/`parallel` from HA YAML), and pair every limitation with a path forward.
- This is the user-facing discovery surface — the design's `design-completeness.md` says docstrings alone are insufficient for a user-facing parameter.
- The page-structure and snippet rules are in `.claude/rules/doc-rules.md`; the `doc-persona-review` requirement is in `.claude/rules/doc-rules.md` ("Verify with a Persona Review").
- Scope the page to the bus only; do not document scheduler modes (deferred to #1027).

## Verify
- [ ] FR#2: the bus concept page documents the `mode` parameter and the four modes on the registration methods, with tested snippets.
- [ ] FR#3: the page and docstrings document the tier-aware default (app→single, framework→parallel) and that explicit `mode=` wins.
- [ ] FR#5: the page states that suppressed/dropped events log at DEBUG.
- [ ] FR#15: the page documents that suppressed/dropped counts are live-only diagnostics shown in the UI.
- [ ] FR#20: the page documents `mode` composition with debounce/throttle.
- [ ] FR#21: the page documents `mode` composition with `once=True`.
- [ ] FR#22: the page documents `mode` composition with duration-hold.
- [ ] `doc-persona-review` returns a passing verdict (`followable` or `followable-with-effort`) on the new content.
