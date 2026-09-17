# Research Brief: Track Home Assistant patch releases for codegen

---
proposal: "Determine whether Hassette should track every stable Home Assistant Core patch release for codegen rather than updating only on the monthly release cadence."
date: 2026-09-17
status: Draft
flexibility: Exploring
motivation: "Home Assistant patch releases may change the upstream source files that Hassette uses to generate typed state models and service wrappers, leaving the committed API stale between monthly updates."
constraints: "Use roughly Home Assistant 2024.10 through 2026.9; distinguish generated API/model changes from runtime-only source edits; treat any verified patch output change as evidence that patch-aware tracking deserves consideration; do not include Frontend, OS, Supervisor, beta, or development releases."
non-goals: "Assessing general runtime compatibility with Home Assistant patches, changing generated code, or implementing the selected tracking policy."
depth: deep
---

**Initiated by**: Investigate whether Hassette should react to every stable Home Assistant Core patch release or continue codegen updates on the monthly cadence.

## Executive answer

Home Assistant Core patch releases do change Hassette's generated output. The authoritative local Core clone contains 111 stable numeric tags in 24 monthly release lines from `2024.10.0` through `2026.9.0`. Those tags form 87 adjacent same-month patch edges. Four edges produced a codegen-visible change:

- `2025.3.3` made `number.set_value.value` required.
- `2025.4.2` renamed the generated light-service argument from `kelvin` to `color_temp_kelvin`.
- `2025.8.1` changed the generated `button.press` docstring.
- `2026.4.1` changed generated media-player service docstrings.

The first two affect callable signatures or request fields. This rules out the premise that patch releases are irrelevant to codegen.

Updating the pin for all 87 patch edges in this window would still be wasteful. Most patches changed only `PATCH_VERSION`, runtime logic, or translation sections the generator does not read. The best fit is a hybrid policy: keep the monthly update as the normal full review, but automatically run codegen against each newly published stable patch and escalate only when `--check` finds output or guard drift. When a patch changes generated output, update the pin and generated files immediately.

Confidence is high that patch-aware detection is warranted. Confidence is medium-high that hybrid tracking is better than pinning every patch, because the observed signal was sparse: four output-changing edges among 87 adjacent patch edges (4.6%), and only two changed the callable API (2.3%).

## Context

### What prompted this

Hassette pins Home Assistant Core source for code generation, but its maintenance process is monthly. The question is whether stable patches can alter the source metadata that drives generated types and service methods before the next monthly update.

The evidence says yes. Patch releases are not limited to runtime fixes. Home Assistant has used them to correct action schemas and descriptions, including a required field and a renamed light-action field.

### Current state

The generator is a standalone Python package under `codegen/`. It does not call a running Home Assistant instance and does not import the `homeassistant` Python package. `hassette-codegen generate` receives either a local Core checkout or a release tag. For a tag, `codegen/src/hassette_codegen/ha_source.py` shallow-clones `https://github.com/home-assistant/core.git` at that tag.

The pipeline reads these upstream files:

| Input | Data consumed | Generated effect |
|---|---|---|
| `homeassistant/components/<domain>/__init__.py` | Domain discovery marker, entity properties, base-class clues, service registrations | State attributes, wrapper methods, response behavior |
| `homeassistant/components/<domain>/const.py` | `*EntityFeature` flags and `StrEnum` members | Feature enums and domain constants |
| `homeassistant/components/<domain>/services.yaml` | Service names, fields, `required`, selectors, response metadata | Async and sync service method signatures and request fields |
| `homeassistant/components/<domain>/strings.json` | Descriptions under the `services` tree | Generated method and parameter docstrings |
| `homeassistant/components/sensor/const.py` | Sensor device classes, state classes, and nonnumeric classes | Sensor model enums and constant literals |
| `homeassistant/components/sensor/__init__.py` | `_numeric_state_expected` source | Drift guard for Hassette's hand-maintained predicate port |
| `homeassistant/const.py` | `UnitOf*` enum values and Core version | Unit literals and version diagnostics |

