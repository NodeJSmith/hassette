---
task_id: "T06"
title: "Document if_exists on the bus (docs site + snippet + migration)"
status: "done"
depends_on: ["T04"]
implements: ["FR#1", "FR#3", "FR#4", "FR#5", "FR#6", "FR#7"]
---

## Summary
Document the new `if_exists` behavior for app authors, mirroring the scheduler's docs, and
record the once-listener breaking change in the migration guide. Per design-completeness, the
docs ship in the same PR as the implementation.

## Prompt
See the design's `## Documentation Updates`.

1. **`docs/pages/core-concepts/bus/methods.md`** — add `if_exists` to the "Shared Parameters"
   table (line ~10–26) and to the "Registration" section (line ~281). Document the three values
   (`error` default, `skip`, `replace`) and their semantics, mirroring the scheduler's
   `docs/pages/core-concepts/scheduler/methods.md`. Explicitly contrast the key shapes: the
   scheduler resolves `if_exists` per **name**, the bus per **(name, topic)** — the same name on
   a different topic does not collide. Follow the project's voice guide (`.claude/rules/voice-guide.md`):
   system-as-subject, present tense, concept-page register (no "you").

2. **New snippet** — add a tested snippet under
   `docs/pages/core-concepts/bus/snippets/` (e.g. `bus_idempotent_registration.py`) showing
   idempotent registration (`if_exists="skip"`) and a hot-swap (`if_exists="replace"`),
   mirroring `docs/pages/core-concepts/scheduler/snippets/scheduler_idempotent_registration.py`.
   Include it in `methods.md` with an `--8<--` include. Snippets are Pyright-checked in CI — keep
   it type-correct and under 80 columns.

3. **`docs/pages/migration/bus.md`** — document the once-listener collision behavior change:
   two `once=True` listeners with the same name+topic now raise `DuplicateListenerError`
   (previously silent). Tell the reader what to do: use distinct names or `if_exists`.

4. **Docstrings** — ensure `on()`, `_on_internal`, `add_listener`, and the `Options` `if_exists`
   key carry clear docstrings (these are mostly written in T03; fill any gaps here), matching the
   scheduler's `add_job`/`schedule` docstring style.

`cancelled_at` is an internal telemetry column — no user-facing documentation beyond the
migration note that the telemetry DB is recreated on the schema bump (consistent with prior
bumps).

## Focus
- The docs site is mkdocs; snippets are external `.py` files included via `--8<--` and
  type-checked by Pyright in CI. A broken snippet fails CI.
- `docs/pages/migration/bus.md` already exists — this is an update, not a new file.
- Read the scheduler's existing `if_exists` docs (`scheduler/methods.md`,
  `scheduler/management.md`, `scheduler/snippets/scheduler_idempotent_registration.py`) and
  mirror their structure and depth.
- This task is documentation-only; it does not change runtime behavior. It depends on T04 so the
  documented behavior (including the once change) is final.

## Verify
- [ ] FR#1: `methods.md` documents `if_exists` (values, default `error`) in the Shared
      Parameters table and Registration section, and the new snippet is included and passes the
      Pyright snippet check.
- [ ] FR#3: `methods.md` documents `skip` semantics (idempotent registration returns the
      existing subscription) via prose and the snippet's `if_exists="skip"` example.
- [ ] FR#4: `methods.md` documents that `skip` raises on configuration drift (listing changed
      fields).
- [ ] FR#5: `methods.md` documents `replace` semantics and the (name, topic) vs name key-shape
      contrast with the scheduler.
- [ ] FR#6: `migration/bus.md` documents the once-listener collision breaking change (same
      name+topic `once=True` listeners now raise `DuplicateListenerError`).
- [ ] FR#7: `migration/bus.md` gives the path forward (use distinct names or `if_exists`) for
      the once-listener behavior change.
