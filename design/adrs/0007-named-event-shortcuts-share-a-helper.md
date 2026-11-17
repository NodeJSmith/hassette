# ADR-0007: Named-event bus shortcuts share one subscribe helper; no code generation

**Status:** Accepted (2026-11-17)
**Relates to:** #2333 (split `bus.py`) · #4255 (split `testing/_simulation.py`) · #4254 (spec 156,
`on_hassette_message`) · `design/specs/071-forgotten-await-detection/design.md` (Shape A / Shape B)

## Context

Each typed event with a `Bus` convenience shortcut (`on_component_loaded`, `on_service_registered`,
`on_hassette_message`, `on_hassette_service_status`, `on_app_state_changed`) has three hand-written
pieces:

- A Shape A primary on `Bus`. Its body repeats the same steps around a few per-event values (topic,
  filter parameters and the payload paths they match, log label, method name): `_require_name`,
  build the scope predicates, `capture_registration_source()`, then `guard_await(self._subscribe(...))`
  with the same dozen keyword arguments.
- A `simulate_*` helper on the harness, which builds the event with a factory and calls
  `simulate_event`.
- A factory in `testing/_factories.py`.

The sync mirror is not part of this cost: `bus/sync_events.py` is already generated from `Bus` by
`codegen/src/hassette_codegen/sync_facade/`. The Shape B delegates (`on_homeassistant_*`,
`on_websocket_*`, `on_app_running`/`on_app_stopping`, `on_hassette_service_failed`/`crashed`/`started`)
are already one-call bodies.

Adding `on_hassette_message` in #4254 copied all three pieces and pushed `bus.py` and
`testing/_simulation.py` past the 800-line threshold. The ship-time challenge on that PR asked
whether a table of per-event values should generate the copies instead. #2333 and #4255 were
asked to settle that before splitting the files, so the split doesn't just move the duplication.

## Decision

Keep every public shortcut hand-written, and collapse the repeated Shape A body into one shared
`Bus` helper. No table, and no runtime or build-time generation.

- **Signatures and docstrings stay per method.** Users read the method they call, and the repo
  keeps full docstrings on user-facing delegates (CLAUDE.md, Code Style). The sync-facade
  generator reads these signatures, so they remain its input.
- **Each Shape A primary's body becomes:** build its scope predicates from its own filter
  arguments, then make one call to the helper with the topic, log label, method name and log
  params. The helper does `_require_name`, `capture_registration_source()`,
  `guard_await(self._subscribe(...))` and the keyword threading.
- **Callers build their own scope.** `on_service_registered` uses `P.DomainMatches` /
  `P.ServiceMatches`, `on_app_state_changed` filters on two values, and the rest match one payload
  path with `P.ValueIs(source=get_path(...))`. The helper takes the predicate list rather than a
  spec of filter paths, so irregular shortcuts need no options or exceptions in it.
- **The helper is a plain synchronous `def`, called directly from the public method.** Design/071
  requires the source capture to run while the user's frame is still on the stack.
  `capture_registration_source` skips frames from `hassette.*` modules, so the helper's own frame is
  skipped, but only if the capture runs before the public method returns its coroutine. An
  `async def` helper would capture inside the coroutine, after the user's frame is gone.
- **Exactly one `guard_await` per registration, built in the helper,** so the helper is the Shape A
  primary for these methods and the public method's `method_name` is passed through for attribution.
- **Shape B delegates, `simulate_*` helpers and factories are unchanged.** They're already thin
  (one call, or a factory plus `simulate_event`), so #4255 only moves them; it doesn't rewrite them.

## Consequences

- A new typed-event shortcut is a hand-written signature and docstring plus a body of a few
  lines, then a `simulate_*` helper and a factory. It's still three edits, but each is small and
  there's no shared body left to copy.
- The #2333 split moves the named-event primaries and the helper into the named-event mixin
  together, so the mixin starts without the duplication.
- Reading a shortcut stays one hop: the public method, then the helper. Nothing is generated or
  attached at runtime, so "where does `on_component_loaded` come from?" is answered by its `def`.
- A single regression test can cover the helper's behavior (name required, scope applied, one
  `guard_await`, source attributed to the user's call site) instead of one test per shortcut.

## Alternatives considered

- **Generate the methods at runtime from a table** (loop over specs and attach functions to `Bus`).
  Rejected: pyright and IDEs can't see attributes created at import time, so users lose the typed
  signatures and docstrings, which are why the shortcuts exist.
- **Generate source at build time from a table**, like the sync facade and the state models.
  Rejected for now. There are five Shape A primaries and new ones are rare (#4254 was the first in
  a while), and they're irregular: two filters, non-path predicates, and differing docstring
  examples. A generator would either grow per-row options or leave some methods hand-written
  beside generated ones. Revisit if typed-event shortcuts start arriving often enough that the
  three edits per event become a recurring cost.
- **Leave the bodies duplicated and only split the files.** Rejected: the split would carry the
  copies into the new mixin, which is the outcome #2333 and #4255 were asked to avoid.