The generator does not consume integration `manifest.json` files. It also does not consume arbitrary translation sections in `strings.json`; `_extract_descriptions()` reads only the `services` object. This distinction explains why several upstream patch edits looked relevant by filename but could not affect output.

Local generator inputs also include the TOML overrides, templates, selector mapping, and ownership manifest under `codegen/`. The outputs are:

- `src/hassette/models/states/<domain>.py`
- `src/hassette/models/entities/<domain>.py`
- state/entity package exports
- `src/hassette/const/sensor.py`
- `.generated-manifest`

The current pipeline reports 34 generated domains, four of which are manually discovered through overrides. Sync-facade generation is separate and does not read Home Assistant source.

Automation currently checks two different concerns:

- `.github/workflows/lint.yml` clones the exact `codegen/ha-version.txt` tag and verifies that committed output matches it.
- `.github/workflows/ha-version-drift.yml` runs daily, queries `repos/home-assistant/core/releases/latest`, and opens an issue whenever the latest version differs from the pin. It compares version strings, not generated output.

The current codegen pin is `2026.9.0`. The Docker/system-test environment still says `HA_VERSION=2026.8`; that mismatch is outside this investigation, but a future design should avoid assuming the two pins always move together.

### Home Assistant's stable release model

Home Assistant documents a monthly Core release on the first Wednesday of the month. A beta starts about a week earlier. Stable patch releases follow as needed rather than on a guaranteed weekly schedule. The precise policy under consideration is therefore "track every stable patch," not "track weekly."

Git tags and GitHub releases provide immutable patch snapshots such as `2025.3.3`. GitHub's `releases/latest` endpoint is already the project's source for the newest stable release. The generator itself needs only the tag and the Core Git repository.

### Key constraints

- A filename change is not enough. The changed syntax must be consumed by an extractor and alter output or a codegen drift guard.
- Runtime changes inside entity methods are out of scope unless they change extracted declarations.
- Description-only output changes count, but they are less urgent than signature or wire-key changes.
- Historical full-generation checks are not uniformly executable with today's generator and formatter. The `2025.4.x` light source, for example, generates code that current Ruff rejects for an unrelated unresolved `Final` annotation. Source-level extractor tracing is required for older tags.

## Empirical findings

### Method

The authoritative source was the clean local Home Assistant Core clone at `/home/jessica/source/core`; no remote tag listing or GitHub API result was used to establish the study window. Local refs were filtered with the exact stable-tag shape `^YYYY.M.P$`, where all three components are numeric. Beta, dev, and other prerelease tags were excluded. The resulting inventory is:

| Period | Stable tags | Adjacent same-month patch edges |
|---|---:|---:|
| 2024.10-2024.12 | 15 | 12 |
| 2025.1-2025.12 | 58 | 46 |
| 2026.1-2026.9 | 38 | 29 |
| **Total** | **111** | **87** |

The first local tag in scope is `2024.10.0` (2024-10-02); the last is `2026.9.0` (2026-09-02). Tags were grouped by `YYYY.M`, and every adjacent pair inside each group was treated as one patch edge. There is no 2026.9 patch edge in the local clone because that line contains only `.0`.

For all 87 edges, the scan covered the exact upstream file classes consumed by `ha_source.py` and the extractors: `homeassistant/const.py`; generated-domain `__init__.py`, `const.py`, `services.yaml`, and `strings.json`; and the base `homeassistant` strings used by description references. The 34 domains generated at the local head were diffed pairwise. A full-history discovery-marker scan found one additional historical generated domain, `tts`, and no other domain-set transition in the window. `tts` had only two patch-range source edits (`2025.8.0` -> `2025.8.1` and `2026.6.0` -> `2026.6.1`); both were pairwise diffed and were runtime-only. This gives a 35-domain union for the historical source scan, including manual-override domains.

