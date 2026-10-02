## Sources Found

### Vault Go client: api/sys_health.go (verified by fetching source)
- **URL**: https://github.com/hashicorp/vault/blob/main/api/sys_health.go
- **Type**: reference implementation
- **Key takeaway**: `Sys().Health()` does NOT treat 5xx as non-errors at the transport level. It appends query params (`uninitcode`, `sealedcode`, `standbycode`, `drsecondarycode`, `performancestandbycode`, `removedcode`, `haunhealthycode` = `299`) so the SERVER remaps its status codes to a 2xx. Code comment: "If the code is 400 or above it will automatically turn into an error, but the sys/health API defaults to returning 5xx when not sealed or inited, so we force this code to be something else so we parse correctly". It then decodes the body into `HealthResponse`.
- **Relevance**: The recollection is right in outcome (body returned as data) but the mechanism matters: the generic client layer raises on >=400, and the health method works around it with a server-side status override. The server has an explicit knob for probes (real 503) vs. clients (remapped).

### Vault `sys/health` API docs
- **URL**: https://developer.hashicorp.com/vault/api-docs/system/health
- **Type**: documentation
- **Key takeaway**: Default codes 200 active, 429 standby, 472 DR secondary, 473 perf standby, 501 uninitialized, 503 sealed, 530 removed. Every one carries a JSON body (`initialized`, `sealed`, `standby`, `version`, ...). Codes are overridable via query params.
- **Relevance**: Canonical "probe returns 503 + normal status body" design; status code is for load balancers, body is for humans/clients.

