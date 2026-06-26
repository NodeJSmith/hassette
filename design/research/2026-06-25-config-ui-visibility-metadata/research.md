---
proposal: "Replace the hand-maintained ConfigResponse allowlist with field-level UI-visibility metadata on HassetteConfig, deriving the response from that metadata (issue #690)."
date: 2026-06-25
status: Draft
flexibility: Decided
motivation: "config_response_from() hand-copies ~31 fields into parallel response models; high drift risk, no field-level metadata, token hidden only by omission (no SecretStr)."
constraints: "Internal refactor — NO UI-visible change. Must preserve exact JSON shape. Must keep token (and other sensitive fields) out of the response. Must keep OpenAPI/TS type export deterministic for the pre-push freshness check."
non-goals: "Not adding alternative architectures — Pattern 1 (field marker + derived model) is chosen. Not exposing new config fields to the UI."
depth: normal
---

# Research Brief: Field-Level UI-Visibility Metadata for ConfigResponse (#690)

**Initiated by**: Replace the drift-prone `config_response_from()` allowlist with `Field(json_schema_extra={"ui": ...})` metadata on the source config fields, deriving the response model from that metadata; type `token` as `SecretStr`; add a test that every field resolves to a known visibility, defaulting to hidden.

## Context

### What prompted this

`config_response_from()` (`src/hassette/web/mappers.py:209-255`) hand-copies a hand-picked subset of `HassetteConfig` fields into a parallel tree of response models (`ConfigResponse` + 6 sub-responses in `src/hassette/web/models.py:405-470`). The exposure decision lives in the mapper and the response classes, never on the source fields. Adding a config field forces no visibility decision, and the two trees drift silently. `token` is kept out of the response purely by omission — there is no `SecretStr`, no field-level marker, and the security boundary is "the mapper author remembered."

Prior-art research (`/tmp/claude-mine-prior-art-Tzkhcz/brief.md`) settled the approach: **Pattern 1 (field marker + derived model)**, with (a) `SecretStr`-typed secrets so `"redacted"` is enforced by the type and (b) an enum-backed marker where unknown/missing resolves to **hidden** (safe-by-default).

### Current state

The source config is wide. `HassetteConfig` (`src/hassette/config/config.py:49`) has 31 top-level fields (8 of them nested config groups) and inherits `ExcludeExtrasMixin, BaseSettings`. The nested groups in `src/hassette/config/models.py` total ~90 fields across 9 classes (`DatabaseConfig` 15, `WebSocketConfig` 14, `LoggingConfig` 21, `LifecycleConfig` 13, `WebApiConfig` 9, `AppsConfig` 6, `SchedulerConfig` 5, `FileWatcherConfig` 3, `BlockingIODetectionConfig` 7) — all `ExcludeExtrasMixin, BaseModel`.

The response exposes **27 fields across 7 groups** today: 6 top-level (`dev_mode`, `base_url`, `asyncio_debug_mode`, `allow_reload_in_prod`, `data_dir`, `config_dir`) + `web_api` (9) + `logging` (2 of 21) + `lifecycle` (3 of 13) + `apps` (2 of 6) + `scheduler` (3 of 5) + `file_watcher` (2 of 3). Three entire groups (`database`, `websocket`, `blocking_io`) are dropped wholesale.

**Critical structural fact — the response is NOT a 1:1 mirror of the source.** The mapper restructures:
- `data_dir`/`config_dir` are top-level on `HassetteConfig` AND top-level on `ConfigResponse` — but `apps.directory` (`Path`) is flattened into `AppsConfigResponse.directory` as `str` (`mappers.py:213,242-245`).
- `Path` → `str` coercion on three fields (`data_dir`, `config_dir`, `apps.directory`).
- `cors_origins` is `tuple[str, ...]` on the source (`models.py:318`) but `list[str]` on the response, copied into a fresh list (`mappers.py:228`, tested at `test_mappers.py:576`).
- The source group names don't all match response names (source has `database`/`websocket`/`blocking_io` groups with no response counterpart).

Confirmed: no `json_schema_extra` usage anywhere in `src/hassette` (greenfield), no `SecretStr` anywhere, and `config.py`/`models.py` do **not** use `from __future__ import annotations` (so runtime `FieldInfo.json_schema_extra` introspection works without string-annotation hazards).

### Key constraints

