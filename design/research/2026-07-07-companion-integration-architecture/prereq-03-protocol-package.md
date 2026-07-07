# Prereq 03: `hassette-protocol` package

**Repo:** new (`hassette-protocol`) · **Blocks:** prereq-04, prereq-05, prereq-06

Shared wire contract consumed by both hassette and `hass-hassette`.

## Scope

- New repo + PyPI package. Pure Python, **zero runtime dependencies**, Python ≥3.11,
  setuptools or uv build backend (never hatchling).
- Contents:
  - Message-type string constants (`hassette/handshake`, `hassette/subscribe`,
    `hassette/entity/register`, `hassette/entity/update`, `hassette/entity/remove`,
    `hassette/sync`; reserved: `hassette/service/register`, `hassette/webhook/register`).
  - `PROTOCOL_VERSION: int` (starts at 1; additive changes do not bump).
  - `TypedDict` payload shapes for every command, response, and push envelope
    (`entity_command` / `service_call` / `webhook` kinds).
  - `StrEnum`s for platforms and entity commands.
  - State coercion pure functions (bool→`on`/`off`, numeric→str, Enum→value, None→
    unavailable; 255-char state limit enforced).
  - Canonical JSON fixtures per message type, shipped as package data — both consumer repos
    run contract tests against them.
- No pydantic, no voluptuous: hassette layers Pydantic models over these shapes in its own
  repo; the integration layers voluptuous schemas in its repo.
- Release automation (release-please or equivalent) since both consumers pin versions.
