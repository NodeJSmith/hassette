---
topic: "Handling degraded HTTP 503 responses in an API and its typed client"
date: 2026-10-02
status: Draft
---

# Prior Art: Degraded 503 Responses

## The Problem

hassette's API uses 503 in two different situations. Health probes (`/api/health/ready`, `/api/telemetry/status`) return 503 plus a status body when unhealthy. About 15 data routes return 503 plus a *success-shaped fallback body* (an empty list or a default model) when the telemetry DB is unavailable. The new typed client (#2386) has to pick a rule for both cases, and the user wants that rule to follow convention, even if that means changing the server.

## How We Do It Today

- `db_degrades_to` (`src/hassette/web/dependencies.py:125`) catches `TelemetryUnavailableError` and sets status 503 on a pre-initialised default body. It has 15 call sites (telemetry ×10, apps, bus, logs, scheduler), plus an inline variant in `executions.py:79`. The body has no `degraded` flag, so a degraded 503 is identical to a healthy empty 200 except for the status code.
- `get_app_manifest` (`routes/apps.py:325`) raises a problem+json `telemetry_unavailable` 503 instead. `.claude/rules/web-api.md` calls this "Category D".
- Spec 118 decision D13 (`design/specs/118-api-problem-details/design.md:296`) kept the 503 success bodies because "these are data, not errors, and the CLI already reads them as data". It rated the decision hard to reverse.
- The consumers barely use these bodies:
  - The frontend throws `ApiError` on any non-OK response and discards the body (`frontend/src/api/client.ts:45`).
  - The CLI reads a 503 body only for `/api/telemetry/status` (`cli/commands/status.py:30`, `tolerate_503`).

## Patterns Found

### Case 1: health and readiness probes

#### 1A: Return the parsed body as data
**Used by**: Vault Go `Sys().Health()` (sends `sealedcode=299` etc. so the server remaps the status codes to 2xx), hvac `read_health_status(raise_exception=False)`, Consul Go `AgentHealthServiceByID` (maps 503 to `HealthCritical` plus the body).
**How it works**: The server keeps non-2xx codes for load balancers. The purpose-built client special-cases the health method and returns a typed status result.
**Strengths**: "Unhealthy" is a normal answer from a health check, so it isn't treated as an exception. The body detail is kept.
**Weaknesses**: Needs a per-method exception to the raise-on-error default. Safe only when the result carries an explicit status field.
**Example**: https://github.com/hashicorp/vault/blob/main/api/sys_health.go ; https://github.com/hashicorp/consul/blob/main/api/agent.go

#### 1B: Raise, with the body attached to the exception
**Used by**: elasticsearch-py (`ApiError.body`, `ignore_status` opt-out). python-consul and elgato also raise, but drop the body.
**How it works**: The generic transport raises on any non-2xx. A per-call knob turns that off.
**Strengths**: Consistent `raise_for_status` behaviour.
**Weaknesses**: Turns a routine "not ready" into exception-driven control flow.
**Example**: https://github.com/elastic/elasticsearch-py/blob/main/elasticsearch/_sync/client/_base.py

#### 1C: The status code is the contract and the body is advisory
**Used by**: Kubernetes `/readyz` `/livez`, Docker `/_ping`, IETF draft-inadarei-api-health-check.
**Weaknesses**: Gives a typed client nothing to parse.
**Example**: https://kubernetes.io/docs/reference/using-api/health-checks/

**Case 1 verdict**: Servers agree on non-2xx plus a status body, which is what hassette already does. Purpose-built clients (Vault, Consul) return the body as a typed result. Generic wrappers raise.

### Case 2: degraded data endpoints

#### 2A: 503 + RFC 9457 problem+json (+ `Retry-After`)
**Used by**: The shape RFC 9110 and RFC 9457 recommend.
**Strengths**: Matches the meaning of 503. Caches, retry layers and 5xx alerting all treat it as a failure. The client raises a typed error.
**Weaknesses**: A UI that wants to render something has to supply its own fallback.
**Example**: https://www.rfc-editor.org/rfc/rfc9457.html

