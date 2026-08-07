---
task_id: "T08"
title: "Document the shape views and run final verification"
status: "planned"
depends_on: ["T07"]
implements: ["AC#13", "AC#14"]
---

## Summary

Document the four value shapes and — the part that matters most — the view/projection concept they
introduce. This is the one genuinely new mental model in the change: the same entity appears under
`self.states.sensor` as a `SensorState` *and* under its shape accessor with a narrowed value type.
Every other state class corresponds 1:1 with a domain, so a reader who assumes that will be
confused. Then run the full lint and test gates across everything T01–T07 built.

## Target Files

- modify: `docs/pages/core-concepts/states/index.md`
- create: `docs/pages/core-concepts/states/snippets/sensor_shapes.py`
- read: `docs/pages/core-concepts/states/conversion.md`
- read: `docs/pages/core-concepts/states/custom-states.md`
- read: `src/hassette/models/states/sensor_shapes.py`
- read: `src/hassette/state_manager/state_manager.py`
- read: `design/specs/093-sensor-device-class-subtypes/design.md`

## Prompt

Read `context.md` first, then the design doc's `## Documentation Updates` section in full.

**Part 1 — the shapes section.**

Add a section to `docs/pages/core-concepts/states/` covering:

- The four value shapes and their `value` types.
- Both access paths: the annotation path (`D.StateNew[NumericSensorState]`) and the accessor path
  (`self.states.numeric_sensor`).
- The membership rule, including its recall gap — sensors with no metadata at all are excluded, and
  `self.states.sensor` is the escape hatch that still contains every sensor. Document this plainly;
  left unstated it reads as a bug.
- Lookup semantics on a narrowed accessor: `.get()` returns `None` for a non-member, `[]` raises
  `EntityNotInViewError`.
- That `self.states[NumericSensorState]` is unsupported, and the accessor to use instead.

**Part 2 — the view/projection concept (the priority).**

Give this explicit, prominent treatment — do not leave it implicit. State plainly that the four
narrowed accessors are **filtered views (projections) over the same underlying sensor states**, not
new domains and not a partition. The same entity appears under `self.states.sensor` (as
`SensorState`, `value: str | None`) **and** under its shape accessor (with the narrowed value type)
— two typed lenses on one state. Membership is computed from metadata per access, so a view is
dynamic where a domain accessor is total.

A short table or diagram contrasting "domain accessor" vs "shape view" across totality, value type,
membership rule, and failure behavior is the suggested form.

**Part 3 — fix the stale device_class claims.**

`docs/pages/core-concepts/states/index.md:121` says `SensorState` has
`attributes.device_class: str | None`. It is `SensorDeviceClass | None`. Line **122** has the same
error for `BinarySensorState`, which is `BinarySensorDeviceClass | None`. Fix both — they are
pre-existing and cheap to correct while editing this page.

**Part 4 — final verification (AC#13, AC#14).**

Run the full gates and fix anything they surface:

```bash
prek -a
prek pyright -a --stage pre-push
uv run pytest tests/unit tests/integration -n 4
```

Note that `prek -a` alone does not run pyright — it is a pre-push-staged hook, hence the second
command.

## Focus

**Docs snippets are executed, not just rendered.** `docs/pages/core-concepts/states/snippets/`
holds real Python files referenced by the docs pages. Follow that pattern rather than inlining large
code blocks in Markdown, and make sure any snippet you add actually type-checks — pyright runs over
the docs tree.

**Run the doc-review skills before this task is done.** Per `.claude/rules/doc-rules.md` and
CLAUDE.md's "Pre-Ship Verification for Docs Changes", any branch that edits `docs/pages/` must run
`doc-persona-review` (followability) and `doc-accuracy-review` (prose-vs-code truth), scoped to the
changed page slugs. A `lost` / `stuck-at-step-N` persona verdict or a confirmed `WRONG` /
`OUTDATED_API` accuracy finding on lines you touched is a ship blocker.

**The docstring half is already done.** T04 wrote the class docstrings, T07 added the
accessor-naming sentences and the predicate's divergence notes. This task covers the docs *site*,
which is where users discover functionality — "the docstring is enough" is explicitly not sufficient
for a user-facing feature.

**No changelog entry.** Release-please generates it from the commit messages. Do not edit
`CHANGELOG.md`.

**Frontend needs nothing.** Verified zero hits for `SensorState`, `BaseState`, or `device_class` in
`frontend/` and `openapi.json`. This qualifies for the documented exception in
`.claude/rules/design-completeness.md` — no screenshots and no type regeneration. The PR carries the
`no-visual-change` label.

**If AC#14 surfaces failures in code from earlier tasks**, fix them here rather than declaring the
task blocked — this is the gate that proves the whole change is green, and a failure it catches is
in scope for it.

## Verify

- [ ] AC#13: `prek -a` exits 0 and `prek pyright -a --stage pre-push` exits 0.
- [ ] AC#14: `uv run pytest tests/unit tests/integration -n 4` passes with no regressions.
