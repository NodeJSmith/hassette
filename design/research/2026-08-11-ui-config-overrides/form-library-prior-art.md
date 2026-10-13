---
proposal: "Decide whether hassette's editable runtime-config form should adopt a JSON Schema form library (@rjsf, JSONForms, uniforms) or be hand-rolled on the existing read-only renderer."
date: 2026-08-11
status: Draft
flexibility: Exploring
motivation: "The frontend has a read-only schema renderer (config-schema-view.tsx) and needs an editable equivalent for runtime-generated pydantic AppConfig schemas."
constraints: "React 19 mandatory; Tailwind v4 + shadcn/radix-ui; no CSS Modules/@apply; entry chunk budget 240 kB gzip (currently 232 kB); vitest + RTL + MSW."
non-goals: "Not deciding the backend write endpoint (see Open Questions — none exists)."
depth: deep
---

# Research Brief: JSON Schema Form Library vs Hand-Rolled Editor

**Initiated by**: "Should we build the editable config form by hand or adopt a JSON Schema form library?"

## Headline

I built a benchmark harness, generated a real `pydantic.model_json_schema()` payload
exercising every construct hassette uses, and rendered it through each candidate. The
results are measured, not estimated.

| | rjsf + @rjsf/shadcn | JSONForms + vanilla | uniforms | Hand-rolled |
|---|---|---|---|---|
| React 19 | ✅ verified rendering | ✅ verified rendering | ❌ **npm install fails** | ✅ |
| Marginal bundle (gzip) | **+108.6 kB** | +45.2 kB | n/a | **~0 kB** |
| Fields rendered (13-field pydantic schema) | 12/13 | **6/13** | not tested | n/a |
| Maintained | ✅ commit yesterday | ✅ commit 5 days ago | ❌ **7 months idle** | n/a |
| shadcn/Tailwind v4 native | ✅ official theme, tokens match exactly | ⚠️ only 3rd-party v0.0.2 | ❌ none | ✅ |

Two findings dominate everything else, and they point in opposite directions:

1. **`@rjsf/shadcn` is a real, officially-maintained, Tailwind-v4 theme whose CSS tokens
   line up perfectly with hassette's `global.css`** — better than I expected going in.
