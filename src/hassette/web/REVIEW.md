# REVIEW.md — web/

## Field Propagation
When a new field is added to a domain model in `src/hassette/schemas/`, does
`src/hassette/web/mappers.py`'s mapper function include it in the response dict,
and does the corresponding model in `src/hassette/web/models.py` declare it? A
field present in the domain model but missing from either layer is silently
dropped from the API.

## WS Message Union Completeness
Does `src/hassette/web/models.py`'s `WsServerMessage` discriminated union include
every concrete server-message model (those with a literal `type` field) defined
in the same file? The generic `WsMessage` (unconstrained `str` discriminator) is
correctly excluded. A new concrete variant not added to the union will be absent
from the schema and unreachable by the frontend.

## Telemetry Degradation Category
When a new telemetry route is added in `src/hassette/web/routes/telemetry.py`,
does it use `db_degrades_to()` or an inline `try/except TelemetryUnavailableError`?
An unguarded DB query that raises through to a 500 instead of degrading to 503
violates the web layer's DB-failure contract (see `src/hassette/web/CLAUDE.md`).

## Mapper Layer Coverage
`src/hassette/web/mappers.py` has explicit mapper functions for domain-to-response
conversions (e.g., `system_status_response_from`, `to_listener_with_summary`).
When a new response model that converts a domain object is added to
`src/hassette/web/models.py`, is there a corresponding mapper — or does the
route inline the conversion? Models constructed directly without a domain source
(e.g., `LivenessResponse`) correctly have no mapper.
