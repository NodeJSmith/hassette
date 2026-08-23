# Design: WS Precompilation + Guard Simplification

**Date:** 2026-08-23
**Status:** draft
**Scope-mode:** hold
**Research:** design/research/2026-08-23-rest-validation/research.md

## Problem

Two independent code quality issues in the frontend validation layer:

1. **WS validation ships unnecessary weight.** `ws-validator.ts` instantiates the full Ajv compiler at runtime (`new Ajv()` + `ajv.compile()`) to validate WebSocket messages. The schema is known at build time — shipping the compiler to the browser to compile it at page load is unnecessary work and bundle cost (~20-30 kB gzipped for the compiler vs ~3-5 kB for runtime-only helpers).

2. **Status map guards are verbose and misleadingly documented.** The `isKnownMapKey()` helper in `status.ts` and the `UNKNOWN_PRIORITY` constant in `status-priority.ts` exist with docstrings citing "REST responses are never runtime-validated against the schema" as their justification. REST responses are validated server-side by Pydantic (`response_model=` on every route), and the compile-time `satisfies Record<Union, X>` checks (spec 102) already catch missing map entries when types regenerate. The guards provide a legitimate forward-compatibility fallback for unknown enum values, but the implementation is verbose (a 4-line generic helper function, called at 4 sites, each with a multi-line docstring explaining why) when a plain `?? default` inline fallback does the same thing in one expression.

## Goals

- WS validation uses precompiled validators — no schema compilation in the browser
- The full Ajv compiler is removed from the production bundle; only `ajv/dist/runtime` helpers ship
- `isKnownMapKey()` helper and `UNKNOWN_PRIORITY` constant are replaced by inline `?? default` fallbacks — shorter, clearer code with the same forward-compatible behavior

## Non-Goals

- REST response validation — REST responses are validated server-side by Pydantic (`response_model=`). Frontend-side REST validation is defense-in-depth against a version-skew window that is effectively seconds for a solo-dev, single-deployment tool. Not justified given the build infrastructure cost.
- Changing the WS `onmessage` error handling behavior — catch/warn/drop stays
- Validating `config_schema` fields — `dict[str, Any]` by design

## User Scenarios

### Developer: Updating a backend enum

- **Goal:** Add a new status variant and have both build and runtime handle it correctly
- **Context:** Modifying `src/hassette/types/enums.py`, then regenerating types

#### New enum value added

1. **Adds `ManifestStatus.RECOVERING` to the backend enum**
   - Then: runs `uv run python scripts/export_schemas.py --types`
2. **TypeScript catches missing map entries**
   - Sees: `satisfies Record<ManifestStatus | ResourceStatus, X>` errors on every status map missing `"recovering"` — compile-time enforcement from spec 102
3. **Adds the new value to all maps, rebuilds**
   - Then: precompiled WS validators are regenerated with the new enum value; `?? default` fallbacks remain as safety for the brief window before the frontend is rebuilt

## Functional Requirements

- **FR#1** A build script precompiles the WS schema from `ws-schema.json` into standalone Ajv validation functions
- **FR#2** `ws-validator.ts` uses precompiled validators instead of runtime `Ajv.compile()`
- **FR#3** The full Ajv compiler (`ajv` default import) is removed from the production bundle; only `ajv/dist/runtime` helpers remain
- **FR#4** The `isKnownMapKey()` helper function and its per-consumer docstrings are removed from `status.ts`; lookup functions use inline `?? default` fallbacks preserving the same return values for both known and unknown inputs
- **FR#5** The `UNKNOWN_PRIORITY` named constant in `status-priority.ts` is removed; `statusPriority()` uses an inline `?? 99` fallback

## Edge Cases

- **Discriminator `mapping` in WS schema**: Pydantic emits `{ propertyName, mapping }` but Ajv only supports `{ propertyName }`. The current `ws-validator.ts` strips `mapping` at line 9. The precompilation script must apply this same stripping before compiling.
- **Ajv strict mode vs schema keywords**: If the precompilation script registers the full `ws-schema.json`, `strict: false` may be needed depending on whether Pydantic emits non-standard keywords. The WS schema is simpler than the OpenAPI doc — verify during implementation.
- **Stale precompiled validators**: Developer modifies a WS response model but forgets to regenerate. The pre-push hook (`check_schemas_fresh.py`) catches this.

