# Design: Type the wire vocabulary fields

**Date:** 2026-10-04
**Status:** built
**Mode:** sketch

## Summary

Part of issue #2448. Response fields that carry a server-defined vocabulary but are typed `str` get a real type before #2386 pins the wire contract:
- `JobSummary.schedule_status` and `schedule_status_reason` (`wire/src/hassette_wire/telemetry.py`)
- `ServiceInfoResponse.role` (`health.py`) and `ServiceStatusData.role` (`ws.py`)
- `ActionResponse.action` (`apps.py`)
- the `AppManifestListResponse.status_counts` keys (`apps.py`)
- `LogLevelResponse.effective_level` (`logs.py`); `LogLevelRequest.level` stays `str` (D6)

The vocabularies move into `hassette_wire` (D3), and a parity check ties them to the SQL CHECK constraints. Class names stay as they are today; spec 126 applies the naming rule last.

The generated artifacts are regenerated with `uv run python scripts/export_schemas.py --types` (writes `frontend/openapi.json`, `frontend/ws-schema.json` and the generated TS under `frontend/src/api/`), and frontend code naming a changed schema is updated to match.

**Calibration:** hassette is greenfield with about three known users, and no consumer is known to depend on these models, the HTTP shapes, or the CLI JSON. Decisions optimize for the correct model, not for minimizing breakage. Breaks are still listed in this ledger's D9 footer.

**Origin:** split from spec 122 (`design/specs/122-wire-contract-tightening/design.md`), where every decision below was ratified, challenged and combed together. Decision numbers keep their spec-122 ids. Order of the four ledgers: 123 (vocabulary) and 124 (health) are independent; 125 (apps resource and grid) builds on 124; 126 (naming and docs) goes last. All four land before #2386.

Out of scope: renames (spec 126), the app resource and grid (spec 125), health (spec 124), any change to which values a vocabulary holds.

## Decisions

### D3: Where do the new vocabularies for (a) live?

**Deciding factor:** one definition per vocabulary. `hassette-wire` exists so the server and its consumers share one definition, and the existing precedent agrees: `ResourceStatus`/`ManifestStatus` live in `wire/src/hassette_wire/enums.py` and the server imports them.

The vocabularies: `ResourceRole` (`src/hassette/types/enums.py`), `ScheduleStatus` and `ScheduleStatusReason` (`src/hassette/scheduler/classes.py`), and `AppAction` (a `Literal` in `src/hassette/web/routes/apps.py`).

| | A: Move each existing `StrEnum` into `wire/src/hassette_wire/enums.py`, move `AppAction` into `literals.py`; old homes re-import (same public name from `hassette`); add an `Open<TypeName>` alias for each | B: Leave the server enums where they are; add mirror `Literal`s plus `Open*` aliases in `literals.py`, and a hassette-side test that each `Literal`'s values equal its enum's |
|---|---|---|
| Definitions per vocabulary | 1 | 2, kept in step by a test |
| `hassette` public API | `hassette.types.enums.ResourceRole` and `hassette.scheduler.classes.ScheduleStatus` keep resolving (re-export) | Unchanged |
| Spec 121 compliance ("no `Literal`→`StrEnum` conversion") | Yes. Existing enums move; no `Literal` is converted | Yes |
| Schema shape | Field becomes a `$ref` to a named enum component (`ResourceRole`, ...) | Inline `enum` on the field |
| Lets the CLI drop its hand-synced action copy (`src/hassette/cli/commands/app.py:28-33`) | Yes, `AppAction` becomes importable without the route layer | No |

At the move, class and member docstrings are rewritten for a contract consumer (final here; spec 126 does not revisit them), with no references to `Job`, `Scheduler.register()`, the heap, or `Resource` inheritance. Scheduler-internal detail that app authors need moves to `docs/pages/core-concepts/scheduler/management.md`. Internal-only members (`ResourceRole.CORE`, `ResourceRole.BASE`, `ScheduleStatusReason.LEGACY_UNKNOWN`) get text that tells a consumer what the value means when received. `ResourceRole` uses `auto()`, and its member values must not change across the move.

**Parity with the SQL CHECK constraints.** Once these fields are typed, server-side parsing is strict, so a single row outside the vocabulary fails the whole response. Each SQL CHECK constraint's value list (from the migration that currently defines it under `src/hassette/migrations_sql/`) must equal the values of its wire enum or `Literal`. The columns covered are `schedule_status` and `schedule_status_reason` (`ScheduleStatus`/`ScheduleStatusReason`), plus the existing `status`, `mode` and `source_tier` checks. The CHECK-parity question in `wire/src/hassette_wire/REVIEW.md` gains the two schedule columns and points to that check.

