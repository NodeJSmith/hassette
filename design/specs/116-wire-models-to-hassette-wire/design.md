# Design: Move the wire models and wire enums into hassette-wire

**Date:** 2026-09-29
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-09-25-shared-wire-models/research.md, design/research/2026-09-29-wire-compat-enforcement/research.md (plus `design/specs/114-hassette-client/brief.md`, item 3b)

Implements #2385. Parent umbrella #1540, epic #45. Blocks #2386.

## Problem

Hassette's HTTP/WebSocket wire contract lives inside the `hassette` package: `src/hassette/web/models.py` holds the response and WS message models, `src/hassette/schemas/` holds the WS event payloads and the telemetry models routes return directly, and the enums and Literals those models use live in `hassette.types`. The upcoming `hassette-client` (#2386) and the HA companion integration need the same definitions, and they can't get them without installing the whole framework and its server stack.

`hassette-wire` exists so that server, client, and integration all use **one definition** of the contract and can't drift. That's the prior-art pattern the research brief recommends: a models package that both client and server depend on (Music Assistant's `music-assistant-models`). Music Assistant's server also imports that package's enums throughout its own internals (`music_assistant/models/__init__.py`, `helpers/player.py`, provider modules), so the shared package is the single source on the server side as well.

This change also removes duplication that exists inside hassette today. `SystemStatus`, `ServiceInfo`, and `BootIssue` in `schemas/domain_models.py` are near field-for-field copies of `SystemStatusResponse`, `ServiceInfoResponse`, and `BootIssueResponse` in `web/models.py`, joined by a mapper that copies fields across.

The empty `hassette-wire` workspace package (#2384) and nested-module scoping for the boundary checker (#2381) have both landed. This design does the move itself.

### What is one thing, and what is two

Spec 114's brief gives the test: two definitions are only a problem when they describe the same thing. Applied here:

- **Same thing, one definition in `hassette_wire`:** every served model; the WS payloads; the enums and Literals those models use (`ResourceStatus`, `ManifestStatus`, `ExecutionMode`, `BackpressurePolicy`, `ExecutionStatus`, `SourceTier`, `LOG_LEVEL_TYPE`, `QuerySourceTier`); and the `SystemStatus`/`ServiceInfo`/`BootIssue` duplicates, which collapse into their `*Response` twins.
- **Different things, kept separate:** `schemas/app_snapshots.py` (live runtime state; `AppInstanceInfo` carries an `Exception`); the telemetry DB query-result models that routes never serve (`ListenerSummary`, `*ErrorRecord`, `SlowHandlerRecord`, `LogRecord`, `BlockingEvent`, `AppHealthSummary`, `*GlobalStats`, `GlobalSummary`, `Session*`, `AppLastError`), none of which appears in `frontend/openapi.json` or `frontend/ws-schema.json` (checked 2026-09-29); and the bus event payload dataclasses in `events/hassette.py`, which are app-author API (see Non-Goals).

## Goals

- Every type that appears in `openapi.json` or `ws-schema.json` has exactly one definition, in `hassette_wire`. The server builds and serves those definitions, and #2386's client will parse them.
- Hassette's own code uses the `hassette_wire` enums and Literals as its single definition. There are no mirrors and no converters.
- `hassette_wire` imports nothing from `hassette` and installs on `pydantic` alone.
- The generated artifacts (`openapi.json`, `ws-schema.json`, `generated-types.ts`, `ws-types.ts`, `ws-validator.generated.ts`) come out byte-identical, and existing tests pass with only import-path changes, apart from the tests that exercise the collapsed mapper.
- The public API for the moved enums is the `hassette` package root: `hassette.ExecutionMode` and `hassette.BackpressurePolicy` keep working, and `hassette.ResourceStatus` and `hassette.ExecutionStatus` are added. Re-exports exist only at public paths. Internal code imports from wherever avoids cycles (in practice `hassette_wire`).

## Non-Goals

- Lenient/`UNKNOWN` parsing for version skew, for both StrEnums and Literal aliases. That belongs to #2386.
- Moving the CLI onto `hassette-client`. That belongs to #2387.
- Converting open-valued `Literal` wire fields into StrEnums (see Architecture, "Literal wire fields").
- Collapsing the `events/hassette.py` bus payload dataclasses (`AppStateChangePayload`, `ServiceStatusPayload`, `ExecutionCompletedPayload`) into the WS payload models. App authors receive those dataclasses in bus handlers, so changing their type is a public API change that deserves its own design.
- Collapsing `ListenerSummary` into `ListenerWithSummary`. `ListenerSummary` is the DB query shape, and `ListenerWithSummary` adds computed fields.
- Deleting the unserved, possibly dead telemetry models (`HandlerErrorRecord`, `JobErrorRecord`, `GlobalSummary`, `SessionSummary`, the `*GlobalStats`). That's a separate cleanup.
- Renaming `hassette-wire`. It is already published on PyPI, and the natural alternative (`hassette-models`) would collide with `hassette.models`, which holds HA state/entity models.
- Any frontend source change.

## User Scenarios

### hassette-client author (#2386): consumer of the contract
- **Goal:** parse server responses into typed models without installing the framework
- **Context:** building `hassette_client`'s typed methods against `hassette_wire`

#### Parse a response
1. **Imports the contract**
   - Sees: `from hassette_wire import SystemStatusResponse, JobSummary, ResourceStatus`, with every served type and enum available from the package root
   - Then: the import succeeds in an environment where `hassette` is not installed

### App author: existing hassette user
- **Goal:** keep using the enums their apps need
- **Context:** an app doing `from hassette import ExecutionMode`, or `from hassette.types.enums import ResourceStatus` as the testing docs showed until now

#### Upgrade hassette
1. **Upgrades to the release carrying this change**
   - Sees: the changelog's `BREAKING CHANGE` note: import `ResourceStatus` and `ExecutionStatus` from `hassette`
   - Then: `from hassette import ExecutionMode, BackpressurePolicy, ResourceStatus, ExecutionStatus` resolves to the enum classes `hassette_wire` defines. `from hassette.types.enums import ResourceStatus` raises `ImportError`.

### Hassette developer: contract maintainer
- **Goal:** change the wire contract safely
- **Context:** adding a field, an enum member, or a Literal value

#### Add a wire field
1. **Edits the model in `hassette_wire`**
   - Sees: the optional-new-fields rule in the `hassette_wire` package docstring
   - Decides: gives the field a default
   - Then: runs `scripts/export_schemas.py --types`, and the pre-push schema-freshness hook covers `wire/`

#### Add an enum member
1. **Adds a member to `hassette_wire`'s `ResourceStatus`**
   - Then: hassette uses it immediately, since it's the same class, and the regenerated schema shows the new value, since the change is published by construction

## Functional Requirements

- **FR#1** Every served model, discriminated union, and Literal alias in `src/hassette/web/models.py` is defined in `hassette_wire` instead, and `web/models.py` no longer exists. The unserved, unreferenced `EntityStateResponse` and `EntityListResponse` are deleted, not moved.
- **FR#2** `AppStatusChangedData`, `ServiceStatusData`, `ConnectivityData`, and `AppManifestsChangedData` are defined in `hassette_wire`.
- **FR#3** `SystemStatus`, `ServiceInfo`, and `BootIssue` no longer exist. `RuntimeQueryService.get_system_status()` returns a `hassette_wire.SystemStatusResponse` with `ServiceInfoResponse`/`BootIssueResponse` children, and sets `version` explicitly from `hassette.utils.get_version()`.
- **FR#4** `Execution`, `ActivityFeedEntry`, and `JobSummary` are defined in `hassette_wire`. Apart from the models FR#1–FR#4 move, every model in `hassette.schemas` stays where it is.
- **FR#5** `ResourceStatus`, `ManifestStatus`, `ExecutionMode`, `BackpressurePolicy`, and `ExecutionStatus` are defined in `hassette_wire` with explicit string values, and have no other definition anywhere.
- **FR#6** `SourceTier`, `LOG_LEVEL_TYPE`, and `QuerySourceTier` are defined in `hassette_wire`, and have no other definition anywhere.
- **FR#7** The `hassette` package root exports `ExecutionMode`, `BackpressurePolicy` (as today), and `ResourceStatus` and `ExecutionStatus` (new) as re-exports of the `hassette_wire` objects (identity, not copies). No other `hassette` module re-exports a name from FR#5/FR#6: `hassette.types.enums`, `hassette.types.types`, and `hassette.types` stop exporting them.
- **FR#8** `CliFormat` and `CliFormatStyle` are defined only in `hassette_wire`, and `cli/output.py` reads `CliFormat` metadata from there.
- **FR#9** Every public name in `hassette_wire` is importable from the package root and listed in its `__all__`.
- **FR#10** Importing `hassette_wire` loads no `hassette` module.
- **FR#11** `to_listener_with_summary` and `enrich_jobs_with_live` build their output through pydantic validation, so a wrongly typed computed value never lands in a response unvalidated. `to_listener_with_summary` raises. `enrich_jobs_with_live` keeps its existing per-job fallback: the `ValidationError` (a `ValueError`) is caught, a warning is logged, and that job is served from its DB row, so one bad live value can't fail the whole jobs endpoint.
- **FR#12** `on_execution_completed` builds each completion as a `hassette_wire.ExecutionCompletedData` when the event arrives, and `_pending_completions` holds those typed models. Every served WS payload is constructed through its wire model, and a malformed completion is rejected on its own rather than taking the rest of its batch with it.
- **FR#13** The boundary checker fails any runtime import of `hassette_client` from anywhere in `src/hassette`.
- **FR#14** The optional-new-fields rule (a wire field added after the first `hassette-wire` release must be optional with a default) is written in the `hassette_wire` package docstring and in `CONTRIBUTING.md`. The same text states that adding an enum member or Literal value is also a version-skew change, in the older-client/newer-server direction, which #2386's lenient parsing handles.
- **FR#15** The pre-push schema-freshness hook runs when files under `wire/src/hassette_wire/` change.
- **FR#16** A wire-compatibility check compares HEAD's `frontend/openapi.json` with the last release's in both skew directions. It fails when a newer client would reject an older server's response: a response property that was optional or absent in the last release is required at HEAD. It also fails when an older client would break against a newer server: oasdiff's default breaking checks, such as a removed response field, a changed type, or a removed endpoint, except for enum value additions, which #2386's lenient parsing owns. It passes for new optional response fields and new endpoints. A deliberate break passes only when it's listed in the committed ignore file.

## Edge Cases

- **Enum identity across paths.** `hassette.ResourceStatus is hassette_wire.ResourceStatus` holds, so `isinstance`, `match`, dict keys, and pickling behave the same whichever path a caller imported from. There is no coercion between two classes, because there's only one class.
- **Removed import paths.** `hassette.types.enums.ResourceStatus`, `hassette.types.{ResourceStatus,SourceTier,QuerySourceTier}`, and the other FR#5/FR#6 names at their old `hassette.types.*` locations stop resolving. The first was shown in the testing docs, so this is a breaking change for app authors who copied it. The fix is a one-line import change to `from hassette import ResourceStatus`. `hassette.types.types.ExecutionStatus` is the other app-facing removal: it types `ExecutionCompletedPayload.status`, which app authors receive through the exported `HassetteExecutionCompletedEvent`, and its replacement is `from hassette import ExecutionStatus`. `SourceTier` and `QuerySourceTier` are telemetry-filter vocabulary no app author uses.
- **Enum descriptions.** OpenAPI emits each enum's `__doc__` as its `description` and `__name__` as its `title`. The enums move with their class docstrings and per-member docstrings unchanged. Switching from `auto()` to explicit string values doesn't change any value, since `StrEnum`'s `auto()` already yields the lowercased member name.
- **Attribute docstrings.** `ListenerWithSummary` sets `use_attribute_docstrings=True`, so its field docstrings are schema descriptions and have to move byte-for-byte, in field order.
- **`version` becomes explicit.** `SystemStatusResponse.version` defaults to `""`, and today's server sets it through the mapper from `SystemStatus.version`'s `get_version` default factory. After the collapse, `get_system_status()` passes `version=get_version()` itself. The `/health` body is unchanged.
- **`ServiceInfo.status` was a `str`.** `get_system_status()` built it from `child.status.value`, and the mapper cast it back to `ResourceStatus`. After the collapse it builds `ServiceInfoResponse(status=child.status)` directly, so there's no round trip through `str`.
- **`model_copy(update=...)` skips validation.** Pydantic v2 documents `update` as unvalidated, and `model_validate(instance)` returns the instance untouched under the default `revalidate_instances="never"`. FR#11 therefore builds the model through its constructor rather than revalidating a copy.
- **Coercion from validated construction.** Under FR#11 and FR#12, an `int` handed to a `float` field now becomes a `float`, which could change JSON output (`1` → `1.0`). The route tests and the schema pin catch any such change, and the PR explains it.
- **Defaults.** `DEFAULT_OVERLAP_MODE` and `DEFAULT_BACKPRESSURE_POLICY` stay in `hassette.types.enums` (they're used by `core/registration.py`), and now point at the `hassette_wire` enums. Wire models that default to them use `ExecutionMode.SINGLE` / `BackpressurePolicy.BLOCK` directly, since `hassette_wire` can't import `hassette`. The schema `default` value is unchanged.
- **Docs cross-references.** Two pages link `[hassette.types.enums.ResourceStatus]` (three occurrences), and `testing_simulate_service_failure.py` imports it from there. They move to `hassette.ResourceStatus` / `from hassette import ResourceStatus`. The mkdocstrings handler loads from `paths: [src]` only, so resolving the alias through to `hassette_wire` needs `wire/src` added to `paths` in `mkdocs.yml`. `mkdocs build --strict` proves the cross-references resolve.
- **Schema component name collision.** With a single enum class there's nothing to collide. No route parameter references a named enum (verified: every parameter schema is inline).

## Acceptance Criteria

- **AC#1** After `uv run python scripts/export_schemas.py --types`, `git diff --exit-code frontend/openapi.json frontend/ws-schema.json frontend/src/api/generated-types.ts frontend/src/api/ws-types.ts frontend/src/api/ws-validator.generated.ts` exits 0. (FR#1–FR#6)
- **AC#2** `src/hassette/web/models.py` does not exist, and `importlib.util.find_spec("hassette.schemas.domain_models")` is `None` (the module is deleted), and a unit test asserts `not hasattr(module, name)` for every moved or deleted name against its old surviving module: `AppStatusChangedData`/`ServiceStatusData`/`ConnectivityData`/`SystemStatus`/`ServiceInfo`/`BootIssue` on `hassette.schemas` (the six it re-exports today; `AppManifestsChangedData` was never re-exported there); `Execution`/`ActivityFeedEntry` on `hassette.schemas.execution_models`; `JobSummary` on `hassette.schemas.job_models`; and `CliFormat`/`CliFormatStyle` on `hassette.types.types`. The check works on module attributes rather than grepping import text, so multi-line parenthesized imports can't hide a leftover. (FR#1–FR#4, FR#8)
- **AC#3** A unit test asserts that `hassette.ExecutionMode`, `hassette.BackpressurePolicy`, `hassette.ResourceStatus`, and `hassette.ExecutionStatus` are each the `hassette_wire` object (`is`), and that no FR#5/FR#6 name is an attribute of `hassette.types`, `hassette.types.enums`, `hassette.types.types`, or `hassette.schemas`. (FR#5–FR#7)
- **AC#4** `uv run nox -s wire` passes, including a test that runs `import hassette_wire` in a fresh interpreter and asserts no `hassette` or `hassette.*` module is in `sys.modules`. (FR#10)
- **AC#5** A `wire/tests` test asserts every public class and alias defined in `hassette_wire`'s submodules is in `hassette_wire.__all__` and importable from the root. (FR#9)
- **AC#6** `tests/unit/core/test_runtime_query_service.py` asserts `get_system_status()` returns a `SystemStatusResponse` whose `version` equals `get_version()` and whose `services[*].status` are `ResourceStatus` members. `GET /api/health` tests pass unchanged. (FR#3)
- **AC#7** A unit test shows `to_listener_with_summary` raises `ValidationError` when a computed value has the wrong type. A unit test shows `enrich_jobs_with_live` returns the unmodified DB row for a job whose live value has the wrong type, where before it returned the unvalidated overlay. (FR#11)
- **AC#8** A unit test shows `flush_completions` broadcasts a batch whose `data` validates against `list[ExecutionCompletedData]`. A second test feeds one malformed completion between two valid ones: it raises in `on_execution_completed`, never reaches `_pending_completions`, and the next flush broadcasts the two valid completions. Existing `execution_completed` WS tests pass. (FR#12)
- **AC#9** `tests/unit/tools/test_check_module_boundaries.py` has a passing test showing a `hassette_client` import is rejected from every layer, and `uv run tools/check_module_boundaries.py` exits 0 against the full tree. (FR#13)
- **AC#10** `hassette_wire.__doc__` contains the optional-new-fields rule and the enum/Literal skew sentence, and `CONTRIBUTING.md` references both. (FR#14)
- **AC#11** `prek.toml`'s `check-schemas-fresh` hook `files` pattern matches `wire/src/hassette_wire/…` paths. (FR#15)
- **AC#12** `uv run pytest tests/unit/cli -n 4` passes. The `test_output*` tests render `CliFormat`-annotated fields (`uptime_seconds`, `handler_avg_duration`, `last_activity_ts`, `JobSummary.next_run`) humanized. (FR#8)
- **AC#13** `uv run mkdocs build --strict` succeeds. (FR#7, Edge Cases: docs cross-references)
- **AC#14** `uv run nox -s dev` passes, `prek -a` is clean, and `prek run pyright -a --stage pre-push` is clean.
- **AC#15** `tools/check_wire_compat.py` exits 0 on this branch against the latest `v*` tag's `frontend/openapi.json`. Given fixture pairs, it exits non-zero when HEAD adds a required property to a response model, makes an optional one required, removes a response property, or removes an endpoint. It exits 0 when HEAD adds an optional response property, a new endpoint, or a new enum value. It exits 0 for a removed response property that the fixture's ignore file lists. It exits non-zero with a message naming the missing tag when no `v*` tag resolves. (FR#16)

## Key Constraints

- **No copies.** Each moved enum, Literal, and model has exactly one definition. No mirror enum, parity test, or domain-to-wire enum converter is introduced.
- **Re-exports only at the public API.** The `hassette` root is the only place hassette re-exports a moved name (`ExecutionMode`, `BackpressurePolicy`, `ResourceStatus`, `ExecutionStatus`). Internal convenience is never a reason to re-export: internal code imports from `hassette_wire` directly, and any path works as long as it creates no import cycle.
- **No LLM-regenerated model bodies.** Moved classes are relocated mechanically so docstrings, field order, and defaults stay byte-exact. The schema pin depends on it.
- **Wire enums use explicit string values, never `auto()`.** The contract must not depend on member-name casing.
- **`hassette_wire` depends on `pydantic` only.** Adding any other runtime dependency is out of scope.
- **Don't change app-author-facing types.** The `events/hassette.py` payload dataclasses and the `hassette.ExecutionMode` import path stay as they are.

## Dependencies and Assumptions

- **Landed prerequisites:** #2384 (the `wire/` workspace member, pinned `hassette-wire==X` in `pyproject.toml`, `nox -s wire`, and pyright/prek coverage of `wire/`) and #2381. #2381's nested scoping isn't needed after this redesign; see Architecture, "Boundary checker".
- **Accepted: enum values are published by construction.** Adding a member to `ResourceStatus` or the other moved enums changes the wire contract immediately. That's accepted: every moved enum is already visible in the UI, config, or DB, so internal-only members don't occur in practice. A genuinely internal-only state would get its own internal enum rather than a member on the shared one.
- **Accepted: breaking import-path removal.** `hassette.types.enums.ResourceStatus` (shown in the testing docs) and the `hassette.types` exports of `ResourceStatus`/`SourceTier`/`QuerySourceTier` go away, with `hassette.ResourceStatus` as the replacement, and so does `hassette.types.types.ExecutionStatus`, replaced by `hassette.ExecutionStatus`. The user chose this at discovery: public surface is the `hassette` root, and `SourceTier`/`QuerySourceTier` aren't app-author vocabulary. The PR is titled with `!` and carries one `BREAKING CHANGE:` footer naming both replacement imports (`ResourceStatus`, `ExecutionStatus`) (see CLAUDE.md, Changelog).
- **Accepted: `hassette` depends on `hassette_wire` for core types.** The two release in lockstep (a single release-please train, with exact pins), so there's no version-coupling cost.
- **Accepted: no structural guard against internal types leaking onto the wire.** Boundary rule 1 from the issue is dropped (see Architecture). What guards leakage is the schema pin (`check-schemas-fresh` pre-push, the CI git-diff), which surfaces every contract change in review.
- **Accepted: validated construction may coerce output** (FR#11, FR#12). This was accepted in the discovery edge-case answer. Any diff gets explained in the PR.
- **Accepted: moving the enums keeps the schemas byte-identical.** The evidence: enum components in `openapi.json` are `{type, enum, title=__name__, description=__doc__}`, no route parameter references a named enum, and component names carry no module path. So moving the enums with their names and docstrings unchanged shouldn't change any generated schema. Mitigation: AC#1's `export_schemas.py` diff catches any drift. If one shows up, the task that runs it finds the cause and either fixes it (preferred) or explains it in the PR.
- **Release timing.** `hassette-wire` is already on PyPI, but as the empty package from #2384. The first release carrying this change fixes the root `__all__` as a contract that #2386 and the HA integration pin against.
- **Process step (not an AC):** update issue #2385's body to match this design: single-source enums, the `SystemStatus` collapse, and rule 1 dropped.
- **CI already covers `wire/**`** in `tests.yml`'s path filter and schema-freshness job, and `docs.yml` already runs `mkdocs build --strict`. The only workflow change is FR#16's wire-compat step in `tests.yml` (see Architecture).

## Architecture

### Package layout (`wire/src/hassette_wire/`)

It's split into domain submodules, and the root `__init__.py` re-exports every public name in `__all__`. That mirrors how `src/hassette/__init__.py` exposes `App`, `Bus`, and `ExecutionMode` from their subpackages. In-repo code outside `hassette.types` and #2386 import from the root (`from hassette_wire import JobSummary`), so files can be reorganized later without breaking callers.

| Module | Contents (moved from) |
|---|---|
| `enums.py` | `ResourceStatus`, `ManifestStatus`, `ExecutionMode`, `BackpressurePolicy` (from `types/enums.py`); `ExecutionStatus` (from `types/types.py`) |
| `literals.py` | `SourceTier`, `LOG_LEVEL_TYPE`, `QuerySourceTier` (from `types/types.py`); `ErrorRateClass`, `HealthStatus`, `ListenerKind`, `SystemHealthStatus` (from `web/models.py`) |
| `cli_format.py` | `CliFormat`, `CliFormatStyle` (from `types/types.py`) |
| `health.py` | `BootIssueResponse`, `ServiceInfoResponse`, `SystemStatusResponse`, `LivenessResponse`, `ReadinessResponse` |
| `apps.py` | `AppInstanceResponse`, `AppStatusResponse`, `AppManifestResponse`, `AppManifestListResponse`, `ActionResponse`, `AppConfigResponse`, `AppSourceResponse` |
| `telemetry.py` | `Execution`, `ActivityFeedEntry`, `JobSummary` (from `schemas/`), `AppHealthResponse`, `ListenerWithSummary`, `ActivityBucket`, `DashboardAppGridEntry`, `DashboardAppGridResponse`, `TelemetryStatusResponse`, `JobTriggerResponse` |
| `logs.py` | `LogEntryResponse`, `LogsByExecutionResponse`, `LogLevelRequest`, `LogLevelResponse` |
| `auth.py` | `MAX_SESSION_TOKEN_LENGTH`, `SessionRequest`, `SessionResponse` |
| `config.py` | `ConfigSchemaResponse` |
| `ws.py` | `AppStatusChangedData`, `ServiceStatusData`, `ConnectivityData`, `AppManifestsChangedData` (from `schemas/domain_models.py`), `ConnectedPayload`, `ExecutionCompletedData`, every `*WsMessage`, `WsServerMessage` |

`EntityStateResponse` and `EntityListResponse` are deleted: no route, test, script, or frontend file references them, and they're absent from `openapi.json`. The package docstring states what belongs in the package (the served contract and the vocabulary it uses) and the optional-new-fields rule.

### Enums and Literals: one definition, re-exported only at the public root

The enums and Literals are defined once in `hassette_wire.enums` / `hassette_wire.literals`. `src/hassette/__init__.py` re-exports `ExecutionMode`, `BackpressurePolicy`, `ResourceStatus`, and `ExecutionStatus` from `hassette_wire` in its `__all__`. The objects are the same, not copies. That's the whole public surface for these names. `hassette.types.enums`, `hassette.types.types`, and `hassette.types` no longer define or export any of them, and `hassette.types/__init__.py`'s `__all__` drops `BackpressurePolicy`, `ExecutionMode`, `ResourceStatus`, `QuerySourceTier`, and `SourceTier`.

Enums that aren't in the contract (`RestartType`, `Topic`, `ConnectionState`, `ResourceRole`, `BlockReason`, `Outcome`, and the rest) stay defined in `hassette.types.enums`. `DEFAULT_OVERLAP_MODE`, `DEFAULT_BACKPRESSURE_POLICY`, `TERMINAL_STATUSES`, and `ACTIVE_STATUSES` stay there too, and import their enums from `hassette_wire`.

Internal modules import these names from `hassette_wire` directly. That's the one path guaranteed cycle-free, since `hassette_wire` imports nothing from `hassette`. Importing from the `hassette` root inside the package would risk cycles. The same one-off rewrite script that handles model imports rewrites the roughly 70 internal files that import them from `hassette.types*` today.

### Literal wire fields

Open-valued Literal aliases stay `Literal`. That covers `ErrorRateClass`, `HealthStatus`, `ListenerKind`, `SystemHealthStatus`, `SourceTier`, `LOG_LEVEL_TYPE`, `BootIssueResponse.severity`, and the `kind: Literal["handler", "job"]` fields. This resolves spec 114's open question. Keeping them keeps `openapi.json` byte-identical, which is this change's pin, and converting later stays cheap because StrEnum members are `str` and compare equal to the same strings. #2386 owns open-set handling for Literal aliases and StrEnums alike.

### `SystemStatus` collapse

- `RuntimeQueryService.get_system_status()` returns `SystemStatusResponse`. It builds `ServiceInfoResponse(name=…, status=child.status, role=child.role.value, ready_phase=…, retry_at=…)` and `BootIssueResponse(...)` (from `collect_boot_issues`, now `-> list[BootIssueResponse]`), and passes `version=get_version()`.
- In `web/mappers.py`, `system_status_response_from` is deleted. `readiness_response_from` and `connected_payload_from` take `SystemStatusResponse`, and their bodies are unchanged. `routes/health.py` returns `runtime.get_system_status()` directly for `/health`. `routes/ws.py` keeps calling `connected_payload_from`.
- `SystemStatus`, `ServiceInfo`, and `BootIssue` are deleted from `schemas/domain_models.py`. What's left in that module (nothing, once the 4 WS payloads also move) is deleted, and `schemas/__init__.py` drops its entries (and its `ManifestStatus` re-export, per FR#7).

### Validated construction (FR#11)

`to_listener_with_summary` builds `ListenerWithSummary(**listener.model_dump(), listener_kind=…, handler_summary=…, target=…, suppressed_count=…, dropped_count=…, backpressure_dropped_count=…)`. Before, it called `model_validate(listener, from_attributes=True).model_copy(update=...)`. The constructor validates every field, and the computed fields are explicit keyword arguments, so pyright checks their types. `enrich_jobs_with_live` (`web/utils.py`, the function that holds the `model_copy`; `enrich_jobs_with_live_data` is only its async wrapper) builds `JobSummary(**js.model_dump(exclude={…updated keys…}), schedule_status=…, …)` the same way, inside its existing `try/except (AttributeError, TypeError, ValueError)`. That clause stays as it is: a `ValidationError` is a `ValueError`, so a bad live value takes the existing warning-and-DB-row fallback for that one job and never reaches the response. `test_listener_summary_fields_are_subset_of_response` keeps guarding that `model_dump()` supplies a field set the response accepts.

### Completion broadcast (FR#12)

`on_execution_completed` builds `ExecutionCompletedData(kind=…, app_key=…, …)` from the `ExecutionCompletedPayload` and appends the model to `_pending_completions` (now `list[ExecutionCompletedData]`). `flush_completions` broadcasts `{"type": "execution_completed", "data": [c.model_dump() for c in batch], "timestamp": now}` and has no validation step left that can raise. Construction happens per event, not per batch, because `flush_completions` swaps out the pending list before it builds anything and runs as a spawned task whose crash is only logged: building there would let one bad completion drop the whole tick from the WS feed. Built per event, a `ValidationError` fails only that one bus-handler invocation and goes through the bus's normal listener-error handling, and DB persistence is unaffected either way. The dict's key order already matches the model's field order.

### Boundary checker (`tools/check_module_boundaries.py`)

- `WATCHED_ROOTS` gains `hassette_client`.
- **Rule `no-hassette-client`:** `applies` = every layer (`lambda _: True`; the existing `applies_prefix`/`applies_outside` helpers can't express "always"). `forbids` = `forbids_prefix("hassette_client")`. Reason: the CLI plugin reaches the client through the `hassette.cli` entry point's `register(app)` argument (#2387), never through an import.
- **The issue's rule 1 (only `web/`, `core/telemetry/`, `runtime_query_service` may import `hassette_wire`) is dropped.** The enums are core vocabulary imported by roughly 70 hassette modules through `hassette.types`, so there's no longer a meaningful boundary to draw around `hassette_wire` imports. What guards against leaks is the schema pin.
- `Rule.applies` keeps its layer-based signature. No file-level scoping is needed.
- The module docstring's rule list gains the new rule. The `test_nested_rule_scopes_to_prefix_not_siblings` comment that names #2385 is reworded to describe nested scoping generically.

### Wire-compatibility check (FR#16)

This follows `design/research/2026-09-29-wire-compat-enforcement/research.md`. `tools/check_wire_compat.py` runs `oasdiff breaking --fail-on ERR` twice. Both runs compare HEAD's `frontend/openapi.json` with the latest `v*` tag's copy, which the script extracts with `git show`.

- **Reversed run (new client, old server):** `oasdiff breaking <HEAD> <last-release>`. By default oasdiff judges old-client/new-server compatibility, and it scores a new required response field `info` (https://www.oasdiff.com/checks/response-required-property-added). With the arguments swapped, the same change reads as `response-required-property-removed` or `response-property-became-optional`, and both are `error` ("It widens what the API may return, so a client can receive a response it was not written to handle"). A reversed run also turns a new endpoint into `api-removed-without-deprecation` and a new optional field into `response-optional-property-removed`. So this run's `--severity-levels` file keeps only the two response-required checks at `err` and sets every other check to `none`.
- **Forward run (old client, new server):** `oasdiff breaking <last-release> <HEAD>` with oasdiff's default severities. It catches removed response fields, type changes, removed endpoints, and new required request parameters. Its `--severity-levels` file lowers only `response-property-enum-value-added` to `info`. That's the only enum-value-added check whose default is `error`: the request-side ones already default to `info`, per `oasdiff checks changelog` in 1.32.1. It's lowered because Literals render as enums in the schema and #2386's lenient parsing owns value additions.

**Override for deliberate breaks.** Both runs take `--err-ignore tools/wire_compat_ignore.txt`. oasdiff documents this format: one accepted change per line, as `METHOD /path <change description>` or `components <change description>` (https://github.com/oasdiff/oasdiff/blob/main/docs/BREAKING-CHANGES.md). A PR that breaks the wire on purpose adds one line per reported change. The PR is titled with `!` and carries the `BREAKING CHANGE:` footer. Review sees exactly which breaks were accepted. Once the next `v*` tag contains the change, oasdiff no longer reports it, so the line goes inert, and the file is cleared after that release. A stale line does no harm. The file ships empty apart from a header comment that explains the format and the clearing rule. This also covers a deliberate required-field addition, which would otherwise be blocked until a release ships.

The two severity-levels files and the ignore file live next to the script. The script runs as a CI step in `tests.yml`'s frontend job. That job's `actions/checkout` gains `fetch-depth: 0`, as `lint.yml` already uses, because the default shallow checkout has no tags. The `changes` path filter gains `tools/check_wire_compat.py` and `tools/wire_compat_ignore.txt` (plus the levels files), so a PR touching only the check still runs it. When no `v*` tag resolves, the script exits non-zero with a message naming the missing tag, rather than skipping the check. It also runs as a pre-push hook, with the same `files` pattern as `check-schemas-fresh` plus the ignore and levels files. oasdiff is pinned in `mise.toml` as `"github:oasdiff/oasdiff" = "1.32.1"`. The `aqua:` backend has no oasdiff package, and the `github:` backend installs the release tarball. Confirmed flags in 1.32.1: `--severity-levels <file>` (lines of `<check-id> <err|warn|info|none>`), `--err-ignore <file>`, and `--fail-on ERR`. CI doesn't use mise, so the frontend job installs the same version the way `docs.yml` installs muffet: `actions/setup-go` (SHA-pinned), then `go install github.com/oasdiff/oasdiff@v1.32.1`, with a comment naming `mise.toml` as the other place that carries the version. The fixture tests in `tests/unit/tools/test_check_wire_compat.py` need the binary. They skip when `oasdiff` isn't on `PATH`, and the frontend job runs them explicitly after installing it, so CI enforces them.

Scope limits: the check covers HTTP requests and responses in `openapi.json`, not WS messages. `ws-schema.json` isn't OpenAPI, and spec 114 scopes WS out of the integration's v0.1. Enum and Literal value additions are downgraded in the forward run because #2386's lenient parsing owns them. Everything else oasdiff classifies as breaking in either direction fails the check unless it's listed in the ignore file.

### Import rewrite

Every import of a moved name becomes `from hassette_wire import …`. That covers models from `hassette.web.models`, `hassette.schemas.{domain,execution,job}_models`, or `hassette.schemas` (the WS payloads); `CliFormat`; and every FR#5/FR#6 enum or Literal imported from `hassette.types`, `hassette.types.enums`, or `hassette.types.types`, across `src/`, `tests/`, and `scripts/`. `examples/` already imports the moved enums from the `hassette` root and needs no change. The docs are hand-edited (see Documentation Updates): the snippet switches to `from hassette import ResourceStatus`, which is the public path. A one-off script does the rewrite so the edit is uniform and reviewable. Staying names imported alongside moved ones (e.g. `AppLastError` from `execution_models`, `Topic` from `types.enums`) keep their original import line.

### Reuse

- `wire/` package scaffolding, `nox -s wire`, the pinned dependency, and the pyright/prek coverage from #2384 are reused as-is.
- `scripts/export_schemas.py --types`, `tools/check_schemas_fresh.py`, the CI git-diff steps, and `mkdocs build --strict` are reused as-is as the pin. Only `scripts/schema_helpers.py`'s `WsServerMessage` import changes.
- `web/mappers.py` stays the domain-to-wire mapping layer for `app_snapshots` and `ListenerSummary`. It loses the `SystemStatus` mapper and the enum-coercion notes in its module docstring.

## Implementation Preferences

- Move code mechanically (cut/paste of exact line ranges, `git mv` where a whole file moves), never retyped. Docstrings, field order, and defaults stay byte-exact.
- Rewrite imports with a one-off script run once over `src/`, `tests/`, and `scripts/`. It isn't committed, since this is a one-time transform.
- Moved StrEnums switch from `auto()` to explicit string values equal to today's values. Class docstrings and per-member docstrings stay unchanged.
- In-repo code imports every moved name (models, enums, Literals) from the `hassette_wire` root. Only app-author-facing docs and examples use `from hassette import …`.
- Google-style docstrings, pyright-clean, no `from __future__ import annotations`, line length 120.
- The optional-new-fields rule goes in the `hassette_wire/__init__.py` module docstring, plus one line in `CONTRIBUTING.md`.

## Replacement Targets

| Target | Replaced by | Treatment |
|---|---|---|
| `src/hassette/web/models.py` | `hassette_wire` submodules | delete the file; `EntityStateResponse`/`EntityListResponse` (unreferenced) are deleted outright |
| `src/hassette/schemas/domain_models.py` (4 WS payloads + `SystemStatus`/`ServiceInfo`/`BootIssue`) | `hassette_wire.ws` / `hassette_wire.health` | delete the file; remove the `schemas/__init__.py` entries |
| `Execution`, `ActivityFeedEntry` in `schemas/execution_models.py` | `hassette_wire.telemetry` | remove; `AppLastError` stays |
| `JobSummary` in `schemas/job_models.py` | `hassette_wire.telemetry` | remove; `JobGlobalStats`/`JobErrorRecord` stay |
| Definitions of `ResourceStatus`, `ManifestStatus`, `ExecutionMode`, `BackpressurePolicy` in `types/enums.py` | `hassette_wire.enums`; `ResourceStatus`/`ExecutionMode`/`BackpressurePolicy` re-exported from the `hassette` root, `ManifestStatus` not re-exported anywhere | remove the definitions; no re-export in `types` |
| `ManifestStatus` re-export in `hassette.schemas` (`schemas/__init__.py` import and `__all__`) | `hassette_wire.ManifestStatus` | remove (not app-author vocabulary; no docs or known app imports it) |
| Definitions of `ExecutionStatus`, `SourceTier`, `LOG_LEVEL_TYPE`, `QuerySourceTier` in `types/types.py` | `hassette_wire.enums` / `hassette_wire.literals` | remove the definitions; no re-export |
| `hassette.types/__init__.py` exports of `BackpressurePolicy`, `ExecutionMode`, `ResourceStatus`, `QuerySourceTier`, `SourceTier` | `hassette` root (first three); none (last two) | remove from imports and `__all__` |
| `CliFormat`, `CliFormatStyle` in `types/types.py` | `hassette_wire.cli_format` | remove (not public API: no docs reference; `cli/output.py` rewritten) |
| `system_status_response_from` in `web/mappers.py` | `get_system_status()` building the wire model | delete |
| `model_copy(update=...)` in `to_listener_with_summary` and `enrich_jobs_with_live` | validated construction | replace |
| Raw-dict batch in `flush_completions` | `ExecutionCompletedData` | replace |

## Convention Examples

### Wire response model

**Source:** `src/hassette/web/models.py`

```python
class ActionResponse(BaseModel):
    """Response for app mutation endpoints (start/stop/reload).

    ``instance_index`` is the server-confirmed instance the action ran against — ``None`` for
    an app-level action, the validated index for an instance-scoped one. ...
    """

    status: Literal["accepted"] = "accepted"
    app_key: str
    action: str
    instance_index: int | None
```

### Domain-to-wire mapper (kept for `app_snapshots`)

**Source:** `src/hassette/web/mappers.py`

```python
def app_manifest_response_from(manifest: AppManifestInfo) -> AppManifestResponse:
    """Convert an ``AppManifestInfo`` snapshot to ``AppManifestResponse``."""
    return AppManifestResponse(**manifest_response_fields(manifest))
```

### StrEnum whose docstring becomes the OpenAPI description

**Source:** `src/hassette/types/enums.py`. It moves with its docstrings unchanged and gets explicit values instead of `auto()`.

```python
class ManifestStatus(StrEnum):
    """Enumeration for app manifest status values (manifest-scoped, distinct from ``ResourceStatus``)."""

    DISABLED = auto()
    ...
```

### Public re-export surface

**Source:** `src/hassette/__init__.py`, the one public surface. Its enum import changes source to `hassette_wire` and gains `ResourceStatus` and `ExecutionStatus` (added to `__all__`).

```python
from .types.enums import BackpressurePolicy, BlockingIOBehavior, ExecutionMode, ForgottenAwaitBehavior, Topic
# becomes
from hassette_wire import BackpressurePolicy, ExecutionMode, ExecutionStatus, ResourceStatus
from .types.enums import BlockingIOBehavior, ForgottenAwaitBehavior, Topic
```

### Boundary rule and its test

**Source:** `tools/check_module_boundaries.py`, `tests/unit/tools/test_check_module_boundaries.py`

```python
Rule(
    name="test-helpers-isolation",
    applies=applies_outside("testing"),
    forbids=forbids_package("testing"),
    reason="production code must not import test helpers from hassette.testing",
),
```

### WS envelope test

**Source:** `tests/unit/test_ws_models.py`

```python
MESSAGE_ADAPTER = TypeAdapter(WsServerMessage)

def validate_envelope(msg_type: str, data: object) -> WsServerMessage:
    return MESSAGE_ADAPTER.validate_python({"type": msg_type, "data": data, "timestamp": TEST_TIMESTAMP})
```

## Alternatives Considered

- **Mirror the enums and Literals in `hassette_wire`, with a parity test and exhaustive domain-to-wire converters.** This was the earlier draft of this design. Rejected: the enums describe the same concept on both sides, so two definitions kept identical by a test plus a converter layer is duplication with extra machinery. The design challenge showed the two guards contradicting each other. It also goes against the package's purpose (one definition), and against prior art: Music Assistant's server imports its models package's enums directly.
- **Keep `SystemStatus`/`ServiceInfo`/`BootIssue` as domain objects mapped to responses.** Rejected: they're near field-for-field copies with no internal-only state, so the mapper exists only to copy fields.
- **Rename the package** (e.g. `hassette-models`). Rejected: `hassette-wire` is already published, and `hassette-models` would collide with `hassette.models` (HA state/entity models).
- **Keep rule 1 as a narrowed allowlist for wire models** (not enums). Rejected: in-repo code imports from the package root, so the checker can't tell a model import from an enum import without forcing submodule import paths, and the schema pin already surfaces every contract change.
- **Convert open-valued Literals to StrEnums now.** Rejected in favor of keeping the byte-identical pin; converting later stays cheap.
- **Domain submodules as the only public paths (no root re-exports), or one flat `models.py`.** Rejected: the first makes every file move after release a breaking change, and the second starts at about 700 lines, against the 800-line cap.
- **Keep `model_copy(update=...)`.** Rejected: an unvalidated update can put a wrongly typed value into a served model.

## Test Strategy

### Required Test Types

- **Unit:** public-path identity, removed-name absence, the `SystemStatus` collapse, validated construction, completion batching, and the boundary rule. These are single-module behaviors.
- **Integration (existing, unchanged apart from imports):** route, WS, and telemetry-query tests. Together with the schema artifacts, they're the pin that proves the move changed no behavior.
- **Member suite:** `nox -s wire`, for package isolation and `__all__`.
- **Docs:** `mkdocs build --strict`, for cross-reference resolution through the re-exports.
- System and e2e tests run in CI as usual. Nothing here needs them run locally.

### Existing Tests to Adapt

Import paths only. Every file importing `hassette.web.models`, a moved name from `hassette.schemas.{domain,execution,job}_models` or `hassette.schemas`, or `CliFormat` from `hassette.types.types`:

`tests/e2e/mock_fixtures/telemetry.py`, `tests/integration/telemetry/{helpers,test_execution_queries,test_global_jobs_and_service_info,test_job_queries,test_union_queries}.py`, `tests/integration/web_api/{test_body_limit,test_dashboard_api,test_telemetry_route}.py`, `tests/support/{web_job_helpers,web_manifest_helpers,web_response_helpers,web_telemetry_helpers}.py`, `tests/system/test_cli_smoke.py`, `tests/unit/cli/{test_client,test_commands_app,test_commands_status,test_output,test_output_detail}.py`, `tests/unit/core/{test_runtime_query_service,test_telemetry_models,test_unified_execution}.py`, `tests/unit/{test_logging_capture_handler,test_model_types,test_source_tier_models,test_telemetry_models,test_ws_models}.py`, `tests/unit/web/test_mappers.py`.

Beyond import paths, the tests touching the `SystemStatus` collapse change: `tests/unit/web/test_mappers.py` (the `system_status_response_from` tests are removed, and the `readiness_response_from`/`connected_payload_from` tests build a `SystemStatusResponse`), `tests/unit/core/test_runtime_query_service.py`, `tests/integration/telemetry/test_global_jobs_and_service_info.py`, `tests/integration/test_dashboard_without_ha.py`, `tests/integration/web_api/test_dashboard_api.py`, and `tests/integration/web_api/test_ws_endpoint.py`. Each asserts on the `SystemStatus`/`ServiceInfo`/`BootIssue` type or shape.

### New Test Coverage

- `wire/tests/test_import.py` (extend): fresh-interpreter isolation (FR#10, AC#4) and `__all__` completeness (FR#9, AC#5).
- `tests/unit/test_wire_public_paths.py` (new): public-path identity (FR#7, AC#3) and removed-name absence (AC#2).
- `tests/unit/core/test_runtime_query_service.py`: `get_system_status()` return type, version, and service statuses (FR#3, AC#6), and completion batch validation (FR#12, AC#8).
- `tests/unit/web/test_mappers.py`: a wrong-typed computed value raises in `to_listener_with_summary` (FR#11, AC#7).
- `tests/unit/test_web_utils.py`: a wrong-typed live value makes `enrich_jobs_with_live` return that job's unmodified DB row, tested directly rather than through the `enrich_jobs_with_live_data` wrapper the file exercises today (FR#11, AC#7).
- `tests/unit/tools/test_check_module_boundaries.py`: `no-hassette-client` (FR#13, AC#9).

### Tests to Remove

- The `system_status_response_from` tests in `tests/unit/web/test_mappers.py` (see Replacement Targets).

## Documentation Updates

- `wire/src/hassette_wire/__init__.py` docstring: what belongs in the package, the optional-new-fields rule, root-import guidance.
- `wire/README.md`: one paragraph on what the package contains and the optional-new-fields rule.
- `CONTRIBUTING.md`: one line on where the contract lives and the optional-new-fields rule, and one on `tools/wire_compat_ignore.txt` (a deliberate wire break adds a line in its `!` PR; the file is cleared after the release that ships it).
- `src/hassette/schemas/__init__.py` docstring: drop the `domain_models.py` entry and point to `hassette_wire` for served types.
- `src/hassette/types/enums.py` / `types/types.py`: a module-level note that the contract enums and Literals live in `hassette_wire` (and that app authors import them from `hassette`).
- `docs/pages/core-concepts/internals/lifecycle.md`, `docs/pages/core-concepts/bus/methods.md`: cross-references `hassette.types.enums.ResourceStatus` → `hassette.ResourceStatus`. `docs/pages/testing/snippets/testing_simulate_service_failure.py`: `from hassette import ResourceStatus`.
- `mkdocs.yml`: add `wire/src` to the mkdocstrings python handler `paths`.
- `src/hassette/web/mappers.py` module docstring: remove the enum-coercion note and the `SystemStatus` mapping.
- `src/hassette/cli/output.py` docstring (around line 270): `:class:`~hassette.types.types.CliFormat`` → `:class:`~hassette_wire.CliFormat``. No docs page renders it, so `mkdocs build --strict` won't catch the stale reference.
- `src/hassette/web/REVIEW.md`, `src/hassette/cli/REVIEW.md`, `src/hassette/bus/REVIEW.md`: replace `src/hassette/web/models.py` references with `hassette_wire`.
- `.claude/rules/frontend-worktree.md`: add `wire/src/hassette_wire/**` to `paths:` and to the "after modifying backend response models" line. `.claude/rules/design-completeness.md`: update the `ListenerWithSummary` location.
- `tools/check_module_boundaries.py` module docstring: the new rule.
- The changelog comes from the PR title via release-please. No hand edit.

## Impact

### Changed Files

Shared / cross-cutting first:

- create `wire/src/hassette_wire/{enums,literals,cli_format,health,apps,telemetry,logs,auth,config,ws}.py`: the moved definitions
- modify `wire/src/hassette_wire/__init__.py`: re-exports, `__all__`, contract docstring
- modify `src/hassette/types/enums.py`, `src/hassette/types/types.py`: remove the moved definitions and `CliFormat`/`CliFormatStyle` (no re-exports)
- modify `src/hassette/types/__init__.py`: drop the moved names from imports and `__all__`
- modify `src/hassette/__init__.py`: import `ExecutionMode`/`BackpressurePolicy`/`ResourceStatus`/`ExecutionStatus` from `hassette_wire`; add `ResourceStatus` and `ExecutionStatus` to `__all__`
- modify `mkdocs.yml`, `docs/pages/core-concepts/internals/lifecycle.md`, `docs/pages/core-concepts/bus/methods.md`, `docs/pages/testing/snippets/testing_simulate_service_failure.py`: `hassette.ResourceStatus` paths
- modify roughly 70 internal `src/hassette` modules that import a FR#5/FR#6 name from `hassette.types*`: import from `hassette_wire` (script)
- delete `src/hassette/web/models.py`
- delete `src/hassette/schemas/domain_models.py`
- modify `src/hassette/schemas/execution_models.py`: remove `Execution`, `ActivityFeedEntry`
- modify `src/hassette/schemas/job_models.py`: remove `JobSummary`
- modify `src/hassette/schemas/__init__.py`: drop the `domain_models` re-exports and the `ManifestStatus` re-export, update the docstring
- modify `src/hassette/core/runtime_query_service.py`: imports, `get_system_status()` / `collect_boot_issues()` build wire models, `on_execution_completed` builds `ExecutionCompletedData` per event and `flush_completions` dumps the typed batch
- modify `src/hassette/web/mappers.py`: imports, delete `system_status_response_from`, validated construction in `to_listener_with_summary`, docstring
- modify `src/hassette/web/utils.py`: imports, validated construction in `enrich_jobs_with_live`
- modify `src/hassette/web/routes/health.py`: return `get_system_status()` directly; imports
- modify `tools/check_module_boundaries.py`: `WATCHED_ROOTS`, the `no-hassette-client` rule, docstring
- modify `prek.toml`: `check-schemas-fresh` `files` pattern covers `wire/src/hassette_wire/`; new `check-wire-compat` pre-push hook
- create `tools/check_wire_compat.py` (+ its two oasdiff severity-levels files and `tools/wire_compat_ignore.txt`) and `tests/unit/tools/test_check_wire_compat.py` (fixture-pair cases for AC#15)
- modify `.github/workflows/tests.yml`: wire-compat step in the frontend job, `fetch-depth: 0` on its checkout, and the check's files in the `changes` path filter; `mise.toml`: oasdiff tool
- modify `src/hassette/core/telemetry/{execution_queries,registration_queries}.py`: imports
- modify `src/hassette/web/telemetry_helpers.py`, `src/hassette/web/routes/{apps,auth,bus,config,executions,logs,scheduler,telemetry,ws}.py`: imports
- modify `src/hassette/cli/{client,output}.py`, `src/hassette/cli/commands/{app,job,listener,log,misc,status}.py`: imports (plus the `CliFormat` docstring reference in `output.py`)
- modify `scripts/schema_helpers.py`: `WsServerMessage` import
- modify every test file listed under Existing Tests to Adapt, plus `tests/unit/tools/test_check_module_boundaries.py` and `tests/unit/test_web_utils.py`
- create `tests/unit/test_wire_public_paths.py`; modify `wire/tests/test_import.py`
- modify `wire/README.md`, `CONTRIBUTING.md`, `src/hassette/{web,cli,bus}/REVIEW.md`, `.claude/rules/{frontend-worktree,design-completeness}.md`

- modify `codegen/src/hassette_codegen/sync_facade/generic.py`: emitted imports of moved names come from `hassette_wire`; regenerate the sync facades
- modify `tools/docs/check_xref_coverage.py`: `ResourceStatus` → `hassette.ResourceStatus`
- modify `pyproject.toml` (coverage `omit`) and `.github/codecov.yml` (ignore): drop the `web/models.py` entries
- modify `frontend/src/REVIEW.md`, `src/hassette/schemas/summary_models.py` (docstring), `.claude/rules/core-startup.md`: stale references to the moved/deleted modules

<!-- Gap check 2026-09-29: 7 gaps included — codegen sync_facade/generic.py:38,95,104,184,232,239,315 (emits moved-name imports) → T01 step 5; tools/docs/check_xref_coverage.py:69 → T01 step 6; tests/unit/tools/test_generate_sync_facade.py (emitted-header expectations) → T01 Focus; pyproject.toml:206 + .github/codecov.yml:36 (web/models.py coverage entries) → T02 step 6; frontend/src/REVIEW.md:7,16 → T02 step 6; src/hassette/schemas/summary_models.py:6 → T03 step 4; .claude/rules/core-startup.md:34,58 → T03 step 7 -->

### Behavioral Invariants

- Every HTTP response and WS message body is byte-for-byte what it was, apart from any coercion from FR#11/FR#12 that the pin surfaces and the PR explains.
- `openapi.json`, `ws-schema.json`, and all generated frontend artifacts are unchanged.
- `from hassette import ExecutionMode, BackpressurePolicy` keeps working and yields the same enum semantics. The removed public paths are `hassette.types.enums.ResourceStatus` (and the `hassette.types` exports) and `hassette.types.types.ExecutionStatus`, replaced by `hassette.ResourceStatus` and `hassette.ExecutionStatus` per Dependencies and Assumptions.
- CLI human-mode rendering of `CliFormat` fields is unchanged, and so is `--json` output.
- Every existing boundary rule flags exactly what it flagged before.

### Blast Radius

- **In-repo:** `types/`, `web/`, `cli/`, `core/runtime_query_service.py`, `core/telemetry`, `schemas/`, the boundary checker, and about 35 test files.
- **App authors:** anyone importing `ResourceStatus` or `ExecutionStatus` (or `SourceTier`/`QuerySourceTier`) from `hassette.types*` changes one import line. Everything else, including `hassette.ExecutionMode`, is unaffected.
- **Future:** from the first release carrying this change, `hassette_wire`'s root `__all__` is a public contract, and hassette's enums are part of it.

## Open Questions

## Addendum

### 2026-10-03: `SourceTier` and `LOG_LEVEL_TYPE` are closed vocabularies; open-set handling uses `Open<TypeName>` aliases

§"Literal wire fields" listed `SourceTier` and `LOG_LEVEL_TYPE` among the open-valued Literal aliases. Spec 121 (`design/specs/121-wire-lenient-unknown-enums/design.md`, D14) declares both closed: their response fields stay strict, and adding a value to either is a breaking wire change that needs manual review. The other aliases and enums stay `Literal`/`StrEnum` as this spec chose. Spec 121 makes their response fields open through `Open<TypeName>` aliases that accept an `UnknownValue` under the client's `LENIENT_CONTEXT`. No `Literal` is converted to a `StrEnum`, and `openapi.json` stays byte-identical.
