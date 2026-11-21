# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A command dropped during shutdown still answers 202

Status: open
Recorded: 2026-11-21 (4219)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/integration_service.py
- src/hassette/core/core.py

Issue:
`dispatch_command` returns `DISPATCHED` once `Hassette.send_event` returns. After the event streams close during shutdown, `send_event` drops the event with only a DEBUG line and returns normally, so the route answers 202 though no handler will run.

Why deferred:
The window is a shutdown only, and the loss is one press the user can resend after restart. Fixing it changes `send_event`'s contract for every publisher. Accepted in the ship-time challenge (Finding 6) on Jessica's standing instruction to use best judgement.

Recommended follow-up:
If commands start driving actions where a lost press matters, have `send_event` report whether it published and map a drop to a refusal in `dispatch_command`.

Acceptance criteria:
- A command sent after the event streams close answers a 409 rather than 202.

## KI-002: `GET /api/apps` grows with declared entities' attributes, with no size cap

Status: open
Recorded: 2026-11-21 (4219)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/integration/declarations.py
- src/hassette/web/routes/apps.py

Issue:
`check_attributes` only requires a JSON object, and the listing serializes every instance's entities with their attributes on every poll.

Why deferred:
No known app declares large attribute payloads; the cost is bandwidth, not correctness, and Home Assistant itself accepts large attributes. Accepted in the ship-time challenge (Finding 7).

Recommended follow-up:
If an app starts declaring large attributes or listing latency shows in the UI, add a documented byte limit to `check_attributes`.

Acceptance criteria:
- Oversized attributes raise `ValueError` from `set()` with the limit named in the docs.

## KI-003: `set_switch(on=...)` turns the switch on for any truthy non-bool

Status: open
Recorded: 2026-11-21 (4219)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- client/src/hassette_client/client.py

Issue:
`set_switch` picks `turn_on` when `on` is truthy, so an untyped caller passing `"off"` or `1` turns the switch on.

Why deferred:
It needs a caller that ignores the `bool` type hint, the result is recoverable, and no other client method checks argument types at runtime. Accepted in the ship-time challenge (Finding 8).

Recommended follow-up:
If untyped callers (scripts translating HA service data) start using `hassette-client` directly, raise `TypeError` unless `isinstance(on, bool)`.

Acceptance criteria:
- `set_switch(..., on="off")` raises `TypeError` without sending a request.