- **No UI change.** `frontend/src/pages/config.tsx` renders the config; the exact JSON shape (field names, nesting, `str`-typed paths) must be byte-identical.
- **Deterministic schema export.** The pre-push check `tools/check_schemas_fresh.py` does a deep dict comparison of `app.openapi()` against `frontend/openapi.json`; CI git-diffs the generated TS. Any derived model must produce stable schema names and field ordering.
- **Security invariant.** `test_token_not_in_response` (`tests/integration/web_api/test_endpoints.py:375`) asserts `token` never appears in the response. This is the boundary the refactor must not regress.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Visibility enum + typed marker helper | 1 new file (`src/hassette/config/visibility.py` or in `classes.py`) | Low | Low |
| Annotate source fields with `ui` markers | `config.py`, `models.py` (~90 fields to touch, mostly defaulting to hidden) | Medium | Low — mechanical, but wide |
| `token` → `SecretStr` + fix read sites | `config.py` (3 props), `core/websocket_service.py`, `server.py`(check), tests | Medium | **Med — functional break risk** |
| Derivation mechanism (selection guard vs. derived model) | `mappers.py`, `models.py`, possibly new builder | Low–Med | Med — see Key Question 1 |
| Safe-by-default test | `tests/unit/web/test_mappers.py` or new `test_config_visibility.py` | Low | Low |
| Test fixture updates for SecretStr | ~6 test files (assertions on `.token`) | Low | Low |

### What already supports this

- **`ExcludeExtrasMixin`** (`classes.py:75-117`) already establishes "serialization is a privacy boundary" as a codebase value — it strips `model_extra` from `model_dump`. The `ui` marker is the same instinct applied to declared fields. The new scheme should be understood as complementary, not redundant: the mixin guards *extra* keys; the marker guards *declared* ones.
- **No `from __future__ import annotations`** in the config modules means `Model.model_fields[name].json_schema_extra` is a live dict at runtime — introspection works cleanly.
- **Field defaults are already explicit `Field(...)` calls** on nearly every field, so adding `json_schema_extra=` is a small in-place edit, not a restructure.
- **The security test already exists** (`test_token_not_in_response`) and gives the refactor a pin to verify against.
- **Schema names are derived from `model.__name__`** by FastAPI (confirmed by the export subagent), so even a `create_model("ConfigResponse", ...)` would emit a stable `"ConfigResponse"` OpenAPI component.

### What works against this

- **The response is a restructure, not a projection.** A naive "walk `model_fields`, keep `visible`, drop `hidden`" builder reproduces the *flat* source shape — it does NOT reproduce the current response's regrouping (`apps.directory` flattened, `Path`→`str`, `cors_origins` tuple→list, three groups dropped). The metadata alone cannot express "move this field, coerce its type, rename this group." This is the single biggest constraint and it pushes hard toward the hybrid recommendation in Key Question 1.
- **`token` as `SecretStr` has a real functional blast radius.** Two sites send the token over the wire via f-string / dict-literal interpolation that would silently become `"**********"` if not converted: `auth_headers` (`config.py:235`) and the WS auth payload (`core/websocket_service.py:557,564`). `truncated_token` (`config.py:243-251`) slices the token and would break. These are correctness bugs, not cosmetic.
- **`BaseSettings` vs `BaseModel`.** `HassetteConfig` is `BaseSettings`; the response models are `BaseModel`. A derivation that tries to subclass or `create_model` from the settings class must use `BaseModel` as the base to avoid dragging settings machinery (env loading, sources) into the response — consistent with the existing nested-response design (spec 060).

## Options Evaluated

The user is **decided** on Pattern 1. This section settles the *one* open fork (import-time derived model vs. per-request filtering vs. hybrid) rather than re-opening the architecture.

### Option A (recommended): Metadata-driven SELECTION + hand-written response classes (hybrid)