## Acceptance Criteria

- **AC#1** `ws-validator.ts` no longer imports or instantiates `Ajv` — uses precompiled validators only (FR#2)
- **AC#2** `grep -r "from \"ajv\"" frontend/src/` returns zero matches — no direct Ajv compiler imports in application code (FR#3)
- **AC#3** The `isKnownMapKey` function definition does not appear in `frontend/src/utils/status.ts`; lookup functions use inline `?? default` fallbacks (FR#4)
- **AC#4** The `UNKNOWN_PRIORITY` named constant does not appear in `frontend/src/utils/status-priority.ts`; `statusPriority()` uses an inline `?? 99` fallback (FR#5)
- **AC#5** `prek -a` passes (lint, type check)
- **AC#6** `cd frontend && npm run build` succeeds and bundle stays within `.size-limit.json` budget
- **AC#7** `cd frontend && npm run test` passes — all existing and new tests green
- **AC#8** `node scripts/compile-validators.cjs` succeeds and produces `ws-validator.generated.ts` (FR#1)

## Key Constraints

- **Do not import `ajv` in application source** — only `ajv/dist/runtime/*` helpers and `ajv/dist/types` type imports may appear in the bundle. The precompilation script (build-time only) may import the full compiler.
- **The precompilation script must strip `mapping` from the WS discriminator** before compiling, matching the existing workaround in `ws-validator.ts:9`.

## Dependencies and Assumptions

- **Ajv 8.x standalone API stability**: The `ajv/dist/standalone` codegen has been stable since Ajv 8.x. A future Ajv major version could break the build script.
- **`strict: false` may be needed**: Confirmed needed for OpenAPI documents; the WS schema may or may not require it — verify during implementation.

## Architecture

### WS precompilation

A CJS build script (`scripts/compile-validators.cjs`) handles WS precompilation, following the existing `scripts/generate-ws-types.cjs` pattern.

**Flow:**
1. Read `frontend/ws-schema.json`
2. Strip `mapping` from the discriminator (same transform as current `ws-validator.ts:9`)
3. Create an Ajv instance with `discriminator: true` and `code: { source: true }`
4. Compile the discriminated union schema
5. Generate standalone code via `standaloneCode()`
6. Write to `frontend/src/api/ws-validator.generated.ts` with a `/* @generated */` banner

The script is run as part of the schema generation pipeline. A new `npm run validators` script is added for standalone use.

### WS validator migration

`ws-validator.ts` replaces:
```typescript
// BEFORE
import Ajv from "ajv";
import rawSchema from "../../ws-schema.json";
const ajv = new Ajv({ discriminator: true });
const validate = ajv.compile<WsServerMessage>(wsSchema);
```

With:
```typescript
// AFTER
import { validate } from "./ws-validator.generated";
```

The `WsValidationError` class stays in `ws-validator.ts`. The `validateWsMessage()` function signature is unchanged — the leading type-guard (`typeof data !== "object"` check) and the `if (validate(data)) return data` / `throw new WsValidationError(validate.errors ?? [])` pattern stay the same. Only the source of `validate` changes. The call site in `use-websocket.ts` is untouched.

The `ErrorObject` type import moves from `from "ajv"` to `from "ajv/dist/types"` to satisfy AC#2.

### Guard simplification

`isKnownMapKey()` (definition at `status.ts:22-24`) and its 4 call sites are replaced by inline `?? default` fallbacks:

```typescript
// BEFORE
export function statusToVariant(status: StatusMapKey): StatusVariant {
  if (isKnownMapKey(status, APP_STATUS_MAP)) return APP_STATUS_MAP[status];
  console.warn(`Unknown status: "${status}"`);
  return "neutral";
}

// AFTER
export function statusToVariant(status: StatusMapKey): StatusVariant {
  return APP_STATUS_MAP[status] ?? "neutral";
}
```

The verbose docstrings citing "REST responses are never runtime-validated" are removed — the `satisfies Record<Union, X>` compile-time checks (spec 102) and server-side Pydantic validation are the real protection; these fallbacks are just forward-compatible defaults.

