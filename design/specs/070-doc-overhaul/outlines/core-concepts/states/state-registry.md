# State Registry

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (advanced depth page)
**Reader's job:** Understand how Hassette maps HA domains to Python state classes, so they can override a mapping or debug unexpected state types.

## What was cut (and where it goes)

- **"Integration with Other Components" section** (DI integration, States Resource integration) — cut. These are the callers of the registry, not the registry itself. The reader who lands here already came from one of those callers. Repeating the integration examples doubles the content without adding information.
- **"Advanced Usage — Accessing the Registry"** — folded into a one-liner at the end of "Domain Override." Direct registry access is rare; it does not need its own H2.
- **"State Conversion — Direct Conversion"** — cut. `try_convert_state` is an internal API. The reader's job is "override a mapping" or "debug a type," not "call conversion functions directly." DI and `self.states` handle conversion automatically.
- **"Why Two Registries?" rationale** — kept but tightened to 2 sentences in the relationship section. The existing page spent 20+ lines explaining a design decision most readers do not need.

## Outline

### (Opening)
The `StateRegistry` maps Home Assistant domains to Python state model classes. When state data arrives as an untyped dictionary, the registry determines which `BaseState` subclass to use for conversion. Most apps never interact with the registry directly — it works behind `self.states` and the DI system.

State this page matters when: overriding a default mapping, writing a custom state class, or debugging an unexpected state type.

### H2: How Registration Works
Classes that inherit from `BaseState` with a valid `Literal["domain"]` annotation register automatically at class definition time via `__init_subclass__`. No explicit registration call needed.

??? note "Collapsible: implementation details"
Show the `__init_subclass__` hook behavior. The `StateRegistry.register()` call, the domain extraction from the `Literal` type.

### H2: Domain Lookup
`StateRegistry.resolve(domain=...)` returns the registered state class for a domain. Falls back to `BaseState` for unregistered domains.

### H2: Overriding a Domain Mapping
Define a custom class with the same domain as a built-in, after imports. The registry silently replaces the existing mapping. Mention `self.hassette.state_registry` for direct access when needed.

### H2: The Conversion Flow
Brief walkthrough of what happens when state data arrives:
1. Raw dict from HA
2. StateRegistry resolves domain to class
3. Pydantic validation begins
4. `value_type` ClassVar checked — TypeRegistry converts the raw value string
5. Typed state object produced

One-sentence relationship note: StateRegistry answers "which class?", TypeRegistry answers "which Python type for the value?" Link to Type Registry page.

### H2: Union Type Support
How the registry handles `D.StateNew[SensorState | BinarySensorState]` — checks each type's domain, selects the match, falls back to `BaseState`.

### H2: Error Handling
Three specific exceptions, one paragraph each:
- `InvalidDataForStateConversionError` — malformed or missing fields
- `InvalidEntityIdError` — bad entity ID format
- `UnableToConvertStateError` — conversion to target class failed

## Snippet Inventory

Moving from `advanced/snippets/state-registry/` — trim from 18 to ~8 files:

| Snippet | Status | Notes |
|---|---|---|
| `raw_data_example.py` | Move | Opening — what raw data looks like |
| `automatic_registration.py` | Move | H2: How Registration Works (collapsible) |
| `domain_lookup.py` | Move | H2: Domain Lookup |
| `domain_override.py` | Move | H2: Overriding a Domain Mapping |
| `flow_raw_input.py` | Move | H2: Conversion Flow |
| `flow_converted_output.py` | Move | H2: Conversion Flow |
| `value_type_example.py` | Move | H2: Conversion Flow |
| `union_type_support.py` | Move | H2: Union Type Support |
| `error_invalid_data.py` | Move | H2: Error Handling |
| `error_invalid_entity_id.py` | Move | H2: Error Handling |
| `error_unable_to_convert.py` | Move | H2: Error Handling |
| `basic_custom_state_usage.py` | Drop | Covered on Custom States page |
| `di_integration.py` | Drop | Covered on DI page |
| `integration_di.py` | Drop | Duplicate of di_integration |
| `integration_states.py` | Drop | Covered on States overview |
| `example_benefits.py` | Drop | Rationale example, not actionable |
| `direct_conversion.py` | Drop | Internal API, not user-facing |
| `accessing_registry.py` | Drop | One-liner folded into Domain Override prose |

## Cross-Links

- **Links to:** Type Registry, Custom States, DI page, States overview
- **Linked from:** States overview, Custom States
