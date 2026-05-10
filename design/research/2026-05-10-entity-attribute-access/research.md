---
topic: "typed Python wrappers around Home Assistant entities — attribute access patterns"
date: 2026-05-10
status: Draft
---

# Prior Art: Entity Attribute Access Patterns

## The Problem

When building typed entity wrappers around Home Assistant state data, the core design question is: how should automation authors access entity attributes like brightness, color_temp, or hvac_mode? The answer affects ergonomics (how much code users write), type safety (IDE support, static analysis), scalability (maintenance cost as entity types grow), and clarity (one obvious way to access data).

## How We Do It Today

Hassette uses nested typed access: `entity.state.attributes.brightness`. The `LightAttributes` class is a fully-typed Pydantic model with all known HA light attributes declared. `BaseEntity` provides shortcut properties for `.entity_id`, `.domain`, and `.value` only. No `__getattr__` delegation exists. The state layer is frozen (immutable), and `extra="allow"` captures custom integration attributes.

## Patterns Found

### Pattern 1: Nested Typed Attributes (Structured Access)

**Used by**: NetDaemon (C#), python-hass-client, zigpy, python-kasa (post-0.7)

**How it works**: Entity state is modeled with attributes as a nested typed object. Access follows the data structure: `entity.attributes.brightness`. The attributes object is a typed class (dataclass, record, or Pydantic model) with all known attribute fields declared. A code generator can create per-domain attribute types for full IDE support.

NetDaemon uses `Entity<TAttributes>` where TAttributes is a code-generated record. python-kasa migrated TO this pattern in 0.7, deprecating flat device-level properties because they didn't scale to heterogeneous device types.

**Strengths**:
- Full type safety and IDE autocomplete
- Serialization is straightforward (model IS the wire format)
- Scales naturally to many entity types (each domain gets its own attributes type)
- Clear separation between entity identity, state value, and detailed attributes

**Weaknesses**:
- More verbose: `entity.attributes.brightness` vs `entity.brightness`
- Requires typed attribute classes per domain (already done in hassette)

**Example**: https://netdaemon.xyz/docs/user/hass_model/hass_model_working_with_entities/

### Pattern 2: Flat Convenience Properties (Explicit @property)

**Used by**: Home Assistant Core (entity base classes), python-kasa (pre-0.7, now deprecated)

**How it works**: The entity class declares explicit `@property` methods for each known attribute. Users access `entity.brightness` directly. Properties read from internal state and return typed values.

In HA Core: `LightEntity` has `@property brightness -> int | None` backed by `_attr_brightness`. SQLAlchemy's `association_proxy` is the same idea — explicit descriptor per forwarded attribute.

**Strengths**:
- Most ergonomic: shortest access path
- Full type safety (explicit return type per property)
- IDE autocomplete works perfectly

**Weaknesses**:
- Doesn't scale: every attribute needs a property declaration
- python-kasa deprecated this because it became a "god object" with dozens of Optional properties
- Maintenance burden grows linearly with attribute count
- Creates ambiguity if nested access is also available

**Example**: https://developers.home-assistant.io/docs/core/entity/

### Pattern 3: Dynamic Delegation via __getattr__

**Used by**: Generic Python proxy libraries, some internal frameworks

**How it works**: `__getattr__` intercepts unknown attribute access and looks it up in a nested attributes dict. Zero boilerplate — any attribute works automatically.

**Strengths**:
- Zero declarations needed
- Scales infinitely

**Weaknesses**:
- **Type safety destroyed** — type checkers treat all accesses as valid (returns Any)
- **No IDE autocomplete** — editor doesn't know what exists
- **Breaks Pydantic** — conflicts with Pydantic's internal `__getattr__` usage, breaks model_dump(), serialization
- **No Python typing solution exists** (confirmed Jan 2025 discuss.python.org thread)
- Typos silently succeed at type-check time

**Example**: https://discuss.python.org/t/typing-support-for-common-proxy-and-delegation-patterns/77909

### Pattern 4: Computed Field Forwarding (Pydantic-native)

**Used by**: Pydantic v2 applications, FastAPI response models

**How it works**: `@computed_field @property` on the entity model forwards selected nested attributes to the top level. Provides flat access while maintaining the nested structure for serialization.

```python
class LightEntity(BaseEntity[LightState, str]):
    @computed_field
    @property
    def brightness(self) -> int | None:
        return self.state.attributes.brightness
```

**Strengths**:
- Full type safety and IDE support
- Serialization-aware (appears in model_dump output)
- Can selectively expose only the most-used attributes (not all)
- Clear that nested model is source of truth

**Weaknesses**:
- Still requires explicit declaration per forwarded attribute
- Creates two access paths (entity.brightness AND entity.state.attributes.brightness)
- Read-only by nature
- Code volume grows with forwarded attributes

**Example**: https://docs.pydantic.dev/latest/concepts/fields/

### Pattern 5: Code-Generated Typed Wrappers

**Used by**: NetDaemon, protobuf/gRPC stubs, OpenAPI generators, HA Core stubs

**How it works**: A code generator reads the schema and produces typed Python classes. The generated code uses Pattern 1 or 2, but maintenance burden is eliminated by automation. NetDaemon generates domain-specific Entity subclasses from a live HA instance.

**Strengths**:
- Best of both worlds: explicit types without manual maintenance
- Regenerate when HA updates
- Schema-first: HA instance is source of truth

**Weaknesses**:
- Requires build-time tooling
- Doesn't help with truly dynamic attributes (custom integrations)
- Generated code can be large and hard to review

**Example**: https://netdaemon.xyz/docs/user/hass_model/hass_model_codegen/

## Anti-Patterns

- **`__getattr__` on Pydantic models**: Conflicts with Pydantic v2 internals, breaks serialization and field tracking. Multiple Pydantic changelog entries document fixes for this exact conflict.
- **Flattening all attributes onto a single class**: python-kasa's deprecation demonstrates why — heterogeneous device types create god objects with dozens of irrelevant `None` properties.
- **Mixing flat AND nested without a canonical answer**: If both `entity.brightness` and `entity.attributes.brightness` exist, users don't know which to use, reviews flag inconsistency, and the two paths can diverge.

## Emerging Trends

- **Migration from flat to nested**: python-kasa 0.7 is the strongest evidence. Convenience properties deprecated in favor of module-qualified access for extensibility.
- **Code generation as the scalability answer**: NetDaemon, OpenAPI, protobuf — generating typed wrappers from schemas eliminates the flat-vs-nested tradeoff.
- **Typing ecosystem may eventually support proxies**: Jan 2025 Python discussion proposes `Proxy[T]` magic superclass. No PEP yet — explicit properties remain the only type-safe option today.

## Relevance to Us

Hassette is in a strong position:
- **State layer already done**: 40+ typed `*Attributes` classes exist with full Pydantic typing. This is Pattern 1's nested typed access already in place.
- **Current access**: `entity.state.attributes.brightness` — one level more nested than most libraries (entity → state → attributes vs entity → attributes).
- **Pydantic constraints**: `__getattr__` is off the table (breaks Pydantic internals). This rules out Pattern 3 entirely.
- **Existing convention**: The attributes classes already have helper properties (e.g., `supports_effect`, `supports_flash`). Users familiar with the state layer will expect attributes to live on the attributes object.

The key question is whether to:
1. **Shorten the path** from `entity.state.attributes.X` to `entity.attributes.X` (one hop fewer, like NetDaemon)
2. **Selectively forward** the 3-5 most common attributes as `@computed_field` properties (Pattern 4)
3. **Leave it nested** and invest in good documentation/IDE support

## Recommendation

**Primary access: `entity.attributes.X`** (shorten by one hop). Add an `attributes` property on `BaseEntity` that delegates to `self.state.attributes`. This gives the NetDaemon-style `entity.attributes.brightness` pattern — typed, IDE-friendly, no duplication, no maintenance burden. The full path `entity.state.attributes.X` still works for anyone who needs it.

**Optional selective forwarding**: For the 2-3 most universal properties (`is_on`, `brightness` for lights; `temperature` for climate), consider `@computed_field @property` on the entity. Keep this minimal — don't forward everything or you recreate the god-object anti-pattern.

**Skip `__getattr__`** entirely — it breaks Pydantic, breaks type checking, and the Python typing ecosystem has no solution.

**Future path**: If the entity count grows beyond 10 domains with heavy attribute sets, consider code generation (Pattern 5) using hassette's existing typed state models as the schema source.

## Sources

### Reference implementations
- https://netdaemon.xyz/docs/user/hass_model/hass_model_working_with_entities/ — NetDaemon typed entity access
- https://netdaemon.xyz/docs/user/hass_model/hass_model_codegen/ — NetDaemon code generation
- https://github.com/music-assistant/python-hass-client — music-assistant's HA client (TypedDict approach)
- https://python-kasa.readthedocs.io/en/latest/topics.html — python-kasa module architecture
- https://python-kasa.readthedocs.io/en/stable/deprecated.html — python-kasa flat property deprecation
- https://github.com/zigpy/zha-device-handlers — zigpy device hierarchy

### Blog posts & writeups
- https://discuss.python.org/t/typing-support-for-common-proxy-and-delegation-patterns/77909 — Python proxy typing discussion (Jan 2025)
- https://github.com/microsoft/pyright/discussions/5926 — Pyright __getattr__ behavior

### Documentation & standards
- https://developers.home-assistant.io/docs/core/entity/ — HA Core entity platform docs
- https://appdaemon.readthedocs.io/en/latest/AD_API_REFERENCE.html — AppDaemon entity API
- https://docs.sqlalchemy.org/en/21/orm/extensions/associationproxy.html — SQLAlchemy association proxy
- https://docs.python.org/3/howto/descriptor.html — Python descriptor protocol
- https://docs.pydantic.dev/latest/concepts/fields/ — Pydantic computed_field docs