**Recommendation:** A, because it removes the second definition instead of guarding it.
**Pick B instead if** you consider `ScheduleStatus`/`ResourceRole` server-domain types that shouldn't be published as wire vocabulary.
**Reversibility:** easy (moving a type back behind a re-export is mechanical).
**Ratified:** Chose moving the vocabularies into wire (A) over mirrored Literals (B), to keep one definition per vocabulary, accepting consumer-facing docstring rewrites at the move and a CHECK-parity test across all five constrained columns (re-ratified after challenge Findings 10 and 11).

### D4: What does `ServiceInfoResponse.role` hold when no role is known?

**Deciding factor:** narrow the type without inventing a sentinel. Today the field defaults to `""` ("Empty string when not available"). Every construction site passes `child.role.value` (`src/hassette/core/runtime_query_service.py:329-335`), and every `Resource` has a role, so `""` is never actually emitted. `ResourceRole` already has an `UNKNOWN` member.

| | A: `role: OpenResourceRole` (required, no default) | B: `role: OpenResourceRole \| None = None` | C: keep `= ""` by widening the type to allow `""` |
|---|---|---|---|
| Matches what the server emits | Yes | Yes (`None` never emitted) | Yes |
| Wire compat (old client, new server) | A required field that was optional: oasdiff flags it in the reversed direction | Nothing new required; `""` → `null` is a type change only for a value never sent | None |
| Type honesty | Exact | Admits a state that can't happen | Keeps a fake sentinel in the vocabulary |

`ServiceStatusData.role` is already required (`ws.py`), and only its type narrows. Server-side construction without `LENIENT_CONTEXT` rejects an out-of-vocabulary `role`, and the same holds for `schedule_status`.

**Recommendation:** A, because the server always has a role, and `ResourceRole.UNKNOWN` already covers "unclassified". The compat finding is recorded in `tools/wire_compat_ignore.txt`.
**Pick B instead if** you want zero compat-ignore entries from this item.
**Reversibility:** easy before #2386.
**Ratified:** Chose required `OpenResourceRole` (A) over optional (B) and the `""` sentinel (C), to type the field exactly as the server emits it, accepting a compat-ignore entry for optional→required.

### D5: How is `status_counts` typed?

The field lives on `AppManifestListResponse` (spec 125 renames it `AppListResponse`).

**Deciding factor:** typed keys without a new model. The server always fills every `ManifestStatus` key with a count, zero included (`MANIFEST_STATUS_KEYS` in `src/hassette/schemas/app_snapshots.py:13,101`).

