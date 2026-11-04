# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A step's wait can be satisfied by a late or duplicate state from an earlier step

Status: open
Recorded: 2026-11-04 (145-live-state-model-validation)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- tests/system/test_state_models.py

Issue:
`StateRecorder.wait_for_new_state` matches any new state of the step's entity recorded after the call. If Home Assistant published a matching state for the entity after the previous step's wait completed, the next step would pass before its own call took effect, and a following call could reach HA in the wrong state and be ignored. The test still fails, but on the attribute gate rather than naming the swallowed step.

Why deferred:
The trigger needs HA to emit an out-of-sequence matching state, which the timer and helper services in the drive don't do, and the failure stays loud. The user accepted it as a known limitation at the ship-time challenge.

Recommended follow-up:
If an attribute-gate failure ever traces back to a skipped transition, correlate each step's wait to the service call's `context.id`.

Acceptance criteria:
- Each drive step's wait matches only states whose context is the step's own call.

## KI-002: On a uniformly slow runner the test can hit pytest's 120s timeout before a named step timeout

Status: open
Recorded: 2026-11-04 (145-live-state-model-validation)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- tests/system/test_state_models.py

Issue:
Each drive step waits up to `TRANSITION_TIMEOUT_SECONDS`, and the drive has many steps. A runner slow on every step without any single one exceeding the step timeout passes CI's `--timeout 120`, and pytest-timeout kills the test with a thread dump instead of the test's own "<entity> to reach <state>" message.

Why deferred:
Normal runtime is about 25s, a single hung step still fails with a named message, and a tighter step timeout would trade this for flakes on a cold runner. The user accepted it as a known limitation at the ship-time challenge.

Recommended follow-up:
If CI ever shows this test dying at the 120s harness timeout, lower the step timeout or give the test an overall deadline that reports the step it was on.

Acceptance criteria:
- A slow drive fails with a message naming the step it stalled on.

## KI-003: Cover position and number min/max model fields are always None

Status: filed (#3799)
Recorded: 2026-11-04 (145-live-state-model-validation)
Source: ship-challenge
Reason not fixed now: out-of-scope
Affected files:
- codegen/src/hassette_codegen/overrides/cover.toml
- codegen/src/hassette_codegen/overrides/number.toml
- tests/system/test_state_models.py

Issue:
HA publishes cover position as `current_position`/`current_tilt_position` and number bounds as `min`/`max`, but `CoverAttributes` and `NumberAttributes` declare `current_cover_position`, `current_cover_tilt_position`, `min_value` and `max_value` with no wire key or alias, so they never fill. The widened attribute gate found them; they are on `ATTRIBUTE_ALLOWLIST` naming #3799.

Why deferred:
The posture keeps this change test-infrastructure only; the fix changes generated public model fields and needs its own `fix:` changelog line. The user chose to allowlist and file.

Recommended follow-up:
Fix #3799, then remove the four allowlist entries so the live check pins the fix.

Acceptance criteria:
- The four fields hold HA's values, and their `ATTRIBUTE_ALLOWLIST` entries are gone.
