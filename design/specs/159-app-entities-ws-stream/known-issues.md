# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A publish failure after the commit makes `set()` raise for a write that landed

Status: open
Recorded: 2026-11-22 (4220)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/integration_service.py
- src/hassette/core/runtime_query_service.py

Issue:
`set_job` commits the row, updates memory and bumps `revision` before awaiting `publish_entity_state`. If the publish raises, the app sees a failed `set()` for state that is already committed, and a retry with the same value hits the unchanged-state early return, so nothing republishes until the next poll.

Why deferred:
D2 ratified "no catch" (loud failure), and no trigger is known: the same `declared_entity_from` builds `GET /api/apps`, so any input that broke the publish would break the listing too.

Recommended follow-up:
If a publish exception is ever seen in a log or issue, fix its cause and reconsider catching and logging publish failures so they never fail the write.

Acceptance criteria:
- A publish failure, if one is found, is reproduced in a test and either fixed at its cause or no longer fails `set()`.

## KI-002: Every `set()` builds and serializes the entity message even with no `/ws` client connected

Status: open
Recorded: 2026-11-22 (4220)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/runtime_query_service.py

Issue:
`publish_entity_state` builds the wire model and `broadcast` runs a JSON round trip before it looks at the client set, inside the single writer job.

Why deferred:
The deployment the feature targets always has hass-hassette connected, and the cost hasn't been measured.

Recommended follow-up:
Return early when no client is registered (reading the set before any await), if profiling shows the publish in write-job time.

Acceptance criteria:
- A profile of a high-rate `set()` app with no client shows no measurable publish cost.

## KI-003: `listen()` decodes every frame to read its type, and matched frames twice

Status: open
Recorded: 2026-11-22 (4220)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- client/src/hassette_client/stream.py

Issue:
`decode()` runs `json.loads` on every frame to read `type`, then `parse_payload` decodes a matched frame's text again.

Why deferred:
Microseconds per frame at hass-hassette's rates; removing it adds a second parse path beside `parse_payload`'s error mapping.

Recommended follow-up:
Validate matched frames from the already-decoded dict if profiling on a busy instance shows `listen`'s decoding on the HA event loop.

Acceptance criteria:
- Each frame is decoded once, with the same `ResponseValidationError` mapping.

## KI-004: Two `types=` classes sharing a `type` tag silently keep only the last one

Status: open
Recorded: 2026-11-22 (4220)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- client/src/hassette_client/stream.py

Issue:
`message_classes` builds a dict keyed by tag, so a later class overwrites an earlier one with the same tag (e.g. a message class and its subclass).

Why deferred:
No caller passes duplicates, and the outcome is a valid instance of a requested class.

Recommended follow-up:
Raise `ValueError` on a duplicate tag, ideally before a hass-hassette release depends on `listen`, since adding the check later breaks callers that pass duplicates.

Acceptance criteria:
- `listen(types=(A, A_subclass))` raises `ValueError` before connecting.
