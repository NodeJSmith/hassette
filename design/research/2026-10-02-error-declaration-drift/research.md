---
topic: "Keeping declared per-route error codes in sync with what handlers raise; per-operation 5xx"
date: 2026-10-02
status: Draft
---

# Prior Art: Keeping per-route error declarations accurate

## The Problem

An API that documents which error codes each operation can return has two artifacts: the declaration, and the code that actually raises. Nothing ties them together by default, so they drift: a helper gains a raise site, and the docs for every route that calls it go stale. The related question is which 5xx codes belong in a per-operation list at all.

The companion survey `design/research/2026-09-29-openapi-per-operation-error-codes/research.md` covers *how* to declare per-operation codes in OpenAPI. This one covers keeping them accurate.

## How We Do It Today

Ledger `design/specs/118-api-problem-details/design.md`, D10: each route hand-lists its codes via `problem_responses(*codes)`, emitted as `x-problem-codes`. Accuracy rests on D1's per-(row, code) integration coverage. Generic, framework-level codes (`not_found`, `method_not_allowed`, `http_error`, `internal_error`, `not_authenticated`, `body_too_large`) aren't listed per route. Route-specific 5xx (`action_failed`, `source_unavailable`, `telemetry_unavailable`) are.

## Patterns Found

### Pattern 1: Type-derived response enum
**Used by**: poem-openapi (strong: the handler's return type *is* the response enum, compiler-enforced), utoipa (weaker: convention only)
**How it works**: the error set is one enum whose variants carry status and schema; OpenAPI is generated from it.
**Strengths**: one artifact; in poem-openapi, drift is impossible on the typed return path.
**Weaknesses**: covers only the typed return path. Extractor/middleware rejections and panics fall outside it. Needs a language where errors are return values; Python exceptions aren't.
**Example**: https://docs.rs/poem-openapi, https://dev.materialize.com/api/rust/utoipa/derive.IntoResponses.html

### Pattern 2: Name the escape hatch (modeled / failed-effect / decode-failure)
**Used by**: tapir (Scala); Smithy's synthetic `InternalFailureException`
**How it works**: the framework states up front which failures are never in an operation's declared set (uncaught exceptions → generic 500; input decode failures → a cross-cutting handler) and gives them a named, global bucket.
**Strengths**: no illusion that the per-operation set is exhaustive.
**Weaknesses**: doesn't make the modeled set accurate; it bounds it.
**Example**: https://tapir-scala.readthedocs.io/en/v1.2.4/server/errors.html

### Pattern 3: AST-derived declarations from raise sites
**Used by**: fastapi-docx, fastapi-responses (small, lightly maintained)
**How it works**: at schema-generation time, walk each path operation's AST (and resolvable dependencies) for `raise HTTPException(...)`, then synthesize `responses=`.
**Strengths**: removes the second artifact.
**Weaknesses**: incomplete by nature (dynamic dispatch, third-party raises, pre-handler errors), one-directional with no check that it found everything, low adoption.
**Example**: https://github.com/Saran33/fastapi-docx

### Pattern 4: Test-time conformance against the declared schema
**Used by**: Schemathesis (`status_code_conformance`), Dredd
**How it works**: exercise the running API and fail when an observed response isn't declared for that operation.
**Strengths**: checks real behavior, including middleware ordering and DI.
**Weaknesses**: only as complete as what the tests or fuzzer trigger. Noisy on first adoption, because most hand-maintained specs are incomplete. Checks status, not semantic codes.
**Example**: https://schemathesis.readthedocs.io/en/stable/reference/checks/

### Pattern 5: IDL as single source with server constraints
**Used by**: Smithy (AWS), TypeSpec (Microsoft)
**How it works**: errors are declared once in the model, and codegen produces the server's throwable set, client types, and docs. AWS splits a service-wide "Common Errors" tier from operation-specific errors.
**Strengths**: one place to drift. Smithy constrains generated servers.
**Weaknesses**: requires codegen as the backend's source; TypeSpec alone doesn't constrain a hand-written server.
**Example**: https://smithy.io/2.0/languages/typescript/ts-ssdk/error-handling.html, https://docs.aws.eu/cloud-map/latest/api/CommonErrors.html

## 5xx per operation

Nobody enumerates *generic* 5xx per operation (Zalando: document predictable errors; Stripe: one global 5xx bucket; AIP-193: small canonical set). AWS/Smithy is the precedent for *specific* semantic server errors: shared ones (throttling, service unavailable, internal failure) go in a service-wide common tier, while errors unique to one operation, server-side included (`@error("server")`), are declared on that operation.

## Anti-Patterns

- A hand-maintained declaration with no enforcement (plain FastAPI `responses=`, Litestar `raises=`). https://docs.litestar.dev/2/usage/exceptions.html
- Signalling errors inside a 2xx body ("partial errors"). https://google.aip.dev/193

## Relevance to Us

- No Python framework closes declared-vs-raised structurally. Real derivation (Pattern 1) depends on errors being typed return values. Pattern 5 needs codegen. Neither fits hassette.
- The practical Python state of the art is declare plus test-time conformance (Pattern 4), which is exactly Finding 4's option B, at `code` granularity instead of status granularity.
- AST derivation (Pattern 3) is Finding 4's option D inverted (derive instead of check). It has the same incompleteness and adds a build-time dependency on the AST pass being right.
- D10 already follows Pattern 2 and AWS's split: generic codes are global, and only operation-unique codes are listed per route. The 5xx it lists per route (`action_failed`, `source_unavailable`, `telemetry_unavailable`) are each raised by specific routes, which matches AWS's operation-specific tier. They aren't the "enumerate generic 5xx" anti-pattern.

## Recommendation

Keep D10 as designed. For Finding 4, use declare plus test-time conformance (option B), with helper-adjacent code constants (option C) to make the declaration easy to keep right where it's edited. Reject AST derivation for the reasons above. Optionally, state in D10 the Pattern-2 boundary (which codes are global and never per-route) so the split is a stated rule rather than an emergent one.

## Sources

### Reference implementations
- https://docs.rs/poem-openapi: compiler-enforced response enum
- https://dev.materialize.com/api/rust/utoipa/derive.IntoResponses.html: utoipa IntoResponses
- https://github.com/Saran33/fastapi-docx: AST-derived FastAPI responses
- https://pypi.org/project/fastapi-responses/: same idea, smaller
- https://pypi.org/project/fastapi-problem/: RFC 9457 for FastAPI; no derivation

### Documentation & standards
- https://tapir-scala.readthedocs.io/en/v1.2.4/server/errors.html: three-way error split
- https://schemathesis.readthedocs.io/en/stable/reference/checks/: status_code_conformance
- https://schemathesis.readthedocs.io/en/stable/guides/triage/: first-run noise
- https://smithy.io/2.0/languages/typescript/ts-ssdk/error-handling.html: Smithy errors and synthetic fallback
- https://typespec.io/docs/getting-started/getting-started-rest/handling-errors: TypeSpec @error
- https://docs.aws.eu/cloud-map/latest/api/CommonErrors.html: AWS common-errors tier
- https://opensource.zalando.com/restful-api-guidelines/: Zalando rules 151/176/177
- https://google.aip.dev/193: AIP-193
- https://docs.stripe.com/error-codes: Stripe global code table
- https://docs.litestar.dev/2/usage/exceptions.html: Litestar raises=
- https://github.com/tiangolo/fastapi/discussions/6695: FastAPI responses= is descriptive only

(URLs were not live-verified.)
