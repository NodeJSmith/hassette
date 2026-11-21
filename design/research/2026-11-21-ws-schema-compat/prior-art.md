---
topic: "Mechanical breaking-change detection for WebSocket JSON Schema payloads (#2439)"
date: 2026-11-21
status: Draft
---

# Prior Art: Breaking-Change Detection for WS Message Schemas

## The Problem

`frontend/ws-schema.json` describes every message the hassette server pushes over its WebSocket. It is a Pydantic `TypeAdapter(WsServerMessage)` schema: a root `oneOf` over 7 `*WsMessage` `$ref`s, discriminated on a `type` `const`, with 16 `$defs`. `tools/check_wire_compat.py` gates the HTTP contract (`openapi.json`) with oasdiff in both skew directions against the last release tag. The WS schema only gets a freshness diff, so a breaking WS change ships undetected. #2439 asks for the same both-direction check on WS payloads: a new optional field or message type passes, while a removed field, a field that becomes required, or a removed message type fails.

The question this brief answers: is there a tool to adopt, does the existing oasdiff pipeline stretch to cover it, or does it need a custom JSON-Schema comparator, as the issue assumes?

## How We Do It Today

- **HTTP check.** `check_wire_compat.py` runs `oasdiff breaking` twice.
  - Reversed run (HEAD → release, new client vs old server) blocks only on an allowlist: `response-required-property-removed` and `response-property-became-optional`.
  - Forward run (release → HEAD, old client vs new server) blocks on every ERR except `response-property-enum-value-added`, because the client parses leniently.
  - `--severity-levels` raises `response-property-enum-value-removed` to ERR.
  - Waivers are verbatim oasdiff `--err-ignore` lines in `tools/wire_compat_ignore.txt`.
  - If no release tag is reachable, the check exits 1. It never skips.
- **Schema shape.**
  - Objects are open: no model sets `extra`, and the schema has no `additionalProperties`.
  - An optional field is `anyOf: [T, {"type": "null"}]` with `default: null` and is left out of `required`.
  - Enums are `$defs` with `enum`. A Literal is a `const`.
  - The schema is server → client only; the server receives no client messages.
- **Consumers.**
  - The frontend is built into the server, so it ships in lockstep and never skews (the same situation as HA core and its frontend). It drops a frame that fails validation.
  - The Python client (`hassette-client`) parses leniently: unknown fields are ignored, and an unknown enum or Literal value becomes `UnknownValue`.
  - No WS client exists yet. #3993 adds one, so the "ignore unknown `type`" contract is set now.

## Patterns Found

### Pattern 1: Hand-bumped schema version, negotiated at connect ("they don't diff")
**Used by**: zwave-js-server and zwave-js-server-python, Music Assistant, python-matter-server.
**How it works**: The server advertises a current schema version and the minimum it still serves, and the client refuses to connect when its version falls outside that window. Music Assistant's `constants.py` documents the bump policy: bump `API_SCHEMA_VERSION` for additions, and bump `MIN_SCHEMA_VERSION` only for removals or type changes.
**Strengths**: Cheap. An incompatible client gets a clear refusal instead of a parse failure.
**Weaknesses**: It's convention only. None of the three repos has CI that checks a removal came with a MIN bump.
**Example**: `MIN_SCHEMA_VERSION = 28` / `API_SCHEMA_VERSION = 124` (Music Assistant); `MIN = MAX = 52` (zwave-js-server-python).
**Read**: `music_assistant/constants.py:65-81`; `zwave_js_server/const/__init__.py:16-18`; `matter_server/common/const.py`, `server/const.py`, `client/connection.py:83-95`; zwave-js-server `src/lib/const.ts`.

### Pattern 2: Lockstep release
**Used by**: HA core and HA frontend.
**How it works**: Core pins `home-assistant-frontend==<date>` in its manifest, so the first-party WS client never skews. Command schemas are voluptuous validators next to each handler. No schema artifact or breaking-change gate was found.
**Strengths**: The skew problem doesn't exist for the first-party client.
**Weaknesses**: Third-party clients get no checkable contract.
**Read**: `homeassistant/components/frontend/manifest.json:25`, `websocket_api/const.py`, `tests/components/websocket_api/`.