#### 2B: 2xx + partial data + an explicit degraded indicator
**Used by**: Google AIP-217 (`unreachable`, opt-in `return_partial_success`), Elasticsearch search (`timed_out`, `_shards.failed`), GraphQL (`data` + `errors`).
**How it works**: The request partly succeeded, so the status is 2xx and the schema names what is missing. If nothing could be returned, the request fails outright: AIP-217 says the service "must fail the entire request with an error".
**Weaknesses**: Callers who ignore the indicator treat the result as complete, and 5xx monitoring misses it.
**Example**: https://google.aip.dev/217 ; http://http-spec.graphql.org/draft/

#### 2C: 5xx + success-shaped fallback body (hassette's current behaviour)
**Used by**: [no source found] as a documented convention.
**Weaknesses**: Contradicts the meaning of 5xx. GraphQL-over-HTTP says "Using 4xx and 5xx status codes when data is present and non-null is not appropriate". Generic HTTP layers raise on it anyway, so only code that deliberately bypasses the error path ever reads the body.

## Anti-Patterns

1. **A 5xx carrying a data-shaped success body.** See GraphQL-over-HTTP above, and RFC 9457's requirement that the status code be correct so that "generic HTTP software ... still behaves correctly".
2. **Returning an empty result as success on total failure.** AIP-217 forbids it: if nothing can be returned, fail the request.
3. **A client exception with a `.partial` attribute.** No library surveyed does this [no source found]. It is the shape the #2386 research brief proposed.

## Relevance to Us

- **Case 2:** our fallback bodies are not partial data. They are empty defaults standing in for a total failure, so 2B doesn't apply: AIP-217 says to fail. Convention points to 2A. That is the shape `get_app_manifest` already uses (`ProblemCode.TELEMETRY_UNAVAILABLE`), so the change is to make the other 15 routes match it, not to invent anything.
- **Cost of the change:** the frontend already throws on these responses and discards the body, so it has nothing to migrate beyond rendering the error. The CLI reads a 503 body only from `/api/telemetry/status`, which is a probe and stays as it is.
- **Paperwork:** it reverses spec 118 D13, so it needs a spec addendum and a changelog entry. `openapi.json` changes the 503 schemas on those routes, and `check_wire_compat.py` will flag that.
- **Case 1:** the probes already follow the server convention. Once case 2 is fixed, they are the *only* routes that return 503 with a body. The client rule then becomes simple: the probe methods (`get_ready`, `get_telemetry_status`) return their status model on 200 or 503 (pattern 1A, as Vault and Consul do), and every other non-2xx raises. `.partial`, which has no prior art, goes away entirely.

## Recommendation

1. **Server:** replace `db_degrades_to`'s fallback bodies with a 503 problem+json `telemetry_unavailable` response, matching `get_app_manifest`. Add `Retry-After` only if a retry interval is meaningful. Do this as its own PR, ahead of the client work, with an addendum to spec 118 D13.
2. **Client:** probe methods return their typed status model on 200 or 503, because the body carries an explicit `ready` or `degraded` field. Every other non-2xx raises the typed exception for its problem code. Drop `.partial` from the design.
3. **Coverage gaps:** the survey did not verify client-go's `/readyz` handling, Docker's `Ping()`, or how proxies and CDNs treat 5xx bodies.

## Sources

### Reference implementations
- https://github.com/hashicorp/vault/blob/main/api/sys_health.go — the Go client remaps health codes to 299 and returns the body
- https://github.com/hashicorp/consul/blob/main/api/agent.go — maps 503 to `HealthCritical` and decodes the body
- https://github.com/elastic/elasticsearch-py/blob/main/elasticsearch/_sync/client/_base.py — `ApiError` with the body, and `ignore_status`
- hvac `health.py` (`raise_exception=False`), python-consul `base.py` (raises on 5xx), python-elgato (raises on >=400): see web-research.md for URLs

### Documentation & standards
- https://www.rfc-editor.org/rfc/rfc9457.html — Problem Details
- RFC 9110 §15.6.4 — 503 semantics
- https://google.aip.dev/217 — unreachable resources and partial success
- http://http-spec.graphql.org/draft/ — status codes for responses that contain data
- https://kubernetes.io/docs/reference/using-api/health-checks/ — probe contract
- IETF draft-inadarei-api-health-check; Spring Boot Actuator health status mapping; RFC 9111 (Warning is obsolete); RFC 5861 (`stale-if-error`)

URLs were not live-verified. Full source notes are in web-research.md.
