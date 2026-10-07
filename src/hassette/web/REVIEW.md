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

## Telemetry Failure Handling
When a route queries telemetry, does it declare `ProblemCode.TELEMETRY_UNAVAILABLE`
in `responses=problem_responses(...)` for every query it lets propagate? And does
every inline `try/except TelemetryUnavailableError` guard a query the route can
genuinely answer without (enrichment at 200, or a probe)? Catching a required
query to return an empty or default body hides an outage from the caller (see
`.claude/rules/web-api.md`).

## Mapper Layer Coverage
`src/hassette/web/mappers.py` has explicit mapper functions for domain-to-response
conversions (e.g., `app_summary_from`, `listener_summary_from`).
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

## Error Codes
Does a new error site raise `WebApiError` with a code that means exactly what
happened, rather than reusing a code whose meaning only roughly fits? Is a new
operation-specific code declared in that route's `problem_responses(...)`, and
does a new `ProblemCode` member come with a `CODE_STATUS` entry, a
`CODE_DESCRIPTIONS` entry, and a row in `docs/pages/web-ui/api-errors.md`? Does
anything change an existing code's name or status — that is a breaking change
(see `.claude/rules/web-api.md`, "Error Responses").
