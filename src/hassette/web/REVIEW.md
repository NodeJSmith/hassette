# REVIEW.md — web/

## Field Propagation
When a new field is added to a domain model in `src/hassette/schemas/`, does
`src/hassette/web/mappers.py`'s mapper function include it in the response dict,
and does the corresponding response model in `hassette_wire` declare it? A
field present in the domain model but missing from either layer is silently
dropped from the API.

## WS Message Union Completeness
Does `hassette_wire`'s `WsServerMessage` discriminated union include every
concrete server-message model (those with a literal `type` field) defined in
the package? A new concrete variant not added to the union will be absent
from the schema and unreachable by the frontend.

## Telemetry Degradation Category
When a new telemetry route is added in `src/hassette/web/routes/telemetry.py`,
does it use `db_degrades_to()` or an inline `try/except TelemetryUnavailableError`?
An unguarded DB query that raises through to a 500 instead of degrading to 503
violates the web layer's DB-failure contract (see `.claude/rules/web-api.md`).

## Mapper Layer Coverage
`src/hassette/web/mappers.py` has explicit mapper functions for domain-to-response
conversions (e.g., `app_manifest_response_from`, `to_listener_with_summary`).
When a new response model that converts a domain object is added to
`hassette_wire`, is there a corresponding mapper — or does the
route inline the conversion? Models constructed directly without a domain source
(e.g., `LivenessResponse`) correctly have no mapper.

## Validated Construction of Served Models
Is every `hassette_wire` response model built through its real constructor,
never `.model_copy(update=...)`? `model_copy` bypasses validation, so an
overlay can ship a response that was never actually validated. Enforced by
`tools/check_module_boundaries.py`'s `model-copy-update` rule for `web/` and
`core/runtime_query_service.py` — if a new site under those paths needs the
pattern for a real reason, add it to `MODEL_COPY_UPDATE_SCAN_PATHS`'s
exclusions there rather than silently reintroducing the bypass.
