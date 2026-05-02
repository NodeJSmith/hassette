---
topic: "Event and State Models"
date: 2026-05-01
status: Draft
---

# Prior Art: Event and State Models

## The Problem

Home automation frameworks must bridge two worlds: the dynamic, string-typed state that Home Assistant produces (where every entity has a string `state` and a `dict[str, Any]` attributes bag) and the typed, validated Python objects that application developers want to work with. The modeling choices cascade: how events are typed determines how handlers are dispatched; how state is parsed determines whether attribute access is safe at runtime; how the registry is organized determines how much maintenance burden each new HA release imposes.

The core tension is between completeness and maintainability. HA has 100+ entity domains, each with integration-specific attributes that evolve across releases. Modeling every attribute for every domain is impractical; leaving everything untyped defeats the purpose of a typed framework. The design space covers: how to parse (eager vs lazy), what to parse (known fields vs everything), how to dispatch events (class hierarchy vs discriminated union vs pattern matching), and how to handle the unknown (extra fields, new event types, unfamiliar domains).

## How We Do It Today

Hassette uses **Pydantic-based per-domain typed models with lazy validation**. The `BaseState` is a frozen, generic Pydantic model parameterized over `StateValueT`. A `StateRegistry` maps `(domain, device_class)` tuples to concrete state classes, populated at import time via `__init_subclass__()` which extracts domain from `Literal` type hints. Events are frozen dataclasses (not Pydantic) — `RawStateChangePayload` stores state as `HassStateDict` (TypedDict, no runtime validation). The event bus dispatches raw unvalidated dicts through the entire predicate-matching and dispatch pipeline. Pydantic validation (`BaseState.model_validate()` with `TYPE_REGISTRY.convert()` coercing raw HA values like `"on"` → `True`) only fires when app code accesses state through the StateManager (e.g., `self.states.light["bedroom"]`), with caching via `CacheValue` to prevent re-validation of unchanged state. All models use `extra="allow"` to capture unmapped HA attributes in `model_extra`, accessible via `.extras` property. Events use explicit pattern-matching dispatch by `event_type` string in `create_event_from_hass()` — no Pydantic discriminated unions. ~35 state model files cover the most common HA domains.

## Patterns Found

### Pattern 1: Untyped Dict Passthrough

**Used by**: AppDaemon, python-hass-client (TypedDict variant), most MQTT clients

**How it works**: State and attributes are stored as plain Python dicts. No runtime validation, no type coercion, no model classes. State values remain strings, attributes remain `dict[str, Any]`. AppDaemon's `get_state()` returns the raw dict from its internal cache. python-hass-client uses TypedDicts for structural typing on top-level keys but leaves `attributes` as `dict[str, Any]`.

This approach accepts that HA's attribute schema is dynamic and per-integration, so any static typing will be incomplete. It prioritizes simplicity and zero overhead.

**Strengths**: Zero parsing overhead. No schema maintenance. Never breaks when HA adds attributes. Trivial to implement.

**Weaknesses**: No IDE assistance for attribute access. Runtime `KeyError` on typos. No type coercion (state always a string). Users must memorize attribute names and types.

**Example**: https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html / https://github.com/music-assistant/python-hass-client

### Pattern 2: Per-Domain Typed Models with Registry Dispatch

**Used by**: Home Assistant core (EntityDescription), hassette (STATE_REGISTRY), ESPHome (CONFIG_SCHEMA)

**How it works**: A registry maps domain identifiers to typed model classes. When raw state data arrives, the framework looks up the entity's domain, selects the appropriate model class, and instantiates it with the raw data. Each model defines typed fields for the domain's known attributes (e.g., `LightState` has `brightness: int`, `color_temp: int`).

HA implements this via `EntityDescription` dataclasses with per-domain properties. ESPHome uses Voluptuous-based `CONFIG_SCHEMA` that validates YAML and code-generates typed C++. Hassette uses `STATE_REGISTRY` with Pydantic models populated via `__init_subclass__()`. Unknown domains fall back to a generic `BaseState`.

**Strengths**: Full IDE autocompletion for known domains. Type coercion (string "255" → int 255). Validation catches impossible values. Discoverable API. Makes illegal attribute access detectable by type checkers.

**Weaknesses**: Maintenance burden — every new HA domain or attribute change requires a model update. Incomplete coverage is inevitable. Version coupling with HA releases. Must handle unknown domains gracefully.

**Example**: https://developers.home-assistant.io/docs/core/entity/ / ESPHome CONFIG_SCHEMA

### Pattern 3: Discriminated Union Events

