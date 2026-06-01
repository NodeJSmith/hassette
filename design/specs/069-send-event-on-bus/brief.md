# Brief: Move send_event onto Bus and add ergonomic emit(topic, data)

**Date:** 2026-05-31
**Status:** explored, challenged
**Issue:** #935

## Idea

Hassette's loose-coupling broadcast primitive (local-only, in-process, fire-and-forget,
ephemeral) currently lives on `App.send_event(event)` and delegates through
`Hassette.send_event` → `EventStreamService`. Before documenting it as *the* inter-app
broadcast pattern (the docs goal of #935), we pressure-tested whether it's in the right
place with the right shape. Conclusion: move the user-facing emit onto `Bus` for
on/emit symmetry, add an ergonomic `emit(topic, data)` that builds the envelope,
keep a raw `emit_event(event)` escape hatch, and remove the old `App.send_event`.

## Key Decisions Made

- **Placement: `emit` goes on `Bus`.** This restores on/emit symmetry
  (`self.bus.on(...)` / `self.bus.emit(...)`) and matches every event-bus convention a
  user arrives with (Node EventEmitter, Vert.x, Guava, NATS — all put emit/publish and
  subscribe on the same object). The Bus is per-app (an ownership/cleanup detail) but is
  framed in docs as "your handle to Hassette's shared event bus," not "your app's private
  bus." That one-sentence framing is what keeps `self.bus.emit()` (which fans out globally)
  from reading as app-scoped.

- **Ergonomic shape: `emit(topic, data)`.** The framework wraps raw `data` in a
  `HassettePayload` + `Event`, deriving `topic` from the single argument. The old
  triple-name redundancy (`send_event("x", Event(topic="x",
  payload=HassettePayload(event_type="x", ...)))`) was eliminated by #946 and #947 —
  `send_event` now takes just an `Event`, and `HassettePayload` no longer has `event_type`.
  What `emit(topic, data)` adds on top is the envelope construction: users pass plain data
  and the framework builds the `HassettePayload` + `Event` wrapper. `emit` pairs with the
  existing `on(...)` subscribe vocabulary — the canonical EventEmitter pattern (`on`/`emit`)
  — and distinguishes the user-facing verb from the internal `send_event` primitive.

- **Raw escape hatch: `emit_event(event)`.** Keep a low-level method that takes a
  pre-built `Event` for advanced callers and internal use, where the envelope already
  exists. Mirrors the generic `on(topic=...)` sitting alongside the typed `on_*` helpers.

- **Origin stamping: REJECTED (post-challenge).** The brief originally proposed stamping
  the payload's `origin` with the sender's `instance_name`. This is wrong on two counts,
  both verified against the code:
  1. `HassettePayload.origin` is `field(default="HASSETTE", init=False)` on a frozen+slots
     dataclass (`events/base.py:108`) — not settable at construction. (The brief's claimed
     `"UNKNOWN"` default is the *base* `EventPayload`, base.py:30, not the concrete payload
     `emit` would build.)
  2. `origin` is **provenance, not sender identity.** `HassPayload.origin` is
     `Literal["LOCAL", "REMOTE"]` (HA network topology, base.py:53); `HassettePayload.origin`
     is the constant `"HASSETTE"` (the tier). Telemetry reads it — `command_executor.py:401`
     copies it into `trigger_origin`. Overwriting it would corrupt the LOCAL/REMOTE/HASSETTE
     telemetry signal.

- **Sender identity: NO framework field (post-challenge).** No new envelope/payload field for
  "who sent this." When an app cares, it carries the sender in its own data — exactly as the
  current snippet already does (`LightsSyncedData(source=self.instance_name)`). Adding a
  universal sender field is YAGNI (cf. `feedback_convenience_apis`) and the loose-coupling
  ethos (research line 167) argues for a minimal envelope.

- **Self-delivery: docs only.** An app receives its own broadcast only if it both `emit`s and
  `on`s the *same* topic — a user-side design smell, same edge EventEmitter has. A one-line
  docs warning covers it; no code mitigation needed.

- **Back-compat: clean break (confirmed post-challenge).** Delete `App.send_event` (now
  `app.py:135`) and `AppSync.send_event_sync` (`app.py:154`); route everything through
  `Bus`. The critics flagged the additive path (keep `App.send_event` as a delegate, remove
  later) as lower-regret, but the maintainer chose the clean break: the bus surface is in
  heavy flux right now, `send_event` is barely documented, and the active user base is < 5
  with near-zero probability any of them use `send_event`. Breaking now — while migration
  cost is effectively zero — beats carrying a delegate through an unstable period. Needs a
  `BREAKING CHANGE:` footer.

- **Delegation preserves guards.** `Bus.emit`/`Bus.emit_event` delegate to
  `hassette.send_event(event)`, which keeps the `event_streams_closed` / `wire_services()`
  guards (`core.py:399-406`). No direct stream writes from Bus.

## Open Questions

Resolved during the challenge pass:

- **Internal caller migration — RESOLVED: keep `hassette.send_event`.** The ~26 internal
  sites (service_watcher, app_lifecycle_service, websocket_service, file_watcher,
  command_executor, resources/mixins, base) stay on `hassette.send_event(event)` as the
  low-level primitive. `Bus` is the resource/user-facing front door only. End state: 2
  conceptual paths (internal primitive + user-facing Bus), not 3.
- **Origin / sender identity — RESOLVED: drop both** (see Key Decisions). No origin stamping,
  no new sender field, so the non-App-owner fallback question is moot.

Still open, feed `/mine.define`:

- **`data` typing.** Should `emit(topic, data)` constrain `data` (e.g. require a frozen
  dataclass, as the current example uses) or accept `Any`? Leaning `Any` / a `TypeVar`
  (constraining is likely YAGNI), but confirm.
- **Sync story.** Replace `AppSync.send_event_sync` with a `BusSyncFacade` method
  (`emit` / `emit_event`) so sync apps keep a path. Confirm naming.
- **Method names — RESOLVED.** `emit(topic, data)` + `emit_event(event)`. `emit` pairs
  canonically with the existing `on(...)` subscribe side (the EventEmitter pattern). It also
  cleanly separates user-facing vocabulary (`emit`) from the internal primitive
  (`hassette.send_event`), avoiding confusion about which layer you're calling.
- **Issue relabel (process, not design).** #935 is `type:documentation`/`size:medium`, but
  this ships a breaking `feat!`. Relabel to `type:enhancement` + `size:large` (or split the
  breaking code into its own issue) so release-please / changelog tooling isn't misled.

## Scope Boundaries

**In:**
- `Bus.emit(topic, data)` (+ sync facade equivalent).
- Removal of `App.send_event` / `AppSync.send_event_sync`.
- The docs work that #935 actually asks for: an `emit` section with broadcast semantics
  (local, in-process, fire-and-forget, ephemeral, self-delivery, ordering), a
  `emit` vs `fire_event` vs DI (#756) comparison table, the migration-guide correction,
  and the `fire_event` doc fix.
- Update the `apps_send_event.py` snippet to the new API.

**Out / deferred:**
- Targeted or scoped sends (send to a specific app). Broadcast-to-all is the model; if
  point-to-point with a contract is wanted, that's DI (#756), explicitly orthogonal.
- Schema enforcement on broadcast payloads — by design, broadcast has none (research doc
  line 167); that's the loose-coupling tradeoff.
- Persistence / replay of events across reloads — events are ephemeral; document that, do
  not build durability.
- Migrating the ~26 internal `hassette.send_event` callers to Bus (they stay on the
  internal primitive by design — see resolved question above).
- `Bus.emit_event(event)` — excluded in design phase; no named user caller exists. Add
  later if a real need emerges.

## Risks and Concerns

- **Self-delivery.** The router maps topic → listeners across all apps; `owner_id`
  is used only for cleanup, never sender exclusion (`router.py`). So an app receives its
  own broadcasts if it subscribes to a topic it also sends — same as EventEmitter/Vert.x.
  Mitigation is a docs warning, not code (a single app sending and listening on one topic
  is a user-side smell; structure topics by intent).
- **Per-app Bus vs global fan-out mismatch.** `self.bus.emit()` looks app-scoped but
  broadcasts globally. Mitigated entirely by doc framing ("shared bus"), but if the framing
  is weak the API misleads. This is a documentation risk, not a code one.
- **Breaking change timing.** Removing `App.send_event` right as the first external users
  arrive. Defensible (tiny install base, the issue itself is the trigger) but must ship
  with a clear `BREAKING CHANGE:` footer and migration note (`self.send_event(event)` →
  `self.bus.emit(topic, data)`).
- **Triple-name desync (RESOLVED by #946 + #947).** The old wart — `Event.topic`,
  `HassettePayload.event_type`, and the `event_name` parameter all carrying the same string
  independently — has been fixed upstream. `send_event` now takes just an `Event` (routes on
  `event.topic`), and `HassettePayload` no longer has `event_type`. The ergonomic `emit`
  method's remaining value is envelope construction (user passes plain data, framework
  builds `HassettePayload` + `Event`), not desync prevention.

## Challenge Summary (2026-05-31)

Four critics (premise-auditor, devils-advocate, scope-skeptic, steelman-then-break) reviewed
the brief. Resolutions:

- **CRITICAL — origin stamping impossible/wrong:** confirmed and removed (see Key Decisions).
- **Scope creep — docs issue → breaking redesign:** acknowledged. User chose to keep the
  full redesign rather than split; relabel #935 accordingly (see Open Questions).
- **`Bus` vs `App` placement / convention analogy oversold:** noted. Symmetry with
  `self.bus.on(...)` is the chosen rationale; the per-app-bus / global-fan-out framing is a
  documentation responsibility, addressed by framing the Bus as the shared medium.
- **Triple-entry-point concern (`hassette.send_event` + `bus.emit_event` + `bus.emit`):**
  mitigated by keeping internals on `hassette.send_event` and treating `bus.emit_event` as
  the single raw user hatch; revisit whether `bus.emit_event` earns its place in `/mine.define`
  (YAGNI — no named user caller yet).
- **Surviving wins:** the ergonomic `emit(topic, data)` (envelope construction convenience)
  and breaking-change timing (near-zero install base) both held under attack. The
  triple-name desync that was the original strongest justification has since been fixed
  independently by #946 + #947.

## Codebase Context

- **Call chain (post-#946):** `App.send_event(event)` (`app.py:135`) →
  `Hassette.send_event(event)` (`core.py:399`, guards: wire_services + streams-open) →
  `EventStreamService.send_event(event)` (`event_stream_service.py:47`) →
  `self._send_stream.send(event)` (memory channel). The stream now carries `Event` objects
  directly — no more `(event_name, event)` tuple.
- **HassettePayload (post-#947):** no longer has `event_type`. Fields: `data`, `event_id`,
  `time_fired`, `origin` (fixed `"HASSETTE"`, `init=False`). `HassPayload` retains
  `event_type` (HA's own field).
- **Bus is subscribe-only today:** `on`, `on_state_change`, and ~20 typed `on_*` helpers
  (`bus.py`). Zero emit methods. Sending lives on `Hassette` + `EventStreamService`.
- **Bus ownership:** created at `app.py:103` via `self.add_child(Bus, priority=0)`; parent
  is the App.
- **Fan-out:** single `BusService` consumes the receive stream and routes by `event.topic`
  match (`router.py` exact + glob buckets). All apps' listeners share the route table.
- **Internal send_event usage:** ~26 sites, all `self.hassette.send_event(prebuilt_event)`
  with `Topic.HASSETTE_EVENT_*` enums set on the Event — service_watcher,
  app_lifecycle_service, websocket_service, file_watcher, command_executor,
  resources/mixins, resources/base, test_utils.
- **Prior art / orthogonal directions:** #756 (implicit inter-app deps via `__init__`
  injection — the chosen *direct, contracted* interaction; orthogonal to broadcast). #660
  (command registry, closed, superseded by #756). #659 (typed event contracts, closed,
  conflated broadcast with contracts).
  `design/research/2026-05-02-inter-app-communication/research.md` — Layer 1 = event bus;
  line 167: broadcast events have no schema enforcement, by design.
- **Docs to fix (the #935 deliverable):** `docs/pages/migration/index.md` (the "not
  supported" line), `docs/pages/core-concepts/api/utilities.md` (`fire_event` framed as the
  inter-app path), `docs/pages/core-concepts/apps/index.md` + its
  `snippets/apps_send_event.py`.