`UNKNOWN_PRIORITY` constant in `status-priority.ts:36` → `return STATUS_PRIORITY[status] ?? 99`.

Note: the `console.warn` in `statusToVariant()` and `executionStatusKind()` is dropped in the simplification. This is intentional — the warn was invisible to the user (no one watches DevTools on a self-hosted dashboard), and the `?? default` fallback provides the same graceful degradation silently.

## Implementation Preferences

- **Ajv 8.x** with `ajv/dist/standalone` for precompilation — already installed, no new dependencies
- **CJS build script** matching `scripts/generate-ws-types.cjs` pattern
- **Generated file convention**: `*.generated.ts` checked into repo
- **Import from `ajv/dist/types`** for `ValidateFunction` and `ErrorObject` types — not from the top-level `ajv` package

## Replacement Targets

| Target | File | Replaced by | Action |
|---|---|---|---|
| Runtime Ajv compilation | `ws-validator.ts:1,11-12` | Precompiled import from `ws-validator.generated.ts` | Remove `Ajv` import and `ajv.compile()` call |
| `isKnownMapKey()` function | `status.ts:22-24` | Inline `?? default` fallbacks | Remove helper; each consumer gets `map[status] ?? fallback` |
| `isKnownMapKey()` in `isFailureStatus()` | `status.ts:61` | Inline fallback | `return IS_FAILURE_STATUS[status] ?? false` |
| `isKnownMapKey()` in `statusToVariant()` | `status.ts:166` | Inline fallback | `return APP_STATUS_MAP[status] ?? "neutral"` |
| `isKnownMapKey()` in `executionStatusKind()` | `status.ts:187` | Inline fallback | `return EXECUTION_STATUS_KIND[status] ?? "err"` |
| `isKnownMapKey()` in `statusToKind()` | `status.ts:266` | Inline fallback | `return STATUS_KIND_MAP[status] ?? "mute"` |
| `UNKNOWN_PRIORITY` constant | `status-priority.ts:36` | Inline fallback | `return STATUS_PRIORITY[status] ?? 99` |

## Convention Examples

### WS validation pattern — current runtime compile (being replaced)

**Source:** `frontend/src/api/ws-validator.ts`

```typescript
import Ajv, { type ErrorObject } from "ajv";
import rawSchema from "../../ws-schema.json";

const wsSchema = { ...rawSchema, discriminator: { propertyName: rawSchema.discriminator.propertyName } };
const ajv = new Ajv({ discriminator: true });
const validate = ajv.compile<WsServerMessage>(wsSchema);
```

### Build script pattern — template for precompilation script

**Source:** `scripts/generate-ws-types.cjs`

```javascript
const SCHEMA_PATH = path.join(FRONTEND_DIR, "ws-schema.json");
const OUTPUT_PATH = path.join(FRONTEND_DIR, "src", "api", "ws-types.ts");
const BANNER = `/* @generated from ws-schema.json — do not edit by hand. */`;

async function main() {
  const schema = JSON.parse(fs.readFileSync(SCHEMA_PATH, "utf8"));
  // ... process schema ...
  fs.writeFileSync(OUTPUT_PATH, output);
}
```

### Guard simplification — before and after

**Source:** `frontend/src/utils/status.ts:165-169`

```typescript
// BEFORE — verbose helper + docstring about REST being unvalidated
export function statusToVariant(status: StatusMapKey): StatusVariant {
  if (isKnownMapKey(status, APP_STATUS_MAP)) return APP_STATUS_MAP[status];
  console.warn(`Unknown status: "${status}"`);
  return "neutral";
}

// AFTER — inline fallback, forward-compatibility preserved
export function statusToVariant(status: StatusMapKey): StatusVariant {
  return APP_STATUS_MAP[status] ?? "neutral";
}
```

## Alternatives Considered

**Full REST + WS precompilation with structural validation** — The original design (see research brief). Rejected: REST responses are already validated server-side by Pydantic (`response_model=`). Frontend structural validation is defense-in-depth against a version-skew window that is effectively seconds for a solo-dev, single-deployment tool. The build infrastructure cost (36-schema precompilation, `RestValidationError`, `apiFetch` signature change, endpoint wiring, `strict: false` workarounds for OpenAPI, `Execution | null` special cases) is disproportionate to the evidenced risk — no structural-mismatch incident has been cited.

