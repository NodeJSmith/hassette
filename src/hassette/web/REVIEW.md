# REVIEW.md — web/

## Field Propagation
When a new field is added to a domain model in `src/hassette/schemas/`, does
`src/hassette/web/mappers.py`'s mapper function include it in the response dict,
and does the corresponding model in `src/hassette/web/models.py` declare it? A
field present in the domain model but missing from either layer is silently
dropped from the API.

## WS Message Union Completeness
Does `src/hassette/web/models.py`'s `WsServerMessage` union include every
`*WsMessage` model defined in the same file? A new WS message type added below
the union definition but not included in the `Annotated[... | ...]` union will
never appear in the schema or reach the frontend.

## Telemetry Degradation Category
When a new telemetry route is added in `src/hassette/web/routes/telemetry.py`,
does it use `db_degrades_to()` or an inline `try/except TelemetryUnavailableError`?
An unguarded DB query that raises through to a 500 instead of degrading to 503
violates the web layer's DB-failure contract (see `src/hassette/web/CLAUDE.md`).

## Mapper Layer Coverage
`src/hassette/web/mappers.py` has explicit mapper functions for each
domain-to-response conversion. When a new response model is added to
`src/hassette/web/models.py`, is there a corresponding mapper — or does the
route inline `model_validate()` directly, bypassing the mapper layer?
