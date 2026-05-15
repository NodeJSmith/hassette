---
topic: "Event data recorder for test fixtures"
date: 2026-05-15
status: Draft
---

# Prior Art: Event Data Recorder for Test Fixtures

## The Problem

Hassette's test infrastructure provides tools for simulating Home Assistant events (`SimulationMixin`, `AppTestHarness`), but every test scenario must be manually constructed — the developer writes `simulate_state_change("light.office", "on", "off", old_attrs={...})` based on what they *think* HA sends. When the real event stream has unexpected attributes, timing, or sequencing, the hand-crafted test passes but the automation breaks in production. This gap between imagined and actual event sequences is where bugs hide, particularly for complex automations like meeting room lights where multiple entities interact with timing-dependent logic.

No existing tool in the HA ecosystem records real WebSocket event streams as replayable test fixtures. HA core itself uses entirely synthetic event construction in tests. The hassette event recorder would fill a genuine gap.

## How We Do It Today

Hassette has no event recording mechanism. Tests use `AppTestHarness` with `SimulationMixin` to manually fire events through the bus. `RecordingApi` captures *output* (service calls made by automations) but not *input* (HA events that triggered them). The closest existing hook points are: (1) the `EventStreamService` memory stream where all events enter the system, (2) `BusService.serve()` where events are dispatched to listeners, and (3) `HandlerInvocationRecord` telemetry which already links event IDs to handler executions via `trigger_context_id`.

## Patterns Found

### Pattern 1: VCR/Cassette Recording (Record-Once, Replay-Forever)

**Used by**: VCR.py (Python), VCR (Ruby), pytest-recording, Betamax
**How it works**: First test run captures all network interactions to a "cassette" file. Subsequent runs replay from the cassette with no network access. Recording modes control behavior: `none` (replay only), `once` (record if no cassette), `new_episodes` (append new interactions), `all` (always re-record). Cassettes are committed to version control.

**Strengths**: Deterministic, fast test execution after recording. Cassette files document the API contract. Record-mode system makes it easy to refresh when upstream changes.

**Weaknesses**: HTTP-only in all major implementations — no WebSocket support. Cassettes can go stale silently. Request matching can be brittle. Large cassettes are hard to review in PRs.