Every non-version-only candidate was classified against the actual extractor behavior, not by filename alone. In particular, only the `services` tree of `strings.json` affects generated output; selector `reorder`, device-automation translations, ordinary integration titles, and runtime methods are not consumed. Positive candidates were followed through `extractors/services.py` into `generators/entities.py`, where requiredness changes alter parameter annotations/defaults and description changes alter generated docstrings.

This is a complete local tag inventory and consumed-source semantic scan, not an 87-edge generated-output archive. Today's generator cannot render every historical tag cleanly: at least the 2025.4 line fails the current Ruff gate with `F821 Undefined name 'Final'`. The count of positive edges therefore comes from pairwise local source semantics and exact extractor/template tracing. No remote-only release is included.

The core audit can be reproduced without checking out or modifying the Core worktree:

```bash
# Inventory local tag refs, dates, and objects; retain only exact numeric YYYY.M.P names.
git -C /home/jessica/source/core for-each-ref \
  --sort=version:refname \
  --format='%(refname:strip=2) %(creatordate:short) %(objectname)' \
  refs/tags | \
  grep -E '^(2024\.(10|11|12)|2025\.([1-9]|1[0-2])|2026\.([1-9]))\.[0-9]+ '

# For each adjacent pair OLD -> NEW in one YYYY.M line, inspect consumed candidates.
git -C /home/jessica/source/core diff --name-status OLD NEW -- \
  homeassistant/const.py \
  homeassistant/components/{alarm_control_panel,automation,binary_sensor,button,camera,climate,cover,date,datetime,event,fan,geo_location,humidifier,image,lawn_mower,light,lock,media_player,number,remote,script,select,sensor,siren,sun,switch,text,time,timer,todo,tts,update,vacuum,water_heater,weather}/{__init__.py,const.py,services.yaml,strings.json}

# Verify historical changes to automatic domain discovery.
git -C /home/jessica/source/core log --oneline --name-only \
  -G'CACHED_PROPERTIES_WITH_ATTR_' 2024.10.0..2026.9.0 -- \
  ':(glob)homeassistant/components/*/__init__.py'

# Attribute a candidate to its source commit, then inspect its exact semantic delta.
git -C /home/jessica/source/core log --oneline OLD..NEW -- PATH
git -C /home/jessica/source/core show COMMIT -- PATH
```

### Patch releases that changed generated output

| Patch edge | Upstream change | Hassette effect | Impact |
|---|---|---|---|
| `2025.3.2` -> `2025.3.3` | `number/services.yaml` adds `required: true` to `set_value.value` | Generated async and sync wrappers change `value: float | None = None` to required `value: float` | Callable API correctness |
| `2025.4.1` -> `2025.4.2` | Light action schema renames `kelvin` to `color_temp_kelvin` in `services.yaml` and `strings.json` | Generated argument and emitted service-data key change to `color_temp_kelvin` | Callable API and wire-key correctness |
| `2025.8.0` -> `2025.8.1` | `button/strings.json` corrects the `button.press` action description | Generated async and sync docstrings change | Documentation only |
| `2026.4.0` -> `2026.4.1` | `media_player/strings.json` makes action naming consistent | Generated media-player method docstrings change | Documentation only |

Local tag and source provenance:

| Released edge | Local tag date | Release-tag commit | Source change commit |
|---|---|---|---|
| `2025.3.2` -> `2025.3.3` | 2025-03-17 | `4d1c89f0d1f` | `7607b7d494f2e7436b0bd618ff2884fdd869e2b9` |
| `2025.4.1` -> `2025.4.2` | 2025-04-11 | `f7794ea6b51` | `d59200a9f59bcb6a58664855ad5d99b3e17537d4` |
| `2025.8.0` -> `2025.8.1` | 2025-08-11 | `dc8aaac6fb4` | `7951e822be81c4ef939ee78117275b4a9c8e78cd` |
| `2026.4.0` -> `2026.4.1` | 2026-04-15 | `b981ece1637` | `6bb91422ffb6a851df90f4fc18bb0dddd782bc23` |

