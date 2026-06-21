---
task_id: "T04"
title: "Verify HA native attribute merge, then conditionally simplify set_state"
status: "planned"
depends_on: []
implements: ["FR#11", "FR#12", "AC#7", "AC#9"]
---

## Summary
`Api._set_state` does a client-side attribute merge: it checks the entity exists, GETs the current
attributes, merges them with the submitted ones (`curr | new`), then POSTs the result. That is 2–3 HTTP
round-trips per write and opens a TOCTOU window where a concurrent write can be lost. A reviewer claims
Home Assistant's `POST /api/states/{entity_id}` already merges attributes natively, which would make the
client-side GET-and-merge redundant. This is a **verify-then-fix** task: probe a live HA instance
first; only if native merge is confirmed do we drop the client-side merge. Either way the observable
contract — "attributes not named in the call are preserved" — must hold, and the docs that state it stay
true.

## Target Files
- read: `src/hassette/api/api.py` — `set_state`/`_set_state` (`:873-923`); the GET-and-merge block is `:901-923`
- read: `docs/pages/core-concepts/api/methods.md` — documented merge contract (`:388-408`)
- read: `tests/system/test_api.py` — `test_set_state_roundtrip` (`:28-40`) and the `ha_container` fixture / `startup_context`
- modify (conditional — only if probe confirms native merge): `src/hassette/api/api.py` — remove the client-side `entity_exists` + `get_state_raw` + `curr | new` merge in `_set_state`, POST submitted attributes directly, keep new-entity creation working
- modify (conditional): `tests/system/test_api.py` — add/extend a system test asserting attribute preservation after the change
- read: `design/specs/081-design-audit-followups-1096/design.md` — Architecture item 5
- read: `design/specs/081-design-audit-followups-1096/tasks/context.md`

## Prompt
Implement item 5 from the design (`## Architecture` → "5. Verify-then-fix `Api._set_state`"). This task
has a hard gate: **do not modify `_set_state` until the probe confirms native merge.**

**Step 5a — verify (required, do this first).** Run a concrete probe against a live HA instance. The
system test suite already brings up an HA container (`ha_container` fixture + `startup_context` in
`tests/system/test_api.py`); reuse that, or use the project demo stack. The experiment:
1. Set an entity to have two attributes, e.g. `POST /api/states/sensor.probe` with
   `{"state": "on", "attributes": {"a": 1, "b": 2}}`.
2. POST again carrying only ONE attribute: `{"state": "on", "attributes": {"a": 9}}` — bypassing the
   hassette client-side merge (hit the REST endpoint directly, or use a path that doesn't pre-merge).
3. GET `sensor.probe` and observe: if `b == 2` survives → HA merges natively (CONFIRMED); if `b` is
   gone → HA replaces (NOT confirmed).

Record the result (confirmed / not-confirmed / inconclusive) with the observed payloads in the
orchestrate task trail (the executor's completion report / trail-log for this task), so the conditional
decision is auditable. If the outcome is not-confirmed, also leave a one-line code comment at the
`_set_state` merge block noting the probe result and date, so a future reader knows the round-trips are
intentional and were verified.

**Step 5b — conditional fix.** ONLY if step 5a confirms native merge:
- In `src/hassette/api/api.py`, simplify `_set_state` (`:901-923`): remove the `entity_exists` check,
  the `get_state_raw` GET, and the `curr_attributes | attributes` merge; POST the submitted
  `attributes` directly to `states/{entity_id}`. Ensure creating a brand-new entity still works
  (today the non-existent-entity path already skips the GET and POSTs directly — preserve that).
- Add/extend a system test asserting that after `set_state(entity, state, {"a": 9})` on an entity that
  had `{"a": 1, "b": 2}`, a subsequent `get_state` shows `b` preserved (the contract holds via HA's
  native merge).
- The docs (`docs/pages/core-concepts/api/methods.md:388-408`) already state the merge contract in
  observable terms — that prose stays true; touch it only if an implementation note needs updating.

If step 5a is NOT confirmed or is inconclusive: leave `_set_state` unchanged, add no production code,
and document the negative result (the round-trips are load-bearing). FR#12 is explicitly conditional —
"no change" is a valid, correct outcome.

## Focus
- This is the highest-blast-radius item (every attribute write) — which is exactly why it is gated on
  empirical evidence, not the reviewer's "probably". Do not shortcut the probe.
- The observable contract is fixed regardless of outcome: un-named attributes are preserved. If the fix
  lands, HA becomes the merge authority (also closes the TOCTOU window); if not, the client-side merge
  stays.
- New-entity creation: the current code skips the GET-merge when `entity_exists` is false and POSTs
  directly. Whatever the outcome, creating a new entity must keep working.
- Use the `tests/system/` HA container for the probe — do not ask the user to run HA manually; the
  fixture provides a live instance. Do not run unbounded `pytest -n auto`.

## Verify
- [ ] FR#11: A live-instance probe determines whether HA's `POST /api/states/{entity_id}` merges submitted attributes; the result and observed payloads are recorded in the task trail.
- [ ] FR#12: If and only if the probe confirms native merge, `_set_state` drops the client-side GET-and-merge while preserving that un-named attributes are retained; otherwise `_set_state` is unchanged.
- [ ] AC#7: The probe result is recorded; if confirmed, a system test asserts `set_state` preserves un-named attributes after the change; if not, `_set_state` is unchanged and the negative result documented.
- [ ] AC#9: The affected unit/integration suites pass for this task; core/api change — the branch-level `nox -s system`/`nox -s e2e` gate is green before push.
