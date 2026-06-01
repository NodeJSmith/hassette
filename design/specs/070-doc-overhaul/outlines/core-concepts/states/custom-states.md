# States — Custom States

**Status:** Stub (3 lines), content moving from Advanced (159 lines)
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

Content source: `docs/pages/advanced/custom-states.md`

### H2: Basic Custom State Class
Defining a state class for a domain Hassette doesn't cover (custom integrations, etc.).

### H2: Choosing a Base Class
#### H3: StringBaseState
#### H3: NumericBaseState
#### H3: BoolBaseState
#### H3: DateTimeBaseState
#### H3: TimeBaseState
#### H3: Define Your Own

### H2: Adding Custom Attributes
Typed attributes beyond the base `value` field.

### H2: Using Custom States in Apps
#### H3: Via `self.states[CustomStateClass]`
Generic access returns a `DomainStates` collection of the custom type.
#### H3: With Dependency Injection
#### H3: Direct API Access

### H2: Runtime vs Type-Time Access
How state classes interact with the registry at runtime.

### H2: Complete Example
Full custom state class with attributes, registration, and usage in an app.

### H2: Troubleshooting
#### H3: State Class Not Registering
#### H3: Type Hints Not Working
#### H3: State Conversion Fails

## Snippet Inventory

Moving from `advanced/snippets/custom-states/`:
| Snippet | Status | Notes |
|---|---|---|
| `basic_custom_state.py` | Move | → `states/snippets/` |
| `string_base_state.py` | Move | |
| `numeric_base_state.py` | Move | |
| `bool_base_state.py` | Move | |
| `datetime_base_state.py` | Move | |
| `time_base_state.py` | Move | |
| `define_your_own.py` | Move | |
| `adding_custom_attributes.py` | Move | |
| `via_get_states.py` | Move | |
| `known_domain_access.py` | Move | → DI usage example |
| `custom_domain_typed_access.py` | Move | |
| `custom_domain_runtime_access.py` | Move | |
| `direct_api_access.py` | Move | |
| `complete_example.py` | Move | |

## Cross-Links

- **Links to:** State Registry, Type Registry, DI page, DomainStates Reference
- **Linked from:** States overview, DomainStates Reference ("for domains not covered")