All four conclusions are supported by local tag-to-tag source diffs and direct extractor/template tracing. For `2025.3.3`, the YAML requiredness feeds `ServiceField.required`, and `generators/entities.py` uses that flag to add or omit `None` and to order required parameters. For `2025.4.2`, `extract_services()` uses the renamed YAML key as `ServiceField.name`, and the entity template uses that name for both the method parameter and payload key. For `2025.8.1` and `2026.4.1`, service descriptions flow into `build_method_docstring()`. A clean end-to-end historical render is not available for every edge because current formatting checks reject some old-source output.

No patch edge in the local window changed a generated constant or enum, an extracted class-level property or supported-feature value, a selector-derived type beyond the two signature cases above, the generated-domain set, or the numeric-state predicate drift guard. The two patch-range edits in the historical-only generated domain (`tts`) were runtime code.

### Relevant-looking changes that did not affect output

Several cases show why version-only patch tracking would be noisy:

| Patch line | Source edit | Why output is unchanged |
|---|---|---|
| `2024.12.x` | Added more power units to `DEVICE_CLASS_UNITS` in sensor and number constants | Hassette reads `UnitOf*` members from global `homeassistant/const.py`, not `DEVICE_CLASS_UNITS` mappings |
| `2025.1.x` | Reverted supported-feature warning changes in light, camera, cover, media player, and vacuum entity code | The edits change runtime compatibility behavior, not extracted annotations or enum declarations |
| `2025.3.x` | Added milliwatt to sensor/number allowed-unit mappings | Same ignored mapping as the 2024.12 case; the patch still mattered independently because of `number/services.yaml` |
| `2025.5.x` | Added lock device-condition translations | The generator reads service descriptions only, not device-condition strings |
| `2025.8.x` | Changed vacuum battery deprecation behavior and non-streaming TTS handling | Both edits are runtime implementation; the historical `tts` domain edit does not change extracted class-level entity metadata |
| `2025.9.x` | Added device-trigger localizations and fixed suggested-unit validation | Neither the device-trigger string tree nor `_is_valid_suggested_unit` is an input to generated output |
| `2026.3.x` | Added `reorder: true` to an area selector in `vacuum/services.yaml` | Hassette's selector type mapping does not consume `reorder`; the signature stays the same |
| `2026.4.x` | Fixed update WebSocket release-note behavior | Runtime implementation only |
| `2026.6.x` | Added and reverted query-token auth changes in camera, image, and media player; added TTS result-stream cleanup methods | Runtime implementation; the query-token change was reverted within the release line, and the TTS methods do not change extracted metadata |

Most other release lines touched only `PATCH_VERSION` among consumed paths. Patch-number changes are read for diagnostics but are not rendered into generated source.

## Feasibility analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|---|---:|---|---|
| Scheduled drift workflow | 1 workflow, primarily `.github/workflows/ha-version-drift.yml` | Medium | The existing five-minute timeout and sparse checkout are too small for environment setup, a shallow Core clone, and full codegen |
| Drift classification/dedup | Existing workflow logic or one small release helper | Low-Medium | Must distinguish a new monthly line from a patch of the pinned monthly line and avoid daily duplicate comments |
| Tests | Likely `tests/integration/test_drift_check.py` plus workflow-oriented fixtures or helper tests | Medium | Shell-only branching is harder to test than extending the existing Python helper |
| Monthly bump procedure | `.claude/skills/ha-version-bump/SKILL.md` or related process documentation | Low | The policy must state when a patch drift becomes an immediate bump rather than waiting for next month |

No generator feature is required. `--ha-release-tag` already performs the shallow clone, and `--check` already exits nonzero when generated files, ownership, or the numeric-state predicate guard drift.

### What already supports this

- The generator accepts arbitrary release tags and leaves the worktree untouched in `--check` mode.
- The pipeline has one exit status for generated drift, skipped domains, ownership rejection, and numeric-predicate drift.
- The repository already queries GitHub's latest stable release daily and has issue dedup/close behavior.
- CI already contains the exact-pin freshness job, so patch detection can reuse its setup rather than introduce another comparison implementation.
- `hassette-codegen` has only Jinja2 and PyYAML as runtime dependencies; Ruff is the existing formatting/check dependency.