**Used by**: Home Assistant core (`Event[_DataT]`), Pydantic ecosystem, webhook handlers

**How it works**: Event types share a common discriminator field (typically `event_type`). Each concrete event class declares its discriminator value as a `Literal` type. A union annotated with `Field(discriminator='event_type')` enables O(1) dispatch to the correct class.

HA's core uses `Event[Generic[_DataT]]` where `_DataT` binds to specific TypedDicts like `EventStateChangedData`. Pydantic v2 formalizes this with `Field(discriminator=...)`. For evolving external systems, a nested union pattern adds a fallback: inner discriminated union for known types, wrapped in an outer `union_mode="left_to_right"` union with a generic catch-all. This prevents validation errors on unknown event types.

**Strengths**: O(1) dispatch vs O(n) for sequential validation. Full type safety for known events. Type checkers narrow event data based on `event_type`. Clean separation of event-specific logic.

**Weaknesses**: Static unions require code changes for new event types. Union annotations grow verbose. Fallback pattern adds a second layer. Discriminator must be present in all payloads.

**Example**: https://pydantic.dev/docs/validation/latest/concepts/unions/ / https://www.lowlevelmanager.com/2025/05/pydantic-v2-discriminated-unions.html

### Pattern 4: Self-Describing Device Schemas (Exposes)

**Used by**: Zigbee2MQTT, Matter specification, some MQTT device frameworks

**How it works**: Instead of the application defining device attributes, the device itself publishes a schema describing its capabilities. Zigbee2MQTT's "exposes" system defines typed categories (binary, numeric, enum, text, composite, list) with metadata (value ranges, units, access permissions). Each expose has a `type` discriminator and `property` field mapping to MQTT payload keys.

The application reads device definitions at runtime and generates validation logic dynamically. This inverts the registry pattern: instead of the framework maintaining domain-to-model mappings, each device carries its own model. It's essentially a capability-based type system — a device doesn't declare "I am a light"; it declares "I have a numeric property called brightness with range 0-254."

**Strengths**: Zero maintenance for new device types. Capabilities are always accurate. Supports devices spanning multiple domains. Access permissions are explicit. Clients can generate UIs dynamically.

**Weaknesses**: No compile-time type safety. Complex per-device validation. Performance overhead from dynamic schema interpretation. Can't use typed attribute access without runtime codegen.

**Example**: https://www.zigbee2mqtt.io/guide/usage/exposes.html

### Pattern 5: Pydantic Extra Fields for Semi-Structured Data

**Used by**: Any Pydantic-based API client handling evolving external schemas

**How it works**: `ConfigDict(extra='allow')` stores unrecognized fields in `__pydantic_extra__`. Known fields get full validation and coercion; unknown fields are preserved as-is. This creates a "known core + unknown extras" model — typed fields for well-known attributes, with integration-specific custom attributes in extras.

Alternatives: `extra='ignore'` for strict consumers that discard unknowns silently; `extra='forbid'` for internal APIs that reject unknowns entirely. The extras dict can be annotated (e.g., `dict[str, JsonValue]`) for basic validation of unknown fields.

**Strengths**: Typed access for known fields, preservation for unknowns. Graceful degradation when HA adds attributes. No data loss. Pydantic handles coercion for known fields.

**Weaknesses**: Extra fields lack individual validation. IDE autocompletion doesn't cover extras. Easy to forget promoting frequent extras to typed fields. Testing must cover both paths.

**Example**: https://docs.pydantic.dev/latest/api/config/

### Pattern 6: Lazy Parsing with model_construct()

**Used by**: High-throughput Pydantic applications, streaming data pipelines

**How it works**: `model_construct()` creates a model instance without running validators. Raw data is stored and validation/coercion happens on first access (or never). This is Pydantic's escape hatch for trusted data where validation overhead is unacceptable. For home automation processing hundreds of `state_changed` events per second, full Pydantic validation on every event adds measurable latency.

A hybrid approach validates at API boundaries (user-facing responses) while skipping validation on internal event dispatch. A more sophisticated variant does minimal parsing (just the discriminator) in `__init__` and defers full field parsing to property access.

**Strengths**: Dramatically lower parsing overhead for high-frequency events. No wasted work on unaccessed fields. Compatible with full validation when needed.

**Weaknesses**: Deferred errors — invalid data not caught until access. Doesn't run validators, defaults, or alias resolution. Easy to create invalid models. Debugging harder when errors surface far from parse point.

**Example**: https://docs.pydantic.dev/latest/concepts/models/#creating-models-without-validation

### Pattern 7: Generic Typed Containers with Domain Parameterization

