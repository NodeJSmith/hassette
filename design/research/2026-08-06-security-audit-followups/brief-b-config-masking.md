# Brief B — container-typed config secrets bypass masking

**Audit finding 3** — medium severity, high confidence, CWE-200 (sensitive information exposure).
**Estimated effort:** ~2h, mostly tests.
**Suggested branch:** `security/config-container-masking`
**Commit type:** `fix(web):` — user-visible, belongs in the changelog.

## The defect

`mask_values()` in `src/hassette/web/config_view.py:74-98` walks a schema node's `properties` and
recurses into nested objects. It never looks at `items`, `prefixItems`, or
`additionalProperties`, so a `SecretStr` sitting inside a list, tuple, or mapping is returned in
plaintext.

The audit called the masker "property-recursive rather than schema/value-recursive." That is exactly
right and is the shape of the fix.

## Verified behavior (do not re-derive this)

A probe against the real `deref_schema` + `mask_values` produced this. Each row was confirmed by
running the code, not by reading it.

| Config field type | Masked today? |
|---|---|
| `SecretStr \| None` | yes |
| `NestedModel \| None` with a `SecretStr` field | yes |
| `SecretStr \| int \| None` (secret in an `anyOf` branch) | yes |
| `list[SecretStr]` | **no** |
| `tuple[SecretStr, SecretStr] \| None` | **no** |
| `dict[str, SecretStr]` | **no** |
| `list[NestedModel]` where the model has a `SecretStr` field | **no** |
| `dict[str, list[SecretStr]]` | **no** |

**The last two matter and the audit's write-up does not mention them.** The audit described "arrays,
tuples, or mappings" of secrets. `list[NestedModel]` leaking is a separate hole: the element schema
is an *object with properties*, so an implementation that only handles scalar containers would still
miss it. Whatever you build has to recurse through container nodes into object nodes and back again,
not special-case two flat shapes.

### The exact schema shapes Pydantic emits

Reproduced from the probe. These are what the co-walk has to match.

```
list[SecretStr]:
  {"type": "array", "items": {"type": "string", "format": "password", "writeOnly": true}}

tuple[SecretStr, SecretStr] | None:
  {"anyOf": [{"type": "array", "maxItems": 2, "minItems": 2,
              "prefixItems": [{...password...}, {...password...}]},
             {"type": "null"}]}

dict[str, SecretStr]:
  {"type": "object", "additionalProperties": {"type": "string", "format": "password",
                                              "writeOnly": true}}

list[NestedModel]:
  {"type": "array", "items": {"type": "object", "title": "Nested",
                              "properties": {"inner_secret": {"anyOf": [{...password...},
                                                                        {"type": "null"}]}}}}

dict[str, list[SecretStr]]:
  {"type": "object", "additionalProperties": {"type": "array", "items": {...password...}}}
```

Two things to notice: the tuple's array shape is **wrapped in `anyOf`** because the field is
optional, so container detection has to look inside union branches the same way the existing
`_object_properties()` already does. And `prefixItems` is positional while `items` is homogeneous —
they are different keys with different semantics.

## Where the exposure actually is

This part is easy to get wrong, and getting it wrong leads to fixing the wrong path.

The **global** config endpoint (`GET /api/config`, `routes/config.py:19-33`) feeds
`mask_values` the output of `hassette.config.model_dump(mode="json")`. Pydantic already serializes
`SecretStr` to `'**********'` in JSON mode, so container secrets in *typed* `HassetteConfig` fields
are masked by Pydantic before `mask_values` ever runs. `config_view.py`'s own docstring says this.

The leak is in **app config**, because `HassetteConfig` types `app_config` as `dict[str, Any]` —
raw TOML that never passed through a `SecretStr` field. That is why
`_mask_manifest_configs()` (`routes/config.py:36-58`) exists at all: it re-resolves each app's real
`AppConfig` class and re-masks with the accurate schema. Both affected endpoints route through
`mask_app_config()` (`config_view.py:206-228`):

- `GET /api/config` → `_mask_manifest_configs` → `mask_app_config`
- `GET /api/apps/{app_key}/config` → `routes/apps.py:206-287` → `deref_schema` + `mask_values`

So: an app whose `AppConfig` declares `api_keys: list[SecretStr]` or
`creds: dict[str, SecretStr]` hands that value out in plaintext to any caller holding the Hassette
token.

**Severity read:** medium is fair. The caller already holds the admin credential, so this is not a
privilege escalation. What crosses the boundary is a *different* secret — the app author's
third-party credential (a cloud API key, a broker password) — to someone who was only ever granted
Hassette access. The `mask_all_values()` safe-floor path already reflects the project's stance that
that distinction is worth protecting.

## Design

Replace the property-only walk with a schema-node/value co-walk. Suggested shape:

```python
def _shape_candidates(node: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield the node itself plus any anyOf/oneOf/allOf branches.

    A container or object shape on an optional field is wrapped in a union, so the shape has to be
    looked for in the branches too — same reason _object_properties() already checks anyOf.
    """
```

Then one recursive `_mask_node(node, value)` that, in order:

