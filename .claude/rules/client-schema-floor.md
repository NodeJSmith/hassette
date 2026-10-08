---
paths:
  - "client/**"
  - "wire/src/**"
  - "src/hassette/web/**"
  - "tools/check_client_floor.py"
---

# hassette-client API Schema Floor

A PR that makes `hassette_client` depend on server API its floor release lacks (a new route, method or query parameter, or a response field the client now requires) raises the API schema in the same PR. The steps, and why it's one raise per release, are in the `MIN_API_SCHEMA_VERSION` docstring (`client/src/hassette_client/version.py`).

The floor release is the oldest release reporting at least `MIN_API_SCHEMA_VERSION`. `tools/check_client_floor.py` checks the client against that release's `openapi.json` on every PR and fails until the bump is made. Until a release reporting the current minimum exists, the floor is HEAD and the check passes trivially.

Rationale: `design/specs/127-hassette-client-transport/design.md`, decisions D20 and D27.
