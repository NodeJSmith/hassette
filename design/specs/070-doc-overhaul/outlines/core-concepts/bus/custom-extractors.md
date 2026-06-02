# Custom Extractors

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (advanced)
**Reader's job:** Extract event data that the built-in `D.*` annotations don't cover.

This is an advanced page. Most readers never need it — the built-in annotations handle common cases. The reader lands here because they have a specific piece of event data (a nested attribute, a custom event field, service data) that no built-in annotation extracts. They need to know: how do I write my own extractor, and how does it plug into the DI system?

## What was cut (and where it goes)

- **Type conversion details** (custom converters, the Type Registry itself) — the previous outline mixed extractor authoring with type conversion. Type conversion is a separate concern. This page covers only how extractors *interact* with converters via the `converter` field on `AnnotationDetails`. The Type Registry page covers everything else.

## Outline

### H2: When to Write a Custom Extractor
One paragraph: the built-in `D.*` annotations cover state values, entity IDs, domains, event data, and event context. A custom extractor is needed when the handler requires data from a different location in the event payload — for example, a specific key from `service_data`, a nested attribute, or a computed value derived from multiple event fields.

### H2: Accessors (`A`)
Accessors are the simplest form of custom extraction. They point a predicate or `P.ValueIs` at a non-standard field. Show how `A.get_service_data_key("brightness")` works. This is custom extraction without writing a full extractor.

Snippet: `custom_accessors.py`.

### H2: Writing an Extractor
The `AnnotationDetails` dataclass: `extractor` (required callable that receives the event and returns a value) and `converter` (optional type converter). Show how to place it inside `Annotated[T, AnnotationDetails(...)]` and how the DI system in `extraction.py` discovers it from the handler's signature.

Walk through one concrete example: extracting a brightness value from a state change event's attributes.

Snippet: `custom_extractor_own.py`.

### H2: How Built-In Extractors Work
Collapsible section. Show the internals of a built-in extractor (e.g., `D.StateNew`) to demystify the pattern. Readers who understand how the built-ins work can write their own with confidence.

Snippet: `custom_extractor_builtin.py`.

### H2: Adding Type Conversion
An extractor can declare a `converter` to automatically convert the extracted value. Show an extractor that extracts a raw string and converts it to a custom type.

Snippet: `custom_extractor_converter.py`.

Link to Type Registry page for writing custom type converters.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `custom_accessors.py` (from `filtering/`) | Move here | Accessor examples |
| `custom_extractor_own.py` (from `dependency-injection/`) | Move here | Writing a custom extractor |
| `custom_extractor_builtin.py` (from `dependency-injection/`) | Move here | Built-in extractor internals |
| `custom_extractor_converter.py` (from `dependency-injection/`) | Move here | Extractor with type converter |

**New snippets needed:**
- `annotation_details_usage.py` — standalone `AnnotationDetails` usage showing the `Annotated[T, AnnotationDetails(...)]` pattern in a handler signature

## Cross-Links

- **Links to:** DI page (built-in annotations), Type Registry (custom converters), State Registry
- **Linked from:** DI page ("See Also"), Filtering (accessor mention)