**How it works**: Keep the hand-written `ConfigResponse` / sub-response classes exactly as they are today (they are the source of truth for the *wire shape* — names, nesting, `str`-typed paths, `list` cors). Add `json_schema_extra={"ui": UiVisibility.VISIBLE}` markers to the *source* `HassetteConfig`/nested fields, defaulting all unmarked fields to `HIDDEN`. Then replace the *implicit* allowlist (the mapper's hand-picked field list) with an *explicit, tested* one derived from the markers:

1. A `UiVisibility` enum (`VISIBLE`, `HIDDEN`, `REDACTED`) and a tiny resolver `field_visibility(field_info) -> UiVisibility` that reads `json_schema_extra["ui"]` and returns `HIDDEN` on missing/unknown/typo.
2. A **structural test** (the spine of #690): walk every field on `HassetteConfig` and each nested config class; assert each resolves to a known `UiVisibility`; assert the set of `VISIBLE`/`REDACTED` source fields exactly equals the set of fields the response actually emits. This makes "I added a field and forgot it" a test failure, and makes "I exposed a field without marking it" a test failure — in both directions.
3. `token` becomes `SecretStr`, marked `REDACTED`. It stays out of `ConfigResponse` (as today) OR is added back as a masked field — but the type guarantees it can't leak even if a future edit adds it.

The mapper keeps its restructuring logic (it has to — the metadata can't express the regroup), but it is no longer the *authority* on what's exposed; the test is. This is the "drive field SELECTION from metadata via a guard" path the prior-art brief flagged as a hybrid.

**Pros**:
- Preserves the exact wire shape with zero risk — the response classes are unchanged, so `openapi.json`/TS output is byte-identical and the freshness check can't trip.
- Handles the restructure (flatten `apps.directory`, `Path`→`str`, tuple→list) that a pure derived model cannot express.
- Static classes keep pyright, IDE navigation, and the existing `make_config_response()` factory (`test_utils/web_helpers.py:385`) working unchanged.
- Gets the full #690 benefit: the marker is the single source of truth for *which* fields are exposed, the test enforces no-drift bidirectionally, and `SecretStr` makes redaction type-level.
- Smallest, most reviewable diff; aligns with `laziness-protocol` and the nested-response design (spec 060) that deliberately chose static `BaseModel` subclasses.

**Cons**:
- The response *classes* still duplicate the source field names (you still write `host: str` in two places). The metadata + test removes the *drift risk* but not the *typing duplication*. This is the honest limitation: #690 eliminates silent drift, not all repetition.
- Two artifacts to keep in sync (source marker + response field), but now a test fails loudly if they diverge — which is exactly the property #690 wants.

**Effort estimate**: Medium. The marker annotations are wide but mechanical; the enum/resolver/test is small; the `SecretStr` change is the real work.

**Dependencies**: None new — `SecretStr` and `json_schema_extra` are stock Pydantic v2.

### Option B: Import-time derived model via `pydantic.create_model`

**How it works**: At import time, walk `HassetteConfig.model_fields`, read each `ui` marker, and `create_model("ConfigResponse", ...)` from the `VISIBLE`/`REDACTED` fields, building nested sub-models the same way. FastAPI uses it as `response_model`.

**Pros**:
- Eliminates the field-name duplication — the response *is* the marked subset of the source.
- The export subagent confirmed the mechanics work: `create_model("ConfigResponse", ...)` yields `__name__ == "ConfigResponse"`, FastAPI names the OpenAPI component `"ConfigResponse"`, Pydantic v2 preserves kwarg field order, and the freshness check's dict comparison is deterministic across runs.

**Cons**:
- **Cannot reproduce the current wire shape without per-field override logic** that re-introduces most of the mapper's complexity: `apps.directory` must move from the `apps` group to a `str` field, `data_dir`/`config_dir` coerce `Path`→`str`, `cors_origins` tuple→`list`. Expressing "coerce this type, move this field, rename this group" in metadata is more machinery than the mapper it replaces — net reader-load *increase* (violates `reader-load.md`).
- No precedent for `create_model` in the repo (confirmed: zero `create_model` usages in `src/`). Introduces a dynamic-model pattern the team hasn't adopted; pyright sees an opaque type, so frontend-facing changes lose static checking.
- A derived model that omits a field (because someone forgot a marker) changes `openapi.json` and trips the freshness check — which is arguably *good* (forces the decision) but couples the security boundary to the type-export pipeline rather than a focused test.

**Effort estimate**: Large — the override/coercion layer to match the existing shape is where the cost hides.

**Dependencies**: None new.

### Option C (do-less): SecretStr + safe-by-default test, keep the mapper as-is

**How it works**: Skip the field markers entirely. Just (1) type `token` as `SecretStr` (type-level redaction), and (2) add a test that asserts the response contains *only* an explicit allowlist of field paths and *never* `token`/`verify_ssl`/etc. — turning the implicit allowlist into an explicit, tested one without touching the source fields.

**Pros**:
- Captures ~70% of the security value (SecretStr + a real anti-leak test) for the smallest diff.
- Zero risk to the wire shape or schema export.

**Cons**:
- Doesn't deliver the headline #690 ask — the exposure decision still lives in the mapper, not on the field. Adding a source field still forces no decision (the test only catches *exposed* fields, not *forgotten* ones, unless it also walks the source — at which point you've built Option A's test anyway).
- Leaves the co-location goal unmet.

**Effort estimate**: Small.

**Dependencies**: None new.

### Recommendation on the fork

**Option A (metadata-driven selection + hand-written classes).** The decisive factor is codebase-specific: the current response is a *restructure* of the source (flatten, coerce, rename, drop-group), not a projection. A derived model (Option B) has to re-encode all of that restructuring as override metadata, which costs more than the mapper it replaces and abandons static typing for no shape benefit. Option A gets the full #690 outcome — single source of truth for visibility, bidirectional no-drift test, type-level redaction — while keeping the wire shape and the schema-export pipeline provably unchanged.

## token → SecretStr Blast Radius

Concrete file list (change verb + path), grouped by failure mode. This is the riskiest part of the refactor.

**Must add `.get_secret_value()` (silent functional break otherwise):**
- Modify `src/hassette/config/config.py:235` — `auth_headers`: `f"Bearer {self.token}"` → `f"Bearer {self.token.get_secret_value()}"`. f-string on `SecretStr` yields `"**********"`, breaking HA REST auth.
- Modify `src/hassette/core/websocket_service.py:557,564` — `token = self.hassette.config.token` then `{"type": "auth", "access_token": token}`. Sending a `SecretStr` in the auth payload serializes to `"**********"`, breaking WS auth. Add `.get_secret_value()`.
- Modify `src/hassette/config/config.py:243-251` — `truncated_token` slices `self.token`. With `SecretStr`, `len()`/`[:]` operate on the masked repr. Read `self.token.get_secret_value()` once at the top, then slice the plaintext.

**Safe as-is:**
- `src/hassette/server.py` token-presence check — truthiness/`is None` works on `SecretStr` (note `auth_headers` already guards `if self.token is None`).
- `src/hassette/core/api_resource.py:100` — reads `config.headers`, which chains through the fixed `auth_headers`; no direct change.
- Logging via `truncated_token` (`websocket_service.py:558,575,578`) — safe once `truncated_token` itself is fixed.

**Test updates (assertions/fixtures):**
- Modify equality assertions on `.token` in `tests/unit/test_make_test_config.py`, `tests/unit/test_config_token_optional.py`, `tests/unit/cli/test_commands_run.py`, `tests/unit/test_config.py` (TestAuthHeaders) — `config.token == "x"` becomes `config.token.get_secret_value() == "x"` (or compare to `SecretStr("x")`).
- Modify `tests/integration/test_websocket_service.py:247` — dict-literal `"access_token": ...config.token` needs `.get_secret_value()`.
- Investigate `src/hassette/test_utils/harness.py:186` `preserve_config` (`model_dump()` → restore via `setattr`). `model_dump()` on a `SecretStr` field emits the masked value by default; restoring it would overwrite the real token with `"**********"`. Use `model_dump(context=...)` or exclude/round-trip the secret, or snapshot via direct attribute copy. **This is the subtle one** — flag for a focused test.
- Note `tests/unit/test_config_classes.py:176-200` asserts `"token" in test_config.model_dump()` — still true, but the *value* becomes masked; update if it asserts the value.

**Other sensitive fields:** Search found none beyond `token` (no `password`/`secret`/`api_key` config fields). `base_url`/`verify_ssl` carry no credentials — `verify_ssl` is currently hidden by omission; under the new scheme it would be explicitly `HIDDEN` (or `VISIBLE` — a deliberate decision the marker now forces).

## Concrete Implementation Sketch

```python
# src/hassette/config/visibility.py (new)
from enum import StrEnum
from pydantic.fields import FieldInfo

class UiVisibility(StrEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    REDACTED = "redacted"

def field_visibility(field: FieldInfo) -> UiVisibility:
    extra = field.json_schema_extra
    raw = extra.get("ui") if isinstance(extra, dict) else None
    try:
        return UiVisibility(raw)        # safe-by-default: missing/typo → HIDDEN
    except ValueError:
        return UiVisibility.HIDDEN
```

```python
# Field annotation pattern (source config) — config.py / models.py
dev_mode: bool = Field(default_factory=get_dev_mode,
                       json_schema_extra={"ui": UiVisibility.VISIBLE})
token: SecretStr | None = Field(default=None,
                       validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
                       json_schema_extra={"ui": UiVisibility.REDACTED})
# unmarked fields → HIDDEN by default (the resolver enforces this)
```

```python
# The spine test (new) — tests/unit/web/test_config_visibility.py
def test_every_config_field_has_known_visibility():
    for model in (HassetteConfig, WebApiConfig, LoggingConfig, ...):
        for name, field in model.model_fields.items():
            vis = field_visibility(field)   # never raises; HIDDEN on unknown
            assert vis in UiVisibility

def test_response_emits_exactly_the_visible_set():
    # Build the set of source fields marked VISIBLE/REDACTED (per group),
    # and assert it equals the set of fields ConfigResponse actually emits.
    # Fails loudly if a field is marked-but-not-mapped or mapped-but-not-marked.
```

The mapper (`config_response_from`) keeps its restructuring (Path→str, tuple→list, group flatten) — it stays the *shape* authority; the markers + test become the *exposure* authority.

## Concerns

### Technical risks
- **SecretStr silent-mask breakage** at `auth_headers` and WS auth — these would pass type-check and unit tests yet break real HA connections. Verify on the system/e2e surface (which exercises real WS auth), not just unit tests. (`verification.md` — observe the running system; this is exactly the "wrong-surface pass" trap.)
- **`preserve_config` round-trip** (`harness.py:186`) could silently corrupt the token to `"**********"` across the `model_dump`/`setattr` cycle, poisoning every test that runs after it in the same harness scope.

### Complexity risks
- Adding `json_schema_extra` to ~90 fields is wide. Most are `HIDDEN` and could be left unmarked (resolver defaults to hidden) — but then the *source* fields don't self-document their hidden status. Decide: mark only `VISIBLE`/`REDACTED` explicitly (less noise, relies on default) vs. mark all (self-documenting, ~90 edits). The former is lazier and safe-by-default; recommend it, with the test guaranteeing the default holds.

### Maintenance risks
- Option A keeps the response-class field list duplicated against the source. The no-drift test makes divergence loud, but the duplication remains a maintenance surface. This is the deliberate trade for a stable wire shape — worth naming in the design doc so a future reader doesn't "simplify" it into Option B and reintroduce the restructure problem.

## Open Questions

- [ ] Mark-all vs. mark-exposed-only on the ~90 source fields? (Recommend mark-exposed-only; resolver defaults to hidden.)
- [ ] Should `token` be *added back* to the response as a masked `"**********"` field (so the UI can show "token: set"), or stay fully omitted? Today it's omitted; `REDACTED` semantics suggest "present but masked," but adding it changes the wire shape and the `test_token_not_in_response` contract. Default: keep omitted unless the UI wants a "configured" indicator.
- [ ] How should `preserve_config` (`harness.py:186`) handle a `SecretStr` field across `model_dump`→`setattr`? Needs a focused test before the change lands.
- [ ] Does any code outside the searched scope (user apps — Hassette is a framework with external callers, per memory) read `config.token` as a plain `str`? `SecretStr` is a public-API behavior change for app authors; if so it may warrant a `BREAKING CHANGE:` footer.

## Recommendation

**Proceed with Option A.** Pattern 1 is sound and has real prior art, but in *this* codebase the response is a restructure of the source, so the cleanest realization is **metadata-driven field selection over the existing hand-written response classes**, not an import-time derived model. That delivers the full #690 outcome — single source of truth for visibility, a bidirectional no-drift test, and type-level redaction via `SecretStr` — while keeping the wire shape and the schema-export pipeline provably unchanged (the highest-value safety property here).

The `SecretStr` change is the real work and the real risk; it touches live HA auth paths that unit tests mock. Sequence it as its own verifiable unit (RED test that the token reaches the wire unmasked → convert → GREEN), verified on the system/e2e surface, *before* layering the marker/derivation work on top.

### Suggested next steps
1. Run `/mine-define` to turn this into a design doc, recording the Option A vs. B decision and the "response is a restructure" rationale so it isn't re-litigated.
2. Land `token` → `SecretStr` as an isolated commit: fix `auth_headers`, WS auth, `truncated_token`, `preserve_config`, and the token-assertion tests; verify on `nox -s system`/`e2e` (real WS auth), not just unit tests.
3. Add the `UiVisibility` enum + `field_visibility` resolver + the bidirectional no-drift test (the #690 spine).
4. Annotate the ~27 exposed source fields with `VISIBLE`/`REDACTED`; confirm the no-drift test passes against the unchanged response classes and that `openapi.json`/TS output is byte-identical (freshness check green).
