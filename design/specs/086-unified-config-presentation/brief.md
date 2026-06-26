# Brief: Unified Config Presentation in the Web UI

**Date:** 2026-06-25
**Status:** explored
**Seed issue:** #690 (field-level UI-visibility metadata) — scope has grown well past the original issue

## Idea

Unify how *all* configuration is surfaced to the web UI — the global `HassetteConfig`
(Config page) and per-app `AppConfig` (each app detail page's Config tab) — under a single
**metadata-driven, self-describing, generically-rendered, read-only** scheme. Today there are
two divergent code paths and three inconsistent secret-redaction mechanisms; the global config
is hand-maintained, restructured, and incomplete, and the user dislikes the current presentation.
The redesign makes config fields self-describe (relevance tier + optional presentation hints +
type-driven redaction), exposes both surfaces as one enriched JSON schema, and renders both with
one generic component that shows the *complete* configured picture.

## Key Decisions Made

- **Read-only.** Editing is explicitly out of scope. Write-back collides with layered config
  sources (init args > env > `.env` > file secrets > `hassette.toml`, `config.py:76-83`), there is
  no write-back infrastructure in `src/`, and the web API is essentially unauthenticated.
- **Show ALL config, tiered by relevance.** Full transparency — expose every field, but visually
  tier it: common/operational fields prominent, internal/advanced fields collapsed behind a
  "show advanced" affordance. (Replaces today's curated ~27-of-~90 global exposure.)
- **Two orthogonal metadata axes — drop the `visible|hidden|redacted` enum** from the research
  brief. There is no "fully hidden" category; everything is shown.
  - **Axis 1 — relevance tier:** `common` | `advanced` (lives in `json_schema_extra`).
  - **Axis 2 — sensitivity:** handled by **type** (`SecretStr`), *not* metadata.
- **Secrets appear as a masked value with set/unset indication.** Masked placeholder when set,
  empty/"not set" when unset — preserves "see the full picture" without leaking the value.
- **No reveal-secret in MVP.** A "reveal via UI button" was requested but deferred: it requires the
  real value over the wire, punches a hole in `SecretStr`, contradicts `test_token_not_in_response`,
  and is unsafe on an unauthenticated API. **Reveal is a follow-up, gated on the web API gaining auth.**
- **Type-driven redaction only — drop the key-name regex, but replace it (not remove it) on the app
  surface.** Remove app config's `_SECRET_KEYS` regex (`apps.py:23-33`) — it is name-matching security
  theatre: it misses `pat`/`connection_string`/innocuously-named secrets while implying coverage.
  **But the app-config endpoint serves `manifest.app_config` as a raw TOML `dict`, not a live
  `AppConfig` instance** (`apps.py:130`), so `SecretStr` alone cannot redact it (challenge F1, CRITICAL).
  Replace the regex with **schema-driven masking**: walk the already-generated
  `app_config_cls.model_json_schema()`, find fields Pydantic marks `"writeOnly": true` /
  `"format": "password"` (i.e. `SecretStr`-typed), and mask those keys in the served dict, recursing
  into nested models. This is real type-grounded redaction — it masks exactly what the author
  *declared* secret — and unifies both surfaces under one principle. **Accepted, documented tradeoff:**
  an untyped `api_key: str` is no longer masked; secrets must be typed `SecretStr` to be auto-redacted.
  This is the honest contract (no false confidence) and nudges app authors toward `SecretStr`.
  Separately, the existing `_redact_dict` recursion bug (single-level only, `apps.py:33`) is moot once
  schema-driven masking replaces it. **No external users yet** (see open question — confirm), so the
  "SecretStr is a breaking change for app authors" concern is low-risk.
- **App-author DX: sane defaults, zero required annotation.** Unannotated `AppConfig` fields default
  to `common` tier, normal sensitivity. `SecretStr` fields auto-redact. Authors *opt in* to tiers and
  presentation overrides; they are never forced to annotate (safe-by-default still holds because
  secrets are typed, not marked).
- **Presentation: derive-by-default + explicit overrides.** Groups derive from the nested
  config-class structure; labels from field names + **docstrings (already written on every field)**;
  value formatting inferred from type (bool→toggle/badge, `Path`→code, enum→badge, duration→humanized).
  Optional explicit presentation metadata (section label, order, widget hint) is available for fields
  that need better-than-default. The *capability* is designed in; rich widgets are a fast-follow.
- **Unify on schema-driven rendering.** Ship one enriched JSON schema (`model_json_schema()` +
  `ui` metadata via `json_schema_extra`) for *both* surfaces; one generic frontend renderer replaces
  both `config.tsx` (global) and `components/app-detail/config-tab.tsx` (app).
- **MVP cut = backend + parity frontend.** First PR: metadata model, `SecretStr`, two-axis exposure,
  enriched schema for *both* surfaces, and a functional-but-basic unified renderer (tiering + masking
  working). Defer rich widgets and presentation-override polish to a fast follow.

## Open Questions

These feed directly into `/mine-define`:

- **Metadata key shape.** Exact `json_schema_extra` structure — e.g. `{"ui": {"tier": "advanced",
  "label": ..., "order": ..., "widget": ...}}` vs flat keys. Define should settle it and the enum.
- **Schema round-trip.** Confirm the enriched `ui` metadata survives `model_json_schema()` and flows
  cleanly + deterministically through `scripts/export_schemas.py` → `openapi.json` / `generated-types.ts`
  and the freshness check (`tools/check_schemas_fresh.py`).
- **Expose source schema directly vs a projected model.** With show-all + type-driven redaction, the
  research brief's "the response restructures the source" obstacle *dissolves* — we are no longer
  preserving the old shape. So `HassetteConfig` can likely be exposed via its own `model_json_schema()`
  (like `AppConfig` already is), letting the hand-written `ConfigResponse` classes + `config_response_from()`
  mapper (`mappers.py:209-255`, `models.py:405-470`) **largely go away**. Confirm in define.
- **Grouping = nested-class structure?** With show-all, the dropped groups (`database`, `websocket`,
  `blocking_io`) now appear. Confirm the nested-group structure is the grouping we want, and the
  default tier policy (which groups/fields are `advanced` by default — e.g. timing/plumbing).
- **Tier taxonomy.** Two levels (`common`/`advanced`) or more? Default-tier policy per field/group.
- **Value formatting** for special types: `timedelta`/duration humanization, `Path`, enums,
  tuples/lists, nested models, `cors_origins`.
- **Frontend placement.** One shared component serving both the Config page and the app Config tab —
  confirm routing/component location and that both test suites (`config.test.tsx`, `config-tab.test.tsx`)
  get reworked.
- **`SecretStr` blast radius** (carried from research brief, still required): `auth_headers`
  (`config.py:235`), WS auth (`websocket_service.py:557,564`), `truncated_token` (`config.py:243-251`),
  and the `preserve_config` harness round-trip (`harness.py:186`). Must be handled and **verified on
  `nox -s system`/`e2e`**, not just unit tests. **Frontend:** `config-tab.test.tsx:14,48` uses a
  fixture `token: "supersecret123"` and asserts the *plaintext* is rendered — this test must be
  rewritten in the same PR to assert the masked placeholder (added per challenge F6).
- **Internal fields under show-all.** `env_file`, `config_file`, `import_dot_env_files` now appear
  (likely `advanced`). Confirm none are themselves sensitive enough to warrant masking.

## Scope Boundaries

**In (MVP):**
- Read-only unified config presentation for both global and app config.
- Two-axis metadata model (relevance tier in metadata; sensitivity via `SecretStr`).
- Type-driven secret redaction; masked value + set/unset; remove the key-name regex.
- One enriched JSON schema per surface; one generic schema-driven renderer (functional/basic), with tiering.

**Deferred (fast-follow / later):**
- Rich presentation widgets + explicit presentation-override polish.
- Reveal-secret button (requires web API auth first).
- Web API authentication.
- Config editing / write-back.

**Rejected:**
- Required app-author annotation (bad DX, unsafe-on-forget).
- Key-name regex redaction (being removed in favor of type-driven).
- Preserving the current global-config wire shape (the user explicitly does not want to anchor on it).

## Risks and Concerns

- **`SecretStr` silent-mask breakage at real auth paths.** `auth_headers` and WS auth interpolate the
  token; with `SecretStr` they'd silently become `"**********"`, breaking real HA connections while
  passing type-check and unit tests (which mock the boundary). Verify on the system/e2e surface.
- **`preserve_config` round-trip** (`harness.py:186`) `model_dump()`→`setattr` could poison the token
  to the masked value across a test scope. Needs a focused test before landing.
- **Generic renderer risks looking bland** — the very "display quality" pain we're fixing. Presentation
  overrides mitigate but are deferred; the MVP "basic" renderer must still be a net *improvement* in
  polish, not a regression. (Consider an `/i-*` design pass on the renderer.)
- **Wire-shape change is intentional but visible.** Dropping the restructuring changes both rendered
  config surfaces → the PR triggers the visual-evidence requirement (`design-completeness.md`); regen
  `docs/_static/web_ui_config.png` and capture app-config-tab screenshots.
- **Schema-export determinism.** Enriched `json_schema_extra` must round-trip deterministically through
  OpenAPI/TS export so the freshness checks stay green.
- **Web UI threat model not fully pinned** (local/trusted vs potentially exposed). Reveal was dropped,
  so masked-only is safe under either — but state the assumption explicitly in the design.

## Challenge Resolutions (2026-06-25)

Ran `/mine-challenge` (Senior Engineer, Systems Architect, Web Platform). 8 findings, 0 invalid.
Resolutions:

- **F1 (CRITICAL) — app-config raw-dict redaction.** Resolved in Key Decisions: drop the regex
  (theatre), replace with **schema-driven masking** of `writeOnly`/`format:password` keys in the
  served dict. Untyped secrets unmasked is the accepted, documented tradeoff.
- **F2 (HIGH) — two surfaces / `$ref` resolution / "one renderer".** Build-vs-reuse eval **done**
  (two parallel web surveys, 2026). **Decision: reuse the deref layer, hand-roll the renderer.**
  - **Resolve `$ref`/`$defs` server-side in Python** — `jsonref.replace_refs(schema)` or Pydantic's
    own ref handling — so the frontend receives a fully-inlined schema and never walks `$ref`. (Caveat:
    `jsonref` can mangle discriminator `mapping` refs under discriminated unions — N/A for the current
    plain nested-model config groups, but re-check if any config field becomes a discriminated union.)
    Return `{config_schema, config_values}` matching the app-config shape.
  - **Render with ~100–200 lines of custom Preact** against the design-system components (`Badge`/`Card`).
  - **Why not a 3rd-party renderer (evidence-based, correcting an earlier overstatement):**
    `preact/compat` covers ~99% of React 15–19 and the libs *would* load — for read-only display the
    "no concurrent rendering" caveat is irrelevant — so **React-coupling is NOT the disqualifier**. The
    real disqualifiers: (1) **RJSF/JSONForms/uniforms/json-editor are form engines** — their "read-only"
    is *disabled inputs*, not text display; getting a real display means writing custom widgets/renderers
    per type (the bulk of the work) plus dead-weight AJV/validation. (2) **Read-only schema-viewers**
    (Stoplight, Atlassian) are React + impose their own design system and render schema structure, not
    labels-over-values-with-masking. (3) **Framework-agnostic value-viewers** (`@andypf/json-viewer`,
    `alenaksu/json-viewer`) are **Web Components whose Shadow DOM walls off the CSS-Modules tokens** and
    render raw JSON keys, not schema labels — the exact "JSON blob" regression we're avoiding. No library
    delivers labels + grouping + masking + the design system together; the custom renderer is small and is
    the only way to get all four.
  - **Escape hatch:** if config *editing* is ever un-deferred, re-evaluate **JSONForms via `preact/compat`**
    (real `readonly` prop, vanilla-renderers set, first-class custom renderers) — read-only would become a
    stepping stone rather than throwaway. For read-only-and-staying-read-only, hand-roll wins.
- **F3 (HIGH) — `ui` metadata invisible to the OpenAPI freshness check.** Deferred to define **with a
  prior-art pass** on how projects CI-guard schema/annotation freshness. Leading candidate: a typed
  `ConfigSchemaResponse(BaseModel)` envelope (freshness-checked) + a dedicated unit test walking
  `model_fields` to assert every field's `{ui:{tier}}` shape; document that the OpenAPI check does not
  cover `ui` annotations.
- **F4 (HIGH) — `preserve_config` SecretStr footgun.** Resolved: **refactor** `preserve_config`
  (`harness.py:179-200`) to snapshot via `config.model_copy(deep=True)` / `copy.deepcopy` instead of
  `model_dump()` — a deep copy preserves `SecretStr` objects and removes the `mode='json'` masking
  footgun structurally. Ships in the same PR as the `SecretStr` migration.
- **F5 (HIGH) — generic renderer could regress from curated `config.tsx`.** Resolved: before locking
  MVP scope, **produce a mockup** (`/i-shape` or `/mine-mockup`) of the full `HassetteConfig` render
  AND run the F2 build-vs-reuse evaluation. "Simpler code" and "better UX" are in tension; the mockup
  sets the quality bar that `config.tsx` (human labels, field renames, curation) currently meets.
- **F6 (HIGH) — `config-tab.test.tsx` asserts plaintext token.** Applied to the blast-radius list above.
- **F7 (MEDIUM) — external-user assumption.** Resolved: **add a `BREAKING CHANGE:` footer
  unconditionally** for the `str` → `SecretStr` change on `AppConfig` field types. Don't rely on the
  "no users yet" inference (project memory warns "grep for callers ≠ zero users"); document the
  migration regardless. Supersedes the "low-risk / confirm" framing in Key Decisions and Open Questions.
- **F8 (MEDIUM) — tier policy left open.** Resolved: **settle the tier map in `/mine-define`** using
  **group-level defaults** (`DatabaseConfig`, `BlockingIODetectionConfig`, `WebSocketConfig` → `advanced`)
  with field-level overrides for exceptions — ~9 decisions, not ~90. The tier map is a concrete define
  deliverable, not an implementer choice.

## Codebase Context

- **Global config:** `config_response_from()` `web/mappers.py:209-255` hand-copies ~27 fields into
  parallel response classes (`web/models.py:405-470`) and *restructures* the source (flattens
  `apps.directory`, `Path`→`str`, `tuple`→`list`, drops `database`/`websocket`/`blocking_io`). Redacts
  `token` by omission. `HassetteConfig` `config/config.py:49` — 31 top-level fields (8 nested groups);
  ~90 fields across 9 nested classes in `config/models.py`. Layered sources at `config.py:76-83`.
- **App config:** `get_app_config()` `web/routes/apps.py:111-131` already ships `app_config` values +
  `config_schema = app_config_cls.model_json_schema()`; frontend `components/app-detail/config-tab.tsx`
  renders generically from that schema. Redacts via `_SECRET_KEYS` regex (`apps.py:23-33`).
  `AppConfig(BaseSettings)` at `app/app_config.py:10`. **This surface already proves schema-driven
  generic rendering works in-repo** — the global surface is being brought up to it, then both unified.
- **Frontend:** `frontend/src/pages/config.tsx` (global) + `frontend/src/components/app-detail/config-tab.tsx`
  (app tab) — both replaced by one generic renderer.
- **Greenfield for the mechanism:** no `json_schema_extra` or `SecretStr` anywhere in `src/hassette`;
  config modules do **not** use `from __future__ import annotations`, so runtime `FieldInfo`
  introspection is safe.
- **Security pin:** `test_token_not_in_response` `tests/integration/web_api/test_endpoints.py:375`.
- **Schema export:** `scripts/export_schemas.py` → `openapi.json` + `generated-types.ts`; freshness
  check `tools/check_schemas_fresh.py` (pre-push) + CI git-diff on generated TS.
- **Prior artifacts:** prior-art brief `/tmp/claude-mine-prior-art-Tzkhcz/brief.md`; research brief
  `design/research/2026-06-25-config-ui-visibility-metadata/research.md` (mechanical findings valid;
  its "Option A — preserve current shape" conclusion is **superseded** by the show-all / don't-anchor
  decisions here).
