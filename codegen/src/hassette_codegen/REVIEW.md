# REVIEW.md — codegen/src/hassette_codegen/

## Upstream File Layout
Each extractor reads a fixed list of HA component files: `ENTITY_MODULE_FILES` in
`codegen/src/hassette_codegen/ha_source.py`, `REGISTRATION_MODULE_FILES` in
`codegen/src/hassette_codegen/extractors/services.py`, and the inline lists in
`codegen/src/hassette_codegen/extractors/features.py`. If upstream moved the thing
an extractor looks for into a file it doesn't scan, would the run fail, warn, or
quietly generate less?

## Silent Degradation
When an extractor finds nothing (no entity class, no registration, a file that
won't parse), does it surface that, or return an empty default that regenerates
as a smaller model (a domain orphaned, `supports_response` falling back to
`NONE`, a property dropped)? Does the regenerated diff remove anything that
upstream still has?

## Hand-Written Collisions
Can a newly discovered domain write over, or duplicate, a hand-written state
class? Check `RESERVED_BASENAMES`, `SIMPLE_STATE_DOMAINS` against
`src/hassette/models/states/simple.py`, and the manifest ownership gate in
`_may_overwrite`.

## Wire Names
Does every generated attribute name match the key HA sends in state attributes,
or only the Python `_attr_*` property name? When upstream renames an entity
property (e.g. to a `native_*` form) without renaming the wire attribute, does
an override in `codegen/src/hassette_codegen/overrides/` map it back?