### Pattern 3: Wrap the message schema in an OpenAPI doc so the existing OpenAPI differ covers it
**Used by**: No project found doing this. We tested it here, first on a toy union and then on the real `ws-schema.json`.
**How it works**: Rewrite `#/$defs/` refs to `#/components/schemas/`, put the union in as `components.schemas.WsServerMessage`, and reference it from one fake `GET /__ws/server-messages` 200 response. Then oasdiff's response rules grade every message change, with the same IDs the HTTP check already handles. Two details matter:
- **Unreferenced components are skipped.** oasdiff's walkers start from `paths` (`checker/media_type_walker.go:216-220`), so the fake operation is required: a `paths: {}` doc produced no field findings.
- **Response-only, not request plus response.** Hassette's WS is server → client only, so the wrapper uses only a response. If the same union also sat on a request, every message-type add or remove would be ERR in one direction or the other.
**Strengths**:
- No new dependency or install step: oasdiff 1.38.0 is already pinned in mise and CI.
- Waivers reuse the existing `--err-ignore` format and file, with lines like `GET /__ws/server-messages ...`.
- The tag resolution, severity overrides and blocking logic in `check_wire_compat.py` apply unchanged.
- `composed_nullability.go` understands Pydantic's `anyOf [T, null]`.
**Weaknesses**:
- Findings say "response" and name a fake path instead of "message type". The failure output has to translate.
- oneOf branches are matched by `$ref` name, so renaming a model with the same wire shape reads as one branch removed and one added (`diff/subschemas_diff.go:12-30`).
- Discriminator-mapping rules are all INFO. The `const` change carries the rename signal.
**Read**: oasdiff `checker/rules.go`, `media_type_walker.go`, `check_components_schemas_removed.go`, `diff/subschemas_diff.go`. We ran oasdiff 1.38.0 `changelog` against eight mutations of the real `ws-schema.json` (table below).

### Pattern 4: Direction-aware compatibility verdicts (BACKWARD / FORWARD)
**Used by**: Confluent Schema Registry (JSON Schema provider), jsoncompat (`serializer` / `deserializer` roles), oasdiff (request vs response levels).
**How it works**: Diff once and judge twice. Confluent's `isBackwardCompatible(prev)` is `SchemaDiff.compare(prev, this)` followed by "every `Difference.Type` is in the compatible set", and FORWARD is the same call with the arguments swapped. Each named change type (`SUM_TYPE_EXTENDED`, `ENUM_ARRAY_NARROWED`, `REQUIRED_ATTRIBUTE_ADDED`, `OPTIONAL_PROPERTY_ADDED_TO_OPEN_CONTENT_MODEL`, and so on) is compatible in exactly one direction.
**Strengths**: The best-written rule table, and it is the semantic model the oasdiff run already implements.
**Weaknesses**: Under FULL (both directions), a sum type can't evolve. Adding a variant is BACKWARD-only (Yokota), so "new message type passes" is a policy choice, not something the rules derive. Open content models make Confluent's strict mode call "add optional field" a BACKWARD break. Its lenient mode, which follows the robustness principle, is the right one for Pydantic's ignore-extra consumers.
**Read**: Confluent `diff/SchemaDiff.java:41-135`, `Difference.java`, `CombinedSchemaDiff.java`, `JsonSchema.java:1141-1190`; Yokota's blog posts (secondary: highlights).

### Pattern 5: The tool emits typed changes, and a small policy wrapper decides what fails
**Used by**: Sentry (`sentry-kafka-schemas` post-processes `json-schema-diff` output), Atlassian's `json-schema-diff-validator` (`allowNewOneOf` and `allowNewEnumValues` flags).
**How it works**: The diff engine reports changes, and the wrapper owns the blocking table. `check_wire_compat.py` already works this way: its allowlist and blocklist sets are the policy.
**Read**: Sentry `src/types.rs:195-260` and README.

## Tool Evaluation

