---
topic: "Declaring per-operation error codes for RFC 9457 problem details in OpenAPI"
date: 2026-09-29
status: Draft
---

# Prior Art: Declaring per-operation error codes in OpenAPI

## The Problem

An API that puts a closed, machine-readable `code` on a shared problem-details schema needs some way to say which codes each operation can actually return. OpenAPI has no native construct for this. OAI issue #567 has been open for years without a resolution.

## How We Do It Today

The hassette design (spec 115) has one `ProblemDetail` schema whose `code` is the full `ProblemCode` enum (~22 values). `problem_responses()` declares each route's codes in the response `description` text. The main consumer, `hassette-client`, imports `ProblemCode` directly from `hassette-wire` rather than generating types from OpenAPI. The frontend reads only `components` from its generated types.

## Patterns Found

### Pattern 1: Shared schema + prose per operation
**Used by**: Zalando guidelines, Speakeasy guidance, Spring/springdoc, Google AIP-193 (reason documented per API in reference docs), Stripe/PayPal (narrative docs generated from internal registries)
**How it works**: every error response `$ref`s one schema, and which codes apply is written in descriptions or generated reference docs.
**Strengths**: universal tool support, nothing novel.
**Weaknesses**: nothing is machine-readable per route.
**Example**: https://opensource.zalando.com/restful-api-guidelines/

### Pattern 2: Vendor extension listing codes per response/operation
**Used by**: production APIs cited in OAI #567 (`x-errors`)
**How it works**: a structured `x-...` array next to the response lists the applicable codes.
**Strengths**: machine-readable, cheap, harmless to tools that ignore it.
**Weaknesses**: openapi-typescript, openapi-generator, and Kiota ignore `x-*` by default. It's for docs, linting, and tests, not a source of generated types.
**Example**: https://github.com/OAI/OpenAPI-Specification/issues/567

### Pattern 3: `oneOf` per-code subschemas + discriminator on `code`
**Used by**: rare, with no major API found using it for error codes
**How it works**: each response is a union of narrow subschemas.
**Strengths**: the only route to narrowed generated types.
**Weaknesses**: schema explosion, and codegen support for discriminated unions is inconsistent (hey-api #3270).
**Example**: https://redocly.com/learn/openapi/discriminator

### Pattern 4: Per-code `type` URIs
**Used by**: RFC 9457's intended design. Zalando stepped away from dereferenceable types (#581).
**How it works**: `type` is the discriminator, and each URI documents one problem kind.
**Strengths**: standard-native.
**Weaknesses**: an orthogonal axis. It doesn't declare which codes apply per operation.
**Example**: https://www.rfc-editor.org/rfc/rfc9457.html

## Anti-Patterns

- `allOf` plus a narrower `enum` or a discriminator to narrow the parent enum. Tools treat it as documentation-only and handle it inconsistently. (https://github.com/OAI/OpenAPI-Specification/discussions/3025, https://bump.sh/blog/the-discriminator-in-openapi-is-generally-redundant-and-confusing/)
- Pitching `x-*` extensions as client type safety. Mainstream generators ignore them.
- Listing every 5xx code per operation. Collapse 5xx instead.

## Relevance to Us

hassette's typed client gets its code enum from `hassette-wire`, not from OpenAPI codegen, so narrowing in the schema buys the main consumer nothing. The per-route declaration matters for two things: the FR#24 test and human or tooling readers of `openapi.json`. Pattern 2 serves both at near-zero cost without claiming type safety. Pattern 3 is the only one that affects generated types, and its cost doesn't match any current need.

## Recommendation

Keep prose descriptions (Pattern 1) and add an `x-problem-codes` list per response (Pattern 2), described explicitly as documentation and test metadata. Avoid the `allOf` override and the `oneOf` explosion.

## Sources

### Documentation & standards
- https://github.com/OAI/OpenAPI-Specification/issues/567: the open OAI request; `x-errors` workaround
- https://opensource.zalando.com/restful-api-guidelines/: problem+json, no per-route code declaration
- https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md: `x-ms-error-code` header
- https://google.aip.dev/193: ErrorInfo reason
- https://www.speakeasy.com/openapi/responses/errors: shared error schema guidance
- https://github.com/OAI/OpenAPI-Specification/discussions/3025: allOf/discriminator semantics

### Reference implementations
- https://github.com/vapor-ware/fastapi-rfc7807: FastAPI problem details, no per-route narrowing
- https://github.com/springdoc/springdoc-openapi/issues/2398: springdoc ProblemDetail support
- https://github.com/hey-api/hey-api/issues/3270: codegen gap for oneOf discriminated unions

### Blog posts & writeups
- https://bump.sh/blog/the-discriminator-in-openapi-is-generally-redundant-and-confusing/
