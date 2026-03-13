# Research Brief: Startup Smoke Tests Against Real Home Assistant

**Date**: 2026-03-13
**Status**: Ready for Decision
**Proposal**: Add smoke tests that run Hassette against a real HA instance (Docker) to catch startup race conditions and protocol-level bugs that `HassetteHarness` cannot detect.
**Initiated by**: Two consecutive PRs (#329, #330) passed all tests but crashed on first homelab deploy due to startup race conditions.

---

## Context

### What prompted this

PRs #329 (CommandExecutor) and #330 (startup race fixes) both passed the full test suite locally and in CI. Both crashed immediately when deployed to the homelab. The failures were:

1. **DB race** — `register_listener()` and `register_job()` accessed `database_service.db` before migrations finished. Fixed by adding `wait_for_ready([database_service])` guards.
2. **Session race** — handlers fired via WebSocket during startup before `_create_session()` completed, causing `RuntimeError("No active session")`. Fixed with `_safe_session_id()` returning sentinel `0`, and `_persist_batch()` filtering those records.

Both bugs share the same root cause: **the full `Hassette.run_forever()` startup sequence — WebSocket connect → services initialize concurrently → session create — is never exercised in any test**.

### Current state

**HassetteHarness** (the primary integration test tool) provides real Bus, Scheduler, StateProxy, and AppHandler — but it unconditionally mocks `WebsocketService`, setting its `ready_event` immediately without any handshake. It never calls `Hassette.run_forever()`. It never creates a session. It cannot trigger the race windows between WebSocket connection and service readiness.

**CommandExecutor startup race tests** (added in #330) use `asyncio.Event` gates to simulate delayed readiness — excellent regression coverage for the specific races fixed, but not a substitute for testing the actual startup sequence.

**Existing Docker tests** (`tests/test_docker_integration.py`) spin up the Hassette container to test requirements.txt discovery. They don't connect to HA.

**hassette-examples repo** (`github.com/NodeJSmith/hassette-examples`) contains a Docker Compose setup with `homeassistant/home-assistant:stable` using the `demo:` integration — all synthetic entities, no hardware. This is the pattern to reuse. The only manual step today is generating the HA long-lived token via the web UI.

### Key constraints

- Tests must run both in CI (GitHub Actions) and locally
- Must not require real hardware or a live homelab HA
- HA token generation is currently a manual step — must be automated
- Solution should complement `HassetteHarness`, not replace it
- New test tier should be clearly marked and skippable for unit/fast-feedback runs

---

## The Startup Sequence and Its Race Windows

The full 16-service startup has three race windows where tests can pass locally but crash in production:

| Window | When it opens | When it closes | Consequence if fired |
|--------|--------------|----------------|---------------------|
| **Listener DB race** | BusService RUNNING | `register_listener_async()` completes | `listener_id=0` in invocation record |
| **Session race** | BusService RUNNING | `_create_session()` completes | `session_id=0` in invocation record |
| **DB access race** | `on_initialize()` begins | DatabaseService marks ready | `RuntimeError("Database connection not initialized")` |

The sentinels (`id=0`, `session_id=0`) and `_persist_batch()` filters were added specifically to handle races 1 and 2 silently. Race 3 is guarded by `wait_for_ready([database_service])`. **These guards work** — but only if the startup sequence actually runs in the right order. There is currently no test that verifies the full sequence fires without uncaught exceptions.

---

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|--------------|--------|------|
| Test infrastructure (HA Docker fixture) | 2–3 new files in `tests/smoke/` | Medium | Low — additive only |
| Pre-seeded HA config (token automation) | 1 new `tests/fixtures/ha-config/` dir | Medium | Low — one-time setup |
| New nox session | `noxfile.py` (+5 lines) | Small | Low |
| CI workflow | `.github/workflows/smoke-tests.yml` (new) | Small | Low |
| Hassette `run_forever()` timeout/signal handling | `src/hassette/core/core.py` | None needed | — |

No existing tests need to change. The smoke test tier is purely additive.

### What already supports this

- `tests/test_docker_integration.py` establishes the pattern: spin up container, mount volume, assert output
- `hassette-examples` Docker Compose uses `homeassistant/home-assistant:stable` + `demo:` — synthetic entities, no hardware
- Hassette's config accepts `HASSETTE__BASE_URL` and `HASSETTE__TOKEN` env vars — trivially pointed at any HA instance
- The HA WebSocket auth protocol is fully documented and already implemented in `websocket_service.py`
- HA WebSocket command `auth/long_lived_access_token` can create tokens programmatically after initial onboarding — enabling full automation

### What works against this

- HA Docker startup is slow (~10–20 seconds for first boot, ~5 seconds on subsequent runs with warm volumes)
- First-run onboarding (creating the admin user) currently requires browser interaction — must be automated via HA's onboarding API
- `pytest-docker` or `testcontainers` isn't in the current dependencies
- CI must handle Docker-in-Docker and network bridging between containers

---

## Options Evaluated

### Option A: Docker HA with pre-seeded config (Recommended)

**How it works**: Commit a minimal HA config directory (`tests/fixtures/ha-config/`) to the repo containing:
- `configuration.yaml` with `demo:` integration
- `.storage/onboarding` — pre-marks onboarding as done so HA skips the browser wizard
- `.storage/auth` — pre-seeds an admin user with a known long-lived token (hardcoded; this is test-only and grants access only to the ephemeral demo container)

On first test run, Docker Compose brings up HA with the pre-seeded config volume. Hassette connects, starts, and smoke tests assert against demo entities.

**Pre-seeding HA auth**: HA stores auth in JSON files under `.storage/`. The format is well-documented via the [Authentication API docs](https://developers.home-assistant.io/docs/auth_api/) and community research. A one-time script generates the fixture files from a known token + bcrypt hash. The token is committed to the repo (it has no value beyond a test container).

**Smoke test assertions** (minimum viable):
1. `Hassette.start()` completes without uncaught exceptions
2. `session_id` is a positive integer after startup (session created successfully)
3. Demo entities (`light.kitchen_lights`, `binary_sensor.movement_backyard`) appear in `StateProxy`
4. A state change dispatched by the demo integration triggers a registered bus handler
5. Startup log contains no `"Dropping N handler invocation record(s)"` warnings (clean startup — no sentinel records)

**Infrastructure**: New `tests/smoke/` directory + `tests/fixtures/ha-config/`. New nox session `nox -s smoke`. New CI workflow `smoke-tests.yml` (separate from `test_and_lint.yml` to avoid slowing the main feedback loop).

**Running locally**: `docker compose -f tests/smoke/docker-compose.yml up -d && nox -s smoke`

**Pros**:
- Highest fidelity — tests the exact scenario that crashed in homelab
- Reuses the pattern from `hassette-examples` which is already proven to work
- Token is static in the repo (no manual step)
- Catches HA API compatibility breaks (when HA updates its WebSocket protocol)
- CI-friendly: separate workflow, not blocking the fast unit/integration feedback loop
- Locally runnable: `nox -s smoke` or `docker compose up` + `pytest -m smoke`

**Cons**:
- Docker overhead: test suite is 20–30 seconds slower
- Pre-seeded auth files need to be generated once and kept in sync if HA's storage format changes (infrequent)
- Docker-in-Docker in CI needs careful network configuration

**Effort estimate**: Medium — 2–3 days to build the fixture, docker-compose, nox session, CI workflow, and initial smoke test file.

**Dependencies**: `pytest-docker` or `docker compose` subprocess (similar to existing docker tests).

---

### Option B: Fake HA WebSocket Server

**How it works**: Implement a lightweight Python WebSocket server (using `aiohttp` which is already a dependency) that speaks the HA WebSocket protocol:
1. Accepts connection, sends `{"type": "auth_required"}`
2. Validates `auth` message with any token
3. Accepts `subscribe_events` subscription
4. Provides `get_states` responses with fake entity data
5. Sends synthetic `state_changed` events on demand

Lives in `tests/integration/` or `test_utils/`, available as a pytest fixture.

**Pros**:
- Fast — no Docker, no real HA startup delay
- Tests the startup race windows directly (can control timing precisely)
- Can simulate edge cases: slow auth, delayed state events, connection drops mid-startup
- No pre-seeded token management
- Can be used in the existing `nox -s tests` session (not a separate tier)

**Cons**:
- Doesn't catch HA API compatibility issues (if HA changes its protocol, tests still pass)
- Higher implementation cost — must implement enough of the HA protocol to satisfy `websocket_service.py`
- Maintenance burden if HA protocol evolves
- Doesn't validate that Hassette works end-to-end against *real* HA behavior (demo entity quirks, state format variations, etc.)

**Effort estimate**: Medium — 1–2 days to implement the fake server plus tests.

**Dependencies**: No new dependencies (`aiohttp` already present).

---

### Option C: Both tiers (Fake server + Docker HA)

**How it works**: Implement Option B as fast startup-race tests in `tests/integration/`, and Option A as slower smoke tests in `tests/smoke/`. Each tier runs in its own nox session.

- `nox -s tests` — fast unit + integration including fake-HA startup race tests
- `nox -s smoke` — slow Docker HA smoke tests, run before merging significant PRs

**Pros**:
- Best coverage: race conditions tested fast + real protocol tested in Docker
- Fake HA tests can run on every commit; Docker HA runs less frequently
- Graduated confidence: green `tests` for day-to-day, green `smoke` before shipping

**Cons**:
- Higher upfront effort
- Two test tiers to maintain

**Effort estimate**: Large — 3–5 days combined.

---

## Concerns

### Technical risks

- **Pre-seeded HA auth format may drift**: HA's `.storage/auth` format is not formally versioned. If it changes in a future HA release, the fixture must be regenerated. Mitigation: pin the HA Docker image version in `docker-compose.yml`; update periodically.
- **Demo integration state is non-deterministic**: Some demo entities simulate state changes autonomously. Tests that assert specific state values may be flaky. Mitigation: assert on entity *presence* and *type*, not specific values; trigger explicit state changes for behavioral tests.
- **Docker-in-Docker in CI**: GitHub Actions supports Docker, but running Docker Compose as a test service requires careful network setup (service aliases, wait-for-ready logic). Mitigation: use GitHub Actions `services:` block with a health check, or a `pytest-docker` wait loop.

### Complexity risks

- A fake HA server (Option B) is a non-trivial implementation that must stay in sync with HA's WebSocket protocol. If the protocol changes, tests may pass while production fails — the opposite of the problem we're solving.
- A separate smoke test tier adds CI surface area. Every workflow file is something that can break independently of the code.

### Maintenance risks

- Pinning `homeassistant/home-assistant:stable` means tests follow HA's release cadence. If HA makes a breaking change to the WebSocket protocol, smoke tests will catch it — but fixing requires updating Hassette's `websocket_service.py`, not just the test infrastructure.

---

## Open Questions

- [ ] **Token provisioning**: Generating the pre-seeded `.storage/auth` JSON requires understanding the exact format (bcrypt hash of password, token hash). This needs a one-time investigation/script. Can we script it as `tests/smoke/generate_ha_fixtures.py` that runs once and commits the output?
- [ ] **HA onboarding automation**: Even with pre-seeded config, HA may re-trigger onboarding on first start. Need to verify that committing `.storage/onboarding` with `"done": true` fully suppresses the wizard.
- [ ] **CI runner resources**: Smoke tests spinning up an HA container in GitHub Actions free tier (2 CPU, 7GB RAM) — is this within resource limits? HA idles at ~300MB RAM.
- [ ] **What's the right smoke test assertion for "clean startup"?**: Option: check that `CommandExecutor._persist_batch` dropped zero sentinel records (i.e., all listeners registered before the first handler fired). This would be the definitive "startup races are gone" assertion.

---

## Recommendation

**Start with Option A (Docker HA, pre-seeded config).** Option B (fake server) is tempting but inverts the problem — we'd be maintaining a fake HA that might diverge from the real one. The reason the last two PRs failed is precisely that our mocks were too accommodating. Replacing one mock with another (even a more realistic one) doesn't fully solve that.

The `hassette-examples` repo proves the Docker HA pattern works. The `demo:` integration gives us a complete synthetic entity set with no hardware dependency. The only novel piece is automating the HA token — a one-time engineering task.

The key insight for the smoke test assertions: we don't need to test everything against real HA. We need to verify that **`Hassette.run_forever()` completes startup without uncaught exceptions, creates a session, and dispatches at least one event**. That's 3–5 test cases, not a full retest of the integration suite.

Once Option A is in place, consider adding Option B's fake HA server as a lighter-weight complement for testing startup edge cases (slow auth, connection drops) that are awkward to simulate with a real Docker container.

### Suggested next steps

1. **Prototype the pre-seeded HA config**: Write `tests/smoke/generate_ha_fixtures.py` to produce the `.storage/auth` + `.storage/onboarding` JSON files with a known token. Run once, commit the output.
2. **Write `tests/smoke/docker-compose.yml`**: Based on `hassette-examples/docker-compose.yml` — HA service + optional Hassette container. Keep it minimal.
3. **Write the smoke tests**: 5 assertions covering startup completion, session creation, entity visibility, event dispatch, and clean startup (no sentinel records dropped).
4. **Add `nox -s smoke` session**: Skipped in `test_and_lint.yml`; new `smoke-tests.yml` workflow runs it on PRs that touch `core/`, `command_executor.py`, `websocket_service.py`, or `database_service.py`.
5. **Optionally add fake HA server** in a follow-up for startup-edge-case testing (connection drop mid-auth, etc.).

---

## Sources

- [HA Authentication API docs](https://developers.home-assistant.io/docs/auth_api/) — WebSocket auth protocol and long-lived token creation
- [hassette-examples Docker Compose](https://github.com/NodeJSmith/hassette-examples) — demo HA setup this builds on
- [HA community thread: generate long-lived token via WebSocket](https://community.home-assistant.io/t/how-to-create-a-long-lived-token-programmatically-using-web-socket-username-and-password/593468) — `auth/long_lived_access_token` WebSocket command