2. **It costs +108.6 kB gzip against an entry-chunk budget with 8 kB of headroom**, and an
   open issue (#1477) already exists because the chunk is too big.

---

## Context

### What prompted this
`frontend/src/components/shared/config-schema-view.tsx` (497 lines) renders a deref'd JSON
Schema + values pair as read-only rows. An editable version is wanted. The schema comes from
`pydantic.model_json_schema()` on a user-defined `AppConfig` subclass, so it is arbitrary and
unknown at build time.

### Current state (verified)

- **Backend** (`src/hassette/web/routes/config.py:29`, `routes/apps.py:228`) calls
  `model_json_schema()` in default *validation* mode, then `deref_schema()`
  (`web/config_view.py:255-269`) runs `jsonref.replace_refs()` and drops `$defs`. Secrets are
  masked server-side to `MASK_SENTINEL = "••••••••"`; the `ui` hint extension key passes
  through untouched.
- **No write path exists.** I grepped every route: there is no `PATCH`/`PUT`/`POST` for config.
  Issues **#489** (runtime config via API) and **#490** (persist to TOML) are both
  **CLOSED as NOT_PLANNED**. *(Correcting an inference one of my subagents made — it saw the
  issues were closed and assumed the feature shipped. It did not.)*
- **No form primitives exist.** `frontend/src/components/ui/` contains only
  `alert-dialog, badge, button, card, command, dialog, drawer, popover, table, tooltip`.
  There is **no** `input`, `select`, `checkbox`, `switch`, `label`, `textarea`, or `form`.
- **No form/validation library.** No react-hook-form, zod, valibot, yup, formik. `ajv@8` is
  present but used only in `src/api/ws-validator.ts` for WebSocket message validation.
- **Only prior art**: `pages/login.tsx` — one bespoke `<form>`, `useState` per field, native
  `required`, no dirty tracking.
- **Bundle budget**: `.size-limit.json` sets 240 kB gzip for the entry chunk, enforced in CI.
  The React 19 migration pushed it to **232 kB**; PR #1476 raised the budget as a stopgap;
  **#1477 is open** to get it back under 200 kB. `vite.config.ts` has **no** `manualChunks`
  and **no** `React.lazy` anywhere — everything ships eagerly today.

### What pydantic actually emits (measured)

Generated from a representative `AppConfig`:

| Pydantic type | JSON Schema emitted |
|---|---|
| `float \| None` | `anyOf: [{type:number},{type:null}]`, **no top-level `type`** |
| `SecretStr \| None` | `anyOf: [{format:password, writeOnly:true, type:string},{type:null}]` |
| `Mode` (StrEnum) | `$ref: "#/$defs/Mode"` **+ sibling `default`** |
| `Literal[...]` | `enum: [...]` + `type: string` |
| `Path` | `format: "path"` (non-standard) |
| `tuple[str, ...]` | `items: {type:string}` — **standard, safe** |
| `tuple[float, float]` | `prefixItems: [...]` + min/maxItems — **2020-12 only** |
| `dict[str, int]` | `additionalProperties: {type:integer}` |
| `Nested \| None` | `anyOf: [{$ref},{type:null}]` |

No `$schema` key is emitted at all, so validators must guess the dialect.

**Frequency in hassette's own `HassetteConfig`** (34 top-level props, 14 `$defs`):

- **18** `X | None` fields · **9** genuine unions (`int \| float`) · **10** `format: path`
- **6** `$ref`-with-siblings · **3** `writeOnly` secrets · **2** `additionalProperties` dicts

The base `AppConfig` contributes **2** `X | None` fields (`forgotten_await_behavior`,
`blocking_io_behavior`), so **every user app inherits at least two** of the problem construct.

---

## Feasibility Analysis

### Measured bundle cost

Method: esbuild bundle, minified, gzip -9. Baseline includes hassette's *existing* shared deps
(react 19, react-dom, ajv 8, radix-ui, lucide-react, cva, cmdk, tailwind-merge, clsx) so the
delta is the true **marginal** cost. Baseline = 147,547 B gzip.

| Configuration | Total gzip | **Marginal** |
|---|---|---|
| `@rjsf/core` + `validator-ajv8` + `@rjsf/shadcn` | 258,743 | **+108.6 kB** |
| `@rjsf/core` + `validator-ajv8` (no theme) | 243,033 | +93.2 kB |
| `@jsonforms/*` + `vanilla-renderers` | 193,787 | +45.2 kB |
| `@jsonforms/core`+`react` only (custom renderers) | 184,790 | +36.4 kB |

Composition (minified bytes in output) explains the rjsf number:

- `markdown-to-jsx` **78 kB** — a hard dep of `@rjsf/core` for rendering descriptions. Pure
  dead weight for hassette, and not tree-shakeable away.
- `@rjsf/core` 71 kB + `@rjsf/utils` 47 kB · `lodash-es` 32 kB · `@rjsf/shadcn` 31 kB ·
  `fast-uri` 24 kB · `@x0k/json-schema-merge` 11 kB

JSONForms' own driver is `lodash` (full CJS, **70 kB**, not tree-shaken).

`ajv` (105 kB minified) is **already in hassette's baseline**, so it is free for every
candidate — a genuine point in favor of any ajv-based option.

**Radix dedupes cleanly.** `radix-ui@1.6.7` declares the individual `@radix-ui/react-*`
packages as dependencies (55 of them, including checkbox/label/select/slider), and the
metafile confirms `@radix-ui/react-select` appears exactly once. `@rjsf/shadcn`'s radix deps
do **not** duplicate.

### What already supports this

- **`global.css` is already shadcn-token-complete for `@rjsf/shadcn`.** I rendered the theme
  and extracted every token utility it emits: `text-muted-foreground, text-foreground,
  bg-primary, text-primary-foreground, bg-input, border-input, border-ring, ring-ring,
  ring-destructive, border-destructive, bg-background, text-popover-foreground, border-primary,
  bg-accent, text-accent-foreground`. **All 15 are registered** in hassette's `@theme inline`.
  Notably `bg-accent` → `var(--highlight-bg)`, which is exactly the shadcn "highlighted
  background" semantic the CLAUDE.md aliasing note was designed to provide. The deliberate
  `--accent` / `--highlight-bg` split turns out to make third-party shadcn components work
  correctly rather than break them.
- `@rjsf/shadcn` ships **Tailwind v4** CSS (`/*! tailwindcss v4.3.0 */` in `dist/default.css`)
  and its README documents the v4 integration as a one-liner:
  `@source "../node_modules/@rjsf/shadcn";`
- `ajv@8` already a dependency — the validator is free.
- The read-only renderer already solves the domain-specific half: `ui` hint handling
  (`label`/`group_label`/`order`/`widget`), section grouping, framework-vs-app field
  partitioning, secret detection mirroring `_is_secret_node`, path detection, duration
  humanizing, enum-inside-`anyOf` detection.

### What works against this

- **8 kB of headroom** on a CI-enforced budget, with #1477 already open because the chunk is
  oversized. Adding 108 kB eagerly is an instant CI failure. Lazy-loading the config route
  fixes CI but still means a 108 kB gzip download for one page — larger than most of the app.
- No code-splitting infrastructure exists yet (`vite.config.ts` has none, zero `React.lazy`
  in `src/`). Any library adoption **depends on #1477 landing first**, or on doing that work
  as part of this.
- No form primitives vendored. `@rjsf/shadcn` sidesteps this by vendoring its **own** copies
  (`input.tsx`, `label.tsx`, `checkbox.tsx`, `radio-group.tsx`, `select`, `slider`, `textarea`,
  `badge.tsx`, `button.tsx`, `dialog.tsx`) — which means hassette would ship **two divergent
  sets** of shadcn primitives whose styling drifts independently.

---

## Candidate Evaluations

### 1. `@rjsf/core` v6 + `@rjsf/validator-ajv8` + `@rjsf/shadcn`

**(a) Health** — Excellent. 15,862 stars; last commit **2026-08-10** (yesterday); 128 open
issues, 14 open PRs; not archived. `@rjsf/core@6.7.1` published 2026-07-24. 1.24 M weekly
downloads. `@rjsf/shadcn` is in the official monorepo, first released 2025-05-02, 46 versions,
now at 6.7.1 in lockstep with core, **71 k weekly downloads**. This is not an abandoned
community theme.

**(b) React 19** — Verified by execution, not by reading. Peer is `react: ">=18"`; installed
against react@19.2.8 with **zero peer warnings**; `renderToStaticMarkup` of the shadcn-themed
`<Form>` succeeded (22,143 chars, 6 inputs, 9 buttons) under React 19.2.8. Note the v6
migration guide's prose is **stale** — it still reads "React 19 support is expected before the
end of beta" although v6 went stable in late 2025. Trust `peerDependencies` and the render
result over the doc text.

**(c) Bundle** — **+108.6 kB gzip** marginal, theme and validator included. 72 % of that is
`@rjsf/core` + `@rjsf/utils` + `markdown-to-jsx`.

**(d) Native look** — Genuinely low effort, the standout result. One `@source` line in
`global.css`, and all 15 emitted token utilities already resolve. Residual gaps: it depends on
`tailwindcss-animate@^1.0.7` (a **Tailwind v3** plugin) for the `animate-in`/`animate-out`
classes on its dialog/popover — under v4 you'd need `tw-animate-css` or accept unanimated
overlays (cosmetic). And its vendored primitives will visually drift from hassette's.

**(e) Runtime-unknown schemas** — This is rjsf's core competency. Pass `schema` as a prop; no
build step, no companion artifact.

**(f) Pydantic constructs — measured, and this is the important part.** Rendering the real
deref'd schema:

- **Every `X | None` field renders a spurious type-selector `<select>`.** `delay`, `token`, and
  `optional_nested` each got a `root_<field>__anyof_select`. The option labels are literally
  **`"Delay option 1"` / `"Delay option 2"`**, and because `default: null`, **option 2 (the
  null branch) is preselected** — so a user must choose a meaningless "option 1" before they
  can type anything. With **18 such fields in `HassetteConfig`** and **2 in the base
  `AppConfig`**, this is not an edge case; it is the dominant field shape.
- **`prefixItems` renders zero controls.** `tuple[float, float]` produced the array shell and
  **no item inputs at all** — silent, no error. (`tuple[str, ...]` is fine: pydantic emits
  plain `items`, and it rendered 2 inputs correctly. hassette's own `cors_origins` /
  `trusted_proxies` are variadic, so the framework config is safe; a user's fixed tuple is not.)
- `format: "path"` triggers an ajv `unknown format "path" ignored` warning on **every**
  validation pass (10 occurrences in `HassetteConfig`). Noisy; fixable with `addFormat`.
- `$ref` + sibling `default`, `enum`, `additionalProperties` (key/value add UI), and nested
  objects all rendered correctly.

**Mitigation — verified.** A ~20-line schema normalizer that collapses `anyOf:[X, null]` → `X`
and rewrites `prefixItems` → array-form `items` **fixes all of it**:

```
anyof selectors remaining: 0
delay input type      : number
token input type      : password   ← format:password correctly derived from the collapsed branch
coords item inputs    : 2
optional_nested fields: root_optional_nested_host, root_optional_nested_port
```

That shim is cheap and is needed for *any* approach, including hand-rolling.

**This is confirmed upstream, not just my measurement.** Open rjsf issues track exactly this:

- **#4843 "Nullable type support for `anyOf` fields with two values"** — open; the precise
  pydantic `X | None` shape. https://github.com/rjsf-team/react-jsonschema-form/issues/4843
- **#4380 "anyOf/oneOf with Discriminated Unions + Null doesn't work"** — open since
  2024-11-13, 11 comments, reporter's schema generated by **Pydantic 2.9.2**.
  https://github.com/rjsf-team/react-jsonschema-form/issues/4380
- **#4918** — anyOf/oneOf formData overwritten by defaults when switching branches (open).
- Upstream context: pydantic v2 deliberately changed `Optional[X]` codegen to the `anyOf`
  form — pydantic **#9057** and **#7161**. This is a pydantic-ecosystem friction point, not an
  rjsf defect.

There are also **5 open shadcn-specific issues**, including **#4642** "shadcn error highlight
not working on parent objects" — worth weighing since validation-error display is a core
requirement here. (**#3199** "Tailwind support" is also still open.)

**(g) Strongest argument against** — **+108.6 kB gzip is disproportionate to the feature.** It
is roughly half the size of the entire current application, for one settings page, against a
budget that is already the subject of an open bug. Nearly 80 kB of it (`markdown-to-jsx`,
`fast-uri`, `json-schema-merge`) serves generality hassette will never use. And to preserve the
read-only renderer's design language — `ui.order`, `ui.group_label` sections, the App/Hassette
field partition, duration humanizing, the info-popover — you must write custom
`ObjectFieldTemplate`, `FieldTemplate`, and several widgets anyway. You pay 108 kB *and* still
write the interesting code.

### 2. `@jsonforms/react` + renderer set

**(a) Health** — Alive but smaller. 2,729 stars; last commit **2026-08-06**; 129 open issues,
18 open PRs. v3.8.0 published 2026-06-16, 3.9.0-alpha in progress. 222 k weekly downloads. MIT.

**(b) React 19** — Explicitly declared: peer is
`^16.12.0 || ^17.0.0 || ^18.0.0 || ^19.0.0`. Verified rendering under React 19.2.8.

**(c) Bundle** — +45.2 kB gzip with vanilla renderers; +36.4 kB with core+react only. Cheaper
than rjsf, driven mainly by full CJS `lodash` (70 kB minified).

**(d) Native look** — **No *official* Tailwind or shadcn renderer set.** Official sets are
Material (`@jsonforms/material-renderers`) and vanilla. One third-party set exists —
`@fragno-dev/jsonforms-shadcn-renderers` — but it is at **v0.0.2** (published 2025-12-29,
~3.5 k weekly downloads). Not something to build a config editor on. Realistically you write
the renderer set yourself, and the Material set's scope suggests that is a double-digit number
of renderer/tester pairs, not a handful.

**(e) Runtime-unknown schemas — the UI-schema premise is false, and I verified it.**
`Generate.uiSchema(schema)` exists and works: it produced a `VerticalLayout` with all 13
Controls from the pydantic schema. Omitting `uischema` entirely produces byte-identical output
(2,863 vs 2,881 chars), because JSONForms auto-generates internally. **The separate-UI-schema
requirement is not a dealbreaker.**

**(f) Pydantic constructs — measured, and worse than rjsf.** With `vanillaRenderers`, only
**6 of 13 fields rendered**. Console emitted `No applicable cell found` for `delay` (anyOf),
`token` (anyOf), `coords` (prefixItems), `overrides` (additionalProperties), `nested` (object),
`optional_nested`, and even `tags` (plain `list[str]`). The unrendered fields produce **no
markup and no error** — silently invisible. For a config editor, a field that vanishes is worse
than a field that renders awkwardly, because the user cannot tell it exists.

**(g) Strongest argument against** — It is the worst of both worlds. You pay 36–45 kB *and*
write a complete renderer set from scratch (no Tailwind/shadcn set exists), *and* you inherit
JSONForms' scope/UI-schema/renderer-ranking indirection as permanent conceptual overhead. If
you are writing all the widgets anyway, the 36 kB buys you a ranking dispatcher and a Redux-ish
core you did not need.

### 3. `uniforms` — **disqualified**

**(a) Health** — Effectively dormant. `uniforms@4.0.0` published **2025-02-28** (~18 months
ago). Last commit to `vazco/uniforms` **2026-01-12** (7 months ago), and that commit was
"Restoration of v3 documentation". 2,105 stars, 25 open issues, 22 k weekly downloads.

**(b) React 19 — hard fail, verified.** Peer is
`react: "^18.0.0 || ^17.0.0 || ^16.8.0"`. `npm install` against react@19 aborts:

```
npm error ERESOLVE unable to resolve dependency tree
npm error Found: react@19.2.8
npm error Could not resolve dependency:
npm error peer react@"^18.0.0 || ^17.0.0 || ^16.8.0" from uniforms@4.0.0
```

It installs only with `--legacy-peer-deps` / `--force`. The brief states React 19 support is
mandatory and must be verified rather than assumed — this fails that test explicitly.

**(c)–(f)** Not evaluated further. **(g)** Requires forcing a peer-dependency override on an
18-month-stale package with no Tailwind/shadcn theme. Not a defensible foundation.

### 4. Others checked and ruled out

- **`@sjsf/form`** (the `@x0k` author whose `json-schema-merge` appears in rjsf's tree) — its
  themes (`@sjsf/shadcn4-theme`) peer-depend on `bits-ui` and `@lucide/svelte`. **It is a
  Svelte library.** Not applicable.
- **`@autoform/react`** (33 k weekly downloads, v5.0.0, React 19 peer OK) is driven by
  validation-library schemas (Zod/Yup via `react-hook-form`/`@tanstack/react-form`), **not** a
  raw JSON Schema document at runtime — the wrong shape for this problem. Its shadcn package
  `@autoform/shadcn` is additionally **stuck at v1.0.1 published 2024-10-16 with a React
  `^16.8 || ^17 || ^18` peer** — it fails the React 19 test just like uniforms.
- **`@ts-react/form`** is Zod-driven at compile time. Not applicable to runtime schemas.
- `@rjsf/daisyui` exists (1.8 k weekly downloads) but DaisyUI conflicts with shadcn's token
  model. `@rjsf/tailwind` does **not** exist (npm 404).

---

## Options

### Option A — Hand-roll the editor on the existing renderer *(recommended)*

**How it works.** Add a `normalizeSchema()` pass (collapse `anyOf:[X,null]` → `X`, `prefixItems`
→ `items`) — the same shim every library needs. Extend the widget dispatch that
`config-schema-view.tsx` already has (`isSecretNode`, `enumValues`, `isPathLike`,
`isDurationField`, `unwrapAnyOf`) so each branch returns an input instead of a span. Vendor the
missing shadcn primitives (`input`, `label`, `select`, `checkbox`, `textarea`) via the standard
shadcn CLI. Hold form state in one immutable nested object with a path-based setter; validate
with the already-present `ajv` and map `error.instancePath` → field.

**Pros**
- **~0 kB marginal bundle.** Does not touch #1477; no dependency on code-splitting landing.
- Preserves the read-only design language exactly — `ui.order`, `ui.group_label`, App/Hassette
  partitioning, duration humanizing, the info popover. These are hassette-specific and do not
  transfer to any library without custom templates.
- Read and edit modes share one schema-walking core; the secret/path/duration heuristics stay
  in one place instead of being mirrored into library widget overrides.
- Matches the codebase's established posture (no form lib, no validation lib, hand-rolled login).

**Cons**
- You own array add/remove/reorder, `additionalProperties` key/value UI, nested-object
  recursion, dirty tracking, and error plumbing. This is the genuinely tedious part and rjsf
  gives it away.
- More code to test. Realistically ~600–900 lines plus tests, versus wiring a `<Form>`.
- Risk of reinventing subtle behavior (unsaved-changes guards, add-then-validate ordering).

**Effort**: Medium–Large. **Dependencies**: none new (shadcn primitives are vendored source).

### Option B — Adopt `@rjsf/core` + `@rjsf/shadcn`, behind a lazy route

**How it works.** Land route-level code splitting (#1477) first, then lazy-load the config
route. Add the `normalizeSchema()` preprocessor. Override `ObjectFieldTemplate` /
`FieldTemplate` to reproduce `ui.*` grouping, and add widgets for secret/path/duration.

**Pros**
- Array/dict/nested-object editing, validation wiring, and touched/dirty state come free —
  the exact part Option A must hand-build.
- Theme integration is close to free and verified (all 15 tokens resolve; one `@source` line).
- Actively maintained with a large user base; `@rjsf/shadcn` tracks core in lockstep.

**Cons**
- +108.6 kB gzip, ~80 kB of which is generality hassette will not use.
- Hard-blocked on #1477 — this drags an unrelated architectural change into scope.
- Ships a second, divergent set of shadcn primitives.
- Custom templates still required to keep the current UX, so the savings are smaller than the
  headline suggests.

**Effort**: Medium — but **Large** including the #1477 prerequisite.
**Dependencies**: `@rjsf/core`, `@rjsf/utils`, `@rjsf/validator-ajv8`, `@rjsf/shadcn`
(+ transitively `markdown-to-jsx`, `lodash-es`, `uuid`, `tailwindcss-animate`).

### Option C — Do less: edit only the scalar leaves

**How it works.** Ship editing for `string`/`number`/`integer`/`boolean`/`enum`/secret only —
which after normalization covers the overwhelming majority of real fields. Arrays, dicts, and
nested objects stay read-only with an "edit in `hassette.toml`" affordance, reusing the existing
`ExpandableValue`.

**Pros**
- Removes precisely the parts that justify a library (arrays, dicts, recursion). Smallest diff,
  smallest test surface, ~0 kB.
- Deliverable without resolving #1477 or the missing write endpoint's full validation story.
- Keeps the option open: if array/dict editing is later demanded, that is the moment to
  reconsider Option B with evidence of real demand.

**Cons**
- `HassetteConfig` has 2 `additionalProperties` dicts and several tuple fields that would stay
  read-only — a visible inconsistency.
- May read as half-finished if users expect full editability.

**Effort**: Small–Medium. **Dependencies**: none.

---

## Concerns

### Technical risks
- **No backend write path exists**, and #489/#490 were closed **NOT_PLANNED**. Every option
  here is frontend-only and blocked on a `PATCH` endpoint that has not been designed. The
  server must re-validate regardless of client-side ajv.
- **Secret round-tripping.** Values arrive masked as `"••••••••"`. An editable form will
  happily POST the mask back as the literal new secret unless secret fields are explicitly
  excluded from the dirty set. This is a real credential-corruption hazard and is independent
  of the library choice.
- `format: "path"` is unknown to ajv and logs a warning per validation; needs `addFormat`.
- The frontend `SchemaNode` type omits `additionalProperties`, `prefixItems`, `oneOf`, `allOf`,
  and `patternProperties` — all present in backend output, all caught only by the
  `[key: string]: unknown` index signature. Editing will need these typed.

### Complexity risks
- Option B introduces rjsf's template/widget/field taxonomy as a concept every future
  contributor must learn, on top of the `ui.*` hint system that already exists.
- Two shadcn primitive sets (hassette's and `@rjsf/shadcn`'s) drifting is a slow, hard-to-attribute
  visual-consistency leak.

### Maintenance risks
- Option B couples the config page to rjsf's major-version cadence; v5→v6 was a breaking
  migration. `@rjsf/shadcn` is only ~15 months old.
- Option A means owning form mechanics forever — but they are mechanics the team already owns
  once (login page) and the domain heuristics are hassette-specific either way.

---

## Open Questions

- [ ] What is the backend write contract? #489/#490 are closed NOT_PLANNED — is this being
      reopened, or is the form writing somewhere else?
- [ ] How are masked secrets meant to round-trip? (Suggest: never send unless explicitly
      re-entered.)
- [ ] Must arrays/dicts/nested objects be editable in v1, or is Option C's scalar-only scope
      acceptable? **This single answer decides library-vs-hand-roll** — it is the only area
      where rjsf's value clearly exceeds its cost.
- [ ] Is #1477 (code splitting) scheduled? Option B is not viable until it lands.
- [ ] Unknown-tier gap: no JSONForms-side issue about `anyOf`+null exists in their tracker; that
      is silence, not evidence of correct handling (my own render test showed it produces no
      markup at all). I also did not measure runtime performance (re-render cost) of any candidate
      on a large schema, nor test keyboard/screen-reader behavior of `@rjsf/shadcn`. I searched
      npm and GitHub for a JSONForms Tailwind/shadcn renderer set and an `@rjsf/tailwind`
      package and found neither (npm 404 for `@rjsf/tailwind`); absence of evidence here is
      reasonably strong but not conclusive.

---

## Recommendation

**Take Option A (hand-roll), scoped initially like Option C.** Ship scalar + enum + secret
editing on the existing renderer, leave arrays/dicts read-only for v1, and revisit only if
users ask for them.

The reasoning, in confidence order:

- **Direct, measured**: +108.6 kB gzip against 8 kB of headroom on a CI-enforced budget that is
  already an open bug. This is the decisive fact. It does not depend on any judgment call.
- **Direct, measured**: JSONForms renders 6 of 13 real pydantic fields with its stock renderers
  and no Tailwind/shadcn set exists, so choosing it means writing all the widgets *and* paying
  36–45 kB. It is dominated by both alternatives.
- **Direct, verified**: uniforms fails `npm install` on React 19 and has been idle 7 months.
- **Supported**: the read-only renderer already implements the schema-walking, `ui.*` hint, and
  type-heuristic logic — the parts specific to hassette. Using rjsf would require reimplementing
  those as custom templates and widgets, so the true saving is narrower than "a library does it
  for you" implies.
- **Inferred**: the `normalizeSchema()` shim is required regardless of approach, and once
  written, the gap between "hand-rolled" and "library plus custom templates" narrows to array
  and dict editing specifically.

### The honest case against my own recommendation

I may be underweighting the tedium. rjsf's array add/remove/reorder, `additionalProperties`
key/value editor, recursive nested-object handling, touched/dirty tracking, and error-to-field
plumbing are exactly the things that are boring to write, easy to get subtly wrong, and where a
15.9k-star library with 1.2 M weekly downloads has absorbed years of edge cases. If full
editability of arrays and dicts is a firm v1 requirement, Option A's scope estimate
(600–900 lines) is optimistic and Option B becomes the better trade.

And I went into this expecting the shadcn theme story to be the weak point. It is not.
`@rjsf/shadcn` is officially maintained, Tailwind v4 native, released in lockstep with core, and
**every single one of the 15 token utilities it emits already resolves in hassette's
`global.css`** — hassette's `--accent`/`--highlight-bg` aliasing decision happens to make it
work correctly. Integration effort is close to one `@source` line. That is a stronger position
than "adopt a library and fight the styling," which is the usual reason to hand-roll.

So the case rests almost entirely on bundle size. **If #1477 lands and the config route is
lazy-loaded, re-run this decision** — a 108 kB route-level chunk on an admin settings page that
users visit rarely is a much easier trade to accept than a 108 kB entry-chunk hit, and at that
point Option B's free array/dict editing may well win.

### Suggested next steps
1. Answer the arrays/dicts question — it is the actual decision, and everything else follows.
2. Design the backend `PATCH` contract and the masked-secret round-trip rule before any UI work
   (this is a correctness hazard, not a preference).
3. Write `normalizeSchema()` + tests first. It is required either way, it is small, and it makes
   the library-vs-hand-roll comparison concrete on real hassette schemas.
4. Vendor the missing shadcn form primitives (`input`, `label`, `select`, `checkbox`,
   `textarea`) — needed for Option A and useful regardless.
5. Extend `SchemaNode` in `config-view-types.ts` with `additionalProperties`, `prefixItems`,
   `oneOf`, `allOf`, `patternProperties`.

---

## Sources

**Primary — measured locally** (esbuild bundle + gzip -9; `renderToStaticMarkup` under
react@19.2.8; `pydantic.model_json_schema()` on representative and real hassette configs):
bundle deltas, per-field render results, the `__anyof_select` markup and its "option 1 /
option 2" labels, `prefixItems` rendering zero controls, JSONForms' 6-of-13 result,
`Generate.uiSchema` behavior, the uniforms ERESOLVE failure, the token-utility inventory, and
the `normalizeSchema()` mitigation.

- https://github.com/rjsf-team/react-jsonschema-form — repo (stars/commits via
  https://api.github.com/repos/rjsf-team/react-jsonschema-form)
- https://github.com/rjsf-team/react-jsonschema-form/tree/main/packages/shadcn — official shadcn theme
- https://www.npmjs.com/package/@rjsf/shadcn · https://registry.npmjs.org/@rjsf/shadcn
- https://www.npmjs.com/package/@rjsf/core · https://registry.npmjs.org/@rjsf/core
- https://rjsf-team.github.io/react-jsonschema-form/docs/ — rjsf docs
- https://github.com/eclipsesource/jsonforms · https://api.github.com/repos/eclipsesource/jsonforms
- https://jsonforms.io/docs/ · https://jsonforms.io/docs/uischema/
- https://registry.npmjs.org/@jsonforms/react · https://registry.npmjs.org/@jsonforms/core
- https://github.com/vazco/uniforms · https://api.github.com/repos/vazco/uniforms
- https://registry.npmjs.org/uniforms · https://registry.npmjs.org/uniforms-bridge-json-schema
- https://registry.npmjs.org/@sjsf/form · https://registry.npmjs.org/@sjsf/shadcn4-theme
- https://api.npmjs.org/downloads/point/last-week/ — weekly download counts
- https://github.com/rjsf-team/react-jsonschema-form/issues/4843 — nullable `anyOf` (open)
- https://github.com/rjsf-team/react-jsonschema-form/issues/4380 — pydantic 2.9.2 anyOf+null (open)
- https://github.com/rjsf-team/react-jsonschema-form/issues/4642 — shadcn error highlight (open)
- https://github.com/rjsf-team/react-jsonschema-form/issues/3199 — Tailwind support (open)
- https://github.com/pydantic/pydantic/issues/9057 · https://github.com/pydantic/pydantic/issues/7161
- https://rjsf-team.github.io/react-jsonschema-form/docs/migration-guides/v6.x%20upgrade%20guide
- https://jsonforms.io/api/core/functions/generatedefaultuischema · https://jsonforms.io/examples/gen-uischema
- https://jsonforms.io/docs/tutorial/custom-renderers
- https://registry.npmjs.org/@fragno-dev/jsonforms-shadcn-renderers
- https://registry.npmjs.org/@autoform/react · https://registry.npmjs.org/@autoform/shadcn