### What works against this

- The existing scheduled workflow checks out only two files. Running codegen requires the generator package, generated targets, manifest, snapshots, and local templates/overrides.
- A historical tag may fail for reasons other than meaningful drift, as the old `Final` annotation/Ruff failure demonstrates. In current operation this risk is much lower because the compared patch is adjacent to the current monthly pin, but the workflow must report "generation failed" separately from "output changed."
- The current workflow comments daily on an existing issue. That behavior would be excessive for a stable, unchanged patch result and should be keyed to a newly observed tag or changed finding.
- New monthly releases should continue through the full monthly review. A codegen-drift result alone does not replace review of new domains and removals.

## Options evaluated

### Option A: Hybrid, output-aware patch tracking

**How it works**: Keep the monthly pin and full regeneration process. When GitHub reports a newer release in the same `YYYY.M` line, run:

```text
uv run --project codegen hassette-codegen generate \
  --ha-release-tag "$LATEST" --check
```

If the check is clean, record or cache that tag and do nothing else. If generated output or a guard drifts, open or update one issue with the tag and captured diff, then perform an immediate patch bump. If generation itself fails, file a distinct actionable failure rather than calling it output drift. If `LATEST` starts a new monthly line, retain the current monthly-bump notification and review path.

**Pros**:

- Catches the two signature-level patch changes found in this survey.
- Avoids pin-only PRs for the large majority of patches that do not affect generated code.
- Reuses the generator as the semantic filter, so the workflow does not need to duplicate extractor knowledge.
- Preserves the existing monthly review for larger changes.

**Cons**:

- Scheduled CI becomes heavier than the current API-only check.
- The workflow must distinguish output drift, guard drift, and generator failure.
- Leaving the pin at `.0` after a clean patch means the file records the generation baseline, not "latest Core tested." The workflow needs another durable tag marker, cache key, or issue state if repeated checks are undesirable.

**Effort estimate**: Medium. The generator already has the required mode; most work is reliable workflow state, failure reporting, and tests.

**Dependencies**: No new project library. GitHub Actions needs the repository's existing Python/uv/Ruff setup and network access to GitHub Core.

### Option B: Pin and regenerate for every stable patch

**How it works**: Treat every stable GitHub Core release as a required pin update. Regenerate all outputs and open a PR even when only `PATCH_VERSION` changed upstream and the generated tree is identical.

**Pros**:

- `codegen/ha-version.txt` always states the latest stable tag tested.
- The process is simple to explain and does not need a separate "last checked" concept.
- Generator failures surface immediately.

**Cons**:

- The observed yield is low: four output-changing edges among 87 adjacent patch edges, with only two callable-API changes.
- Most patch PRs would contain only a pin change, creating review and release noise without changing Hassette behavior.
- Home Assistant does not guarantee a weekly patch rhythm, so maintenance load can cluster after monthly releases.

**Effort estimate**: Medium initial automation, then higher ongoing PR/review volume.

**Dependencies**: Same as Option A, plus automated branch/PR creation if the work should not remain manual.

### Option C: Keep monthly-only tracking

**How it works**: Continue notifying on version mismatch but defer all regeneration to the next monthly cycle.

**Pros**:

- No workflow or process changes.
- One predictable review per month.

**Cons**:

- Hassette can expose a stale generated signature or payload key for weeks. `2025.3.3` and `2025.4.2` prove this is not hypothetical.
- The current version-only issue cannot tell a harmless patch from one that changes generated output.

**Effort estimate**: Small.

**Dependencies**: None.

## Concerns

### Technical risks

- A full codegen check against an adjacent patch is authoritative only for concerns represented in the generator. It does not prove runtime compatibility with that Home Assistant patch.
- A nonzero `--check` exit covers several conditions. The workflow should retain the command output so a maintainer can tell ordinary generated diff from extractor/formatter failure.
- `releases/latest` is appropriate for stable-only tracking, but month-boundary logic matters. Comparing a new `.0` release as though it were a patch would collapse the monthly review into the lighter patch path.