| Tool | Install | Verdict | Why |
|---|---|---|---|
| oasdiff via an OpenAPI wrapper | Already pinned (1.38.0) | **Adopt** | Grades every case on the real schema (table below), and reuses our waivers and policy sets |
| jsoncompat (PyPI 0.6.0, Rust core) | pip wheel | Not as a gate | Alpha. It returns `unknown` for exactly the cases that must pass (new optional field, new message type) |
| getsentry/json-schema-diff | Rust build, not on PyPI | Reject | Ignores `oneOf` entirely: it printed nothing until `oneOf` was rewritten to `anyOf` |
| Atlassian json-schema-diff | npm | Reject | Ignores `const` and `enum`, so it reported "no differences" for a new message type and for a renamed Literal |
| asyncapi/diff | npm | Reject | Classifies nothing below `payload`, so field-level changes come out `unclassified` |
| Confluent JSON Schema checker | JVM, coupled to the registry | Prior art only | Its rule table informs the policy |
| jsonschema-changelog, api-schema-diff | PyPI | Not evaluated | Read from the README only. Single-maintainer packages, no oneOf or discriminator semantics claimed |

## Experiment: oasdiff on the real `ws-schema.json`

Response-only wrapper. "Forward" is `changelog release HEAD` (old client, new server). "Reversed" is `changelog HEAD release` (new client, old server). Only ERR (level 3) findings are listed. The last column applies `check_wire_compat.py`'s current policy sets without changes.

| Mutation at HEAD | Forward ERR | Reversed ERR | Outcome under today's HTTP policy | Wanted (#2439) |
|---|---|---|---|---|
| Add required field | none | `response-required-property-removed` | **fail** (reversed allowlist) | fail ✓ |
| Add optional field | none | none | pass | pass ✓ |
| Remove message type | none (`one-of-removed` is INFO) | `response-body-one-of-added` | **pass**: not in the reversed allowlist | fail ✗ |
| Add message type | `response-body-one-of-added` | none | **fail**: forward blocks every ERR | pass ✗ |
| Enum value added | `response-property-enum-value-added` | none | pass (forward allowlist) | pass ✓ |
| Enum value removed | promoted to ERR by override | n/a | **fail** | fail ✓ |
| Rename discriminator Literal | `response-property-const-changed` | `response-property-const-changed` | **fail** | fail ✓ |
| Widen `number` → `number \| null` | `response-property-list-of-types-widened` | none | **fail** | fail ✓ (a strict old client gets null) |

Removing an optional field is INFO in both directions and passes, which matches the HTTP check today.

The policy needs exactly two changes, and both are explained by the asymmetry this mismatch reflects:
1. **Forward:** allow `response-body-one-of-added`, so a new message type passes. It's the same reasoning as the existing `enum-value-added` exemption, and it depends on the WS client ignoring unknown `type`s.
2. **Reversed:** block `response-body-one-of-added`, which in that run means HEAD lacks a type the release sends, so a removed message type fails.

Both changes must be scoped to the WS run. Adding them to the HTTP run would also change HTTP oneOf behavior. Whether HTTP should get them too is a separate decision.

## Anti-Patterns

