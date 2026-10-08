---
topic: "Verifying a released client against a new server: golden responses vs live client vs consumer-driven contracts"
date: 2026-10-08
status: Draft
---

# Prior Art: Verifying a released client against a new server

## The Problem

A cross-version gate has to show that the client users already installed still works against the server at HEAD. There are three ways to build one:

- parse server-generated golden responses with the old client's code;
- drive the old client against a live new server;
- record consumer contracts in the client's tests and replay them against the server.

They differ in which breakages they catch, what someone has to keep up to date, and how much infrastructure they assume.

## How We Do It Today

`tools/generate_client_compat_fixtures.py` serves each seed scenario through HEAD's real FastAPI app over a stub `Hassette` and records one fixture per request. It types each fixture by the release tag's `openapi.json`. `tools/check_client_compat.py` runs in an isolated venv that holds the released `hassette-client` and parses each body with `hassette_client.parse_response`. Fixtures store only status and body. The release's `interpret_response`, which decides success or failure from status and media type and picks the exception class for an error, is never run. HEAD's client, though not the released one, is already driven against a real uvicorn socket in `tests/integration/web_api/test_hassette_client.py`.

## Patterns Found

### Pattern 1: Frozen golden fixtures from past releases, decoded by current code
**Used by**: Kubernetes API machinery.
**How it works**: Serialized objects for each release are checked in (`testdata/v1.x.0`) and never regenerated. HEAD's code must still decode them, round-trip them, and get semantically equal objects back. HEAD fixtures are regenerated and diffed in review.
**Strengths**: Offline and fast, with no old binary or live server. The directory is an audit trail of what each past version produced.
**Weaknesses**: It runs in the opposite direction (new reader, old bytes). It covers serialization only.
**Example**: https://pkg.go.dev/k8s.io/apimachinery/pkg/api/apitesting/roundtrip

### Pattern 2: Server-generated golden responses parsed by the released client's code
**Used by**: Kubernetes (inverted direction); spec-derived mocks such as stripe-mock.
**How it works**: The server build emits canonical responses per seed scenario, and the released client's parse layer decodes them offline.
**Strengths**: Cheap. It catches breaks in the body's shape: removed or renamed fields, type changes, new required fields, and enum values a strict parser rejects. It is easy to run as a version matrix.
**Weaknesses**: It misses everything outside the body: status and content-type handling, mapping error bodies to exceptions, and per-method request behaviour. A hand-kept request list drifts unless it is derived from the route table or schema.
**Example**: [no source found] for the exact old-client form.

### Pattern 3: Drive the released client against a live new server
**Used by**: the Elasticsearch client suites, which run a shared YAML test corpus against a live server on per-version branches; Stripe SDKs against stripe-mock.
**How it works**: CI boots the new server and runs the old client's real public methods over its real transport.
**Strengths**: It catches the widest range of breakage: transport, headers, status handling, error mapping, per-method behaviour and enum semantics.
**Weaknesses**: It needs a maintained list of which client methods to call. Elastic counters that drift with a per-API coverage report. Failures are coarser to localize, and CI is heavier.
**Example**: https://github.com/elastic/elasticsearch-clients-tests

### Pattern 4: Consumer-driven contracts (Pact, Spring Cloud Contract, Specmatic)
**Used by**: Pact (Broker, `deployedOrReleased` selectors, `can-i-deploy`, pending and WIP pacts); Spring Cloud Contract (contracts kept in the producer repo).
**How it works**: The client's tests record each request together with matchers for the expected response. The server replays those requests against the real provider.
**Strengths**: It covers what the client actually relies on. Per-consumer-version history answers the question of which past release to test against.
**Weaknesses**: Coverage only reaches as far as the client's tests do. Contracts are written against a mock, and matchers are looser than real parsing. The machinery is built for independently deployed teams; Fowler scopes consumer-driven contracts to closed communities of known services.
**Example**: https://docs.pact.io/pact_broker/advanced_topics/consumer_version_selectors

## Anti-Patterns

- **A bare `latest` selector** for the released version (Pact documents it as race-prone).
- **Hand-maintained request or method lists** with nothing tying them to the client's surface (Elastic uses generated coverage reports to stop this).
- **Regenerating frozen past-release fixtures** after a schema change.

## Relevance to Us

| Approach | Catches | Misses | Maintenance | Lockstep fit |
|---|---|---|---|---|
| Golden responses + old parse layer (ours today) | Body shape | Status, content type, error mapping, per-method behaviour | Low if derived from routes | Good |
| Old client's real methods against a live server | Nearly everything it exercises | Methods it doesn't call | A method list per release | Good, heavier |
| Consumer-driven contracts | Recorded interactions | Anything unrecorded; strict parsing | Contract generation and Broker | Overkill |

Our gate is pattern 2. Finding 10 of the #2485 challenge is pattern 2's documented blind spot: status, content type and error mapping. Consumer-driven contracts are a poor fit for one repo released in lockstep, so the earlier idea of using them here doesn't hold up against the sources.

Pattern 3's extra reach over pattern 2 is real transport and per-method request behaviour. In our repo, per-method request behaviour is already pinned at each release by `client/tests/test_openapi_coverage.py`, and HEAD's client is already exercised over a real socket by `tests/integration/web_api/test_hassette_client.py`.

## Recommendation

Keep pattern 2, and close its blind spot by also feeding each fixture's status and content type through the released client's own `interpret_response`. That covers status and media-type handling and the code-to-exception mapping offline, while the generator and checker stay decoupled and the fixtures stay inspectable.

Move to pattern 3 (a live server driven through the release's transport) only if real-HTTP behaviour (headers, auth) or per-method behaviour starts producing misses that pattern 2 can't see.

Coverage was moderate:
- No source argues directly that consumer-driven contracts are overkill for a lockstep monorepo; that conclusion is inferred from Fowler and from Pact's own scope.
- Nothing was found on how the Kubernetes Python client tests compatibility with newer servers.

## Sources

Not live-verified.

### Reference implementations
- https://pkg.go.dev/k8s.io/apimachinery/pkg/api/apitesting/roundtrip — frozen per-release fixtures, round-trip checked
- https://github.com/elastic/elasticsearch-clients-tests — shared YAML corpus run by every client against a live server
- https://github.com/stripe/stripe-mock — spec-derived mock server for SDK tests

### Blog posts & writeups
- https://martinfowler.com/articles/consumerDrivenContracts.html — scope of consumer-driven contracts
- https://www.infoq.com/articles/contract-testing-spring-cloud-contract — contracts kept in the producer repo

### Documentation & standards
- https://docs.pact.io/pact_broker/advanced_topics/consumer_version_selectors — `deployedOrReleased`; why `latest` is discouraged
- https://docs.pact.io/pact_broker/can_i_deploy — version-matrix gating
