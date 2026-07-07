---
task_id: "T04"
title: "Update tests, docs, and tooling for moved/deleted symbols"
status: "planned"
depends_on: ["T01", "T02", "T03"]
implements: ["AC#1"]
---

## Summary
Update all test files, documentation pages, and tooling scripts that reference symbols moved to `hassette.di` or deleted from `bus/extraction.py`. This is the cleanup task — fixing import paths, cross-reference links, and tool configurations that break after the extraction.

## Target Files
- modify: `tests/integration/test_extraction.py`
- modify: `tests/integration/test_injection.py`
- modify: `tests/integration/test_annotation_conversion.py`
- modify: `tests/integration/test_type_detection.py`
- modify: `docs/pages/core-concepts/bus/dependency-injection.md`
- modify: `docs/pages/core-concepts/bus/custom-extractors.md`
- modify: `docs/pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_converter.py`
- modify: `docs/pages/core-concepts/bus/handlers.md`
- modify: `tools/docs/gen_ref_pages.py`
- modify: `tools/docs/check_xref_coverage.py`
- read: `src/hassette/di/__init__.py`

## Prompt
Update all files that reference moved or deleted symbols. Reference the design doc Test Strategy and Documentation Updates sections.

### Test files

**`tests/integration/test_extraction.py`:**
- Replace `from hassette.bus.extraction import extract_from_annotated, extract_from_signature, has_dependency_injection, validate_di_signature` with imports from `hassette.di` (`AnnotatedMatcher`, `build_injection_plan`, `validate_di_signature`).
- Tests calling `extract_from_annotated(annotation)` → adapt to call `AnnotatedMatcher(source_type=Event).match(param)` where `param` is an `inspect.Parameter` constructed from a handler signature.
- Tests calling `extract_from_signature(sig)` → adapt to call `build_injection_plan(sig, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])`.
- Remove tests for `has_dependency_injection` (function deleted, FR#12).
- Keep tests for `validate_di_signature` — just update the import path.

**`tests/integration/test_injection.py`:**
- Replace `from hassette.bus.extraction import extract_from_annotated` with import from `hassette.di`.
- The ~12 tests that call `extract_from_annotated(D.SomeAlias)` to get `AnnotationDetails` — these can either use `AnnotatedMatcher` or call the underlying `get_type_and_details` utility directly (since they're testing the extractors, not the matching logic).
- `ParameterInjector` import from `hassette.bus.injection` stays unchanged.

**`tests/integration/test_annotation_conversion.py`:**
- Replace `from hassette.bus.extraction import extract_from_annotated` with import from `hassette.di`.

**`tests/integration/test_type_detection.py`:**
- Replace `from hassette.bus.extraction import extract_from_annotated, extract_from_event_type` with imports from `hassette.di` (`AnnotatedMatcher`, `TypeMatcher`).
- Adapt `TestExtractFromAnnotated` tests to use `AnnotatedMatcher`.
- Adapt `TestExtractFromEventType` tests to use `TypeMatcher`.

### Documentation

**`docs/pages/core-concepts/bus/dependency-injection.md`:**
- Update mkdocstrings cross-reference links from `hassette.event_handling.dependencies.AnnotationDetails` to `hassette.di.AnnotationDetails`.

**`docs/pages/core-concepts/bus/custom-extractors.md`:**
- Same cross-reference link update.
- Update the tutorial code snippet at `docs/pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_converter.py` to import `AnnotationDetails` from `hassette.di`.

**`docs/pages/core-concepts/bus/handlers.md`:**
- Update the cross-reference link `[hassette.event_handling.dependencies]` at line 58 to `[hassette.di]`.

### Tooling

**`tools/docs/gen_ref_pages.py`:**
- Remove `"hassette.bus.extraction"` from `PUBLIC_MODULES`.
- Add `"hassette.di"` to `PUBLIC_MODULES`.

**`tools/docs/check_xref_coverage.py`:**
- Update `XREF_MAP["AnnotationDetails"]` from `"hassette.event_handling.dependencies.AnnotationDetails"` to `"hassette.di.AnnotationDetails"`.

## Focus
- `test_extraction.py` imports at line 13-18: `extract_from_annotated`, `extract_from_signature`, `has_dependency_injection`, `validate_di_signature` from `hassette.bus.extraction`. Also imports `get_typed_signature` from `hassette.utils.type_utils` at line 22 — keep that.
- `test_injection.py` imports at line 13: `from hassette.bus.extraction import extract_from_annotated`. Nearly every test calls `extract_from_annotated(D.SomeAlias)` directly — this is the most mechanical but highest-volume update.
- `test_type_detection.py` imports at line 13: both `extract_from_annotated` and `extract_from_event_type`. Also imports `is_annotated_type` from `hassette.utils.type_utils` and `is_event_type` from `hassette.events` — those stay.
- `gen_ref_pages.py` has `PUBLIC_MODULES` as a list around line 40-60. Search for `hassette.bus.extraction` in that list.
- `check_xref_coverage.py` has `XREF_MAP` dict around line 19.
- The snippet file at `docs/pages/core-concepts/bus/snippets/dependency-injection/custom_extractor_converter.py` is Pyright-checked in CI — the import must resolve.
- `handlers.md:58` has a cross-reference `[hassette.event_handling.dependencies]` — this is a bare module reference, not a class reference. Check whether `hassette.di` is the right replacement or if it should be more specific.

## Verify
- [ ] AC#1: All existing tests in `test_extraction.py`, `test_injection.py`, `test_annotation_conversion.py`, and `test_type_detection.py` pass after import updates; behavioral assertions unchanged
