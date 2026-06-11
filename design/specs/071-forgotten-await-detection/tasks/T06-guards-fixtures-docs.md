---
task_id: "T06"
title: "Add completeness guard, Pyright fixtures, and documentation"
status: "planned"
depends_on: ["T02", "T03", "T04", "T05"]
implements: ["FR#5", "FR#9", "FR#12", "AC#3", "AC#6", "AC#8"]
---

## Summary

Cap the feature with its cross-cutting guards and the user-facing documentation. Add the canonical
protected-method list plus a completeness test that fails if a future registration method is added
without protection; the Pyright probe fixture (simple/overloaded/`None`-returning) and the
annotation-origin guard that pins the `Coroutine[...]` return type; and the docs that recommend
Pyright (with a copy-paste config), explain the warning, and document the per-app config and the
`self.sub = coro()` shutdown-timing limitation.

## Prompt

This task runs after all method conversions (T02–T04) and the codegen wave (T05).

1. **Canonical protected-method list + completeness guard (FR#9, AC#6).** Define the canonical
   protected-method set in one place (a module-level constant the parametrized tests consume). Add a
   test that (a) iterates the list and confirms each method — primaries and two-hop delegates alike —
   emits `HassetteForgottenAwaitWarning` when its handle is dropped un-awaited (single assertion, no
   warning-type split), and (b) a **completeness/drift guard**: enumerate every public (non-`_`)
   method on `Bus`, `Scheduler`, and `Api`, assert every registration/scheduling/side-effect method
   is in the canonical list (so a future un-protected addition fails CI), and assert the documented
   exclusions (`bus.emit`, `get_state`/`get_states`/`get_entity`/`get_history`) are NOT in it. See the
   design's FR#9 for the exact membership and exclusion rationale.

2. **Pyright probe fixture (FR#5, AC#3).** Add a fixture file (type-checked in CI, mirroring the
   verification probes used during design) with bare un-awaited calls to: a simple converted method,
   the overloaded `call_service` (both the `ServiceResponse` and `None` overloads), and a bare
   `None`-returning method (`turn_on`). Assert (via `uv run pyright` exit/output, or a captured
   expected-diagnostics snapshot) that each is reported as `reportUnusedCoroutine`.

3. **Annotation-origin guard (AC#8).** Add a CI fixture/test that, for every method in the canonical
   list, resolves its return annotation (`typing.get_type_hints`) and asserts `__origin__ is
   collections.abc.Coroutine` — failing the build if a future edit narrows an annotation to
   `Awaitable`/a concrete type and silently kills the static layer.

4. **Documentation** (follow `.claude/rules/voice-guide.md` — system-as-subject on concept pages;
   `.claude/rules/doc-rules.md`). Per the design's `## Documentation Updates`:
   - `docs/pages/core-concepts/bus/`, `scheduler/`, `api/`: a short admonition that these methods
     must be awaited and that a forgotten `await` produces a `HassetteForgottenAwaitWarning` naming
     the app.
   - A "forgotten await" troubleshooting entry (extend `docs/pages/troubleshooting.md` or add a short
     page): symptom ("my handler never fires"), cause (missing `await`), fix, the assignment blind
     spot, the lingering-reference / `self.sub = coro()` **shutdown-timing** limitation (FR#12), and
     the `ERROR`-cannot-crash limitation.
   - Pyright recommendation with a **copy-paste `pyrightconfig.json` snippet** enabling
     `reportUnusedCoroutine` (note `basic` mode already turns it on; Pyright catches bare/`if`/
     overload/`None` cases; the runtime warning covers the `_ = coro()` gap).
   - `docs/pages/configuration/`: document `forgotten_await_behavior` (`IGNORE`/`WARN`/`ERROR`,
     default `WARN`, per-app with global default).
   - `AppSync`/sync docs: note the sync facades carry the same await-safety.
   - Ensure `HassetteForgottenAwaitWarning` and `ForgottenAwaitBehavior` are exported and docstringed
     if they belong in `PUBLIC_MODULES` (`tools/gen_ref_pages.py`).

Run `uv run pyright`, the new tests, and (if practical) `uv run mkdocs build` locally; confirm green.
Do NOT manually edit `CHANGELOG.md` (release-please owns it).

## Focus

- The completeness guard is the structural answer to "someone adds a new `on_*`/`run_*` method later
  and forgets to protect it" — it must enumerate by reflection over the real classes, not a
  hardcoded duplicate list, or it can drift from the canonical constant it's guarding.
- The canonical list is also consumed by AC#6's parametrized warning test (this task) — keep it the
  single source of truth.
- Two-hop delegates (`on_app_running`, `on_hassette_service_failed`, `run_in`) must be in the
  parametrized list; each still emits `HassetteForgottenAwaitWarning` because Shape B threads the
  primary's handle up.
- Pyright behavior was empirically verified during design (2026-06-11): `def -> Coroutine[Any, Any, T]`
  fires `reportUnusedCoroutine` for simple, overloaded, and `None`-returning methods;
  `-> Awaitable[T]` and `-> RegistrationHandle[T]` do NOT — which is exactly what AC#8 guards.
- Docs voice: concept/reference pages use system-as-subject (no "you"); getting-started/troubleshooting
  procedure may address the reader. Don't manufacture admonition stacks (doc-rules.md).

## Verify

- [ ] FR#5: the Pyright probe fixture confirms `reportUnusedCoroutine` fires on bare calls to a simple, an overloaded (both overloads), and a `None`-returning converted method.
- [ ] FR#9: a completeness test enumerates public Bus/Scheduler/Api methods and asserts every registration/scheduling/side-effect method is in the canonical protected list, and the documented exclusions are not — failing if a future method is added unprotected.
- [ ] FR#12: the troubleshooting docs document the `self.sub = coro()` shutdown-timing limitation and point to Pyright for the earliest signal.
- [ ] AC#3: the Pyright probe fixture covers simple + overloaded (both overloads) + `None`-returning bare calls and all are reported.
- [ ] AC#6: the parametrized test iterates the canonical list (primaries + two-hop delegates), asserts each emits `HassetteForgottenAwaitWarning` on drop, plus the completeness/exclusion drift guard.
- [ ] AC#8: a CI fixture asserts each protected method's return annotation `__origin__` is `collections.abc.Coroutine`, failing on a narrowed annotation.