1. `_is_secret_node(node)` → return `MASK_SENTINEL` when the value is non-empty and not `None`.
   (`_is_secret_node` is already `anyOf`-aware — reuse it, don't reimplement.)
2. For each shape candidate, if the value is a `dict`:
   - mask keys named in `properties` against their own nodes;
   - mask remaining keys against `additionalProperties` when present.
     A model with `extra="allow"` can carry both, so handle both rather than picking one.
3. For each shape candidate, if the value is a `list`:
   - mask positionally against `prefixItems` when present;
   - mask any remaining elements against `items` when present.
4. Otherwise return the value unchanged.

`mask_values(schema_props, values)` stays the public entry point and keeps its signature — it has
two external callers (`build_config_view`, `mask_app_config`) plus tests. Have it delegate per key
to `_mask_node`.

### Constraints to respect

- **Immutable output.** The existing function builds a new dict and never mutates its input; there
  is a test pinning this (`test_config_view.py:260-261` calls `mask_values` twice on the same props
  and asserts independent results). Keep returning new containers.
- **Idempotent over Pydantic's native mask.** The global path feeds in values Pydantic already
  masked. Masking a `MASK_SENTINEL` again must be a no-op, which it is as long as the "non-empty
  string" rule is kept.
- **Cycle safety is already handled upstream.** `deref_schema` → `_materialize`
  (`config_view.py:101-123`) breaks reference cycles by returning `{}` for a repeated object id, so
  the schema tree handed to the masker is finite. Don't add a depth counter; there is an existing
  `TestCyclicSchema` class covering this.
- **Type-driven, never name-driven.** The module docstring is explicit that masking reads schema
  markers rather than field names. Do not reintroduce a name deny-list (see the #708 note below).

## Tests

Add to `tests/unit/web/test_config_view.py` (322 lines, model classes declared at the top, tests
grouped into `TestTypeDrivenMasking` / `TestNestedMasking` / `TestUnsetSecrets` / etc.). Follow that
layout — declare the container models near the other `_*Config` classes and add a
`TestContainerMasking` class.

Cover every "no" row from the verified table above, since each is a distinct schema key:

- `list[SecretStr]` → `items`
- `tuple[SecretStr, SecretStr] | None` → `prefixItems` nested in `anyOf`
- `dict[str, SecretStr]` → `additionalProperties`
- `list[NestedModel]` → `items` containing `properties`
- `dict[str, list[SecretStr]]` → two container levels
- A plain `list[str]` and `dict[str, str]` stay **visible** — the point of type-driven masking is
  that it doesn't blanket-mask, and a regression to blanket-masking would break the config UI.
- Empty string and `None` inside containers stay untouched, matching the scalar rule.

The audit also asked for coverage that "both JSON and generated TOML mask values." Check whether
`routes/apps.py` has a TOML-rendering path (it serves an app-source/config view) and add a case
there if so; if the TOML path shares `mask_app_config`, one test at that seam is enough.

Also add an integration test at the endpoint level for at least one container shape — a unit test on
`mask_values` proves the function, not that the response is masked. `tests/integration/web_api/`
has `test_api_app_config.py` for exactly this.

## Issue #708 needs reconciling in this PR

`#708` ("Harden config endpoint secret redaction and restore frontend reveal toggle") predates the
schema-driven rework and is now partly wrong:

- "Incomplete deny-list" / "Regex-only approach" — **obsolete.** There is no deny-list anymore;
  masking is schema-driven off `writeOnly`/`format: password`.
- "No nested dict handling" — **already fixed.** `mask_values` recurses into nested object
  `properties` today (verified).
- "No list-of-dicts recursion" — **half true, and this brief fixes the remaining half.** The
  multi-instance case (`list[dict]` of whole app-config instances) is handled by `mask_app_config`
  mapping over the list. Nested models *inside* a list are not.
- "Frontend reveal toggle" — **still valid and out of scope here.** It's a UI feature, not a
  security fix.

Recommended action: comment on #708 explaining which bullets this PR closes, and narrow it to the
frontend reveal-toggle half. Don't silently close it — the toggle is real outstanding work.

## Verification

```bash
# Unit + integration for the touched area
uv run pytest tests/unit/web/test_config_view.py tests/integration/web_api/test_api_app_config.py -q

# Full web surface
uv run pytest tests/unit/web tests/integration/web_api -q -n 4

# Gates — check the EXIT CODE, not the printed output (see shared-gotchas.md)
uv run ruff check . ; echo "exit=$?"
prek -a ; echo "exit=$?"
prek pyright -a --stage pre-push ; echo "exit=$?"
```

No schema regeneration expected: this changes masking behavior, not any Pydantic model or route
signature. If you find yourself editing `web/models.py`, re-read the plan — you probably shouldn't
be.

## Docs

Likely none. Masking behavior is already described in general terms and this closes a gap rather
than adding a user-facing knob. If you do touch `docs/pages/`, `.claude/rules/doc-rules.md`
requires running `doc-persona-review` and `doc-accuracy-review` on the changed pages.
