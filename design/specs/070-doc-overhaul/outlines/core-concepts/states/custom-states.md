# Custom States

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Create a typed state class for a Home Assistant domain that Hassette does not cover (custom integrations, third-party add-ons).

## What was cut (and where it goes)

- **"Runtime vs Type-Time Access" section** — cut. This distinction (property access vs `states[Class]`) is an implementation detail about the `.pyi` stub. The "Using Custom States" section covers both access patterns naturally without naming the mechanism.
- **Troubleshooting section** — kept but tightened. Three concrete failure modes, one sentence each.
- **"Complete Example" section** — cut as a standalone section. The realistic example in "Adding Custom Attributes" already shows a full class. A second "complete" example adds length without new information.
- **Best Practices** — cut as a section header. The two actionable rules (one domain per class, use `Literal` for domain) are folded into the opening and "Basic Custom State" sections where the reader encounters them naturally.

## Outline

### (Opening)
Hassette auto-generates typed state classes for standard HA domains. For custom integrations or third-party add-ons, a custom state class maps an unrecognized domain to a typed Python model. Define the class, and the State Registry picks it up automatically.

### H2: Defining a Custom State
Minimal example: inherit from a base class, set `domain: Literal["my_domain"]`. One domain per class. Registration is automatic via `__init_subclass__` — no explicit call needed.

### H2: Choosing a Base Class
Each base class determines the Python type of `value`:

#### H3: `StringBaseState` — `str` value (most common)
#### H3: `NumericBaseState` — `Decimal` value
#### H3: `BoolBaseState` — `bool` value (auto-converts `"on"`/`"off"`)
#### H3: `DateTimeBaseState` — `ZonedDateTime` / `PlainDateTime` / `Date`
#### H3: `TimeBaseState` — `Time` value
#### H3: Custom value type — inherit `BaseState` directly, set `value_type` ClassVar

### H2: Adding Typed Attributes
Define an attributes class for domain-specific fields beyond `value`. Show a realistic example with 2-3 typed attribute fields.

### H2: Using Custom States in Apps
Two access patterns, simplest first:

#### H3: Via `self.states[CustomStateClass]`
Returns a `DomainStates` collection typed to the custom class.

#### H3: With Dependency Injection
`D.StateNew[CustomState]` in a handler — Hassette converts automatically.

### H2: Troubleshooting
- **Class not registering** — missing `Literal["domain"]` annotation, or `__init_subclass__` not calling super.
- **Type hints not working** — use `self.states[CustomState]` for full type checking on custom domains.
- **Conversion fails** — base class does not match the entity's actual state value type; check HA's raw data.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `basic_custom_state.py` | Move from `advanced/snippets/custom-states/` | H2: Defining a Custom State |
| `string_base_state.py` | Move | H3: StringBaseState |
| `numeric_base_state.py` | Move | H3: NumericBaseState |
| `bool_base_state.py` | Move | H3: BoolBaseState |
| `datetime_base_state.py` | Move | H3: DateTimeBaseState |
| `time_base_state.py` | Move | H3: TimeBaseState |
| `define_your_own.py` | Move | H3: Custom value type |
| `adding_custom_attributes.py` | Move | H2: Adding Typed Attributes |
| `via_get_states.py` | Move | H3: Via self.states[CustomStateClass] |
| `direct_api_access.py` | Drop | Redundant with the self.states example |
| `known_domain_access.py` | Drop | Runtime-vs-type-time distinction cut |
| `custom_domain_typed_access.py` | Drop | Merged into the self.states example |
| `custom_domain_runtime_access.py` | Drop | Merged into the self.states example |
| `complete_example.py` | Drop | Redundant with adding_custom_attributes example |
| New: DI usage example | Create | H3: With Dependency Injection — handler using `D.StateNew[CustomState]` |

## Cross-Links

- **Links to:** State Registry, Type Registry, DI page, States overview (auto-generated API reference for built-in types)
- **Linked from:** States overview ("for domains not covered")
