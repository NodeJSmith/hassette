# Paused: lifecycle history writers (#3678)

**Paused:** 2026-11-13, during the sketch-time re-challenge walkthrough. `design.md` stays `**Status:** draft`.

## Why it's paused

Two challenge rounds kept patching problems that come from existing code, not from the lifecycle table. Three structural gaps sit underneath the writers:

1. **App status has no single owner, and its event does two jobs.** `AppRegistry` holds every instance's status (#1605), but `HassetteAppStateEvent` is sent by hand from six sites beside the registry changes. Four sites send no `previous_status`, no STARTING event exists, some transitions send nothing, and site 198 (`app_lifecycle_start_stop.py` ~180–198) uses the same event as a UI cache re-sync, mixing new and stale failures. HA keeps "changed" and "re-send anyway" apart (`force_update`). D1's funnel and structural test, D2's dedupe map and its eviction rules, and the three meanings of `from_status` all work around this. A registry that owns transitions and records `from → to` is #1446's projector, which parent D1 left in Later without knowing about site 198's mixing or the `previous_status` gaps.
2. **Connection state has two incomplete owners.** `WebsocketService.set_connection_state` owns `ConnectionState`, which has no "waiting for HA core" state (it exists only as a ready-reason string). `OutageLog` keeps a gap/episode model built for log pacing (spec 131 D11). D4 therefore needs a third, inferred "last state written". Adding a `WAITING_FOR_CORE` state and writing rows from `set_connection_state` would remove that.
3. **The bus doesn't drain on shutdown** (`core/bus_service.py:759`), which ruled out the plain-subscriber pattern HA uses and forced D1's funnel.

D3, D5's schema shape, D6 and D7 hold either way. D1, D2, D4 and most open findings would simplify or disappear with gaps 1 and 2 fixed first.

## Where things stand

- `design.md`: D1–D7 ratified; the first challenge round and the peer check are folded in (every decision has a Peer divergence line).
- `review-log.jsonl`: the first sketch-challenge record and one sketch-comb record. The re-challenge has **no** record yet, because its findings weren't resolved.
- `rechallenge-findings.md`: the re-challenge's 13 findings, all `disposition: pending`. Finding 4 (startup outage length) was classified Auto-apply but was **not** applied. The walkthrough stopped at Finding 1, the convergence on the writers' last-row memory, which depends on gap 1.
- Research: `design/research/2026-11-13-framework-timeline/research.md` and `peer-check.md`.

## To resume

Decide first how to handle gaps 1 and 2: scope the prerequisites (a registry-owned app-transition slice of #1446 and a `WAITING_FOR_CORE` connection state), fold only the connection fix into this sketch, or ship the workarounds and file the gaps. Then re-sketch or revise D1, D2 and D4, re-run the sketch challenge, and continue at `/mine-sketch design/specs/152-lifecycle-history-writers/`.