**Do nothing** — The WS validator works, the guards work. But the WS path ships ~20 kB of unnecessary compiler code, and the guard implementation is verbose with misleading docstrings. Worth cleaning up while touching this area.

## Test Strategy

### Required Test Types

Unit tests (vitest). No cross-service boundary, no user-facing flow change.

### Existing Tests to Adapt

- `frontend/src/api/ws-validator.test.ts` — adapt import path if the validate function source changes
- `frontend/src/utils/status.test.ts` — update tests referencing `isKnownMapKey` behavior
- `frontend/src/utils/status-priority.test.ts` — update `UNKNOWN_PRIORITY` fallback test to use inline `?? 99`

### New Test Coverage

- WS precompiled validator tests: existing `ws-validator.test.ts` cases continue to pass with precompiled validators (FR#2)
- Verify precompilation script produces valid output (FR#1)

### Tests to Remove

No tests to remove.

## Smoke Test

1. Run `node scripts/compile-validators.cjs` — should generate `ws-validator.generated.ts` without errors
2. Run `cd frontend && npm run build` — should succeed, confirming precompiled validators compile and the full Ajv import is gone
3. Run `grep -r "from \"ajv\"" frontend/src/` — should return zero matches
4. Run `cd frontend && npm run test` — all tests pass

## Documentation Updates

No user-facing documentation updates required. This is build infrastructure and code cleanup.

Internal:
- `.claude/rules/frontend-worktree.md` — mention `npm run validators` as part of the schema regeneration flow
- `CLAUDE.md` Common Commands section — mention `ws-validator.generated.ts` in the regenerated artifacts list

## Impact

### Changed Files

**Created:**
- `scripts/compile-validators.cjs` — build script for Ajv standalone WS precompilation
- `frontend/src/api/ws-validator.generated.ts` — precompiled WS message validator

**Modified:**
- `frontend/src/api/ws-validator.ts` — replace runtime Ajv compile with precompiled import; move `ErrorObject` import to `ajv/dist/types`
- `frontend/src/utils/status.ts` — remove `isKnownMapKey()` and its 4 consumers; simplify functions to inline `?? default`
- `frontend/src/utils/status-priority.ts` — remove `UNKNOWN_PRIORITY`; simplify `statusPriority()` to `?? 99`
- `frontend/src/api/ws-validator.test.ts` — adapt for precompiled import
- `frontend/src/utils/status.test.ts` — update after `isKnownMapKey` removal
- `frontend/src/utils/status-priority.test.ts` — update `UNKNOWN_PRIORITY` test
- `frontend/package.json` — add `validators` script
- `tools/check_schemas_fresh.py` — add `ws-validator.generated.ts` freshness check
- `CLAUDE.md` — update Common Commands regenerated artifacts list
- `.claude/rules/frontend-worktree.md` — mention `npm run validators`

### Behavioral Invariants

- `WsValidationError` class and `validateWsMessage()` function signature are unchanged — `use-websocket.ts` call site is untouched
- `statusToVariant()`, `executionStatusKind()`, `statusToKind()`, `statusPriority()`, `isFailureStatus()` return the same values for all known status strings and the same fallback defaults for unknown values
- The `satisfies Record<Union, X>` compile-time exhaustiveness checks remain

### Blast Radius

- **Build pipeline**: one new generated file that must stay fresh — mitigated by extending the existing freshness check
- **Bundle**: removing the Ajv compiler changes what ships — mitigated by keeping `ajv/dist/runtime` and testing the bundle builds
- **Status utility consumers**: functions lose the `console.warn` on unknown values — intentional; the warn was invisible in practice

## Open Questions

- Whether standalone mode needs `Ajv2020` (from `ajv/dist/2020`) vs default `Ajv` for the WS schema's JSON Schema dialect. Verify during implementation.
- Whether the WS discriminator `mapping` stripping is still needed in precompiled mode, or whether Ajv's standalone codegen handles it differently. Resolve when implementing.
