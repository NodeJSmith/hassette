# Bus — Custom Extractors

**Status:** Stub (3 lines), content to be written in T07
**Voice mode:** Concept/reference hybrid — system-as-subject, code-heavy

## Outline

### H2: Writing a Custom Extractor
How to implement the extractor protocol. When to write one (data not covered by built-in annotations).

### H2: Custom Accessors with `A`
How accessors work, creating custom field accessors for event data.

### H2: AnnotationDetails
The AnnotationDetails object that extractors receive. Fields and usage.

General type conversion lives on the Type Registry page. This page covers only how extractors *interact* with the registry (e.g., calling converters from a custom extractor).

## Snippet Inventory

Existing snippets in `dependency-injection/` that belong here:
| Snippet | Status | Notes |
|---|---|---|
| `custom_extractor_builtin.py` | Move here | Built-in extractor internals |
| `custom_extractor_converter.py` | Move here | Extractor with type converter |
| `custom_extractor_own.py` | Move here | Writing your own extractor |
| `custom_type_converter.py` | Move here | Custom type converter (or Type Registry?) |
| `custom_accessors.py` (from filtering/) | Move here | Accessor examples |

**New snippets needed:**
- AnnotationDetails usage example

## Cross-Links

- **Links to:** DI page (built-in annotations), Type Registry, State Registry
- **Linked from:** DI page (see also)