**Example**: [VCR.py docs](https://vcrpy.readthedocs.io/en/latest/usage.html), [pytest-recording](https://github.com/kiwicom/pytest-recording)

### Pattern 2: Event Sourcing Log (Append-Only Event Store)

**Used by**: OpenHands, EventStoreDB, pyeventsourcing
**How it works**: Every state change is stored as an immutable event in an append-only log with full payload, timestamp, causality metadata (which event caused this one), and ordering guarantees. Current state is derived by replaying the log. For testing, production log segments are extracted, sanitized, and used as test input. Events are domain-level objects ("light.kitchen turned on"), not protocol-level objects (WebSocket frames).

**Strengths**: Human-readable recordings at the domain level. Causality links enable understanding *why* events happened. Natural fit for event-driven architectures. Events can be filtered, sampled, or replayed at different speeds.

**Weaknesses**: Requires an event capture layer in the application. Replaying events doesn't automatically reproduce timing-dependent behavior. Log can grow large for long sessions.

**Example**: [OpenHands Event Storage and Replay](https://deepwiki.com/All-Hands-AI/OpenHands/12.2-event-storage-and-replay)

### Pattern 3: Golden File / Snapshot Testing

**Used by**: Jest, Syrupy (Python), pytest-golden, Go testdata
**How it works**: First test run captures actual output as a "golden file." Subsequent runs compare current output against the golden file; differences fail the test. A CLI flag (`--snapshot-update`) regenerates golden files. For event recording, the golden file contains both the recorded event sequence (input) and expected automation outcomes (assertions).

**Strengths**: Self-maintaining — generated, not hand-written. Easy update workflow when behavior changes intentionally. Golden files serve as documentation. Diff-friendly for PR review.

**Weaknesses**: Risk of "golden file rot" from blind `--update` commits. Sensitive to non-determinism (timestamps, UUIDs must be normalized).

**Example**: [Syrupy](https://til.simonwillison.net/pytest/syrupy)

### Pattern 4: Proxy-Based Traffic Capture

**Used by**: mitmproxy, Charles Proxy, HAR tools
**How it works**: An external proxy sits between client and server, capturing all traffic including WebSocket frames. Recordings are saved in various formats and can be replayed. For hassette, this means running mitmproxy between hassette and HA during development, then converting captured traffic to fixtures.

**Strengths**: No code changes required. Captures full bidirectional conversation with timing. mitmproxy's Python API allows custom filtering during capture.

**Weaknesses**: External tool dependency. Adds latency. Recordings are protocol-level (raw frames), not domain-level — requires conversion. Not suitable for CI. TLS adds complexity.

**Example**: [mitmproxy WebSocket docs](https://docs.mitmproxy.org/stable/api/mitmproxy/websocket.html)

### Pattern 5: Deterministic Input Recording (Game Replay Pattern)

**Used by**: Game engines (Unity, Unreal), RR debugger, deterministic simulation frameworks
**How it works**: Only external inputs are recorded (user actions, network messages, random seeds, timestamps). If the system is deterministic, replaying the same inputs reproduces the same outputs. Minimal recording size. For hassette, the "inputs" are HA WebSocket events and wall-clock time.

**Strengths**: Tiny recordings. Perfect replay fidelity if truly deterministic. Natural regression detection — any code change producing different outputs from same inputs is flagged.

**Weaknesses**: Requires full determinism, which is hard in async Python (task scheduling, event loop ordering). Any unrecorded non-determinism source breaks fidelity. Must replay from the beginning — no fast-forward.

**Example**: [ACM — Deterministic Record and Replay](https://cacm.acm.org/practice/deterministic-record-and-replay/)

## Anti-Patterns

- **Recording at the wrong abstraction level**: Raw WebSocket frames (bytes) instead of domain events produces opaque fixtures that break on serialization changes. Record Pydantic models, not transport.
- **Ignoring timing in recordings**: Event payloads without timestamps make it impossible to test debounce, throttle, and `run_in` logic. Timestamps and ordering metadata are essential.
- **Coupling to implementation details**: Including internal framework state (listener IDs, sequence numbers) in fixtures means they break on every refactor. Record only what crosses the HA-to-hassette boundary.
- **Blind golden file updates**: Running `--update` without reviewing diffs silently accepts regressions. Require golden file diffs in PR review.

## Emerging Trends

- **Deterministic replay as a first-class testing primitive**: The May 2025 ACM article signals mainstream recognition that replay catches timing/ordering/race bugs that unit tests structurally cannot.
- **Dual-purpose event logs**: OpenHands and event-sourced systems use the same format for production and testing, eliminating format translation. Favors building the recorder into the framework.
- **AI agent trajectory replay**: Replay-based testing is being adopted in domains where behavior is complex and hard to unit-test — the same argument applies to home automations.

## Relevance to Us

Hassette is well-positioned for an in-process event tap approach:
- **Events are already Pydantic models** — serialization to JSON/YAML is nearly free via `.model_dump()`.
- **The event stream is centralized** — `EventStreamService` is the single funnel through which all HA events flow, making it a natural tap point.
- **Causality links exist** — `HandlerInvocationRecord.trigger_context_id` already tracks which event triggered which handler, enabling the recorder to capture causal chains.
- **TimeControlMixin exists** — the test infrastructure already supports time manipulation, which is needed for replay of timing-dependent logic.
- **The Bus already filters** — `BusService` has domain/entity exclusion filters that could be reused for selective recording.

The VCR/cassette UX conventions (record modes, automatic fixture naming, default-deny) are directly applicable. The event sourcing pattern (domain-level, append-only, with causality) is the right data model. The golden file pattern may be useful for the assertion side (expected outputs alongside recorded inputs).

The proxy-based approach (mitmproxy) is viable as a quick interim solution but not the long-term answer — it operates at the wrong abstraction level and requires external tooling.

## Recommendation

**Pattern 2 (Event Sourcing Log) for the data model + Pattern 1 (VCR/Cassette) for the UX**, implemented as **Pattern 7 (In-Process Event Tap)** from the web research.

Concretely:
1. **Tap the EventStreamService** — clone the receive stream to capture all events as they enter the system, before bus filtering
2. **Serialize as domain-level Pydantic models** — use `.model_dump()` to produce human-readable JSON/YAML fixtures with full attributes, timestamps, context, and ordering
3. **Adopt pytest-recording's UX conventions** — `--record-mode` CLI flag, automatic fixture naming from test paths, `none` as default mode
4. **Include timing metadata** — timestamps and inter-event deltas for replay of debounce/throttle logic
5. **Leave replay integration as a design question** — the recording format should be replay-framework-agnostic; the replay mechanism can be designed once real recordings exist and patterns emerge

The proxy approach (mitmproxy) could serve as a quick proof-of-concept to validate that real recordings expose useful test scenarios before investing in the in-process implementation.

## Sources

### Reference implementations
- [VCR.py](https://vcrpy.readthedocs.io/en/latest/) — HTTP cassette recording, gold-standard API design
- [pytest-recording](https://github.com/kiwicom/pytest-recording) — VCR.py pytest plugin with --record-mode convention
- [ObsPy VCR](https://github.com/obspy/vcr) — Socket-level recording, only Python lib that captures WebSocket in-process
- [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) — HA test fixture extraction
- [Syrupy](https://til.simonwillison.net/pytest/syrupy) — Pytest snapshot testing with --update workflow

### Blog posts & writeups
- [Record-Replay Strategy for Event-Driven Architecture (HackerNoon)](https://hackernoon.com/record-replay-strategy-for-testing-event-driven-architecture) — Kafka event recording patterns
- [Sakura Sky — Deterministic Replay for AI Agents](https://www.sakurasky.com/blog/missing-primitives-for-trustworthy-ai-part-8/) — Replay as missing testing primitive

### Documentation & standards
- [Home Assistant Testing Docs](https://developers.home-assistant.io/docs/development_testing/) — Confirms gap: no event recording in HA ecosystem
- [OpenHands Event Storage and Replay](https://deepwiki.com/All-Hands-AI/OpenHands/12.2-event-storage-and-replay) — Append-only event log with causality links
- [mitmproxy WebSocket API](https://docs.mitmproxy.org/stable/api/mitmproxy/websocket.html) — Proxy-based WebSocket capture
- [ACM — Deterministic Record and Replay (May 2025)](https://cacm.acm.org/practice/deterministic-record-and-replay/) — Survey of replay techniques and non-determinism sources
- [Django Channels WebSocket Testing](https://channels.readthedocs.io/en/stable/topics/testing.html) — WebSocket communicator API pattern