### Complexity risks

- Adding a second pin solely to record "latest patch checked" would create synchronization state. Prefer a GitHub Actions cache/artifact, issue metadata, or idempotent issue search unless a committed audit marker is an explicit requirement.
- Reimplementing a list of watched upstream paths in the workflow would drift from the extractors. Run codegen itself instead.

### Maintenance risks

- Home Assistant may change its source layout or required Python version in a patch. This should be treated as an actionable generator failure, not silently ignored.
- Description-only changes may produce issues that feel noisy. They still represent committed generated drift, but issue labels or severity text can distinguish docs-only output from signature/model changes.

## Open questions

- [ ] Should a clean patch check be recorded durably in the repository, or is GitHub Actions history/cache sufficient? Code does not state an auditability requirement.
- [ ] Should description-only generated drift trigger an immediate patch bump, or may it wait for the monthly update? The stated threshold counts any output change, but urgency policy was not found in code or docs.
- [ ] Should the current Docker/system-test `HA_VERSION` pin move when codegen takes an urgent patch bump? The repository currently allows these versions to differ, and this investigation did not find a documented coupling rule.

## Recommendation

Adopt Option A. Stable patch releases have crossed the codegen boundary in ways that matter to callers, so monthly-only detection is too weak. Pinning every patch is the wrong response to sparse signal. It creates work even when the extractor's semantic output is unchanged.

The scheduled job should classify releases before acting:

1. Fetch the latest stable Core tag.
2. If it is a new monthly line, retain the existing monthly drift issue and full review procedure.
3. If it is a newer patch in the pinned monthly line, run full codegen `--check` against that tag.
4. On a clean result, remain silent after recording the checked tag outside the codegen pin.
5. On generated or guard drift, open one issue with the diff and bump promptly.
6. On command failure, open one distinct issue containing the failure output.

This recommendation is grounded in direct source and generator evidence. The exact workflow state mechanism remains a design choice; the codebase does not reveal whether durable in-repository audit history is valuable enough to justify another committed marker.

### Suggested next steps

1. Write a small design for the three workflow outcomes: monthly release, clean same-month patch, and patch drift/failure.
2. Add characterization tests around release classification and issue dedup before editing the workflow.
3. Prototype the scheduled command with three local fixtures: `2026.8.0` -> `2026.8.1` for a no-drift path, `2025.3.2` -> `2025.3.3` for signature drift, and `2026.4.0` -> `2026.4.1` for documentation-only drift.

## Sources

- Home Assistant release schedule FAQ: https://www.home-assistant.io/faq/release/
- Home Assistant Core latest stable release API used by Hassette: https://api.github.com/repos/home-assistant/core/releases/latest
- `2025.3.3` release: https://github.com/home-assistant/core/releases/tag/2025.3.3
- `2025.3.2...2025.3.3` comparison: https://github.com/home-assistant/core/compare/2025.3.2...2025.3.3
- Required-number-field commit: https://github.com/home-assistant/core/commit/7607b7d494f2e7436b0bd618ff2884fdd869e2b9
- `2025.4.2` release: https://github.com/home-assistant/core/releases/tag/2025.4.2
- `2025.4.1...2025.4.2` comparison: https://github.com/home-assistant/core/compare/2025.4.1...2025.4.2
- Light Kelvin-field commit: https://github.com/home-assistant/core/commit/d59200a9f59bcb6a58664855ad5d99b3e17537d4
- `2025.8.1` release: https://github.com/home-assistant/core/releases/tag/2025.8.1
- Button-description commit: https://github.com/home-assistant/core/commit/7951e822be81c4ef939ee78117275b4a9c8e78cd
- `2026.4.1` release: https://github.com/home-assistant/core/releases/tag/2026.4.1
- Media-player-description commit: https://github.com/home-assistant/core/commit/6bb91422ffb6a851df90f4fc18bb0dddd782bc23
