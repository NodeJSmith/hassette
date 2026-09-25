---
topic: "Sharing wire models between a server and its Python client package"
date: 2026-09-25
status: Draft
---

# Prior Art: Sharing Wire Models Between Server and Client Packages

## The Problem

A project that ships both a server and a Python client wants one definition of its wire models. It has to decide which package owns them, how the server gets strict validation while the client parses a newer server leniently, and how versions line up when a downstream consumer (here, a Home Assistant integration) pins the client as a range.

## How We Do It Today

The wire models live in the server (`src/hassette/web/models.py`, `src/hassette/schemas/`), mixed with internal domain objects. The frontend consumes them via OpenAPI → generated TypeScript. Spec 114 proposes that `hassette-client` own the wire models, that the server import them from it, and that both release in lockstep. The `[cli]` extra puts the `hassette` CLI in the client package, so hassette depends on `hassette-client[cli]` anyway.

## Patterns Found

### Pattern 1: Three packages: models, client, server
**Used by**: Music Assistant (`music-assistant-models`, `music-assistant-client`, server); structurally, protobuf-generated packages and Kubernetes `k8s.io/api` + `apimachinery`.
**How it works**: A models-only package with no transport. The client and server both depend on it.
**Strengths**: Names say what each package is, the models package stays tiny, and both sides depend down.
**Weaknesses**: A third artifact to publish and order. Coordinated releases for breaking changes.
**Example**: https://github.com/music-assistant/models

### Pattern 2: One package, client as the base install, server behind an extra
**Used by**: python-matter-server (`[server]` extra).
**Strengths**: Lockstep by construction, one repo, a lightweight client install.
**Weaknesses**: Coarse versioning, and it makes the server the optional part.
**Example**: https://github.com/matter-js/python-matter-server

### Pattern 3: Models inside the client package, imported by the server
**Used by**: No precedent found. It's the current spec 114 plan.
**Weaknesses**: The name suggests downstream or permissive semantics, which invites client-flavored changes to the authoritative contract.

### Pattern 4: One model class, strictness chosen at the call site
**Used by**: pydantic strict mode (per call / per field), Stripe SDK open enums (`Literal[...] | str`), protobuf open enums (Editions 2024+).
**How it works**: The server validates strictly and the client leniently, with no second model set.
**Weaknesses**: The right mode has to be chosen at every call site unless a helper encodes it once.
**Example**: https://docs.pydantic.dev/latest/concepts/strict_mode/, https://protobuf.dev/programming-guides/enum/

## Anti-Patterns

- **Required fields added to shared models break an older server.** In Music Assistant's mobile-app issue #1012, a newer client's non-nullable new fields failed every call against an older server, with no clear error. https://github.com/music-assistant/mobile-app/issues/1012
- **One strictness everywhere.** No surveyed ecosystem validates identically on both sides.
- **Schema negotiation added only after skew hurt.** zwave-js-server-python added min/max schema versions after the fact (PR #144). https://github.com/home-assistant-libs/zwave-js-server-python/pull/144

## Relevance to Us

- **Strictness split:** spec 114's client-side validation mode (Finding 1) matches Pattern 4. That part is standard.
- **Layout:** spec 114's layout is Pattern 3, the one with no precedent. Pattern 1's main advantage, that both sides depend downward, is largely moot for hassette, because hassette already depends on `hassette-client[cli]` for its CLI. A models package would still fix the naming and give the contract a home that's plainly authoritative.
- **Pattern 2:** a poor fit. `hassette` is a framework that app authors import, not an optional server.
- **The #1012 footgun applies directly.** The HA integration's client can be newer than the user's server whenever the server sits above `MIN_HASSETTE_VERSION`, so a required field added to a wire model breaks it.

## Recommendation

- **Layout:** either Pattern 1 (a `hassette-models` package) or Pattern 3 with an explicit `hassette_client.models` namespace. Given the `[cli]` dependency, Pattern 3 plus a sub-namespace captures most of Pattern 1's naming benefit without a third artifact.
- **New wire fields:** fields added after the first release are optional with a default. A new required field forces a `MIN_HASSETTE_VERSION` bump.

Coverage caveat: no source was found for a direct Pattern 3 precedent, or for HA's no-exact-pin rule as a documentation page (the epic cites core #173019 and hassfest PR #181913 instead).

## Sources

### Reference implementations
- https://github.com/music-assistant/models — shared models package
- https://github.com/music-assistant/client — client depends on the models package
- https://github.com/music-assistant/server — server depends on the models package
- https://github.com/matter-js/python-matter-server — client as the base install, `[server]` extra
- https://github.com/home-assistant-libs/zwave-js-server-python — min/max schema negotiation
- https://github.com/home-assistant-libs/zwave-js-server-python/pull/144 — negotiation added later
- https://github.com/music-assistant/mobile-app/issues/1012 — required-field skew failure

### Documentation & standards
- https://protobuf.dev/programming-guides/enum/ — open enums
- https://protobuf.dev/best-practices/dos-donts/ — compatibility rules
- https://docs.stripe.com/api/enums — open enums in the SDK
- https://docs.pydantic.dev/latest/concepts/strict_mode/ — per-call strictness
- https://developers.home-assistant.io/docs/creating_integration_manifest/ — manifest requirements