**Used by**: Pydantic generic models, FastAPI response wrappers, hassette's `App[AppConfig]`

**How it works**: A generic base class is parameterized by a domain-specific type. `EntityState[T]` wraps domain-specific attribute models in a common state envelope (entity_id, state string, last_changed). This separates common infrastructure (timestamps, context) from domain-specific attributes (brightness, temperature).

Pydantic v2's generic `BaseModel` supports this natively, including JSON schema generation that reflects the parameterized type. Runtime parameterization requires care — Pydantic rebuilds schemas for each concrete parameterization.

**Strengths**: Clean separation of concerns. Type-safe access to both common and domain-specific fields. Reusable base logic. Excellent IDE support via generic type inference.

**Weaknesses**: Generic types add class hierarchy complexity. Runtime parameterization has schema-rebuild overhead. Not all serialization formats handle generics well.

**Example**: https://dev.to/mechcloud_academy/advanced-pydantic-generic-models-custom-types-and-performance-tricks-4opf

## Anti-Patterns

- **Treating state values as typed without conversion**: HA state values are always strings. Naively passing `state.state` to arithmetic causes `TypeError`. AppDaemon users hit this frequently. Any framework must include a type conversion layer, even if models are otherwise untyped. ([source](https://www.home-assistant.io/docs/configuration/state_object/))

- **Exhaustive domain modeling**: Attempting typed models for every HA domain (100+ domains, integration-specific attributes) creates unmaintainable schemas tightly coupled to HA's release cycle. HA itself doesn't do this — `extra_state_attributes` is `dict | None` because attribute schemas are integration-defined. ([source](https://developers.home-assistant.io/docs/core/entity/))

- **Discriminated unions without fallback**: Using `Field(discriminator='event_type')` without a fallback means any new HA event type breaks the parser. External systems evolve independently; the parsing layer must be resilient to unknown discriminator values. ([source](https://www.lowlevelmanager.com/2025/05/pydantic-v2-discriminated-unions.html))

- **Eager full validation on every state change**: Running full `model_validate()` on every `state_changed` event adds overhead that scales with model complexity, not consumer needs. Most events are checked for a single field ("did the light turn on?"). `model_construct()` is the recommended escape hatch for trusted data in hot paths. Hassette already avoids this — the event bus dispatches raw TypedDicts and defers Pydantic validation to state access. ([source](https://dev.to/mechcloud_academy/advanced-pydantic-generic-models-custom-types-and-performance_tricks-4opf))

## Emerging Trends

**Runtime-typed state from device self-description**: Zigbee2MQTT's exposes system and the Matter specification move toward devices self-describing capabilities at runtime rather than relying on application-side schemas. This favors dynamic validation (Pydantic with runtime-constructed models) over static model registries. ([source](https://www.zigbee2mqtt.io/guide/usage/exposes.html))

**Hybrid validation strategies**: The Pydantic ecosystem is converging on `model_construct()` for hot paths and `model_validate()` for cold paths. For home automation: validate user-facing API responses fully, skip validation on internal event dispatch. ([source](https://dev.to/mechcloud_academy/advanced-pydantic-generic-models-custom-types-and-performance-tricks-4opf))

**TypedDict as wire format, Pydantic as domain model**: Use TypedDicts to represent the exact wire format, convert to Pydantic at the boundary where domain logic needs typed access. Separates "what did the API send" from "what does my application need" — wire format evolves independently of domain model. ([source](https://www.speakeasy.com/blog/pydantic-vs-dataclasses-vs-annotations-vs-typedicts))

## Relevance to Us

Hassette's approach combines **Pattern 2** (per-domain typed models with registry dispatch), **Pattern 5** (Pydantic extra fields), **Pattern 6** (lazy validation), and **Pattern 7** (generic typed containers). The `__init_subclass__()` auto-registration is cleaner than manual registry population. The `extra="allow"` + `.extras` accessor is the right compromise for HA's dynamic attributes. Lazy validation with `TYPE_REGISTRY` converters solves the string-state problem that AppDaemon users struggle with, without paying the cost on the hot path.

**What we're doing well:**
- **Lazy validation — already the recommended pattern**: The event bus dispatches raw `HassStateDict` (TypedDict, no Pydantic overhead) through the entire predicate-matching and dispatch pipeline. `BaseState.model_validate()` with `TYPE_REGISTRY.convert()` only fires when app code accesses state via the StateManager, with `CacheValue` preventing re-validation of unchanged state. This is exactly the "hybrid validation" pattern the Pydantic ecosystem recommends (Pattern 6) — hassette already implements it.
- **Auto-registering state models via `__init_subclass__()`** — cleaner than manual dict population and prevents registration-forgetting bugs. This is the decorator-registration pattern without decorators.
- **`extra="allow"` with typed accessor** — the `.extras` property and `.extra(key, default)` method are exactly the "known core + unknown extras" pattern recommended by the Pydantic ecosystem.
- **Frozen models** — immutability prevents a class of bugs where event handlers mutate shared state objects.
- **Generic `BaseState[StateValueT]`** — parametric typing on value type provides stronger guarantees than HA's "everything is a string."
- **Events as frozen dataclasses** — lightweight construction on the hot path (no Pydantic overhead), with `HassStateDict` TypedDicts preserving structural typing without runtime validation cost.

**Gaps worth examining:**

1. **No discriminated union for events**: Events use explicit pattern-matching dispatch (`create_event_from_hass()`) rather than Pydantic discriminated unions. This works but misses O(1) dispatch and type-narrowing benefits. The nested union pattern (discriminated inner + left-to-right fallback outer) would add type safety while handling unknown event types gracefully. Whether this is worth the migration depends on how often event dispatch is a bottleneck. Note: since events are dataclasses (not Pydantic), adopting discriminated unions would require either migrating event payloads to Pydantic or building a manual dispatch registry — the pattern-matching approach may be the better fit for the current architecture.

2. **Maintenance burden of ~35 state models**: Hassette covers the most common domains but HA has 100+. The current coverage is pragmatic, but new HA releases may add attributes to covered domains. There's no mechanism to detect when a model is stale (i.e., HA added a new attribute that should be a typed field). Periodic diffing against HA's entity registry could automate staleness detection.

3. **Dataclass/Pydantic split**: State models are Pydantic, events are dataclasses. This is actually a deliberate performance optimization (lightweight event construction on the hot path), but it means events don't benefit from Pydantic's serialization or discriminated union support. If event payloads ever need wire-format parsing (e.g., from a persistent event store), this asymmetry would need resolution.

## Recommendation

Hassette's modeling approach is the most sophisticated in the HA Python ecosystem (AppDaemon doesn't type at all, python-hass-client uses TypedDicts without validation). The combination of typed registry + lazy validation + extra fields + frozen models + dataclass events already implements the recommended hybrid validation pattern — raw dicts on the hot path, Pydantic at the access boundary.

The main area worth evaluating is **model staleness detection** — as HA evolves, covered domains may gain attributes that should be promoted from `model_extra` to typed fields. A periodic diff against HA's entity registry (or a CI check comparing model fields to a live HA instance's attribute keys) would catch drift without requiring exhaustive domain coverage.

Discriminated unions for events are a theoretical improvement but low priority — the current pattern-matching dispatch is fast, and events being dataclasses (not Pydantic) means the migration cost is significant for marginal benefit.

The ~35 state models are the right scope — covering common domains without chasing exhaustiveness. The `extra="allow"` fallback handles everything else gracefully.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/core.py — HA core State and Event classes
- https://github.com/music-assistant/python-hass-client — TypedDict-based HA client
- https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html — AppDaemon untyped state API
- https://developers.esphome.io/architecture/components/ — ESPHome CONFIG_SCHEMA

### Blog posts & writeups
- https://www.lowlevelmanager.com/2025/05/pydantic-v2-discriminated-unions.html — Discriminated union with fallback pattern
- https://gist.github.com/spazm/516f3875ad27db497f37bf8390826d84 — Nested union fallback gist
- https://dev.to/mechcloud_academy/advanced-pydantic-generic-models-custom-types-and-performance-tricks-4opf — Pydantic generics and model_construct()
- https://blog.frankel.ch/illegal-state-unrepresentable/ — Making illegal state unrepresentable
- https://dev.to/dentedlogic/stop-writing-giant-if-else-chains-master-the-python-registry-pattern-ldm — Python registry pattern
- https://www.speakeasy.com/blog/pydantic-vs-dataclasses-vs-annotations-vs-typedicts — Pydantic vs TypedDict comparison

### Documentation & standards
- https://www.home-assistant.io/docs/configuration/state_object/ — HA state object documentation
- https://developers.home-assistant.io/docs/core/entity/ — HA entity developer docs
- https://pydantic.dev/docs/validation/latest/concepts/unions/ — Pydantic discriminated unions
- https://docs.pydantic.dev/latest/api/config/ — Pydantic model_config
- https://www.zigbee2mqtt.io/guide/usage/exposes.html — Zigbee2MQTT exposes
- https://talbotknighton.github.io/pydantic-discriminated/ — pydantic-discriminated library
