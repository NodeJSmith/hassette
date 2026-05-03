---
topic: "Python + TS frontend type/asset consistency"
date: 2026-05-02
status: Draft
---

# Prior Art: Python + TS Frontend Type & Asset Consistency

## The Problem

Dual-language projects (Python backend + TypeScript frontend) face a fundamental consistency challenge: types, enums, and message schemas must be defined and maintained in both languages. REST endpoint types can be generated from OpenAPI specs, but WebSocket messages, shared enums, event payloads, and other non-HTTP communication channels have no standard generation pipeline. Without enforcement, these types drift silently until a runtime error surfaces in production.

The secondary challenge is testing: how do you test a system where the boundary is a runtime protocol (HTTP/WebSocket) rather than a compile-time interface? Type generation provides static safety, but runtime validation and E2E testing are needed to catch semantic drift.

## How We Do It Today

Hassette has a solid two-tier approach:
- **REST types**: Fully generated via `scripts/export_schemas.py` → `openapi-typescript` → `generated-types.ts`, with CI freshness checks (`tools/check_schemas_fresh.py`) and a pre-push hook.
- **WebSocket types**: Hand-authored in `frontend/src/api/ws-types.ts`, validated against a `ws-schema.json` file (generated from Pydantic's `TypeAdapter(WsServerMessage).json_schema()`). CI checks schema freshness, and parametrized tests verify structural properties (e.g., all messages have `timestamp`).
- **Testing**: Python-side unit tests validate WS message parsing; TS-side tests mock WebSocket connections; E2E Playwright tests exercise the real boundary.

The main gap: WS types are hand-authored and manually synchronized. The JSON Schema is exported but not compiled to TypeScript — it validates the Python side but doesn't generate the TS side.

## Patterns Found

### Pattern 1: OpenAPI as Single Source of Truth (REST)

**Used by**: FastAPI (canonical), Django Ninja, HackerOne, hassette (current)

**How it works**: Python framework auto-generates an OpenAPI spec from Pydantic models and route signatures. `openapi-typescript` or similar converts the spec to TS types. A CI step regenerates and diffs against committed output — if stale, the build fails.

**Strengths**: Mature tooling, widely adopted, zero manual type maintenance for REST. Generated types include request/response shapes and HTTP methods.

**Weaknesses**: Only covers HTTP endpoints. WebSocket messages, shared enums, and event schemas that don't flow through routes are invisible.

**Example**: https://fastapi.tiangolo.com/advanced/generate-clients/

---

### Pattern 2: JSON Schema as Intermediate Representation (WebSocket/Events)

**Used by**: Projects with non-REST communication, Pact ecosystem

**How it works**: Pydantic models for WebSocket messages or events export JSON Schema via `model_json_schema()`. The schema is written to a file (e.g., `ws-schema.json`). `json-schema-to-typescript` compiles it to TS interfaces. The JSON Schema file becomes the contract — both Python (Pydantic) and TypeScript (AJV/Zod) can validate against it at runtime.

Pipeline: `Pydantic model → JSON Schema → TypeScript types` + optional runtime validation on both sides.

**Strengths**: Works for any message format. Language-agnostic contract. Enables runtime validation on the TS side (not just static types). Extends naturally to cover shared enums by including them in the schema.

**Weaknesses**: Requires a custom export script. JSON Schema has quirks with discriminated unions and recursive types. Two tools to maintain (Python export + TS compiler).

**Example**: https://www.npmjs.com/package/json-schema-to-typescript + Pydantic's `model_json_schema()`

---

### Pattern 3: Direct Pydantic-to-TypeScript Compilation

**Used by**: Teams using pydantic-to-typescript2, ts-type

**How it works**: A CLI tool introspects Python modules containing Pydantic models and emits TypeScript interfaces directly, bypassing JSON Schema. Imports the module, walks model definitions, writes `.ts` files. Runs as pre-commit hook or CI step.

**Strengths**: Single-step generation. Handles Pydantic-specific features (validators, discriminated unions) better than JSON Schema. Simple setup.

**Weaknesses**: Tightly coupled to Pydantic. Original tool unmaintained; fork has limited community. Must import the module (side effects risk). Doesn't cover plain dataclasses or TypedDicts.

**Example**: https://github.com/Darius-Labs/pydantic-to-typescript2

---

### Pattern 4: Python-Compiled Frontend (Zero Separate Types)

**Used by**: Reflex, FastUI

**How it works**: The framework compiles Python definitions directly into frontend code. No TypeScript types exist independently — the frontend is entirely generated. In Reflex, Python State classes produce a Next.js app. In FastUI, Pydantic models define UI components the TS frontend renders.

**Strengths**: Zero type drift by construction. No generation step or CI check needed. Single-language stack.

**Weaknesses**: Only works for framework-managed UIs. Cannot apply to custom React/Vue/Svelte frontends. Limits frontend flexibility. Poor fit for hassette's custom SPA.

**Example**: https://reflex.dev/blog/reflex-architecture/

---

### Pattern 5: Contract Testing for Message Schemas

**Used by**: Pact ecosystem, teams with event-driven architectures

**How it works**: Consumer (frontend) writes a contract describing expected messages. Provider (backend) verifies it produces conforming messages. Bidirectional — each side runs verification independently. Pact Plugins abstract transport, focusing on message shapes.

**Strengths**: Decouples frontend/backend development. Catches semantic drift (not just structural). Works for any transport.

**Weaknesses**: Heavyweight for small teams. Overkill when the same person writes both sides. Learning curve. Requires both sides to maintain contracts.

**Example**: https://docs.pact.io/implementation_guides/javascript/docs/messages

---

### Pattern 6: Shared Enum/Constant Export

**Used by**: Custom tooling across various projects [no canonical implementation]

**How it works**: A Python script imports enum modules, iterates members, and writes a `.ts` file with matching `const enum` or `as const` objects. Runs alongside OpenAPI generation in the same CI freshness check.

**Strengths**: Covers the gap that OpenAPI and JSON Schema miss — standalone constants used as WebSocket discriminators, event type strings, status values.

**Weaknesses**: No standard tool (always custom). Must be maintained alongside other pipelines. Easy to forget adding new enums to the export.

**Example**: [no source found] — common ad-hoc pattern without a canonical reference.

---

### Pattern 7: CI Freshness Check (Diff-Based Validation)

**Used by**: Any project with generated types

**How it works**: CI runs the generation pipeline, compares output to committed files via `git diff --exit-code`. Fails with a clear message if stale. Advanced implementations use `oasdiff` or `openapi-changes` for human-readable schema diffs in PRs.

**Strengths**: Catches drift regardless of generation tool. Simple to implement. Makes schema changes visible in code review.

**Weaknesses**: Only catches at CI time (delayed feedback unless also a pre-commit hook). Non-deterministic generation causes false failures.

**Example**: hassette's `tools/check_schemas_fresh.py` + https://aetherio.tech/en/articles/generation-types-typescript-openapi-synchronisation-backend-frontend

## Anti-Patterns

- **Manual type maintenance across languages**: Home Assistant defines TS types by hand, separate from its Python backend. This causes silent drift, especially for WebSocket messages. HA's use of voluptuous (not Pydantic) makes auto-generation harder — but hassette doesn't have this excuse. Source: https://developers.home-assistant.io/docs/frontend/architecture/

- **Generation without enforcement**: Generating types is useless without a CI gate that fails on stale output. Without it, the script becomes "that thing nobody runs" and drift returns.

- **Over-relying on OpenAPI for non-REST**: WebSocket messages, SSE events, and background task results don't appear in OpenAPI specs. Projects that only generate from OpenAPI have a blind spot.

- **Non-deterministic generation output**: If the tool produces different output on different runs (property ordering, timestamps in comments), the freshness check yields false failures — training developers to ignore it.

## Emerging Trends

- **JSON Schema as universal contract**: The trend is toward JSON Schema as the bridge format for all languages, rather than language-specific tools. Driven by Pydantic v2's excellent `model_json_schema()`, mature `json-schema-to-typescript`, and `datamodel-code-generator`.

- **Runtime validation on both sides**: Moving beyond "generate types and trust them" to runtime validation with the same schema. Pydantic on Python, AJV/Zod on TypeScript, both sourced from the same JSON Schema.

- **Discriminated unions for WS protocols**: `type` field discriminated unions becoming standard for multi-message WebSocket protocols. Both Pydantic v2 and TypeScript handle well; JSON Schema's `oneOf` + `discriminator` generates correctly.

## Relevance to Us

Hassette is already 80% of the way there:
- REST types: fully generated, CI-enforced (Patterns 1 + 7 ✓)
- WS schema: JSON Schema exported and freshness-checked (Pattern 2, partially ✓)
- E2E testing: Playwright catches runtime breakage (Pattern 9 ✓)

The gap is the **last mile of Pattern 2**: `ws-schema.json` exists but isn't compiled to TypeScript. The hand-authored `ws-types.ts` is the HA anti-pattern — functional today because the schema is small, but a drift risk as WS message complexity grows.

Pattern 4 (compiled frontend) doesn't apply — hassette has a custom SPA. Pattern 5 (contract testing) is overkill for a single-developer project. Pattern 3 (pydantic-to-typescript2) would work but the JSON Schema path is more flexible and hassette already generates the schema.

The shared enum gap (Pattern 6) is worth watching — hassette uses string literals as WS message discriminators (e.g., `"app_status_changed"`), and these currently live in both `WsServerMessage` discriminated union and `ws-types.ts` without a generation link.

## Recommendation

**Close the JSON Schema → TypeScript loop.** The infrastructure is 90% built:

1. `ws-schema.json` already exists (generated from `TypeAdapter(WsServerMessage).json_schema()`)
2. Add `json-schema-to-typescript` to the frontend npm deps
3. Add a generation step: `json2ts ws-schema.json -o src/api/ws-types.ts` (or a script that post-processes for hassette conventions)
4. Delete the hand-authored `ws-types.ts` — replace with generated output
5. Add to the same CI freshness check that validates `generated-types.ts`

**Optional next steps** (lower priority):
- Add AJV or Zod runtime validation on the frontend for incoming WS messages (defense in depth)
- Add a shared-enums export script if standalone constants proliferate
- Evaluate `oasdiff` for human-readable schema change summaries in PRs

This is a low-effort, high-leverage change — hassette already does the hard parts (schema export, freshness checks, CI gating). The missing piece is one `npm` dependency and one line in the generation script.

## Sources

### Reference implementations
- https://github.com/phillipdupuis/pydantic-to-typescript — original Pydantic→TS tool (unmaintained)
- https://github.com/Darius-Labs/pydantic-to-typescript2 — maintained fork with Pydantic v2 + GitHub Action
- https://github.com/home-assistant-libs/voluptuous-openapi — HA's partial voluptuous→OpenAPI bridge

### Blog posts & writeups
- https://aetherio.tech/en/articles/generation-types-typescript-openapi-synchronisation-backend-frontend — FastAPI + openapi-typescript CI pipeline
- https://dev.to/qa-leaders/your-api-tests-are-lying-to-you-the-schema-drift-problem-nobody-talks-about-4h86 — schema drift problem framing
- https://medium.com/@asafshakarzy/embedding-a-react-frontend-inside-a-fastapi-python-package-in-a-monorepo-c00f99e90471 — FastAPI+React monorepo structure
- https://www.vintasoftware.com/blog/django-react-monorepo — Django+React type generation
- https://www.hackerone.com/blog/generating-typescript-types-openapi-rest-api-consumption — production experience report
- https://reflex.dev/blog/reflex-architecture/ — Python-compiled frontend architecture
- https://pactflow.io/blog/contract-testing-using-json-schemas-and-open-api-part-2/ — schema-based contract testing

### Documentation & standards
- https://fastapi.tiangolo.com/advanced/generate-clients/ — official FastAPI SDK generation guide
- https://openapi-ts.dev/cli — openapi-typescript documentation
- https://www.npmjs.com/package/json-schema-to-typescript — JSON Schema→TS compiler
- https://pypi.org/project/ts-type/ — lightweight Python→TS generation
- https://docs.pydantic.dev/fastui/ — FastUI architecture
- https://docs.pact.io/implementation_guides/javascript/docs/messages — Pact message contracts
- https://developers.home-assistant.io/docs/frontend/architecture/ — HA frontend architecture
- https://deepwiki.com/gradio-app/gradio/3-frontend-system — Gradio frontend system
