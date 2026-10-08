# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: The client floor walk doesn't check that the schema never decreases

Status: open
Recorded: 2026-10-08 (2386-take-two)
Source: ship-challenge
Reason not fixed now: out-of-scope
Affected files:
- tools/check_client_floor.py

Issue:
`find_floor_tag` walks final-release tags newest first and stops at the first tag below
`MIN_API_SCHEMA_VERSION`. That's only sound if `API_SCHEMA_VERSION` never decreases toward newer tags, and
nothing asserts it. A reverted raise would break it: the walk would stop at the reverted tag and report a
newer floor than the oldest release that actually serves the minimum, or fall back to HEAD.

Why deferred:
The bump rule only ever raises the constant, and no release has lowered it, so the walk's result is right
today.

Recommended follow-up:
Scan every reachable final-release tag rather than breaking early, fail naming the tag if
`API_SCHEMA_VERSION` ever decreases toward newer tags, and pick the oldest tag at or above the minimum.

Acceptance criteria:
- A fixture repo where the constant decreases between two tags fails with that tag named.
- A fixture repo whose constant only rises picks the same floor tag as today.

The other half of the original issue, pre-release tag ordering, is fixed (2026-10-08, #2485):
`list_release_tags` in `tools/check_wire_compat.py` orders tags by PEP 440 and drops pre-release tags, so
the walk never sees one and its order no longer depends on git's `versionsort.suffix`. The tripwire that
guarded it is gone.
