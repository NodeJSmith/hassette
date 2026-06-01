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

### H2: Automatic Type Conversion
**Note:** This was originally considered for this page but belongs in Type Registry instead (confirmed during T03). Remove if still here; the Type Registry page covers conversion.

**Revision:** Keep only extractor-specific type conversion concerns here (e.g., how extractors interact with the type registry). General type conversion → Type Registry page.

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
