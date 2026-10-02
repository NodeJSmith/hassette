---
topic: "Enforcing new-client/old-server wire compatibility for a shared schema package"
date: 2026-09-29
status: Draft
---

# Prior Art: Enforcing New-Client/Old-Server Wire Compatibility

## The Problem

A shared wire-model package (`hassette-wire`) is parsed by clients that may be newer than the server they talk to: the HA integration pins a client range, and users upgrade the integration before upgrading their hassette server. Two changes break that direction. A response field added as required fails a newer strict client when an older server omits it. New enum/Literal values break the other direction, where an older client talks to a newer server. The question is whether off-the-shelf breaking-change checkers enforce this mechanically, or whether it needs a custom check.

## How We Do It Today

`tools/check_schemas_fresh.py` (pre-push) and the CI "Regenerate schemas" + `git diff --exit-code` step only compare generated schemas against the same branch's code. Nothing diffs against a previous release. Spec 114 covers the old-client/new-server direction with a planned CI job (the released client against the HEAD server) plus client-side lenient parsing (#2386). The new-client/old-server direction is covered only by the optional-new-fields rule, written as prose (spec 116 FR#14).

## Patterns Found

### Pattern 1: OpenAPI breaking-change diff against a release baseline (oasdiff)
**Used by**: teams gating API PRs with `oasdiff breaking base revision` or the official `oasdiff/oasdiff-action/breaking` GitHub Action (`fail-on: ERR|WARN`).
**How it works**: Diff the committed OpenAPI spec against a baseline, meaning a previous release's spec from a git ref, and fail on checks at or above a severity. oasdiff scores changes from the *old client / new server* point of view by default. `response-required-property-added` and `response-property-became-required` are `info` (non-breaking). `response-property-enum-value-added` is `error`. For the *new client / old server* direction, the same tool works with the arguments swapped (base = HEAD, revision = last release). A required response field added at HEAD then shows up as `response-required-property-removed` / `response-property-became-optional`, both **error**: "It widens what the API may return, so a client can receive a response it was not written to handle."
**Strengths**: Off-the-shelf, maintained, per-check severities, git-ref baselines, a GitHub Action. It works on the `openapi.json` hassette already commits.
**Weaknesses**: A reversed run also flips *legitimate* additions. A new optional response field reads as `response-optional-property-removed` (info, harmless), but a new endpoint reads as `api-removed-without-deprecation` (breaking), so a reversed run needs oasdiff's documented severity-levels file to disable or lower every check except the response-required ones. The exact flag name and file format weren't confirmed from the docs page. Covers OpenAPI only. WS messages (`ws-schema.json`, JSON Schema) aren't checked. The reversed-argument use is our own application of documented check semantics, not a documented oasdiff workflow. Enum additions show up as errors in the forward direction, which needs `x-extensible-enum` or a lenient client to be tolerable.
**Example**: https://www.oasdiff.com/docs/breaking-changes, https://github.com/oasdiff/oasdiff-action, https://www.oasdiff.com/checks/response-required-property-removed

### Pattern 2: Schema-version handshake at connect time
**Used by**: zwave-js-server / zwave-js-server-python, Music Assistant, python-matter-server (HA ecosystem).
**How it works**: The server reports an integer schema version (or a min/max range). The client refuses, or degrades, when ranges don't overlap. It's a coarse gate, independent of package versions.
**Strengths**: Incompatibility becomes a legible error rather than a parse failure.
**Weaknesses**: Depends on disciplined bumps. It's a gate, not a per-field check. Spec 114 already scoped min/max negotiation out ("revisit if floor-plus-warning proves insufficient").
**Example**: https://github.com/home-assistant-libs/zwave-js-server-python/pull/144

### Pattern 3: Open enums with a documented unknown fallback
**Used by**: Stripe (per-enum open/closed documentation), Stainless-generated SDKs (an `_UNKNOWN` variant).
**How it works**: The provider documents which enums may grow, and clients must handle an unknown case.
**Strengths**: Enum growth stops being breaking for clients.
**Weaknesses**: The classification has to be right up front.
**Example**: https://docs.stripe.com/api/enums, https://www.stainless.com/blog/making-java-enums-forwards-compatible/

### Pattern 4: Eliminate "required" in the schema language (protobuf proto3)
**Used by**: protobuf/buf ("never add a required field").
**How it works**: There's no `required` keyword, so every field is optional with a zero default.
**Weaknesses**: Doesn't port to Pydantic/OpenAPI. There it reduces to a convention that needs external enforcement.
**Example**: https://protobuf.dev/best-practices/dos-donts/

## Anti-Patterns

- **Treating a green default oasdiff run as proof of new-client safety.** A new required response field is scored `info` by default, so a naive forward run misses exactly this hazard. (https://www.oasdiff.com/checks/response-required-property-added)
- **Porting enum-safety assumptions across ecosystems.** Protobuf treats added enum values as safe. oasdiff treats them as `error` for responses.

## Relevance to Us

- Finding 10 (required fields): Pattern 1, run in reverse against the last release tag's `frontend/openapi.json`, gives an off-the-shelf mechanical check for exactly the new-client/old-server hazard. The custom model_fields snapshot test the critic proposed has no prior-art backing (no citable pydantic snapshot convention was found).
- Finding 11 (enum/Literal values): that's the old-client/new-server direction, which spec 114 already assigns to lenient parsing (#2386), a Pattern 3 variant, plus its cross-version CI job. A forward oasdiff run would flag every enum addition as `error`, which is useful as a reminder but belongs with #2386's lenient mode.
- WS messages aren't covered by oasdiff. Spec 114 scopes WS push out of the integration's v0.1, so that gap doesn't matter yet.

## Recommendation

For Finding 10, use oasdiff in reverse (`oasdiff breaking <HEAD openapi.json> <last-release openapi.json> --fail-on ERR`) as the enforcement, in place of a custom snapshot test. For Finding 11, a sentence in the rule text pointing enum/Literal growth at #2386's lenient parsing. Coverage caveat: the buf rule IDs weren't verified verbatim. The reversed-argument oasdiff usage is an application of the documented per-check semantics, not a documented workflow.

## Sources

### Reference implementations
- https://github.com/oasdiff/oasdiff-action: GitHub Action (`base`/`revision`, `fail-on`)
- https://github.com/home-assistant-libs/zwave-js-server-python/pull/144: min/max schema negotiation added after the fact
- https://github.com/music-assistant/models: shared models package

### Documentation & standards
- https://www.oasdiff.com/docs/breaking-changes: check levels and the severity override file
- https://www.oasdiff.com/checks/response-required-property-added: info (not breaking)
- https://www.oasdiff.com/checks/response-property-became-required: info (not breaking)
- https://www.oasdiff.com/checks/response-required-property-removed: error (breaking)
- https://www.oasdiff.com/checks/response-property-became-optional: error (breaking)
- https://www.oasdiff.com/checks/response-property-enum-value-added: error (breaking)
- https://protobuf.dev/best-practices/dos-donts/: never add required fields
- https://buf.build/docs/breaking/rules/: buf rules (IDs not verified verbatim)
- https://docs.stripe.com/api/enums: open vs closed enums
- https://www.stainless.com/blog/making-java-enums-forwards-compatible/: the unknown enum variant