- **Running a differ that ignores the union's keywords.** Sentry's differ ignores `oneOf`, and Atlassian's ignores `const` and `enum`. On a Literal-discriminated union both exit 0 with "no differences": a silent pass.
- **Diffing components that no operation reaches.** oasdiff skips them with no warning.
- **Assuming a variant addition is safe without a client contract.** It's safe only if old readers ignore unknown `type`s. Our frontend drops them, but it's lockstep anyway. The Python WS client (#3993) doesn't exist yet, so the check's forward exemption has to be paired with that client behavior. (Confluent FULL, oasdiff ERR, Atlassian's `allowNewOneOf=false` default.)
- **Hand-bumped versions with no check** (Pattern 1). Nothing proves a removal came with a MIN bump.

## Gaps

- We didn't read oasdiff's docs on the severity-override flags. The existing `check_wire_compat.py` already uses `--severity-levels` and `--err-ignore`, which covers what's needed.
- buf rows (field, message and oneof delete) come from general knowledge, not the extracted rules page. They don't affect the recommendation.
- `jsonschema-changelog` and `api-schema-diff` were never installed or run.
- HA core and frontend: `gh` code search returned 404. "No breaking-change gate" rests on reading the trees and the WS API files, not an exhaustive search.

## Relevance to Us

- **The ecosystem doesn't mechanically diff WS schemas.** HA peers use hand-bumped versions or lockstep releases. #2439 already goes further than any HA-ecosystem peer, so the cheapest mechanism that works is the right size.
- **The issue's premise ("needs its own JSON-Schema comparator") doesn't hold.** The comparator already exists: oasdiff, through a ~15-line wrapper. A custom walker would reimplement `$ref` resolution, oneOf branch matching and nullable `anyOf` normalization, all of which oasdiff already does, and would need its own waiver format. That is more machinery than the problem calls for.
- **Most of the issue's open decisions are already answered** by the HTTP check's existing policy and the experiment above:
  - **Waiver file:** shared, because oasdiff's `--err-ignore` format carries over.
  - **Code location:** extend `check_wire_compat.py`. Same tag resolution, same runs, plus one spec.
  - **No release tag:** fail loudly, the existing behavior. `ws-schema.json` exists in every tag since v0.54.0.
  - **Type widening:** blocks in the forward run.
  - **Discriminator rename:** blocks both ways via `const-changed`.
  - **Enum and Literal values:** HTTP rules: an addition is allowed forward, a removal blocks.
- **Two real decisions remain:**
  1. A new message type passes only if the WS client ignores unknown `type`s. That's a contract to state now for #3993.
  2. Removing a message type should fail, which needs the reversed-run addition above.

## Recommendation

Wrap `ws-schema.json` as a response-only OpenAPI 3.1 doc in memory, generated from the release tag's file and HEAD's. Run it through `check_wire_compat.py`'s existing oasdiff pipeline as a third and fourth run with WS-specific policy sets:
- **Forward:** additionally allow `response-body-one-of-added`.
- **Reversed:** additionally block `response-body-one-of-added`.

Reuse `tools/wire_compat_ignore.txt` for waivers. Translate findings for the fake path to say "WS message" in the failure output. State, in the wire package docs and #3993, the client contract that unknown `type` values are ignored.

Don't adopt jsoncompat, Sentry, Atlassian or asyncapi tools: each either can't see the union's keywords or can't give verdicts on the cases that must pass. Don't write a custom comparator: oasdiff already covers every case in the issue's pass/fail list on the real schema.

## Sources

### Reference implementations
- https://github.com/oasdiff/oasdiff: `checker/rules.go`, `checker/media_type_walker.go`, `diff/subschemas_diff.go`, `checker/composed_nullability.go`
- https://github.com/confluentinc/schema-registry/tree/master/json-schema-provider: `diff/SchemaDiff.java`, `Difference.java`, `JsonSchema.java`
- https://github.com/getsentry/json-schema-diff: `src/types.rs`, `src/diff_walker.rs`
- https://github.com/asyncapi/diff: `src/standards/v3.ts`, `src/classifier.ts`
- https://github.com/ostrowr/jsoncompat, https://pypi.org/project/jsoncompat/: set-inclusion prover with roles
- https://bitbucket.org/atlassian/json-schema-diff and https://bitbucket.org/atlassian/json-schema-diff-validator: read from the npm tarballs
- https://github.com/zwave-js/zwave-js-server, https://github.com/home-assistant-libs/zwave-js-server-python: schema version negotiation
- https://github.com/music-assistant/server: `constants.py` bump policy
- https://github.com/home-assistant-libs/python-matter-server: `SCHEMA_VERSION`/`MIN_SCHEMA_VERSION`
- https://github.com/home-assistant/core: frontend pin, `websocket_api`

### Blog posts & writeups
- https://yokota.blog/2021/03/29/understanding-json-schema-compatibility/: backward and forward rules for JSON Schema
- https://yokota.blog/2025/10/07/json-schema-compatibility-and-the-robustness-principle/: lenient policy; full compatibility forbids sum-type evolution

### Documentation & standards
- https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html: compatibility types
- https://docs.confluent.io/platform/current/schema-registry/fundamentals/serdes-develop/serdes-json.html: open vs closed content model
- https://buf.build/docs/breaking/rules/: protobuf breaking rules (partly read)
- https://pypi.org/project/jsonschema-changelog/, https://pypi.org/project/api-schema-diff/ (README only)
- design/research/2026-09-29-wire-compat-enforcement/research.md: the HTTP-side brief this extends
