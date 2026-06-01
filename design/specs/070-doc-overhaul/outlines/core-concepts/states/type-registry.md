# States — Type Registry

**Status:** Stub (3 lines), content moving from Advanced (329 lines)
**Voice mode:** Concept/reference hybrid — system-as-subject

## Outline

Content source: `docs/pages/advanced/type-registry.md`

### H2: Purpose
Converts raw HA values (strings) to typed Python values. The second step after State Registry picks the class.

### H2: Core Concepts
#### H3: Registration System — Decorator and Simple Registration
#### H3: Conversion Lookup

### H2: Integration with State Models
#### H3: The `value_type` ClassVar
#### H3: Automatic Conversion in Models
#### H3: Union Type Handling

### H2: Integration with Dependency Injection
How type conversion works when DI extracts state data.

### H2: Relationship with State Registry
The workflow: raw string → State Registry → Type Registry → typed value.

### H2: Built-in Converters
#### H3: Numeric Conversions
#### H3: Boolean Conversions
#### H3: DateTime Conversions
#### H3: Conversion Errors
#### H3: Missing Converters
#### H3: Custom Error Messages

### H2: Inspection and Debugging
Tools for inspecting the registry.

### H2: Best Practices
Key rules for custom converters.

### H2: Common Patterns
#### H3: Enum Conversion
#### H3: Structured Data
#### H3: Units of Measurement

### H2: Automatic Type Conversion
Content originally considered for Custom Extractors page — lives here instead. How extractors use the type registry for automatic conversion.

## Snippet Inventory

Moving from `advanced/snippets/type-registry/` (24 files):
| Snippet | Status | Notes |
|---|---|---|
| All 24 files | Move | → `states/snippets/` (review for voice, trim if 329 lines of content is over-documented) |

Also moving from `dependency-injection/`:
| Snippet | Status | Notes |
|---|---|---|
| `builtin_conversions_explicit.py` | Move here | Type conversion examples |
| `builtin_conversions_implicit.py` | Move here | |
| `bypass_conversion_any.py` | Move here | |
| `bypass_conversion_custom.py` | Move here | |

## Cross-Links

- **Links to:** State Registry, Custom States, DI page, Custom Extractors
- **Linked from:** States overview, State Registry, DI page
