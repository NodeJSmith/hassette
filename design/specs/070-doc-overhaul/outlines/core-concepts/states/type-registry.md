# Type Registry

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (advanced depth page)
**Reader's job:** Register a custom type converter so Hassette can convert raw HA string values to a Python type that the built-in converters do not cover.

## What was cut (and where it goes)

- **"Integration with State Models" section** — cut as a standalone section. The `value_type` ClassVar and automatic conversion are explained in the Conversion Flow on the State Registry page. Repeating them here is the source-code-mirror anti-pattern — organized by "which internal calls which," not by the reader's job.
- **"Integration with Dependency Injection" section** — cut. Custom extractors and DI type conversion belong on the DI page. The reader who needs a custom converter does not also need to understand extractor internals.
- **"Relationship with StateRegistry" section** — cut as a standalone H2. One sentence in the opening suffices: "The TypeRegistry handles value conversion; the State Registry handles domain-to-class mapping."
- **"Best Practices" section** — cut. The five "best practices" are either already stated in context (define `value_type`, register early) or generic advice (test your code, use type hints). Best practices sections are an AI tell that pads length without serving the reader's job.
- **"Inspection and Debugging" section** — kept as a collapsible. Useful for debugging but not the primary job.
- **"Union Type Performance"** — folded into one sentence in the "How Conversion Works" section. Ordering types by specificity is good advice but does not need its own section.

## Outline

### (Opening)
Home Assistant sends nearly all values as strings. The `TypeRegistry` converts those strings to typed Python values — `int`, `float`, `bool`, `ZonedDateTime`, `Decimal`, etc. Most apps never touch the registry directly because the built-in converters handle all standard HA types.

This page matters when: a custom state model's `value_type` is a type Hassette does not know how to convert, or a built-in conversion gives unexpected results.

### H2: How Conversion Works
The registry maps `(from_type, to_type)` pairs to converter functions. When state data arrives and the raw value does not match the expected `value_type`, the registry looks up a converter for the pair and applies it. If no converter exists, it tries the target type's constructor as a fallback.

For union types (`value_type = (int, float, str)`), conversion attempts each type in order. Put the most specific type first.

### H2: Built-in Converters
What ships out of the box. Grouped by category:

#### H3: Numeric
`str` to `int`, `float`, `Decimal`; cross-conversions between numeric types.

#### H3: Boolean
`str` to `bool` — HA-specific: `"on"`/`"true"`/`"yes"`/`"1"` map to `True`.

#### H3: DateTime
`str` to `ZonedDateTime`, `Date`, `Time`, `OffsetDateTime`, `PlainDateTime`. Cross-conversions between `whenever` types. Stdlib `datetime`/`date`/`time` conversions for boundary compatibility.

### H2: Registering a Custom Converter
The reader's primary job. Two approaches:

#### H3: Decorator Registration
`@register_type_converter_fn` — define a function with `from_type` and `to_type` annotations. Show a concrete example (e.g., `str` to a custom enum).

#### H3: Simple Type Registration
`register_simple_type_converter(from_type, to_type, func)` — one-liner for straightforward conversions.

### H2: Common Patterns
Concrete examples the reader can adapt:

#### H3: Enum Conversion
Convert HA string values to Python enums.

#### H3: Structured Data
Convert JSON strings to dataclasses.

### H2: Error Handling
- Conversion failure wraps the original error with context (source value, types involved).
- Missing converter + failed constructor raises `UnableToConvertValueError`.
- Custom error messages via `error_message` parameter on registration.

??? note "Collapsible: Inspection and Debugging"
`TypeRegistry` methods for listing converters, checking for specific converters, getting converter details. Primarily useful for debugging.

## Snippet Inventory

Moving from `advanced/snippets/type-registry/` — trim from 24 to ~10 files:

| Snippet | Status | Notes |
|---|---|---|
| `custom_type_converter.py` (from `bus/snippets/dependency-injection/`) | Keep in place, reference | H3: Decorator Registration |
| `simple_registration.py` | Move | H3: Simple Type Registration |
| `lookup_example.py` | Move | H2: How Conversion Works |
| `pattern_enum.py` | Move | H3: Enum Conversion |
| `pattern_structured.py` | Move | H3: Structured Data |
| `conversion_error.py` | Move | H2: Error Handling |
| `missing_converter.py` | Move | H2: Error Handling |
| `custom_error_msg.py` | Move | H2: Error Handling |
| `inspect_list.py` | Move | Collapsible: Inspection |
| `inspect_check.py` | Move | Collapsible: Inspection |
| `inspect_list_output.txt` | Move | Collapsible: Inspection |
| `entry_example.py` | Drop | Implementation detail, not user-facing |
| `state_model_value_type.py` | Drop | Covered on State Registry page |
| `base_state_convert_call.py` | Drop | Internal API detail |
| `typed_model_usage.py` | Drop | Generic usage, covered elsewhere |
| `union_type_order.py` | Drop | Folded into one sentence in How Conversion Works |
| `union_type_performance.py` | Drop | Folded into one sentence |
| `di_custom_extractor.py` | Drop | Belongs on DI page |
| `best_practice_*.py` (5 files) | Drop | Best practices section cut |
| `pattern_units.py` | Drop | Niche pattern, low value |
| `inspect_details.py` | Drop | Low-value inspection detail |

Also dropping the 4 DI-related snippets that were planned to move here from `dependency-injection/`:
| Snippet | Status | Notes |
|---|---|---|
| `builtin_conversions_explicit.py` | Stay on DI page | DI context, not type registry context |
| `builtin_conversions_implicit.py` | Stay on DI page | |
| `bypass_conversion_any.py` | Stay on DI page | |
| `bypass_conversion_custom.py` | Stay on DI page | |

## Cross-Links

- **Links to:** State Registry, Custom States, DI page
- **Linked from:** States overview, State Registry, Custom States