### hvac (Python) health.py
- **URL**: https://github.com/hvac/hvac/blob/main/hvac/api/system_backend/health.py (docs: https://hvac.readthedocs.io/en/latest/usage/system_backend/health.html)
- **Type**: reference implementation
- **Key takeaway**: `read_health_status` calls the adapter with `raise_exception=False` for both HEAD and GET and exposes `*_code` override params (`sealed_code`, `standby_code`, ...). GET returns `response.json()`; HEAD returns the raw `requests.Response`. (The GET-returns-JSON detail comes from a search summary of hvac's source, not a line-by-line read.)
- **Relevance**: Python precedent for "return the parsed body, never raise" on a probe endpoint, implemented as a per-method opt-out of the client's raise-on-error default.

### Consul Go client api/agent.go
- **URL**: https://github.com/hashicorp/consul/blob/main/api/agent.go
- **Type**: reference implementation
- **Key takeaway**: `AgentHealthServiceByID/ByName` map 200->passing, 429->warning, 503->critical, 404->critical, and return the decoded body alongside the aggregated status for 200/429/503; any other code returns the error `Unexpected Error Code %v`.
- **Relevance**: Strongest Go precedent that 503 from a health endpoint is a VALID DATA RESULT (status enum + parsed body), not an error.

### Consul API docs: agent service health
- **URL**: https://developer.hashicorp.com/consul/api-docs/agent/service
- **Type**: documentation
- **Key takeaway**: `/agent/health/service/id|name/:x` returns 200 passing, 429 warning, 503 when at least one check is critical, with an `AggregatedStatus` body.
- **Relevance**: Server-side convention: HTTP code encodes aggregate status; body carries detail.

### python-consul base.py
- **URL**: https://github.com/cablehead/python-consul/blob/master/consul/base.py
- **Type**: reference implementation
- **Key takeaway**: `CB._status` raises `ConsulException("%d %s" % (code, body))` for any 5xx; the body is only stringified into the message. Its `health.service()` uses the generic `CB.json` path. I did not verify that python-consul wraps `/agent/health/service` at all.
- **Relevance**: Counter-example: the Python client raises on all 5xx and discards the structured body; the Go client returns it. Same server, opposite conventions.

### Kubernetes API health endpoints
- **URL**: https://kubernetes.io/docs/reference/using-api/health-checks/
- **Type**: documentation
- **Key takeaway**: "Machines that check the healthz/livez/readyz of the API server should rely on the HTTP status code"; the verbose body (`[+]ping ok`) is "intended to be used by human operators". The page shows no failing example. client-go handling was NOT verified [no source found].
- **Relevance**: Opposite end of the spectrum: body explicitly not a machine contract.

### Spring Boot Actuator health (status mapping)
- **URL**: https://docs.spring.io/spring-boot/docs/2.0.0.M6/reference/html/production-ready-monitoring.html (mapping summarized by secondary sources found via search: UP/UNKNOWN->200, DOWN/OUT_OF_SERVICE->503, configurable via `management.endpoint.health.status.http-mapping.*`)
- **Type**: documentation
- **Key takeaway**: Actuator returns 503 with the JSON body (`status` + `components`) when DOWN. I found no authoritative page on how consumers read the DOWN body [no source found for consumer-side convention].
- **Relevance**: Same shape as the probe case: 503 + normal status body; mostly consumed by orchestrators via status code only.

### Elasticsearch `_cluster/health` API docs
- **URL**: https://www.elastic.co/docs/api/doc/elasticsearch/v9/operation/operation-cluster-health
- **Type**: documentation
- **Key takeaway**: Documents only a 200 response with `status` green/yellow/red and a `timed_out` boolean. Red is still HTTP 200. The 408-on-wait_for_status-timeout claim could NOT be verified from these docs [no source found].
- **Relevance**: "Health = data in a 200" model; contrasts with Vault/Consul/Spring where status maps to the HTTP code.

### elasticsearch-py _base.py
- **URL**: https://github.com/elastic/elasticsearch-py/blob/main/elasticsearch/_sync/client/_base.py
- **Type**: reference implementation
- **Key takeaway**: Non-2xx raises `HTTP_EXCEPTIONS.get(status, ApiError)(message=..., meta=meta, body=resp_body)`; the exception carries `.body` and `.meta`. Callers can opt out per-request with `ignore_status`.
- **Relevance**: Best typed-client template for "raise, but carry the parsed body on the exception, with a per-call opt-out".

### IETF draft-inadarei-api-health-check
- **URL**: https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check
- **Type**: standard (expired Internet-Draft)
- **Key takeaway**: Media type `application/health+json`. `pass` MUST be 2xx-3xx; `warn` MUST be 2xx-3xx (with additional info); `fail` MUST be 4xx-5xx.
- **Relevance**: The closest thing to a standard says an unhealthy probe uses 5xx AND a normal status-shaped body. It says nothing about client behavior.

### Docker Engine `/_ping`
- **URL**: https://bump.sh/christophedujarric/hub/docker/doc/docker-engine-api/operation/operation-systemping
- **Type**: documentation
- **Key takeaway**: 200 `OK` text/plain with `Api-Version`, `Builder-Version`, `Swarm` headers; HEAD supported. No degraded body documented.
- **Relevance**: Minimal liveness, status-code only. Client-side `Ping()` error handling not verified [no source found].

### python-elgato (frenck HA lib)
- **URL**: https://github.com/frenck/python-elgato/blob/main/src/elgato/elgato.py
- **Type**: reference implementation
- **Key takeaway**: `_request` raises `ElgatoConnectionError` for ANY status >= 400 without reading the body.
- **Relevance**: Typical HA-ecosystem convention: non-2xx is an error. `python-matter-server`'s client (verified) uses WebSocket for server info, so it has no HTTP status handling to compare. `tailscale`, `aioesphomeapi`, `zwave-js-server-python` not checked [no source found].

### RFC 9110 section 15.6.4 (503)
- **URL**: https://httpwg.org/specs/rfc9110.html#status.503
- **Type**: standard
- **Key takeaway**: 5xx = "the server failed to fulfill an apparently valid request". 503 = "currently unable to handle the request due to a temporary overload or scheduled maintenance, which will likely be alleviated after some delay"; server MAY send `Retry-After`. My fetch tool truncated surrounding text, so a statement on whether a 5xx body is a representation of the resource was NOT verified.
- **Relevance**: Core semantic argument: 5xx means "request not fulfilled", which sits badly with a body that fulfills it with a fallback.

### RFC 9457 Problem Details
- **URL**: https://www.rfc-editor.org/rfc/rfc9457.html
- **Type**: standard
- **Key takeaway**: `application/problem+json`; `status` is "only advisory" and "Generators MUST use the same status code in the actual HTTP response, to assure that generic HTTP software that does not understand this format still behaves correctly." Clients MUST ignore unrecognized extension members.
- **Relevance**: Standard error body for 503 (with `Retry-After`); extension members can carry degraded detail.

### Google AIP-217 Unreachable resources
- **URL**: https://google.aip.dev/217
- **Type**: standard (API design guide)
- **Key takeaway**: Partial results use `repeated string unreachable` in a normal success response, with a request-side `bool return_partial_success` opt-in so the default is unchanged. If the unreachable part prevents returning any data, "the service must fail the entire request with an error".
- **Relevance**: Best-documented "200 + degraded indicator" pattern, including the rule that total failure must not be empty-as-success.

### GraphQL over HTTP spec
- **URL**: http://http-spec.graphql.org/draft/
- **Type**: standard (draft)
- **Key takeaway**: "Using 4xx and 5xx status codes when data is present and non-null is not appropriate; ... it is seen as a 'partial response' or 'partial success'." With `application/graphql-response+json`, data+errors SHOULD get 294; legacy `application/json` gets 2xx.
- **Relevance**: Explicit statement that data-bearing responses must not use 5xx, the inverse of the studied server.

### RFC 9111 (Warning header)
- **URL**: https://www.rfc-editor.org/rfc/rfc9111.html#name-warning
- **Type**: standard
- **Key takeaway**: Obsoletes `Warning` ("not widely generated or surfaced to users"). No standard replacement for "degraded".
- **Relevance**: Rules out `Warning` for the 200-with-degraded pattern; use a body field or custom header.

### RFC 5861 stale-if-error
- **URL**: https://httpwg.org/specs/rfc5861.html
- **Type**: standard
- **Key takeaway**: Caches may serve stale content on origin 5xx. The success-shaped fallback lives in the cache layer; the origin's 5xx stays an honest error.
- **Relevance**: The only recognized mechanism where a 5xx event yields a success-shaped response, and it is layered outside the origin.

### Elasticsearch search partial results (partial verification)
- **URL**: https://www.elastic.co/docs/api/doc/elasticsearch/v9/operation/operation-search
- **Type**: documentation
- **Key takeaway**: `allow_partial_search_results`: "If true and there are shard request timeouts or shard failures, the request returns partial results. If false, it returns an error with no partial results." Response fields `timed_out` / `_shards.failed` were not on the fetched page [no source found this session].
- **Relevance**: Partial success is a 2xx plus in-band indicators, with an opt-out into hard failure.

## Patterns Found

### CASE 1: Health/readiness probe endpoints

#### Pattern 1A: Return the parsed body as data (status folded into a typed result)

**Used by**: Vault Go `Sys().Health()` (299 remap), hvac `read_health_status` (`raise_exception=False`), Consul Go `AgentHealthServiceByID/Name` (503 -> `HealthCritical` + body).
**How it works**: The server uses non-2xx codes so load balancers act on the code alone, and always sends a status-shaped body. The client treats the health method as a special case: it asks the server to remap codes to 2xx (Vault Go), disables raise-on-error for the call (hvac), or maps known codes to an enum and decodes the body while still erroring on unknown codes (Consul).
**Strengths**: Uniform typed answer for healthy and unhealthy; "unhealthy" is a normal outcome of a health check, not exceptional; body detail is kept.
**Weaknesses**: Needs a per-method exception to the raise-on-error default; callers checking only "no exception" can treat 503 as healthy unless the result has an explicit status field; Vault's trick needs server support.
**Example**: https://github.com/hashicorp/vault/blob/main/api/sys_health.go ; https://github.com/hashicorp/consul/blob/main/api/agent.go

#### Pattern 1B: Raise, carrying the parsed body on the exception

**Used by**: elasticsearch-py (`ApiError.body`/`.meta`, `ignore_status` opt-out). python-consul and elgato raise too but drop the body (weaker variant).
**How it works**: Generic transport raises a typed exception for non-2xx; good implementations attach status, headers and decoded body so the caller can recover the same data as in 1A via try/except. A per-call knob converts it to 1A.
**Strengths**: Consistent with `raise_for_status` conventions; no special-case endpoints.
**Weaknesses**: "Not ready" is a routine answer for a readiness probe, so exceptions as control flow are noisy; bodies lost if not attached.
**Example**: https://github.com/elastic/elasticsearch-py/blob/main/elasticsearch/_sync/client/_base.py

#### Pattern 1C: Status code is the contract, body is advisory

**Used by**: Kubernetes `/livez` `/readyz` `/healthz`; Docker `/_ping`; the IETF draft maps `fail` to 4xx-5xx.
**How it works**: Consumers key off the HTTP code only; body is for humans.
**Strengths**: Simple, robust through proxies.
**Weaknesses**: Gives a typed client nothing to parse; only fits when the body is not a published schema.
**Example**: https://kubernetes.io/docs/reference/using-api/health-checks/

#### Pattern 1D: Health is data in a 200

**Used by**: Elasticsearch `_cluster/health` (red = 200, `timed_out` flag).
**How it works**: The endpoint reports cluster state, not request success; nothing to raise on.
**Strengths**: No client special-casing.
**Weaknesses**: LB/k8s probes cannot use it directly.
**Example**: https://www.elastic.co/docs/api/doc/elasticsearch/v9/operation/operation-cluster-health

**Case 1 conclusion**: No single convention. Server side is consistent (non-2xx plus status body: Vault, Consul, Actuator, IETF draft). Client side splits: purpose-built HashiCorp clients return the body as a typed result; generic wrappers raise (ideally with the body attached).

### CASE 2: Data/read endpoints that degrade

#### Pattern 2A: 503 + RFC 9457 problem+json (+ Retry-After)

**Used by**: RFC 9457/9110-recommended shape.
**How it works**: Honest error status, standard error body, `Retry-After`; extension members can name the failed dependency. Clients, caches, retry layers, and 5xx alerting all agree it is a failure.
**Strengths**: Matches 503 semantics; generic HTTP software behaves correctly; clients can raise a typed error.
**Weaknesses**: UI consumers get no data unless they implement their own fallback.
**Example**: https://www.rfc-editor.org/rfc/rfc9457.html

#### Pattern 2B: 2xx + partial data + in-band degraded indicator

**Used by**: Google AIP-217 (`unreachable`, `return_partial_success` opt-in), Elasticsearch search (`allow_partial_search_results`, `timed_out`, `_shards`), GraphQL (`data` + `errors`; GraphQL-over-HTTP says 4xx/5xx are not appropriate when data is present).
**How it works**: The request partly succeeded, so transport status is 2xx and the schema says what is missing. Opt-in flags keep default behavior strict. If nothing can be returned, fail with an error.
**Strengths**: Clients get usable data; degradation is explicit and typed; no HTTP-layer retry storm.
**Weaknesses**: Callers who ignore the indicator treat partial as complete; 5xx-rate monitoring does not see it, so you need metrics on the indicator. `Warning` is obsolete, so the signal must be a body field or custom header.
**Example**: https://google.aip.dev/217 ; http://http-spec.graphql.org/draft/

#### Pattern 2C: Success-shaped fallback body under 5xx (the studied behavior)

**Used by**: [no source found] as a documented convention. Nearest mechanisms: RFC 5861 `stale-if-error` (a cache serves stale as a 200 while the origin 5xx stays honest) and the probe shape (5xx + status-shaped body), but that body describes the failure, not a fallback for the requested data.
**How it works**: Server returns 503 but the body validates as the normal success schema (empty list, default model).
**Strengths**: Status code signals degradation to monitors/LBs; naive UI clients can render without branching.
**Weaknesses**: Contradicts 5xx semantics ("failed to fulfill an apparently valid request") and GraphQL-over-HTTP guidance; generic layers error on it (see anti-patterns); an empty body is indistinguishable from "legitimately empty" for clients that do parse it.

#### Pattern 2D: 206 / other codes

**Used by**: [no source found] for degraded data. 206 is defined for range requests; GraphQL-over-HTTP's 294 is a draft custom code for GraphQL only.
**Weaknesses**: Intermediaries may read 206 as a range response; not recommended.

#### How typed clients surface degraded results (observed)
- Exception with body attached: elasticsearch-py `ApiError(.body, .meta)`.
- Result wrapper / status enum: Consul Go (`HealthCritical` + body).
- In-band field on a normal result: AIP-217 `unreachable`, ES `timed_out`/`_shards`, GraphQL `errors`.
- An exception with a `.partial` attribute: [no source found].

**Case 2 conclusion**: Two recognized options: honest 503 + problem+json, or 2xx + data + explicit degraded field. 5xx + success-shaped body is not a recognized convention.

## Anti-Patterns

1. **5xx with a data-bearing success body.** GraphQL-over-HTTP: "Using 4xx and 5xx status codes when data is present and non-null is not appropriate" (http://http-spec.graphql.org/draft/). RFC 9457 requires the status code be right "to assure that generic HTTP software that does not understand this format still behaves correctly" (https://www.rfc-editor.org/rfc/rfc9457.html).
2. **Generic layers treat 5xx as failure regardless of body.** python-consul raises on any 5xx (body only in the message); elgato raises on >=400 without reading the body; elasticsearch-py raises `ApiError` unless `ignore_status`; Vault's Go client needs a 299 remap because its transport turns >=400 into an error. aiohttp/requests/httpx `raise_for_status`, proxies and CDNs were not individually tested here [no source found for proxy/CDN behavior]. A success-shaped 503 body is only reachable by code that deliberately bypasses the generic error path.
3. **Empty-as-success on total failure.** AIP-217: if nothing can be returned, "the service must fail the entire request with an error" (https://google.aip.dev/217).

## Emerging Trends

- Opt-in partial success (`return_partial_success`, `allow_partial_search_results`) so default behavior stays strict.
- GraphQL-over-HTTP moving partial responses to a dedicated 2xx-class code and distinct media type (draft).
- `Warning` header obsolete (RFC 9111); degradation signalling moves into body fields.
