# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: The client floor walk doesn't order pre-release tags or check that the schema never decreases

Status: open
Recorded: 2026-10-08 (2386-take-two)
Source: ship-challenge
Reason not fixed now: out-of-scope
Affected files:
- tools/check_client_floor.py
- tools/check_wire_compat.py

Issue:
`resolve_floor_openapi` walks release tags in `git tag --sort=-v:refname` order and stops at the first tag
below `MIN_API_SCHEMA_VERSION`. git's default version sort puts `v0.57.0rc1` and `v0.57.0.dev1` above
`v0.57.0`, and the order depends on each machine's `versionsort.suffix`, so a schema raise landing between a
pre-release and its final release would end the walk early and fall back to HEAD: the check passes without
checking anything. The walk also assumes `API_SCHEMA_VERSION` never decreases along tag order (a reverted
raise breaks that), and nothing asserts it.

Why deferred:
Hassette doesn't cut pre-release tags (the last ones are `v0.18.0.dev1`–`dev3`, which predate the constant
and are never reached by the walk), so the hazard can't occur today. A tripwire makes it impossible to hit
silently: the tool fails with a pointer here if the floor walk reaches any tag that isn't a final `vX.Y.Z`
release.

Recommended follow-up:
When pre-release tags start being cut (or the tripwire fires): order tags by PEP 440 (`packaging.Version`)
instead of git's sort, scan every reachable tag rather than breaking early, fail naming the tag if
`API_SCHEMA_VERSION` ever decreases toward newer tags, pick the oldest tag at or above the minimum, and remove
the tripwire.

Acceptance criteria:
- A fixture repo with `v1.1.0rc1` (schema 1) and `v1.1.0` (schema 2) and minimum 2 picks `v1.1.0`, not HEAD.
- A fixture repo where the constant decreases between two tags fails with that tag named.
- The result is the same with and without `versionsort.suffix` configured.
