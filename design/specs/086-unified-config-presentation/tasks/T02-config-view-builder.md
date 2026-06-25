---
task_id: "T02"
title: "Add shared config-view builder: deref + type-driven masking"
status: "done"
depends_on: []
implements: ["FR#3", "FR#4", "FR#5"]
---

## Summary
Create the single backend helper both config endpoints will use. It takes a JSON schema and a values
dict and returns `{config_schema (deref'd), config_values (masked)}`. Deref inlines `$ref`/`$defs` via
`jsonref` so the frontend never walks a ref. Masking is type-driven: any schema property marked
`writeOnly: true` or `format: "password"` (i.e. `SecretStr`-typed) has its value replaced with a mask
sentinel when set, left null/absent when unset — recursing into nested objects. This is the one masking
rule for both surfaces and the replacement for the deleted `_SECRET_KEYS` regex.

## Target Files
- create: `src/hassette/web/config_view.py` — the `build_config_view` helper (deref + schema-driven mask).
- modify: `pyproject.toml` — add `jsonref` to runtime dependencies.
- create: `tests/unit/web/test_config_view.py` — unit tests for masking and deref.
- read: `src/hassette/web/routes/apps.py` — current `_redact_*` behavior being replaced (reference only).

## Prompt
Implement the shared view builder described in the design doc's `## Architecture → Backend: one
config-view builder, two callers`.

1. Add `jsonref` to `pyproject.toml` runtime dependencies and run `uv sync`.
2. Create `src/hassette/web/config_view.py` exposing `build_config_view(schema: dict, values: dict) ->
   dict` returning `{"config_schema": <deref'd>, "config_values": <masked>}`:
   - **Deref:** use `jsonref.replace_refs(schema)` and materialize a plain dict (no lazy proxies left in
     the output — convert to concrete dict/list so it serializes cleanly through FastAPI). The output
     must contain no `$ref`/`$defs`.
   - **Mask:** walk the deref'd schema's `properties`; for any property whose node has `writeOnly: true`
     or `format == "password"`, mask the same-named key in the values dict — replace with the mask
     sentinel (a constant, e.g. `"••••••••"` or `"**********"`) when the value is present and non-null,
     leave it null/absent when unset. Recurse into nested object properties (group → field) so a
     `SecretStr` nested inside a group is masked at depth.
   - Masking operates on the values dict only; it does not mutate the schema. Apply it idempotently (for
     the global surface the caller will pass an already-`model_dump(mode="json")`-masked dict; masking it
     again must be a no-op).
3. Unit tests in `tests/unit/web/test_config_view.py` (`uv run pytest -n 4 <test file>`):
   - A throwaway model with a `SecretStr` field and an untyped `str` field: the `SecretStr` value is
     masked, the `str` value is not (type-driven, not name-driven).
   - Masking on both a live-model dump and a raw dict, recursing into a nested object.
   - Deref inlines a nested-model schema with no `$ref` remaining; a self-referential / cyclic schema
     terminates rather than recursing forever (jsonref handles this — assert it returns).

## Focus
The builder is generic — its unit tests use throwaway models, so it does not depend on T01's token change.
Watch the `jsonref` output type: `replace_refs` returns proxy objects; FastAPI must serialize the result,
so convert to concrete `dict`/`list` before returning (e.g. a recursive rebuild or `json.loads(
jsonref.dumps(...))`). Known caveat (note in code): `jsonref` can mangle discriminator `mapping` refs
under discriminated unions — N/A for the current plain nested-model config groups, but leave a comment.
The mask sentinel should be a module constant reused by both endpoints.

## Verify
- [ ] FR#3: A `SecretStr`-typed field's value is masked in `config_values` (placeholder when set, null
  when unset); the plaintext never appears in the builder output.
- [ ] FR#4: Masking is driven by schema `writeOnly`/`format:password` markers — an untyped `str` field
  with a secret-sounding name is NOT masked; a `SecretStr` field with any name IS masked.
- [ ] FR#5: `build_config_view` output contains no `$ref`/`$defs` (fully inlined) and terminates on a
  cyclic schema.
