# States — State Registry

**Status:** Stub (3 lines), content moving from Advanced (216 lines)
**Voice mode:** Concept/reference hybrid — system-as-subject

## Outline

Content source: `docs/pages/advanced/state-registry.md`

### H2: What Is the State Registry?
Maps HA entity domains to Python state classes. Automatic registration via `__init_subclass__`.

### H2: How It Works
#### H3: Automatic Registration
State classes register themselves when defined.
#### H3: Domain Lookup
`StateRegistry.get(domain)` → state class.

### H2: Relationship with Type Registry
#### H3: The Complete Flow
Raw HA state string → State Registry (domain → class) → Type Registry (value → typed value).
#### H3: The `value_type` ClassVar
How state classes declare their value type.
#### H3: Why Two Registries?
State Registry = domain mapping, Type Registry = value conversion. Separate concerns.

### H2: State Conversion
#### H3: Direct Conversion
#### H3: Via Dependency Injection

### H2: Domain Override
Overriding the default state class for a domain.

### H2: Union Type Support
How the registry handles `D.StateNew[SensorState | BinarySensorState]`.

### H2: Error Handling
#### H3: InvalidDataForStateConversionError
#### H3: InvalidEntityIdError
#### H3: UnableToConvertStateError

### H2: Advanced Usage — Accessing the Registry
Direct registry access for introspection.

## Snippet Inventory

Moving from `advanced/snippets/state-registry/` (18 files):
| Snippet | Status | Notes |
|---|---|---|
| All 18 files | Move | → `states/snippets/` (review for voice, trim redundant examples) |

## Cross-Links

- **Links to:** Type Registry, Custom States, DI page, States overview
- **Linked from:** States overview, DI page, Custom States