| | A: `dict[OpenManifestStatus, int]` (spec 125's D16 later renames it `OpenAppStatus`) | B: a `ManifestStatusCounts` model with one `int = 0` field per status | C: keep `dict[str, int]` and document the keys |
|---|---|---|---|
| Schema | `propertyNames: $ref` to the status enum component (verified with pydantic 2.12) | Named object, one property per status | Untyped keys |
| New status from a newer server | Lenient: the key parses as `UnknownValue` (verified) | Ignored extra field, so the count is silently dropped | Passes as a string |
| Generated TS | `{ [key: string]: number }` (openapi-typescript ignores `propertyNames`; key typing is Python-only) | Fixed interface | `{ [key: string]: number }` |
| New public names | None | One | None |

A `status_counts` holding an unknown key parses leniently and round-trips unchanged through `model_dump(mode="json")`.

**Recommendation:** A, because it types the keys through the existing open alias and keeps unknown statuses visible.
**Pick B instead if** you want the generated TS to guarantee every key is present. **Pick C instead if** you consider the keys display-only.
**Reversibility:** easy before #2386.
**Ratified:** Chose `dict[OpenManifestStatus, int]` (A) over a counts model (B) and untyped keys (C), to type the keys with no new public name, accepting that key typing is Python-only because generated TS ignores `propertyNames` (re-ratified after challenge Finding 13).

### D6: Does `LogLevelRequest.level` narrow to `LogLevel` too?

**Deciding factor:** request validation in the schema versus today's lenient input. Today `level: str` accepts any case and the route upper-cases it, then rejects unknown names with a `VALIDATION_FAILED` problem (`src/hassette/web/routes/logs.py:96-102`). `LogLevelResponse.effective_level` narrows to the closed `LogLevel` regardless: the route sets the target logger to a validated name, so its effective level is always one of the five (`src/hassette/web/dependencies.py:20-27`).

| | A: Keep `level: str`; document the accepted names, case-insensitive, in the field description | B: `level: LogLevel` (strict, uppercase only) |
|---|---|---|
| Behavior change for callers | None | `"debug"` starts failing with a 422 |
| Schema tells a client the valid values | Description only | Yes, as an `enum` |
| Error path | One route-level check (current) | Pydantic 422, and the route check becomes dead code |

**Recommendation:** A, because a request field accepting more than the response emits is fine, and B breaks lowercase callers for no contract gain.
**Pick B instead if** you want the request vocabulary machine-readable and accept case-sensitive input.
**Reversibility:** easy.
**Ratified:** Chose keeping `level: str` with documented case-insensitive values (A) over strict `LogLevel` (B), to avoid breaking lowercase callers, accepting that the schema lists the values only in prose.

### D9: Is the PR a breaking change (`feat!` with a `BREAKING CHANGE:` footer)?

**Deciding factor:** the changelog tells users what actually breaks. Spec 122's D9 ratified `feat!` with one `BREAKING CHANGE:` footer naming every break; this ledger's list is its share:
- `ServiceInfoResponse.role` becomes required and typed (D4)
- The (a) fields listed in the Summary become enums in the OpenAPI/WS schemas, where they were free strings (D3, D5, D6). The frontend's generated WS validator rejects unknown `role` values
- `ResourceRole`, `ScheduleStatus`, `ScheduleStatusReason` and `AppAction` are published wire names; `hassette` keeps re-exporting them from their old homes (D3)
- `JobSummary.schedule_status` becomes required, losing its `"scheduled"` default (added during the build; see Build)

Any compat-ignore lines come from `tools/check_wire_compat.py`'s output, and the header of `tools/wire_compat_ignore.txt` pairs them with `!` plus a footer.

**Recommendation:** `feat!` with exactly one `BREAKING CHANGE:` footer at the end of the PR body, naming every item above.
**Reversibility:** easy until merge.
**Ratified:** Chose `feat!` with one footer over `refactor:`, because D4 makes a field required.

## Assumed

- **Package isolation.** `hassette_wire` cannot import `hassette`, so any vocabulary shared with the server must be defined in wire. Evidence: `wire/src/hassette_wire/REVIEW.md` ("Package Isolation"); `wire/pyproject.toml` depends on `pydantic` only.
- **Open/closed vocabularies.**
  - Response fields typed with an enum or multi-value `Literal` use an `Open<TypeName>` alias (`Annotated[X | UnknownValue, LenientValue("X")]`). `SourceTier` and `LogLevel` are closed and stay strict.
  - Every new vocabulary in this change is open: `ResourceRole`, `ScheduleStatus`, `ScheduleStatusReason`, `AppAction`, and the `ManifestStatus` keys.
  - "Open" means a Python client parsing with `LENIENT_CONTEXT` tolerates unknown values. `openapi.json` and `ws-schema.json` describe what the server emits, so consumers generated from them (the frontend's TS types and `ws-validator.generated.ts`) see closed enums, as spec 121 intends.
  - Narrowing WS `ServiceStatusData.role` therefore tightens the frontend's WS validator. WS has no compat check (the `hassette_wire/__init__.py` docstring).

  Evidence: `design/specs/121-wire-lenient-unknown-enums/design.md` (D5, D14); spec 116 addendum 2026-10-03.
- **`effective_level` is always a `LogLevel`.** The route only sets `VALID_LOG_LEVEL_NAMES` (the five `LOG_LEVELS` keys) on the target logger. Evidence: `src/hassette/web/routes/logs.py:96-112`, `src/hassette/web/dependencies.py:20-27`.
- **Role values.** `ServiceStatusData.role` comes from `ServiceStatusPayload.role: ResourceRole`. Evidence: `src/hassette/events/hassette.py:35`.
- **Request side stays strict.** Only response fields get `Open*` aliases. Evidence: spec 121.
- **No released consumer imports `hassette_wire` names.** Evidence: v0.55.0 wire `__init__.py` is a stub; models moved in by #2449 after that tag. `client/src` does not import `hassette_wire` yet.
- **Generated TS.** `frontend/src/api/generated-types.ts`, `ws-types.ts` and `ws-validator.generated.ts` are regenerated, not hand-edited. Evidence: `scripts/export_schemas.py` docstring.
- **Required checks.** `tools/check_wire_compat.py` runs against the latest `v*` tag (v0.55.0) in both directions, and deliberate breaks go in `tools/wire_compat_ignore.txt` verbatim from its output. Evidence: the module docstring and the file header.
- **Tests encoding the old behavior.** `tests/integration/telemetry/test_global_jobs_and_service_info.py` asserts `role == ""` and builds `role="Service"`, which is not a `ResourceRole` value (`auto()` values are lowercase); `tests/unit/test_model_types.py` builds `ServiceInfoResponse` without `role`. Evidence: those files; `src/hassette/types/enums.py:176-195`.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**
- CHECK parity covers every IN-list CHECK in the migrated schema, not only the five columns D3 names: `listeners.backpressure`, `executions.kind` and `blocking_events.tier` also equal a wire vocabulary, and `tests/unit/core/test_wire_check_parity.py` fails on any new IN-list CHECK until it is classified as a wire match or server-only (`blocking_events.reason` is server-only: it also holds `attributed`, which `UnattributedReason` excludes). Same cost, and drift in a constrained column that nobody listed is exactly what the check exists to catch.
- The CHECK-sync notes on `ScheduleStatus`/`ScheduleStatusReason` are source comments, not docstrings: enum class docstrings are emitted into `openapi.json`, and `REVIEW.md` bars server table names there.
- `PUT /api/logs/level` still reads the level back with `logging.getLevelName(target_logger.getEffectiveLevel())`, so `effective_level` reports the logger's real state rather than echoing the request. The name is narrowed to `LogLevel` by `is_log_level` (`src/hassette/web/dependencies.py`), and a non-standard name raises instead of being emitted unchecked.
- Server-side `status_counts` (`AppFullSnapshot`, `tally_manifest_statuses`) is typed `dict[ManifestStatus, int]`; `app_manifest_list_response_from` copies it through `.items()` so the key type widens to `OpenManifestStatus` (dict keys are invariant).
- `JobSummary.schedule_status` drops its `"scheduled"` default and becomes required, applying D4's reasoning (no invented default for a field the server always sends) to it as well: the column is NOT NULL and the server always sends the field, so a missing value must fail rather than read as "will run again". It is listed in D9's breaks for the `BREAKING CHANGE:` footer, with its compat-ignore entries.
- `JobSummary.schedule_status`/`schedule_status_reason` docstrings drop their hand-listed values, which the enums now document. Other field docstrings are left for spec 126.
- Version-skew policy for the in-package clients. One policy per client, because each place that handles an unknown value (the WS validator, the display fallbacks, CLI parsing) otherwise implies its own answer:
  - **SPA: skew is unsupported, and enforced.** A tab left open across a server upgrade used to keep running the old bundle indefinitely: the WS reconnects without reloading, and nothing compared versions. Now the build bakes the project version into the bundle (`BUNDLE_VERSION` in `frontend/src/state/store.ts`, from `frontend/hassette-version.ts`), and `handleWsConnected` sets `serverUpdated` when any connect, the first included, reports a `connected.version` other than it. Anchoring to the bundle rather than to the first version the tab saw covers a tab whose first connect already reaches an upgraded server. `useServerUpdatePrompt` then shows a persistent reload prompt. It prompts rather than reloading, so nothing in progress is lost. A tab whose socket stays down gets no prompt until it connects. The closed generated types are therefore the contract:
    - The WS validator rejecting an unknown `role` is pinned in `ws-validator.test.ts`.
    - The schedule-status display and sort maps are total `Record<ScheduleStatus, ...>`, so a new status fails to compile until it has an entry. Their lookups stay defensive (`?.`, `??`), because REST data isn't runtime-validated and a stale tab can receive a newer server's status in the window before the prompt appears. `schedule-status.test.ts` pins that with a parsed-JSON input.
  - **CLI: skew is supported.** `--server-url` targets a separately deployed server, and the CLI's own error paths anticipate version skew. Every CLI response parse passes `LENIENT_CONTEXT`, so a newer server's unknown value renders as its raw string instead of failing the command. This also closes the same gap for fields this ledger doesn't touch (`ManifestStatus`, `ExecutionMode`, and others).
- `ResourceRole` members spell out their string values instead of using `auto()`. The values are unchanged (`test_resource_role_values_are_unchanged` pins them), and a member rename can no longer silently change the wire value. `CORE`, `BASE` and `UNKNOWN` are assigned nowhere in the server, so their consumer docstrings say they are not currently reported. Whether they, and `role` on the wire, should exist at all is #2524.
- The frontend consumes the new types instead of `string`: `MergedService.role` and `ServiceStatusEntry.role` are `ResourceRole` with the `?? ""` fallback dropped, and the `ACTIONS` map `satisfies Record<ActionResponse["action"], ...>`. Tests that fed out-of-vocabulary values to typed parameters now use real ones.
- The server's write path is typed too: `ScheduledJobRegistration.schedule_status` (required, like `JobSummary`'s) and `schedule_status_reason`, and both `mark_job_status` signatures (repository and command executor) take `ScheduleStatus`/`ScheduleStatusReason`, and the callers pass enum members (a `StrEnum` binds as text in sqlite3). Only typed values reach the CHECK-constrained columns.
- Drift guards: `LOG_LEVELS` keys equal `LogLevel` and both `_ACTION_PAST_TENSE` maps (CLI and route) cover every `AppAction` (`tests/unit/test_wire_vocabulary_typing.py`); the CLI's `_SCHEDULE_STATUS_TEXT` covers every `ScheduleStatus` (`tests/unit/cli/test_commands_job.py`).

## Addendum
